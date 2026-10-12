"""Bounded in-process batch workers, shared permits, progress, and sensitive-data TTL."""

import asyncio
from collections.abc import Callable
from typing import Any, TypeVar

from app.core.config import Settings
from app.core.exceptions import ApplicationError, ErrorCode
from app.core.tenant_auth import Permission, Principal, TenantRegistry, principal_context
from app.schemas.batch import (
    BatchDownload, BatchReport, JobAccepted, JobState, JobStatus, RecordState, ResultsPage,
    TERMINAL_STATES, UploadOptions,
)
from app.services.file_parser import FileParser, ParsedFile
from app.services.reporting_service import ReportingService
from app.services.sentiment_service import SentimentService
from app.storage.job_store import Job, JobStore
from app.storage.postgres_job_store import PostgresJobStore
from app.tools.batch_analysis import analyze_record, failed_result

T = TypeVar("T")

FATAL_PROVIDER_ERRORS = frozenset({
    ErrorCode.GROQ_NOT_CONFIGURED, ErrorCode.GROQ_MODEL_UNSUPPORTED,
    ErrorCode.GROQ_CONFIGURATION_ERROR, ErrorCode.UPSTREAM_AUTHENTICATION_FAILED,
    ErrorCode.UPSTREAM_REQUEST_REJECTED,
})


class BatchService:
    """At most one worker per accepted job; no row-task fanout or unbounded queue."""

    def __init__(
        self, sentiment_service: SentimentService, settings: Settings, *, store: JobStore | None = None,
        reporter: ReportingService | None = None,
        registry: TenantRegistry | None = None,
    ) -> None:
        self._sentiment = sentiment_service
        self._settings = settings
        self.registry = registry if registry is not None else TenantRegistry(settings)
        self._store = store if store is not None else PostgresJobStore(settings,self.registry)
        self._store._bind_registry(self.registry)
        self._reporter = reporter if reporter is not None else ReportingService()
        self._parser = FileParser(
            max_bytes=settings.batch_max_upload_bytes, max_records=settings.batch_max_records,
            max_text=settings.batch_max_text_chars, max_extracted=settings.batch_max_extracted_bytes,
        )
        self._permits = asyncio.Semaphore(settings.batch_model_concurrency)
        self._tasks: set[asyncio.Task[None]] = set()
        self._parses: set[asyncio.Future[ParsedFile]] = set()
        self._reservations = 0
        self._tenant_reservations: dict[str, int] = {}
        self._fatal_error: ErrorCode | None = None
        self._closing = False
        self._cleanup: asyncio.Task[None] | None = None
        self._admission_lock = asyncio.Lock()
        self._active_ids: set[str] = set()

    async def start(self) -> None:
        if isinstance(self._store, PostgresJobStore):
            await self._io(self._store.start)
            if self._store.available:
                await self._io(self._store._purge)
                await self._recover()
        if self._cleanup is None:
            self._cleanup = asyncio.create_task(self._sweep(), name="batch-expiration")

    async def close(self) -> None:
        self._closing = True
        for task in tuple(self._tasks):
            task.cancel()
        if self._tasks:
            await asyncio.gather(*tuple(self._tasks), return_exceptions=True)
        if self._parses:
            await asyncio.gather(*(asyncio.shield(item) for item in tuple(self._parses)), return_exceptions=True)
        if self._cleanup is not None:
            self._cleanup.cancel()
            await asyncio.gather(self._cleanup, return_exceptions=True)
        if isinstance(self._store, PostgresJobStore):
            await self._io(self._store.close)
        else:
            self._store._clear()

    async def _sweep(self) -> None:
        interval = 1.0 if isinstance(self._store, PostgresJobStore) else max(0.01, min(15, self._settings.batch_job_ttl_seconds / 2))
        while True:
            await asyncio.sleep(interval)
            if isinstance(self._store, PostgresJobStore):
                if not self._store.available:
                    for task in tuple(self._tasks): task.cancel()
                    continue
                try:
                    await self._io(self._store._purge)
                    await self._recover()
                except ApplicationError:
                    continue  # Safe bounded retry; no SQL/credential diagnostics.
            else:
                self._store._purge()

    @staticmethod
    async def _io(function: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        task = asyncio.create_task(asyncio.to_thread(function, *args, **kwargs))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            # A cancelled coroutine must not abandon an in-flight DB commit.
            await asyncio.gather(task, return_exceptions=True)
            raise

    def _spawn(self, job: Job) -> None:
        if job.job_id in self._active_ids:
            if isinstance(self._store,PostgresJobStore) and self._store._jobs.get(job.job_id) is not job:
                for record in job.records:record.text=None
                job.records.clear()
            return
        self._active_ids.add(job.job_id)
        if isinstance(self._store,PostgresJobStore):self._store._jobs[job.job_id]=job
        task = asyncio.create_task(self._run_owned(job), name=f"batch-{job.job_id}")
        self._tasks.add(task)
        def done(finished):
            self._tasks.discard(finished)
            self._active_ids.discard(job.job_id)
            if isinstance(self._store,PostgresJobStore):self._store._jobs.pop(job.job_id,None)
        task.add_done_callback(done)

    async def _recover(self) -> None:
        if self._closing: return
        remaining = self._settings.batch_max_active_jobs - len(self._active_ids)
        jobs = await self._io(self._store._recoverable, remaining, set(self._active_ids))
        for job in jobs:
            owner_active = sum(j.owner.tenant_id == job.owner.tenant_id for key,j in self._store._jobs.items() if key in self._active_ids)
            if owner_active >= self.registry.batch_active_limit:
                for record in job.records: record.text=None
                continue
            self._spawn(job)

    async def _reserve_for(self, principal: Principal) -> None:
        if not isinstance(self._store, PostgresJobStore):
            self._reserve(principal)
            return
        async with self._admission_lock:
            if self._closing or not self._store.available: raise ApplicationError(ErrorCode.BATCH_UNAVAILABLE)
            if self._fatal_error is not None: raise ApplicationError(self._fatal_error)
            await self._io(self._store._purge)
            active,total,owned_active,owned = await self._io(self._store._counts,principal.tenant_id)
            reserved=self._tenant_reservations.get(principal.tenant_id,0)
            if active+self._reservations >= self._settings.batch_max_active_jobs or total+self._reservations >= self._settings.batch_max_retained_jobs:
                raise ApplicationError(ErrorCode.BATCH_CAPACITY_EXCEEDED)
            if owned_active+reserved >= self.registry.batch_active_limit or owned+reserved >= self.registry.limit(self._settings.tenant_max_retained_batch_jobs,self._settings.batch_max_retained_jobs):
                raise ApplicationError(ErrorCode.TENANT_CAPACITY_EXCEEDED)
            self._reservations+=1
            self._tenant_reservations[principal.tenant_id]=reserved+1

    def _reserve(self, principal: Principal) -> None:
        self._store._purge()
        if self._closing:
            raise ApplicationError(ErrorCode.BATCH_UNAVAILABLE)
        if self._fatal_error is not None:
            raise ApplicationError(self._fatal_error)
        jobs = self._store._jobs.values()
        active = sum(job.status not in TERMINAL_STATES for job in jobs)
        if (
            active + self._reservations >= self._settings.batch_max_active_jobs
            or len(self._store._jobs) + self._reservations >= self._settings.batch_max_retained_jobs
        ):
            raise ApplicationError(ErrorCode.BATCH_CAPACITY_EXCEEDED)
        owned = [job for job in jobs if job.owner.tenant_id == principal.tenant_id]
        reserved = self._tenant_reservations.get(principal.tenant_id, 0)
        if (sum(job.status not in TERMINAL_STATES for job in owned) + reserved >= self.registry.batch_active_limit
            or len(owned) + reserved >= self.registry.limit(self._settings.tenant_max_retained_batch_jobs, self._settings.batch_max_retained_jobs)):
            raise ApplicationError(ErrorCode.TENANT_CAPACITY_EXCEEDED)
        self._reservations += 1
        self._tenant_reservations[principal.tenant_id] = reserved + 1

    def _release(self, principal: Principal) -> None:
        self._reservations -= 1
        self._tenant_reservations[principal.tenant_id] -= 1
        if not self._tenant_reservations[principal.tenant_id]:
            del self._tenant_reservations[principal.tenant_id]

    def _abandoned_parse(self, future: asyncio.Future[ParsedFile], principal: Principal) -> None:
        self._release(principal)
        if not future.cancelled() and future.exception() is None:
            parsed = future.result()
            for record in parsed.records:
                record.text = None
            parsed.records.clear()

    async def submit(
        self, data: bytes, filename: str, content_type: str, options: UploadOptions, *, principal: Principal | None = None,
    ) -> JobAccepted:
        principal = self.registry.require(principal, Permission.BATCH_CREATE)
        await self._reserve_for(principal)
        try:
            future = asyncio.get_running_loop().run_in_executor(
                None, self._parser.parse, data, filename, content_type, options
            )
        except Exception:
            self._release(principal)
            raise ApplicationError(ErrorCode.BATCH_UNAVAILABLE) from None
        self._parses.add(future)
        future.add_done_callback(self._parses.discard)
        try:
            parsed = await asyncio.shield(future)
        except asyncio.CancelledError:
            # A cancelled HTTP request cannot free its parse slot while a thread
            # still holds uploaded bytes; release and erase only after it finishes.
            future.add_done_callback(lambda done: self._abandoned_parse(done, principal))
            raise
        except Exception:
            self._release(principal)
            raise
        try:
            if self._closing:
                raise ApplicationError(ErrorCode.BATCH_UNAVAILABLE)
            if isinstance(self._store, PostgresJobStore):
                job = await self._io(self._store.add,options,parsed.records,parsed.skipped_blank_rows,principal=principal)
            else:
                job = self._store.add(options,parsed.records,parsed.skipped_blank_rows,principal=principal)
        except BaseException:
            for record in parsed.records: record.text=None
            parsed.records.clear()
            raise
        finally:
            self._release(principal)
        self._spawn(job)
        return JobAccepted(job_id=job.job_id,total_records=job.total_records)

    async def _run_owned(self, job: Job) -> None:
        with principal_context(job.owner):
            if isinstance(self._store, PostgresJobStore):
                await self._run_persistent(job)
            else:
                await self._run(job)

    def _abort_remaining(self, job: Job, error: ErrorCode, attempted_id: str | None = None) -> None:
        job.error_code = error
        for record in job.records[len(job.results):]:
            job.results.append(failed_result(
                record, record.validation_error or error, attempted=record.meta.feedback_id == attempted_id,
            ))
            record.text = None

    async def _run(self, job: Job) -> None:
        job.status = JobState.RUNNING
        attempted_id = None
        try:
            async with asyncio.timeout(self._settings.batch_job_timeout_seconds):
                for record in job.records:
                    attempted_id = None
                    if record.validation_error is not None:
                        result = failed_result(record, record.validation_error)
                    else:
                        async with self._permits:
                            if self._fatal_error is not None:
                                job.error_code = self._fatal_error
                                result = failed_result(record, self._fatal_error)
                            else:
                                attempted_id = record.meta.feedback_id
                                result = await analyze_record(record, job.options.business_type, self._sentiment)
                                if result.error_code in FATAL_PROVIDER_ERRORS:
                                    self._fatal_error = result.error_code
                                    job.error_code = result.error_code
                    job.results.append(result)
                    record.text = None
        except asyncio.CancelledError:
            self._abort_remaining(job, ErrorCode.BATCH_UNAVAILABLE, attempted_id)
            for record in job.records:
                record.text = None
            raise
        except TimeoutError:
            self._abort_remaining(job, ErrorCode.BATCH_JOB_TIMEOUT, attempted_id)
        except Exception:
            self._abort_remaining(job, ErrorCode.INTERNAL_ERROR, attempted_id)
        successes = sum(result.status == RecordState.SUCCESS for result in job.results)
        status = (
            JobState.COMPLETED if successes == job.total_records
            else JobState.PARTIAL_SUCCESS if successes else JobState.FAILED
        )
        try:
            job.report = self._reporter.build(job, status)
        except Exception:
            # Never publish unverified findings if reduction fails unexpectedly.
            job.results = [
                failed_result(record, record.validation_error or ErrorCode.BATCH_REPORT_UNAVAILABLE,
                              attempted=job.results[index].attempted if index < len(job.results) else False)
                for index, record in enumerate(job.records)
            ]
            job.report = None
            job.error_code = ErrorCode.BATCH_REPORT_UNAVAILABLE
            status = JobState.FAILED
        self._store._terminal(job, status)

    def status(self, job_id: str, *, principal: Principal | None = None) -> JobStatus:
        return self._store.get(job_id, principal=principal).snapshot()

    def report(self, job_id: str, *, principal: Principal | None = None) -> BatchReport | JobStatus:
        job = self._store.get(job_id, principal=principal)
        if job.error_code == ErrorCode.BATCH_REPORT_UNAVAILABLE:
            raise ApplicationError(ErrorCode.BATCH_REPORT_UNAVAILABLE)
        if job.status not in TERMINAL_STATES:
            return job.snapshot()
        if job.report is None:
            raise ApplicationError(ErrorCode.BATCH_REPORT_UNAVAILABLE)
        return job.report.model_copy(deep=True)

    def results(self, job_id: str, *, page: int = 1, page_size: int = 25, principal: Principal | None = None) -> ResultsPage:
        principal = self.registry.require(principal, Permission.BATCH_READ)
        if page < 1 or not 1 <= page_size <= 100:
            raise ApplicationError(ErrorCode.VALIDATION_ERROR)
        job = self._store.get(job_id, principal=principal)
        start = (page - 1) * page_size
        return ResultsPage(
            job_id=job_id, status=job.status, page=page, page_size=page_size,
            total_results=len(job.results), results=[item.model_copy(deep=True) for item in job.results[start:start + page_size]],
        )

    def download(self, job_id: str, *, principal: Principal | None = None) -> BatchDownload | JobStatus:
        principal = self.registry.require(principal, Permission.BATCH_READ)
        report = self.report(job_id, principal=principal)
        if isinstance(report, JobStatus) and not isinstance(report, BatchReport):
            return report
        job = self._store.get(job_id, principal=principal)
        return BatchDownload(report=report, results=[item.model_copy(deep=True) for item in job.results])

    async def _run_persistent(self, job: Job) -> None:
        """Same T01/reducer and limits; durable outcomes precede visible progress."""
        attempted_id = None
        try:
            abort_code = job.error_code if job.error_code in FATAL_PROVIDER_ERRORS else None
            job.error_code = abort_code
            if not await self._io(self._store.running, job):
                for record in job.records: record.text=None
                job.records.clear()
                return
            async with asyncio.timeout(self._settings.batch_job_timeout_seconds):
                settled_ids = {row.feedback_id for row in job.results}
                for record in job.records:
                    identifier = record.meta.feedback_id
                    if identifier in settled_ids:
                        continue
                    while True:
                        delay = 0
                        async with self._permits:
                            token, delay = await self._io(self._store.claim, job, identifier)
                            if token is not None:
                                attempted_id = None
                                if record.validation_error is not None or record.text is None:
                                    result = failed_result(record, record.validation_error or ErrorCode.BATCH_INVALID_TEXT)
                                elif abort_code is not None or self._fatal_error is not None:
                                    result = failed_result(record, abort_code or self._fatal_error,
                                        attempted=await self._io(self._store._has_attempted, job, identifier))
                                else:
                                    await self._io(self._store.attempted,job,record,token)
                                    attempted_id = identifier
                                    try:
                                        async with asyncio.timeout(self._settings.groq_timeout_seconds):
                                            result = await analyze_record(record,job.options.business_type,self._sentiment)
                                    except TimeoutError:
                                        result = failed_result(record,ErrorCode.UPSTREAM_TIMEOUT,attempted=True)
                                if result.error_code in FATAL_PROVIDER_ERRORS:
                                    abort_code = result.error_code
                                    self._fatal_error = result.error_code
                                    job.error_code = result.error_code
                                await self._io(self._store.save_result,job,record,result,token)
                                job.results.append(result)
                                job.results.sort(key=lambda item:item.source_row)
                                settled_ids.add(identifier)
                                record.text = None
                        if delay:
                            await asyncio.sleep(delay)
                            continue
                        if token is None:
                            job.results = await self._io(self._store._worker_results,job)
                            settled_ids = {r.feedback_id for r in job.results}
                        break
            await self._complete_persistent(job)
        except asyncio.CancelledError:
            await self._pause_persistent(job)
            raise
        except TimeoutError:
            try:
                job.error_code = ErrorCode.BATCH_JOB_TIMEOUT
                await self._fail_remaining_persistent(job,attempted_id)
                await self._complete_persistent(job)
            except ApplicationError:
                await self._pause_persistent(job)
        except ApplicationError as error:
            job.error_code = error.code
            await self._pause_persistent(job)
        except Exception:
            await self._pause_persistent(job)

    async def _pause_persistent(self, job: Job) -> None:
        try:
            await self._io(self._store.pause,job)
        except ApplicationError:
            # Database unavailability cannot delete committed work or fake completion.
            self._store._jobs.pop(job.job_id,None)
            for record in job.records:record.text=None
            job.records.clear()

    async def _fail_remaining_persistent(self, job: Job, attempted_id: str | None) -> None:
        settled_ids={r.feedback_id for r in job.results}
        for record in job.records:
            if record.meta.feedback_id in settled_ids:continue
            while True:
                token=self._store._claims.get((job.job_id,record.meta.feedback_id))
                if token is None:
                    token,delay=await self._io(self._store.claim,job,record.meta.feedback_id)
                else:
                    delay=0
                if delay:
                    await asyncio.sleep(delay)
                    continue
                break
            if token is None:
                job.results=await self._io(self._store._worker_results,job)
                continue
            attempted=record.meta.feedback_id==attempted_id or await self._io(self._store._has_attempted,job,record.meta.feedback_id)
            result=failed_result(record,record.validation_error or job.error_code,attempted=attempted)
            await self._io(self._store.save_result,job,record,result,token)
            job.results.append(result);record.text=None
        job.results.sort(key=lambda item:item.source_row)

    async def _complete_persistent(self, job: Job) -> None:
        successes=sum(r.status==RecordState.SUCCESS for r in job.results)
        status=JobState.COMPLETED if successes==job.total_records else JobState.PARTIAL_SUCCESS if successes else JobState.FAILED
        try:
            self._reporter.build(job,status)
        except Exception:
            job.error_code=ErrorCode.BATCH_REPORT_UNAVAILABLE
            raise ApplicationError(ErrorCode.BATCH_REPORT_UNAVAILABLE) from None
        await self._io(self._store.finish,job,status)
