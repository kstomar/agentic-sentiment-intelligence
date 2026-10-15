"""Short PostgreSQL transactions; no OAuth tokens, email bodies or model results."""
from collections.abc import Iterator
from contextlib import contextmanager
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.exceptions import ApplicationError, ErrorCode as E
from app.storage.gmail_message_models import GmailMessageRow as G
from app.storage.gmail_message_store import GmailMessageStore, PageClaims, now
from app.storage.gmail_store import Connection, GmailJob, GmailStore
from app.storage.postgres_job_store import PostgresJobStore

ADMISSION_LOCK = 527493740216


class PostgresGmailMessageStore(GmailMessageStore):
    persistent = True

    def __init__(self, database: PostgresJobStore, store: GmailStore) -> None:
        super().__init__(store)
        self.database = database

    @property
    def available(self) -> bool:
        return self.database.available

    @contextmanager
    def _session(self) -> Iterator[Session]:
        if not self.available: raise ApplicationError(E.GMAIL_UNAVAILABLE)
        try:
            with self.database._session(write=True) as session:
                yield session
        except ApplicationError as error:
            if error.code == E.BATCH_UNAVAILABLE:
                raise ApplicationError(E.GMAIL_UNAVAILABLE) from None
            raise

    def claim_page(self, job: GmailJob, connection: Connection, ids: list[str], maximum: int) -> PageClaims:
        tenant, mailbox = self._scope(job, connection); self._validate_page(job, ids, maximum)
        result = PageClaims(); stamp = now()
        with self._session() as session:
            # Atomic lookup/quota/insert even for new identities. The existing
            # single coordinator remains mandatory; unique keys also fence races.
            session.execute(select(func.pg_advisory_xact_lock(ADMISSION_LOCK)))
            rows = {r.message_id:r for r in session.scalars(select(G).where(
                G.tenant_id == tenant, G.mailbox_key == mailbox, G.message_id.in_(ids)).with_for_update())}
            total, owned = session.execute(select(func.count(), func.count().filter(G.tenant_id == tenant)).select_from(G)).one()
            for mid in ids:
                row = rows.get(mid)
                category = self._classify(row, stamp) if row is not None else 'eligible'
                if category != 'eligible':
                    if category == 'completed': result.completed += 1
                    else: result.deferred += 1
                    continue
                if len(result.claims) >= maximum: continue
                if row is None:
                    if (total >= self.settings.gmail_max_dedup_records
                        or owned >= min(self.settings.gmail_tenant_max_dedup_records, self.settings.gmail_max_dedup_records - 1)):
                        result.capacity_limited = True; continue
                    row = G(tenant_id=tenant, mailbox_key=mailbox, message_id=mid, status='PENDING',
                            attempts=0, created_at=stamp, updated_at=stamp)
                    session.add(row); rows[mid] = row; total += 1; owned += 1
                result.claims[mid] = self._reserve(row, job, stamp)
        return result

    def completed_ids(self, job: GmailJob, connection: Connection, ids: list[str]) -> set[str]:
        tenant, mailbox = self._scope(job, connection)
        self._validate_page(job, ids, job.maximum)
        with self._session() as session:
            return set(session.scalars(select(G.message_id).where(
                G.tenant_id == tenant, G.mailbox_key == mailbox,
                G.message_id.in_(ids), G.status == 'SUCCEEDED')))

    def _row(self, session: Session, job: GmailJob, connection: Connection, mid: str,
             token: str, *, cleanup: bool = False) -> G | None:
        tenant, mailbox = self._scope(job, connection, cleanup=cleanup)
        return session.scalar(select(G).where(G.tenant_id == tenant, G.mailbox_key == mailbox,
            G.message_id == mid, G.job_id == job.job_id, G.claim_token == token).with_for_update())

    def begin(self, job: GmailJob, connection: Connection, mid: str, token: str) -> bool:
        self._scope(job, connection)
        with self._session() as session:
            row = self._row(session, job, connection, mid, token)
            return row is not None and self._begin(row, token, now())

    def finish(self, job: GmailJob, connection: Connection, mid: str, token: str, error: E | None) -> bool:
        self._scope(job, connection, cleanup=True)
        with self._session() as session:
            row = self._row(session, job, connection, mid, token, cleanup=True)
            if row is None or row.status != 'PROCESSING': return False
            self._settle(row, error, now()); return True

    def release_job(self, job: GmailJob, connection: Connection, error: E) -> None:
        tenant, mailbox = self._scope(job, connection, cleanup=True)
        with self._session() as session:
            rows = session.scalars(select(G).where(G.tenant_id == tenant, G.mailbox_key == mailbox,
                G.job_id == job.job_id, G.status.in_(['RESERVED','PROCESSING'])).with_for_update())
            for row in rows: self._release(row, error, now())
