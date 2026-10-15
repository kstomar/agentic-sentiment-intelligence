"""Shared message-claim policy and an explicitly injected ephemeral test adapter.

Production uses PostgresGmailMessageStore. OAuth credentials, message bodies and
analysis never belong in this registry. A mailbox hash is pseudonymous, not secret.
"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import hashlib
from typing import Protocol
from uuid import uuid4

from app.core.exceptions import ApplicationError, ErrorCode as E
from app.core.tenant_auth import Permission
from app.integrations.google_gmail import identifier
from app.schemas.batch import JobState
from app.storage.gmail_store import Connection, GmailJob, GmailStore


def now() -> datetime:
    return datetime.now(timezone.utc)


class TrackedMessage(Protocol):
    status: str
    attempts: int
    claim_token: str | None
    claim_expires_at: datetime | None
    job_id: str | None
    last_error: str | None
    retry_at: datetime | None
    updated_at: datetime
    last_attempt_at: datetime | None
    completed_at: datetime | None


@dataclass(repr=False)
class MessageRecord:
    status: str = 'PENDING'
    attempts: int = 0
    claim_token: str | None = None
    claim_expires_at: datetime | None = None
    job_id: str | None = None
    last_error: str | None = None
    retry_at: datetime | None = None
    updated_at: datetime = field(default_factory=now)
    last_attempt_at: datetime | None = None
    completed_at: datetime | None = None


@dataclass
class PageClaims:
    claims: dict[str, str] = field(default_factory=dict)
    completed: int = 0
    deferred: int = 0
    capacity_limited: bool = False


class GmailMessageStore:
    persistent = False

    def __init__(self, store: GmailStore) -> None:
        self.store = store
        self.registry = store.registry
        self.settings = self.registry.settings

    @property
    def available(self) -> bool:
        return True

    def _scope(self, job: GmailJob, connection: Connection, *, cleanup: bool = False) -> tuple[str, str]:
        owner = self.registry.require(job.owner, Permission.GMAIL_IMPORT)
        if (self.store._jobs.get(job.job_id) is not job or connection.tenant_id != owner.tenant_id
            or job.connection_version != connection.version or job.mailbox != connection.mailbox):
            raise ApplicationError(E.GMAIL_JOB_NOT_FOUND)
        if not cleanup and (self.store._connections.get(owner.tenant_id) is not connection or not connection.active):
            raise ApplicationError(E.GMAIL_RECONNECT_REQUIRED)
        return owner.tenant_id, hashlib.sha256(connection.mailbox.casefold().encode('utf-8')).hexdigest()

    def _validate_page(self, job: GmailJob, ids: list[str], maximum: int) -> None:
        if not 0 < maximum <= job.maximum <= 100 or len(ids) > self.settings.gmail_max_messages_per_import:
            raise ApplicationError(E.GMAIL_RESPONSE_INVALID)
        if len(set(ids)) != len(ids):
            raise ApplicationError(E.GMAIL_RESPONSE_INVALID)
        for mid in ids:
            identifier(mid)

    def _classify(self, row: TrackedMessage, stamp: datetime) -> str:
        if row.status == 'SUCCEEDED':
            return 'completed'
        if row.status in {'RESERVED', 'PROCESSING'}:
            active = self.store._jobs.get(row.job_id)
            if ((row.claim_expires_at is not None and row.claim_expires_at > stamp)
                or (active is not None and active.status not in {JobState.COMPLETED, JobState.PARTIAL_SUCCESS, JobState.FAILED})):
                return 'deferred'
            old_deadline = row.claim_expires_at or stamp
            was_started = row.status == 'PROCESSING'
            row.status = 'FAILED' if row.attempts else 'PENDING'
            row.last_error = E.GMAIL_UNAVAILABLE
            row.retry_at = old_deadline + timedelta(seconds=self.settings.gmail_message_retry_delay_seconds) if was_started else None
            row.claim_token = row.claim_expires_at = None
            row.updated_at = stamp
        if row.attempts >= self.settings.gmail_message_max_attempts or (row.retry_at is not None and row.retry_at > stamp):
            return 'deferred'
        return 'eligible'

    def _reserve(self, row: TrackedMessage, job: GmailJob, stamp: datetime) -> str:
        token = uuid4().hex
        # Claims cover the entire bounded job plus network/model cancellation and
        # commit headroom. Current local active jobs cannot be stolen on expiry.
        lease = (self.settings.gmail_import_timeout_seconds + self.settings.groq_timeout_seconds
                 + 2 * self.settings.gmail_http_timeout_seconds + 30)
        row.status = 'RESERVED'; row.claim_token = token
        row.claim_expires_at = stamp + timedelta(seconds=lease)
        row.job_id = job.job_id; row.last_error = None; row.retry_at = None; row.updated_at = stamp
        return token

    def _begin(self, row: TrackedMessage, token: str, stamp: datetime) -> bool:
        if (row.status != 'RESERVED' or row.claim_token != token or row.claim_expires_at is None
            or row.claim_expires_at <= stamp or row.attempts >= self.settings.gmail_message_max_attempts):
            return False
        row.status = 'PROCESSING'; row.attempts += 1
        row.last_attempt_at = row.updated_at = stamp
        return True

    def _settle(self, row: TrackedMessage, error: E | None, stamp: datetime) -> None:
        row.status = 'FAILED' if error else 'SUCCEEDED'
        row.last_error = error; row.claim_token = row.claim_expires_at = None
        row.updated_at = stamp
        row.completed_at = None if error else stamp
        row.retry_at = (stamp + timedelta(seconds=self.settings.gmail_message_retry_delay_seconds)
                        if error and row.attempts < self.settings.gmail_message_max_attempts else None)

    def _release(self, row: TrackedMessage, error: E, stamp: datetime) -> None:
        if row.status == 'PROCESSING':
            self._settle(row, error, stamp)
        elif row.status == 'RESERVED':
            row.status = 'FAILED' if row.attempts else 'PENDING'
            row.last_error = error; row.retry_at = None
            row.claim_token = row.claim_expires_at = None; row.updated_at = stamp

    def claim_page(self, job: GmailJob, connection: Connection, ids: list[str], maximum: int) -> PageClaims:
        raise NotImplementedError

    def completed_ids(self, job: GmailJob, connection: Connection, ids: list[str]) -> set[str]:
        """Batch-filter durable successes before label-only network checks.

        This is an optimization, not a claim: claim_page still rechecks every
        state atomically after metadata checks, including concurrent completions.
        """
        raise NotImplementedError

    def begin(self, job: GmailJob, connection: Connection, mid: str, token: str) -> bool:
        raise NotImplementedError

    def finish(self, job: GmailJob, connection: Connection, mid: str, token: str, error: E | None) -> bool:
        raise NotImplementedError

    def release_job(self, job: GmailJob, connection: Connection, error: E) -> None:
        raise NotImplementedError


class MemoryGmailMessageStore(GmailMessageStore):
    """Ephemeral unit-test adapter; never a production database fallback."""

    def __init__(self, store: GmailStore) -> None:
        super().__init__(store)
        self._records: dict[tuple[str, str, str], MessageRecord] = {}

    def completed_ids(self, job: GmailJob, connection: Connection, ids: list[str]) -> set[str]:
        tenant, mailbox = self._scope(job, connection)
        self._validate_page(job, ids, job.maximum)
        return {mid for mid in ids if (row := self._records.get((tenant, mailbox, mid))) is not None
                and row.status == 'SUCCEEDED'}

    def claim_page(self, job: GmailJob, connection: Connection, ids: list[str], maximum: int) -> PageClaims:
        tenant, mailbox = self._scope(job, connection); self._validate_page(job, ids, maximum)
        result = PageClaims(); stamp = now()
        for mid in ids:
            key = (tenant, mailbox, mid); row = self._records.get(key)
            category = self._classify(row, stamp) if row is not None else 'eligible'
            if category != 'eligible':
                if category == 'completed': result.completed += 1
                else: result.deferred += 1
                continue
            if len(result.claims) >= maximum: continue
            if row is None:
                if (len(self._records) >= self.settings.gmail_max_dedup_records
                    or sum(k[0] == tenant for k in self._records) >= min(self.settings.gmail_tenant_max_dedup_records, self.settings.gmail_max_dedup_records - 1)):
                    result.capacity_limited = True; continue
                row = self._records[key] = MessageRecord()
            result.claims[mid] = self._reserve(row, job, stamp)
        return result

    def begin(self, job: GmailJob, connection: Connection, mid: str, token: str) -> bool:
        tenant, mailbox = self._scope(job, connection)
        row = self._records.get((tenant, mailbox, mid))
        return row is not None and row.job_id == job.job_id and self._begin(row, token, now())

    def finish(self, job: GmailJob, connection: Connection, mid: str, token: str, error: E | None) -> bool:
        tenant, mailbox = self._scope(job, connection, cleanup=True)
        row = self._records.get((tenant, mailbox, mid))
        if row is None or row.job_id != job.job_id or row.status != 'PROCESSING' or row.claim_token != token:
            return False
        self._settle(row, error, now()); return True

    def release_job(self, job: GmailJob, connection: Connection, error: E) -> None:
        tenant, mailbox = self._scope(job, connection, cleanup=True)
        for (t, m, _), row in self._records.items():
            if t == tenant and m == mailbox and row.job_id == job.job_id:
                self._release(row, error, now())
