import asyncio
import time

import pytest
from pydantic import ValidationError

from app.core.exceptions import ApplicationError, ErrorCode
from app.schemas.ingestion import IngestionRequest
from app.services.ingestion_service import IngestionService
from app.services.sentiment_service import SentimentService
from app.services.webhook_service import WebhookService
from tests.helpers import Model, harness, settings, until
from tests.t06_helpers import INTEGRATION
from tests.t06_helpers import SECRET, signed
from starlette.datastructures import Headers
from app.core.webhook_security import authenticate_webhook


def manager(model=None, **overrides):
    return WebhookService(IngestionService(harness(model=model).sentiment), settings(**({"webhook_integration_id": INTEGRATION, "webhook_shared_secret": SECRET} | overrides)))


def admit(service, delivery="delivery-1", text="Late delivery."):
    raw = text.encode()
    identity = authenticate_webhook(service.settings, Headers(signed(raw, delivery)), raw, registry=service.registry)
    return service.accept(identity, raw, IngestionRequest(text=text, channel="external_api"))


async def test_worker_bound_pending_capacity_state_transitions_and_shutdown():
    gate = asyncio.Event()
    model = Model(gate=gate)
    service = manager(model, webhook_max_pending_events=2, webhook_max_concurrent_analyses=2)
    await service.start()
    try:
        assert admit(service, "one").status == "ACCEPTED"
        assert service.status("one").status == "ACCEPTED"
        await until(lambda: model.active == 1)
        admit(service, "two")
        await until(lambda: model.active == 2)
        admit(service, "three")
        admit(service, "four")
        with pytest.raises(ApplicationError) as caught:
            admit(service, "five")
        assert caught.value.code == ErrorCode.WEBHOOK_CAPACITY_EXCEEDED
        assert len(service.store.events) == 4 and service.queue.qsize() == 2
        assert service.status("one").status == "PROCESSING"
        gate.set()
        await service.queue.join()
        assert model.peak == 2 and len(model.calls) == 4
        assert all(event.status == "COMPLETED" and event.request is None for event in service.store.events.values())
    finally:
        await service.close()
    assert not service.store.events and not service.workers and service.queue.empty()


async def test_shutdown_cancels_active_drains_pending_and_releases_raw_references():
    model = Model(gate=asyncio.Event())
    service = manager(model, webhook_max_concurrent_analyses=1)
    await service.start()
    admit(service, "one")
    await until(lambda: model.active == 1)
    admit(service, "two")
    events = list(service.store.events.values())
    tasks = list(service.workers)
    await service.close()
    await service.queue.join()
    assert model.active == 0 and all(t.done() for t in tasks)
    assert all(event.request is None for event in events)
    assert not service.store.events and service.queue.empty()
    with pytest.raises(ApplicationError) as caught:
        admit(service, "three")
    assert caught.value.code == ErrorCode.WEBHOOK_UNAVAILABLE


@pytest.mark.parametrize("kind,expected", [("provider", ErrorCode.UPSTREAM_UNAVAILABLE), ("unexpected", ErrorCode.INTERNAL_ERROR), ("timeout", ErrorCode.WEBHOOK_PROCESSING_TIMEOUT)])
async def test_worker_failures_and_deadline_are_sanitized(kind, expected):
    error = ApplicationError(ErrorCode.UPSTREAM_UNAVAILABLE) if kind == "provider" else RuntimeError("private provider body")
    model = Model(errors={"Late delivery.": error}, gate=asyncio.Event() if kind == "timeout" else None)
    service = manager(model, webhook_processing_timeout_seconds=.02)
    await service.start()
    try:
        admit(service)
        await service.queue.join()
        status = service.status("delivery-1")
        assert status.status == "FAILED" and status.error_code == expected
        assert "private" not in status.model_dump_json() and service.store.events[(INTEGRATION, "delivery-1")].request is None
    finally:
        await service.close()


async def test_retention_expiry_full_store_never_evicts_active_and_fresh_retry_is_duplicate():
    gate = asyncio.Event()
    service = manager(Model(gate=gate), webhook_max_pending_events=1, webhook_max_concurrent_analyses=1, webhook_max_retained_events=2)
    await service.start()
    try:
        admit(service, "active")
        await until(lambda: service.status("active").status == "PROCESSING")
        admit(service, "pending")
        assert admit(service, "active").status == "DUPLICATE"
        with pytest.raises(ApplicationError) as error:
            admit(service, "new")
        assert error.value.code == ErrorCode.WEBHOOK_CAPACITY_EXCEEDED
        assert service.status("active").status == "PROCESSING"
        gate.set()
        await service.queue.join()
        with pytest.raises(ApplicationError) as error:
            admit(service, "new")
        assert error.value.code == ErrorCode.WEBHOOK_CAPACITY_EXCEEDED
        service.store.events[(INTEGRATION, "active")].expires_at = time.monotonic() - 1
        with pytest.raises(ApplicationError) as error:
            service.status("active")
        assert error.value.code == ErrorCode.WEBHOOK_EVENT_NOT_FOUND
        assert admit(service, "active").status == "ACCEPTED"
        await service.queue.join()
    finally:
        await service.close()


async def test_missing_provider_configuration_is_rejected_before_reserving():
    service = WebhookService(IngestionService(SentimentService(None)), settings(webhook_integration_id=INTEGRATION, webhook_shared_secret=SECRET))
    await service.start()
    try:
        with pytest.raises(ApplicationError) as error:
            admit(service)
        assert error.value.code == ErrorCode.GROQ_NOT_CONFIGURED
        assert not service.store.events and service.queue.empty()
    finally:
        await service.close()


@pytest.mark.parametrize("overrides", [
    {"webhook_event_ttl_seconds": 599}, {"webhook_max_retained_events": 21},
    {"webhook_shared_secret": "too-short"}, {"webhook_integration_id": "bad.id"},
    {"webhook_max_pending_events": 0}, {"webhook_max_concurrent_analyses": 0},
])
def test_configuration_prevents_unsafe_capacities_or_replay_retention(overrides):
    with pytest.raises(ValidationError):
        settings(**overrides)


async def test_background_sweeper_expires_terminal_metadata_without_a_lookup(monkeypatch):
    # This test uses a 5 ms replay window; freeze wall time to issue a valid
    # integer-seconds signature while monotonic expiry still advances normally.
    monkeypatch.setattr("app.core.webhook_security.time.time", lambda: 2000000000)
    service = manager(webhook_timestamp_tolerance_seconds=.005, webhook_event_ttl_seconds=.02)
    await service.start()
    try:
        admit(service)
        await service.queue.join()
        assert len(service.store.events) == 1
        await until(lambda: not service.store.events)
    finally:
        await service.close()
