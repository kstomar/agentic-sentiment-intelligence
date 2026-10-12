"""Batch domain objects and an explicit ephemeral adapter for isolated unit tests."""

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from uuid import uuid4

from app.core.exceptions import ApplicationError, ErrorCode
from app.core.tenant_auth import Permission, Principal, TenantRegistry, current_principal
from app.schemas.batch import BatchReport, BatchResult, JobState, JobStatus, ParsedRecord, RecordState, UploadOptions


@dataclass(slots=True)
class Job:
    job_id: str
    owner: Principal = field(repr=False)
    options: UploadOptions
    records: list[ParsedRecord] = field(repr=False)
    skipped_blank_rows: int
    total_records: int
    valid_records: int
    status: JobState = JobState.PENDING
    results: list[BatchResult] = field(default_factory=list, repr=False)
    error_code: ErrorCode | None = None
    report: BatchReport | None = field(default=None, repr=False)
    expires_at: float | None = None

    def snapshot(self) -> JobStatus:
        successful = sum(result.status == RecordState.SUCCESS for result in self.results)
        return JobStatus(
            job_id=self.job_id, status=self.status, total_records=self.total_records,
            processed_records=len(self.results), successful_records=successful,
            failed_records=len(self.results) - successful,
            progress_percentage=round(len(self.results) * 100 / self.total_records, 2),
            error_code=self.error_code,
        )

    def erase(self) -> None:
        for record in self.records:
            record.text = None
        self.records.clear()
        self.results.clear()
        self.report = None


class JobStore:
    """Ephemeral test adapter; production FastAPI uses PostgresJobStore."""

    def __init__(self, ttl_seconds: float, *, clock: Callable[[], float] = time.monotonic, registry: TenantRegistry | None = None) -> None:
        self._jobs: dict[str, Job] = {}
        self._registry = registry
        self._ttl = ttl_seconds
        self._clock = clock

    def _authorize(self, principal: Principal | None, permission: Permission) -> Principal:
        principal = current_principal() if principal is None else principal
        if not isinstance(principal, Principal):
            raise ApplicationError(ErrorCode.AUTHENTICATION_FAILED)
        registry = self._registry if self._registry is not None else principal._authority
        if not isinstance(registry, TenantRegistry):
            raise ApplicationError(ErrorCode.AUTHENTICATION_FAILED)
        verified = registry.require(principal, permission)
        if self._registry is None:
            self._registry = registry
        return verified

    @property
    def jobs(self) -> Mapping[str, Job]:
        """Owner-filtered inspection; no public unrestricted job lookup."""
        principal = self._authorize(None, Permission.BATCH_READ)
        self._purge()
        return MappingProxyType({key: job for key, job in self._jobs.items() if job.owner.tenant_id == principal.tenant_id})

    def _bind_registry(self, registry: TenantRegistry) -> None:
        # Caller-owned stores must not acquire a new authorization universe merely
        # because another service is composed around them.
        if self._registry is not None and self._registry is not registry:
            for job in self._jobs.values():
                registry.require(job.owner, Permission.BATCH_CREATE)
        self._registry = registry

    def _purge(self) -> None:
        for identifier, job in list(self._jobs.items()):
            if job.expires_at is not None and self._clock() >= job.expires_at:
                job.erase()
                del self._jobs[identifier]

    def add(self, options: UploadOptions, records: list[ParsedRecord], skipped: int, *, principal: Principal | None = None) -> Job:
        principal = self._authorize(principal, Permission.BATCH_CREATE)
        job = Job(
            job_id=uuid4().hex, owner=principal, options=options, records=records, skipped_blank_rows=skipped,
            total_records=len(records), valid_records=sum(row.validation_error is None for row in records),
        )
        self._jobs[job.job_id] = job
        return job

    def get(self, job_id: str, *, principal: Principal | None = None) -> Job:
        principal = self._authorize(principal, Permission.BATCH_READ)
        self._purge()
        job = self._jobs.get(job_id)
        if job is None or job.owner.tenant_id != principal.tenant_id:
            raise ApplicationError(ErrorCode.BATCH_JOB_NOT_FOUND)
        return job

    def _terminal(self, job: Job, status: JobState) -> None:
        job.status = status
        job.expires_at = self._clock() + self._ttl
        for record in job.records:
            record.text = None
        job.records.clear()

    def _clear(self) -> None:
        for job in self._jobs.values():
            job.erase()
        self._jobs.clear()
