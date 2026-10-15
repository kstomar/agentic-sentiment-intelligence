"""Tenant-scoped ingestion repository sharing the batch database's coordinator.

SQL operations are synchronous and must be offloaded by the service. No secrets,
principal proofs, signed headers, original upload files or provider diagnostics
are persisted. Restart terminalizes unfinished work instead of repeating inference.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import ApplicationError, ErrorCode as E
from app.core.tenant_auth import Permission, Principal, TenantRegistry
from app.schemas.ingestion import EventResult, EventState, EventStatus, IngestionRequest
from app.schemas.sentiment import SentimentResponse
from app.storage.event_store import Event
from app.storage.feedback_models import FeedbackEventRow as F
from app.storage.postgres_job_store import PostgresJobStore

ADMISSION_LOCK = 527493740215


def now() -> datetime:
    return datetime.now(timezone.utc)


class PostgresEventStore:
    """The database is authoritative; no terminal feedback/result cache exists."""

    def __init__(self, database: PostgresJobStore, settings: Settings, registry: TenantRegistry) -> None:
        self.database = database
        self.settings = settings
        self.registry = registry

    @contextmanager
    def _session(self, *, write: bool = False) -> Iterator[Session]:
        if not self.database.available:
            raise ApplicationError(E.WEBHOOK_UNAVAILABLE)
        try:
            with self.database._session(write=write) as session:
                yield session
        except ApplicationError as error:
            if error.code == E.BATCH_UNAVAILABLE:
                raise ApplicationError(E.WEBHOOK_UNAVAILABLE) from None
            raise

    def start(self) -> None:
        if not self.database.available:
            return
        # Only after the exclusive database coordinator is acquired. Never replay
        # an uncommitted provider response, even when the same delivery retries.
        with self._session(write=True) as session:
            stamp = now()
            session.execute(update(F).where(F.status.in_([EventState.ACCEPTED, EventState.PROCESSING])).values(
                status=EventState.FAILED, analysis=None, error_code=E.INGESTION_INTERRUPTED,
                updated_at=stamp, completed_at=stamp, expires_at=self._deadline(stamp)))
            self._purge_in(session)

    def _deadline(self, stamp: datetime) -> datetime | None:
        ttl = self.settings.ingestion_result_ttl_seconds
        return stamp + timedelta(seconds=ttl) if ttl else None

    def _purge_in(self, session: Session) -> None:
        ttl = self.settings.ingestion_result_ttl_seconds
        if ttl:
            session.execute(update(F).where(F.completed_at.is_not(None)).values(
                expires_at=F.completed_at + timedelta(seconds=ttl)))
            session.execute(delete(F).where(F.completed_at.is_not(None), F.expires_at <= now()))
        else:
            session.execute(update(F).where(F.expires_at.is_not(None)).values(expires_at=None))

    def _purge(self) -> None:
        with self._session(write=True) as session:
            self._purge_in(session)

    def reserve(self, event: Event, *, kind: str, configuration_error: E | None = None,
                queue_full: bool = False) -> bool:
        owner = self.registry.require(event.owner, Permission.INGEST)
        if kind == "webhook":
            if owner.kind != "webhook" or owner.credential_id != event.integration_id:
                raise ApplicationError(E.WEBHOOK_AUTHENTICATION_FAILED)
        elif kind != "direct" or owner.kind != "api_key":
            raise ApplicationError(E.AUTHENTICATION_FAILED)
        assert event.request is not None
        feedback = IngestionRequest.model_validate(event.request.model_dump())
        with self._session(write=True) as session:
            # Serialize lookup, quota counts and insertion, including empty-key
            # races. Short transaction; never held during network/model work.
            session.execute(select(func.pg_advisory_xact_lock(ADMISSION_LOCK)))
            self._purge_in(session)
            existing = session.scalar(select(F).where(F.tenant_id == owner.tenant_id,
                                                      F.delivery_id == event.delivery_id).with_for_update())
            if existing is not None:
                if kind != "webhook" or existing.kind != kind or existing.integration_id != event.integration_id:
                    raise ApplicationError(E.WEBHOOK_DELIVERY_COLLISION)
                if existing.digest != event.digest:
                    raise ApplicationError(E.WEBHOOK_DELIVERY_CONFLICT)
                return False
            if configuration_error is not None:
                raise ApplicationError(configuration_error)
            if queue_full:
                raise ApplicationError(E.WEBHOOK_CAPACITY_EXCEEDED)
            counts = list(session.execute(select(F.tenant_id, F.status, func.count()).group_by(F.tenant_id, F.status)))
            total = sum(n for _, _, n in counts)
            retained = sum(n for t, _, n in counts if t == owner.tenant_id)
            pending = sum(n for t, s, n in counts if t == owner.tenant_id and s == EventState.ACCEPTED)
            if total >= self.settings.webhook_max_retained_events:
                raise ApplicationError(E.WEBHOOK_CAPACITY_EXCEEDED)
            if retained >= self.registry.limit(self.settings.tenant_max_retained_events, self.settings.webhook_max_retained_events):
                raise ApplicationError(E.TENANT_CAPACITY_EXCEEDED)
            if kind == "webhook" and pending >= self.registry.limit(self.settings.tenant_max_pending_events, self.settings.webhook_max_pending_events):
                raise ApplicationError(E.TENANT_CAPACITY_EXCEEDED)
            stamp = now()
            session.add(F(tenant_id=owner.tenant_id, delivery_id=event.delivery_id,
                integration_id=event.integration_id if kind == "webhook" else None,
                kind=kind, event_type="customer.feedback.created" if kind == "webhook" else None,
                digest=event.digest if kind == "webhook" else None, operation_id=event.operation_id,
                feedback=feedback.model_dump(mode="json"), status=EventState.ACCEPTED,
                analysis=None, created_at=stamp, updated_at=stamp))
        return True

    def _owned(self, session: Session, event: Event) -> F:
        owner = self.registry.require(event.owner, Permission.INGEST)
        row = session.scalar(select(F).where(F.tenant_id == owner.tenant_id,
            F.delivery_id == event.delivery_id, F.operation_id == event.operation_id).with_for_update())
        if row is None or (owner.kind == "webhook" and row.integration_id != owner.credential_id):
            raise ApplicationError(E.WEBHOOK_EVENT_NOT_FOUND)
        return row

    def processing(self, event: Event) -> bool:
        with self._session(write=True) as session:
            row = self._owned(session, event)
            if row.status != EventState.ACCEPTED:
                return False
            row.status = EventState.PROCESSING
            row.updated_at = now()
        return True

    def finish(self, event: Event, analysis: SentimentResponse | None = None, error: E | None = None) -> None:
        with self._session(write=True) as session:
            row = self._owned(session, event)
            if row.status in {EventState.COMPLETED, EventState.FAILED}:
                return
            if (analysis is None) == (error is None):
                raise ApplicationError(E.INVALID_MODEL_RESPONSE)
            validated = None if analysis is None else SentimentResponse.model_validate(
                analysis.model_dump(), context={"feedback_text": IngestionRequest.model_validate(row.feedback).text})
            stamp = now()
            row.analysis = validated.model_dump(mode="json") if validated is not None else None
            row.status = EventState.FAILED if error else EventState.COMPLETED
            row.error_code = error
            row.updated_at = row.completed_at = stamp
            row.expires_at = self._deadline(stamp)

    def get(self, delivery_id: str, *, principal: Principal | None = None) -> EventResult:
        owner = self.registry.require(principal, Permission.EVENT_READ)
        with self._session() as session:
            row = session.scalar(select(F).where(F.tenant_id == owner.tenant_id,
                F.delivery_id == delivery_id, (F.expires_at.is_(None)) | (F.expires_at > now())))
            if row is None:
                raise ApplicationError(E.WEBHOOK_EVENT_NOT_FOUND)
            try:
                feedback = IngestionRequest.model_validate(row.feedback)
                analysis = None if row.analysis is None else SentimentResponse.model_validate(
                    row.analysis, context={"feedback_text": feedback.text})
                return EventResult(delivery_id=row.delivery_id, status=row.status,
                    integration_id=row.integration_id, event_type=row.event_type, feedback=feedback,
                    analysis=analysis, error_code=row.error_code, created_at=row.created_at,
                    updated_at=row.updated_at, completed_at=row.completed_at)
            except Exception:
                raise ApplicationError(E.WEBHOOK_UNAVAILABLE) from None

    def status(self, delivery_id: str, *, principal: Principal | None = None) -> EventStatus:
        row = self.get(delivery_id, principal=principal)
        return EventStatus(delivery_id=row.delivery_id, status=row.status, error_code=row.error_code)
