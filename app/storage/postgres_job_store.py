"""Tenant-filtered PostgreSQL repository; short transactions and fenced record claims."""

from contextlib import contextmanager
from collections.abc import Iterator, Mapping
from types import MappingProxyType
from datetime import datetime, timedelta, timezone
import threading
from uuid import uuid4

from alembic.migration import MigrationContext
from sqlalchemy import Select, delete, func, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import ApplicationError, ErrorCode as E
from app.core.tenant_auth import Permission, Principal, TenantRegistry
from app.schemas.batch import BatchResult, JobState, ParsedRecord, RecordMetadata, RecordState, TERMINAL_STATES, UploadOptions
from app.services.reporting_service import ReportingService
from app.storage.batch_models import BatchJobRow as J, BatchRecordRow as R
from app.storage.database import REVISION, create_database_engine
from app.storage.job_store import Job, JobStore

LOCK_ID = 527493740214  # One batch coordinator per configured PostgreSQL database.


def now() -> datetime:
    return datetime.now(timezone.utc)


class PostgresJobStore(JobStore):
    """No credentials/proofs are persisted. _jobs contains only active worker inputs."""

    def __init__(self, settings: Settings, registry: TenantRegistry) -> None:
        super().__init__(settings.batch_job_ttl_seconds, registry=registry)
        self._registry: TenantRegistry = registry
        self.settings = settings
        self.engine = None
        self._coordinator = None
        self._backend_pid = None
        self._guard_lock = threading.Lock()
        self.available = False
        self._claims: dict[tuple[str, str], str] = {}

    def _bind_registry(self, registry: TenantRegistry) -> None:
        if self._registry is not registry:
            raise ApplicationError(E.AUTHENTICATION_FAILED)

    def start(self) -> None:
        if self.settings.database_url is None:
            return  # Other stateless features remain usable; batch fails closed503.
        try:
            self.engine = create_database_engine(self.settings.database_url)
            self._coordinator = self.engine.connect()
            if MigrationContext.configure(self._coordinator).get_current_revision() != REVISION:
                raise ApplicationError(E.BATCH_UNAVAILABLE)
            if not self._coordinator.scalar(select(func.pg_try_advisory_lock(LOCK_ID))):
                raise ApplicationError(E.BATCH_UNAVAILABLE)
            self._backend_pid = self._coordinator.scalar(select(func.pg_backend_pid()))
            self._coordinator.commit()
            self.available = True
        except Exception:
            self.close()
            raise ApplicationError(E.BATCH_UNAVAILABLE) from None

    def _guard(self) -> None:
        """Detect lock-session replacement/loss before mutating or starting model work."""
        with self._guard_lock:
            if not self.available or self._coordinator is None:
                raise ApplicationError(E.BATCH_UNAVAILABLE)
            try:
                pid = self._coordinator.scalar(select(func.pg_backend_pid()))
                self._coordinator.commit()
                if pid != self._backend_pid:
                    raise RuntimeError
            except Exception:
                self.available = False
                raise ApplicationError(E.BATCH_UNAVAILABLE) from None

    @contextmanager
    def _session(self, *, write: bool = False) -> Iterator[Session]:
        if self.engine is None:
            raise ApplicationError(E.BATCH_UNAVAILABLE)
        if write:
            self._guard()
        try:
            with Session(self.engine, expire_on_commit=False) as session:
                with session.begin():
                    yield session
        except ApplicationError:
            raise
        except Exception:
            # Never expose SQL parameters, driver messages, URLs or stored feedback.
            raise ApplicationError(E.BATCH_UNAVAILABLE) from None

    def _query(self, job_id: str, owner: Principal) -> Select[tuple[J]]:
        return select(J).where(J.public_id == job_id, J.tenant_id == owner.tenant_id)

    def _owned_job(self, session: Session, job_id: str, owner: Principal, *, lock: bool = False) -> J:
        query = self._query(job_id, owner)
        row = session.scalar(query.with_for_update() if lock else query)
        if row is None:
            raise ApplicationError(E.BATCH_JOB_NOT_FOUND)
        return row

    def _rows(self, session: Session, row: J) -> list[R]:
        # Parent row is already tenant-filtered; join also scopes child SQL explicitly.
        return list(session.scalars(select(R).join(J, R.job_id == J.id).where(
            J.public_id == row.public_id, J.tenant_id == row.tenant_id).order_by(R.position)))

    def _domain(self, session: Session, row: J, owner: Principal, *, worker: bool = False) -> Job:
        rows = self._rows(session, row)
        records = [ParsedRecord(meta=RecordMetadata(feedback_id=r.feedback_id, source_row=r.source_row,
            normalized_date=r.normalized_date, date_status=r.date_status), text=r.raw_text if worker else None,
            validation_error=E(r.validation_error) if r.validation_error else None) for r in rows]
        results = [self._result(r) for r in rows if r.status in {'SUCCESS','FAILED'}]
        job = Job(row.public_id, owner, UploadOptions.model_validate(row.options | {'business_type':row.business_type,'source':row.source}), records,
            row.skipped_blank_rows, row.total, row.valid, status=JobState(row.status), results=results,
            error_code=E(row.error_code) if row.error_code else None)
        if job.status in TERMINAL_STATES:
            if row.error_code != E.BATCH_REPORT_UNAVAILABLE:
                try:
                    job.report = ReportingService().build(job, job.status)
                except Exception:
                    raise ApplicationError(E.BATCH_REPORT_UNAVAILABLE) from None
            job.records.clear()
        return job

    @staticmethod
    def _result(row: R) -> BatchResult:
        return BatchResult.model_validate({name:getattr(row,name) for name in BatchResult.model_fields})

    def get(self, job_id: str, *, principal: Principal | None = None) -> Job:
        owner = self._authorize(principal, Permission.BATCH_READ)
        with self._session() as session:
            row = self._owned_job(session, job_id, owner)
            if row.expires_at is not None and row.expires_at <= now():
                raise ApplicationError(E.BATCH_JOB_NOT_FOUND)
            return self._domain(session, row, owner)

    @property
    def jobs(self) -> Mapping[str, Job]:
        owner = self._authorize(None, Permission.BATCH_READ)
        with self._session() as session:
            rows = session.scalars(select(J).where(J.tenant_id == owner.tenant_id,
                (J.expires_at.is_(None)) | (J.expires_at > now())).limit(self.settings.batch_max_retained_jobs))
            return MappingProxyType({r.public_id:self._domain(session,r,owner) for r in rows})

    def _counts(self, tenant: str) -> tuple[int, int, int, int]:
        with self._session() as session:
            rows = session.execute(select(J.tenant_id,J.status,func.count()).group_by(J.tenant_id,J.status)).all()
            total=sum(n for _,_,n in rows);active=sum(n for _,s,n in rows if s not in TERMINAL_STATES)
            owned=sum(n for t,_,n in rows if t==tenant)
            owned_active=sum(n for t,s,n in rows if t==tenant and s not in TERMINAL_STATES)
            return active,total,owned_active,owned

    def add(self, options: UploadOptions, records: list[ParsedRecord], skipped: int, *, principal: Principal | None = None) -> Job:
        owner=self._authorize(principal,Permission.BATCH_CREATE)
        timestamp=now()
        job=Job(uuid4().hex,owner,options,records,skipped,len(records),sum(r.validation_error is None for r in records))
        with self._session(write=True) as session:
            row=J(public_id=job.job_id,tenant_id=owner.tenant_id,options=options.model_dump(mode='json',exclude={'business_type','source'}),business_type=options.business_type,source=options.source,
                status='PENDING',total=job.total_records,valid=job.valid_records,invalid=job.total_records-job.valid_records,
                skipped_blank_rows=skipped,processed=0,successful=0,failed=0,created_at=timestamp,updated_at=timestamp)
            session.add(row);session.flush()
            for i,r in enumerate(records):
                session.add(R(job_id=row.id,position=i,**r.meta.model_dump(),raw_text=r.text,
                    validation_error=r.validation_error,status='PENDING',attempted=False,aspects=[],
                    evidence_phrases=[],updated_at=timestamp))
        return job

    def _recoverable(self, limit: int, excluded: set[str]) -> list[Job]:
        owners = {}
        for credential in self._registry._credentials.values():
            if Permission.BATCH_CREATE in credential.permissions:
                owners.setdefault(credential.tenant_id, Principal(credential.tenant_id,credential.credential_id,
                    credential.permissions,'api_key',credential.digest,self._registry))
        if not owners or limit<=0:return []
        with self._session() as session:
            query=select(J).where(J.status.in_(['PENDING','RUNNING']),J.tenant_id.in_(owners))
            if excluded:query=query.where(J.public_id.not_in(excluded))
            rows=session.scalars(query.order_by(J.created_at).limit(limit))
            jobs=[self._domain(session,r,self._registry.require(owners[r.tenant_id],Permission.BATCH_CREATE),worker=True) for r in rows]
        return jobs

    def _has_attempted(self, job: Job, feedback_id: str) -> bool:
        owner=self._registry.require(job.owner,Permission.BATCH_CREATE)
        with self._session() as session:
            parent=self._owned_job(session,job.job_id,owner)
            return bool(session.scalar(select(R.attempted).where(R.job_id==parent.id,R.feedback_id==feedback_id)))

    def _worker_results(self, job: Job) -> list[BatchResult]:
        owner=self._registry.require(job.owner,Permission.BATCH_CREATE)
        with self._session() as session:
            parent=self._owned_job(session,job.job_id,owner)
            return [self._result(r) for r in self._rows(session,parent) if r.status in {'SUCCESS','FAILED'}]

    def running(self, job: Job) -> bool:
        owner=self._registry.require(job.owner,Permission.BATCH_CREATE)
        with self._session(write=True) as session:
            row=self._owned_job(session,job.job_id,owner,lock=True)
            if row.status in TERMINAL_STATES:
                return False
            row.status='RUNNING';row.started_at=row.started_at or now();row.updated_at=now();row.error_code=job.error_code
        job.status=JobState.RUNNING
        return True

    def claim(self, job: Job, feedback_id: str) -> tuple[str | None, float]:
        owner=self._registry.require(job.owner,Permission.BATCH_CREATE)
        with self._session(write=True) as session:
            parent=self._owned_job(session,job.job_id,owner,lock=True)
            row=session.scalar(select(R).join(J,R.job_id==J.id).where(J.public_id==job.job_id,
                J.tenant_id==owner.tenant_id,R.feedback_id==feedback_id).with_for_update(of=R,skip_locked=True))
            if row is None:return None, .1
            if row.status in {'SUCCESS','FAILED'}:return None, 0
            if row.status=='PROCESSING' and row.claim_expires_at>now():
                return None,min(1.,max(.01,(row.claim_expires_at-now()).total_seconds()))
            token=uuid4().hex
            row.status='PROCESSING';row.claim_token=token
            row.claim_expires_at=now()+timedelta(seconds=self.settings.groq_timeout_seconds+15)
            row.updated_at=now()
        self._claims[(job.job_id,feedback_id)]=token
        return token,0

    def attempted(self, job: Job, record: ParsedRecord, token: str) -> None:
        owner=self._registry.require(job.owner,Permission.BATCH_CREATE)
        with self._session(write=True) as session:
            parent=self._owned_job(session,job.job_id,owner,lock=True)
            row=session.scalar(select(R).where(R.job_id==parent.id,R.feedback_id==record.meta.feedback_id,
                R.status=='PROCESSING',R.claim_token==token).with_for_update())
            if row is None:raise ApplicationError(E.BATCH_UNAVAILABLE)
            row.attempted=True;row.updated_at=now()

    def save_result(self, job: Job, record: ParsedRecord, result: BatchResult, token: str) -> None:
        owner=self._registry.require(job.owner,Permission.BATCH_CREATE)
        result=BatchResult.model_validate(result.model_dump(mode='json'))
        if result.feedback_id!=record.meta.feedback_id:raise ApplicationError(E.BATCH_REPORT_UNAVAILABLE)
        if result.status==RecordState.SUCCESS:
            from app.schemas.sentiment import SentimentResponse
            SentimentResponse.model_validate(result.analysis_data(),context={'feedback_text':record.text})
        with self._session(write=True) as session:
            parent=self._owned_job(session,job.job_id,owner,lock=True)
            row=session.scalar(select(R).where(R.job_id==parent.id,R.feedback_id==record.meta.feedback_id,
                R.status=='PROCESSING',R.claim_token==token).with_for_update())
            if row is None:raise ApplicationError(E.BATCH_UNAVAILABLE)
            for name,value in result.model_dump(mode='json',exclude={'normalized_date'}).items():setattr(row,name,value)
            row.normalized_date=result.normalized_date
            row.raw_text=None;row.claim_token=None;row.claim_expires_at=None;row.updated_at=now()
            session.flush();self._recount(session,parent)
            parent.error_code=job.error_code
        self._claims.pop((job.job_id,record.meta.feedback_id),None)

    @staticmethod
    def _recount(session: Session, parent: J) -> None:
        counts=dict(session.execute(select(R.status,func.count()).where(R.job_id==parent.id).group_by(R.status)).all())
        parent.successful=counts.get('SUCCESS',0);parent.failed=counts.get('FAILED',0)
        parent.processed=parent.successful+parent.failed;parent.updated_at=now()

    def finish(self, job: Job, status: JobState) -> None:
        owner=self._registry.require(job.owner,Permission.BATCH_CREATE)
        with self._session(write=True) as session:
            parent=self._owned_job(session,job.job_id,owner,lock=True)
            self._recount(session,parent)
            if parent.processed!=parent.total:raise ApplicationError(E.BATCH_UNAVAILABLE)
            expected='COMPLETED' if parent.successful==parent.total else 'PARTIAL_SUCCESS' if parent.successful else 'FAILED'
            if status!=expected:raise ApplicationError(E.BATCH_REPORT_UNAVAILABLE)
            parent.status=status;parent.error_code=job.error_code;parent.completed_at=now()
            ttl=self.settings.batch_job_ttl_seconds
            parent.expires_at=now()+timedelta(seconds=ttl) if ttl else None
        job.status=status;job.records.clear()

    def pause(self, job: Job) -> None:
        """After awaited cancellation, release only this coordinator's fenced claims."""
        owner=self._registry.require(job.owner,Permission.BATCH_CREATE)
        with self._session(write=True) as session:
            parent=self._owned_job(session,job.job_id,owner,lock=True)
            for r in self._rows(session,parent):
                if r.status=='PROCESSING' and self._claims.get((job.job_id,r.feedback_id))==r.claim_token:
                    r.status='PENDING';r.claim_token=None;r.claim_expires_at=None;r.updated_at=now()
            if parent.status not in TERMINAL_STATES:
                parent.status='PENDING';parent.updated_at=now();parent.error_code=job.error_code
        for key in list(self._claims):
            if key[0]==job.job_id:self._claims.pop(key,None)
        for record in job.records:record.text=None
        job.records.clear()

    def _purge(self) -> None:
        with self._session(write=True) as session:
            ttl=self.settings.batch_job_ttl_seconds
            if ttl:
                # Explicit policy applies to existing completed jobs as well.
                session.execute(update(J).where(J.completed_at.is_not(None)).values(
                    expires_at=J.completed_at+timedelta(seconds=ttl)))
                session.execute(delete(J).where(J.completed_at.is_not(None),J.expires_at<=now()))
            else:
                session.execute(update(J).where(J.expires_at.is_not(None)).values(expires_at=None))

    def close(self) -> None:
        self.available=False
        with self._guard_lock:
            if self._coordinator is not None:
                try:
                    if self._backend_pid is not None:
                        self._coordinator.execute(select(func.pg_advisory_unlock(LOCK_ID)));self._coordinator.commit()
                except Exception:pass
                self._coordinator.close();self._coordinator=None
        if self.engine is not None:
            self.engine.dispose();self.engine=None
        self._clear()

    def _clear(self) -> None:
        # Erase process-local copies only. Never delete durable jobs on shutdown.
        super()._clear()
        self._claims.clear()
