"""Process-local, bounded OAuth/connection/import state; no persistence or raw messages."""

import asyncio
import time
from dataclasses import dataclass, field

from pydantic import SecretStr

from app.core.exceptions import ApplicationError, ErrorCode as E
from app.core.tenant_auth import Permission, Principal, TenantRegistry
from app.integrations.google_gmail import Tokens
from app.schemas.batch import JobState
from app.schemas.gmail import GmailJobStatus, GmailResult


@dataclass(repr=False)
class OAuthState:
    owner: Principal
    verifier: SecretStr | None
    expires_at: float
    consumed: bool = False
    cancelled: bool = False


@dataclass(repr=False)
class Connection:
    tenant_id: str
    mailbox: str
    version: str
    tokens: Tokens
    expires_at: float
    active: bool = True
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def invalidate(self) -> None:
        self.active = False
        self.tokens.clear()


@dataclass(repr=False)
class GmailJob:
    job_id: str
    owner: Principal
    mailbox: str
    connection_version: str
    maximum: int
    status: JobState = JobState.PENDING
    selected: int = 0
    results: list[GmailResult] = field(default_factory=list)
    error_code: E | None = None
    expires_at: float | None = None
    scanned: int = 0
    previously_processed: int = 0
    deferred: int = 0
    scan_exhausted: bool = False
    scan_limit_reached: bool = False
    capacity_limit_reached: bool = False
    claims: dict[str, str] = field(default_factory=dict, repr=False)

    def snapshot(self) -> GmailJobStatus:
        counts = {status: sum(row.status == status for row in self.results) for status in ['SUCCESS', 'FAILED', 'SKIPPED', 'DUPLICATE']}
        return GmailJobStatus(job_id=self.job_id, status=self.status, selected_messages=self.selected,
            processed_messages=len(self.results), successful_messages=counts['SUCCESS'],
            failed_messages=counts['FAILED'], skipped_messages=counts['SKIPPED'], duplicate_messages=counts['DUPLICATE'],
            error_code=self.error_code, scanned_messages=self.scanned,
            previously_processed_messages=self.previously_processed, deferred_messages=self.deferred,
            scan_exhausted=self.scan_exhausted, scan_limit_reached=self.scan_limit_reached,
            capacity_limit_reached=self.capacity_limit_reached)


class GmailStore:
    def __init__(self, registry: TenantRegistry) -> None:
        self.registry = registry
        self._states: dict[bytes, OAuthState] = {}
        self._flows: dict[str, OAuthState] = {}
        self._connections: dict[str, Connection] = {}
        self._mailboxes: dict[str, str] = {}
        self._jobs: dict[str, GmailJob] = {}

    def job(self, job_id: str, principal: Principal | None = None) -> GmailJob:
        owner = self.registry.require(principal, Permission.GMAIL_READ)
        self._purge()
        job = self._jobs.get(job_id)
        if job is None or job.owner.tenant_id != owner.tenant_id:
            raise ApplicationError(E.GMAIL_JOB_NOT_FOUND)
        return job

    def _purge(self) -> None:
        now = time.monotonic()
        for digest, state in list(self._states.items()):
            if now >= state.expires_at:
                state.verifier = None
                state.cancelled = True
                self._states.pop(digest, None)
                if self._flows.get(state.owner.tenant_id) is state:
                    self._flows.pop(state.owner.tenant_id, None)
        for connection in self._connections.values():
            if now >= connection.expires_at:
                connection.invalidate()
        for key, job in list(self._jobs.items()):
            if job.expires_at is not None and now >= job.expires_at:
                job.results.clear()
                del self._jobs[key]

    def _clear(self) -> None:
        for state in self._flows.values():
            state.cancelled = True
            state.verifier = None
        for connection in self._connections.values():
            connection.invalidate()
        for job in self._jobs.values():
            job.results.clear()
        self._states.clear()
        self._flows.clear()
        self._connections.clear()
        self._mailboxes.clear()
        self._jobs.clear()
