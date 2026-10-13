"""Fixed workers and atomic admission on one event loop; acknowledgments are not results."""

import asyncio
import hashlib
from typing import Callable, TypeVar
from uuid import uuid4

from anyio import CancelScope

from app.core.config import Settings
from app.core.exceptions import ApplicationError, ErrorCode
from app.core.tenant_auth import Permission, Principal, TenantRegistry, principal_context
from app.core.webhook_security import SignedDelivery, verify_delivery
from app.schemas.ingestion import EventResult, EventState, EventStatus, IngestionRequest, IngestionResponse, WebhookAcknowledgment, WebhookPayload
from app.schemas.sentiment import SentimentResponse
from app.services.ingestion_service import IngestionService, normalize_event
from app.storage.event_store import Event, EventStore
from app.storage.postgres_event_store import PostgresEventStore

T = TypeVar("T")


class WebhookService:
    def __init__(self, ingestion: IngestionService, settings: Settings, *, registry: TenantRegistry | None = None,
                 store: EventStore | PostgresEventStore | None = None) -> None:
        self.ingestion = ingestion
        self.settings = settings
        self.registry = registry if registry is not None else TenantRegistry(settings)
        # FastAPI supplies PostgreSQL. The ephemeral adapter is retained for
        # explicitly isolated unit tests and never selected as a DB fallback.
        self.store = store if store is not None else EventStore(settings.webhook_max_retained_events, settings.webhook_event_ttl_seconds, self.registry)
        self.queue: asyncio.Queue[Event] = asyncio.Queue(settings.webhook_max_pending_events)
        self.workers: list[asyncio.Task[None]] = []
        self.cleaner: asyncio.Task[None] | None = None
        self.running = False
        self._ready = asyncio.Event()
        self._active: dict[str, int] = {}
        self._admission_lock = asyncio.Lock()
        self._persistence_failed = False

    @staticmethod
    async def _io(function: Callable[..., T], *args, **kwargs) -> T:
        task = asyncio.create_task(asyncio.to_thread(function, *args, **kwargs))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            # ASGI disconnects use AnyIO level cancellation: cleanup awaits need
            # an explicit shield as well as asyncio's in-flight commit shield.
            with CancelScope(shield=True):
                await asyncio.gather(task, return_exceptions=True)
            raise

    async def start(self) -> None:
        if self.running:
            return
        if isinstance(self.store, PostgresEventStore):
            await self._io(self.store.start)
        self.running = True
        self.workers = [asyncio.create_task(self._worker()) for _ in range(self.settings.webhook_max_concurrent_analyses)]
        self.cleaner = asyncio.create_task(self._cleanup())

    async def close(self) -> None:
        self.running = False
        tasks = [*self.workers, *([self.cleaner] if self.cleaner is not None else [])]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        while not self.queue.empty():
            event = self.queue.get_nowait()
            try:
                await self._finish_event(event, error=ErrorCode.WEBHOOK_UNAVAILABLE)
            finally:
                event.request = None
                self.queue.task_done()
        if isinstance(self.store, EventStore):
            self.store._clear()
        self._active.clear()
        self.workers.clear()
        self.cleaner = None

    def _verify(self, identity: SignedDelivery, raw_body: bytes) -> Principal:
        if not isinstance(identity, SignedDelivery) or identity.principal is None:
            raise ApplicationError(ErrorCode.WEBHOOK_AUTHENTICATION_FAILED)
        principal = self.registry.require(identity.principal, Permission.INGEST)
        if verify_delivery(self.settings, identity, raw_body, self.registry).principal != principal:
            raise ApplicationError(ErrorCode.WEBHOOK_AUTHENTICATION_FAILED)
        if not self.running or self._persistence_failed or not all(not worker.done() for worker in self.workers):
            raise ApplicationError(ErrorCode.WEBHOOK_UNAVAILABLE)
        return principal

    async def submit(self, identity: SignedDelivery, raw_body: bytes, request: IngestionRequest) -> WebhookAcknowledgment:
        if isinstance(self.store, EventStore):
            return self.accept(identity, raw_body, request)
        principal = self._verify(identity, raw_body)
        # Bind persisted text to the authenticated bytes, even for non-HTTP callers.
        normalized = normalize_event(WebhookPayload.model_validate_json(raw_body))
        if normalized != request:
            raise ApplicationError(ErrorCode.WEBHOOK_AUTHENTICATION_FAILED)
        event = Event(principal, identity.integration_id, identity.delivery_id, hashlib.sha256(raw_body).digest(), normalized)
        try:
            async with self._admission_lock:
                created = await self._io(self.store.reserve, event, kind="webhook",
                    configuration_error=self.ingestion.sentiment.configuration_error, queue_full=self.queue.full())
                if created:
                    if not self.running:
                        await self._finish_event(event, error=ErrorCode.WEBHOOK_UNAVAILABLE)
                        raise ApplicationError(ErrorCode.WEBHOOK_UNAVAILABLE)
                    self.queue.put_nowait(event)
                    self._ready.set()
        except asyncio.CancelledError:
            # The operation token prevents an interrupted retry from modifying
            # the earlier event. Await any in-flight commit before settling.
            with CancelScope(shield=True):
                await self._finish_event(event, error=ErrorCode.WEBHOOK_UNAVAILABLE)
            raise
        return WebhookAcknowledgment(delivery_id=event.delivery_id,
            status="ACCEPTED" if created else "DUPLICATE",
            message="Feedback event accepted for analysis." if created else "Feedback event already accepted.")

    async def reserve_direct(self, request: IngestionRequest, *, principal: Principal) -> Event | None:
        owner = self.registry.require(principal, Permission.INGEST)
        if isinstance(self.store, EventStore):
            return None  # Explicit historical test adapter only.
        if not self.running or self._persistence_failed:
            raise ApplicationError(ErrorCode.WEBHOOK_UNAVAILABLE)
        event = Event(owner, "", uuid4().hex, b"", IngestionRequest.model_validate(request.model_dump()))
        try:
            await self._io(self.store.reserve, event, kind="direct",
                           configuration_error=self.ingestion.sentiment.configuration_error)
        except asyncio.CancelledError:
            with CancelScope(shield=True):
                await self._finish_event(event, error=ErrorCode.WEBHOOK_UNAVAILABLE)
            raise
        return event

    async def process_direct(self, event: Event) -> IngestionResponse:
        self.registry.require(event.owner, Permission.INGEST)
        if not isinstance(self.store, PostgresEventStore):
            raise ApplicationError(ErrorCode.WEBHOOK_UNAVAILABLE)
        try:
            if not await self._io(self.store.processing, event):
                raise ApplicationError(ErrorCode.WEBHOOK_UNAVAILABLE)
            assert event.request is not None
            with principal_context(event.owner):
                response = await self.ingestion.analyze(event.request)
            await self._finish_event(event, analysis=response.analysis, strict=True)
            return response
        except asyncio.CancelledError:
            with CancelScope(shield=True):
                await self._finish_event(event, error=ErrorCode.WEBHOOK_UNAVAILABLE)
            raise
        except ApplicationError as error:
            await self._finish_event(event, error=error.code)
            raise
        except Exception:
            await self._finish_event(event, error=ErrorCode.INTERNAL_ERROR)
            raise ApplicationError(ErrorCode.INTERNAL_ERROR) from None
        finally:
            event.request = None

    async def _finish_event(self, event: Event, *, analysis: SentimentResponse | None = None,
                            error: ErrorCode | None = None, strict: bool = False) -> None:
        if isinstance(self.store, EventStore):
            self.store._finish(event, error)
            return
        try:
            await self._io(self.store.finish, event, analysis, error)
        except ApplicationError as failure:
            if not strict and failure.code == ErrorCode.WEBHOOK_EVENT_NOT_FOUND:
                return  # Cancelled duplicate reservation did not create this operation.
            # Never acknowledge a result commit that failed or repeat inference.
            # Existing rows are terminalized safely at the next exclusive startup.
            self._persistence_failed = True
            if strict:
                raise ApplicationError(ErrorCode.WEBHOOK_UNAVAILABLE) from None

    def accept(self, identity: SignedDelivery, raw_body: bytes, request: IngestionRequest) -> WebhookAcknowledgment:
        """Caller supplies authenticated context. No await between lookup and queue reservation."""
        principal = self._verify(identity, raw_body)
        if not isinstance(self.store, EventStore):
            raise ApplicationError(ErrorCode.WEBHOOK_UNAVAILABLE)  # Use async submit for PostgreSQL.
        # Recheck signed scope/bytes at this public service boundary; a modified
        # delivery object cannot transplant a previously authenticated principal.
        verified = verify_delivery(self.settings, identity, raw_body, self.registry)
        if verified.principal != principal:
            raise ApplicationError(ErrorCode.WEBHOOK_AUTHENTICATION_FAILED)
        integration_id, delivery_id = identity.integration_id, identity.delivery_id
        if not self.running or not all(not worker.done() for worker in self.workers):
            raise ApplicationError(ErrorCode.WEBHOOK_UNAVAILABLE)
        self.store._purge()
        key = (principal.tenant_id, delivery_id)
        digest = hashlib.sha256(raw_body).digest()  # timestamp deliberately excluded
        existing = self.store._events.get(key)
        if existing is not None:
            if existing.integration_id != integration_id:
                raise ApplicationError(ErrorCode.WEBHOOK_DELIVERY_COLLISION)
            if existing.digest != digest:
                raise ApplicationError(ErrorCode.WEBHOOK_DELIVERY_CONFLICT)
            return WebhookAcknowledgment(delivery_id=delivery_id, status="DUPLICATE", message="Feedback event already accepted.")
        configuration_error = self.ingestion.sentiment.configuration_error
        if configuration_error is not None:
            raise ApplicationError(configuration_error)
        if self.queue.full() or len(self.store._events) >= self.store.maximum:
            raise ApplicationError(ErrorCode.WEBHOOK_CAPACITY_EXCEEDED)
        pending = sum(e.owner.tenant_id == principal.tenant_id for e in self.store._events.values() if e.status == EventState.ACCEPTED)
        retained = sum(e.owner.tenant_id == principal.tenant_id for e in self.store._events.values())
        if (pending >= self.registry.limit(self.settings.tenant_max_pending_events, self.settings.webhook_max_pending_events)
            or retained >= self.registry.limit(self.settings.tenant_max_retained_events, self.store.maximum)):
            raise ApplicationError(ErrorCode.TENANT_CAPACITY_EXCEEDED)
        event = Event(principal, integration_id, delivery_id, digest, request)
        self.store._events[key] = event
        self.queue.put_nowait(event)
        self._ready.set()
        return WebhookAcknowledgment(delivery_id=delivery_id, status="ACCEPTED", message="Feedback event accepted for analysis.")

    def status(self, delivery_id: str, *, principal: Principal | None = None) -> EventStatus:
        if isinstance(self.store, PostgresEventStore):
            return self.store.status(delivery_id, principal=principal)
        return self.store.get(delivery_id, principal=principal).public_status()

    def result(self, delivery_id: str, *, principal: Principal | None = None) -> EventResult | EventStatus:
        self.registry.require(principal, Permission.EVENT_READ)
        if not isinstance(self.store, PostgresEventStore):
            raise ApplicationError(ErrorCode.WEBHOOK_UNAVAILABLE)
        value = self.store.get(delivery_id, principal=principal)
        if value.status in {EventState.ACCEPTED, EventState.PROCESSING}:
            return EventStatus(delivery_id=value.delivery_id, status=value.status, error_code=value.error_code)
        return value

    async def _next_event(self) -> Event:
        """Skip saturated owners, so their pending work cannot occupy all workers."""
        while True:
            for _ in range(self.queue.qsize()):
                event = self.queue.get_nowait()
                owner = event.owner.tenant_id
                limit = self.registry.limit(self.settings.tenant_max_concurrent_webhook_analyses, self.settings.webhook_max_concurrent_analyses)
                if self._active.get(owner, 0) < limit:
                    self._active[owner] = self._active.get(owner, 0) + 1
                    return event
                self.queue.put_nowait(event)
                self.queue.task_done()
            self._ready.clear()
            await self._ready.wait()

    async def _worker(self) -> None:
        while True:
            event = await self._next_event()
            try:
                if isinstance(self.store, PostgresEventStore):
                    if not await self._io(self.store.processing, event):
                        continue
                event.status = EventState.PROCESSING
                async with asyncio.timeout(self.settings.webhook_processing_timeout_seconds):
                    assert event.request is not None
                    with principal_context(event.owner):
                        response = await self.ingestion.analyze(event.request)
                await self._finish_event(event, analysis=response.analysis)
            except asyncio.CancelledError:
                await self._finish_event(event, error=ErrorCode.WEBHOOK_UNAVAILABLE)
                raise
            except TimeoutError:
                await self._finish_event(event, error=ErrorCode.WEBHOOK_PROCESSING_TIMEOUT)
            except ApplicationError as error:
                await self._finish_event(event, error=error.code)
            except Exception:
                await self._finish_event(event, error=ErrorCode.INTERNAL_ERROR)
            finally:
                event.request = None
                owner = event.owner.tenant_id
                self._active[owner] -= 1
                if not self._active[owner]:
                    del self._active[owner]
                self.queue.task_done()
                self._ready.set()
                # Do not retain a completed request through an idle worker frame.
                del event

    async def _cleanup(self) -> None:
        while True:
            await asyncio.sleep(min(30, self.settings.webhook_event_ttl_seconds / 2))
            if isinstance(self.store, PostgresEventStore):
                if self.store.database.available:
                    try:
                        await self._io(self.store._purge)
                    except ApplicationError:
                        pass
            else:
                self.store._purge()
