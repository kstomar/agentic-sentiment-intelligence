import asyncio
import time

import pytest

from tests.helpers import Model, harness, until
from tests.t06_helpers import INTEGRATION, REST, client_app, raw_event, signed

PATH = "/api/v1/webhooks/feedback"


async def test_valid_raw_signature_no_rest_key_status_and_duplicate():
    raw = b'  ' + raw_event() + b'\n'
    async with client_app() as (app, client, services):
        response = await client.post(PATH, content=raw, headers=signed(raw))
        assert response.status_code == 202 and response.json()["status"] == "ACCEPTED"
        await app.state.webhook_service.queue.join()
        status = await client.get("/api/v1/ingest/events/DELIVERY-1", headers=REST)
        assert status.json() == {"delivery_id": "DELIVERY-1", "status": "COMPLETED", "error_code": None}
        assert status.headers["Cache-Control"] == "no-store"
        assert (await client.get("/api/v1/ingest/events/DELIVERY-1")).status_code == 401
        assert (await client.get("/api/v1/ingest/events/unknown", headers=REST)).status_code == 404
        retry = await client.post(PATH, content=raw, headers=signed(raw, timestamp=int(time.time()) + 1))
        assert retry.status_code == 200 and retry.json()["status"] == "DUPLICATE"
        assert len(services.model.calls) == 1
        stored = app.state.webhook_service.store.events[(INTEGRATION, "DELIVERY-1")]
        assert stored.request is None and stored.expires_at is not None


@pytest.mark.parametrize("header,value", [
    ("X-Feedback-Signature", "sha256=" + "0" * 64), ("X-Feedback-Signature", "bad"),
    ("X-Feedback-Signature", "sha256=" + "F" * 64),
    ("X-Feedback-Integration-Id", "unknown"), ("X-Feedback-Integration-Id", "bad.id"),
    ("X-Feedback-Delivery-Id", "OTHER"), ("X-Feedback-Delivery-Id", "bad/id"),
    ("X-Feedback-Timestamp", "nonsense"), ("X-Feedback-Timestamp", "0"),
])
async def test_tampered_or_malformed_signed_headers(header, value):
    raw = raw_event()
    async with client_app() as (_, client, services):
        response = await client.post(PATH, content=raw, headers=signed(raw) | {header: value})
        assert response.status_code == 401
        assert not services.model.calls


@pytest.mark.parametrize("header", ["X-Feedback-Integration-Id", "X-Feedback-Delivery-Id", "X-Feedback-Timestamp", "X-Feedback-Signature"])
async def test_missing_signed_headers(header):
    raw = raw_event()
    headers = signed(raw)
    del headers[header]
    async with client_app() as (_, client, services):
        assert (await client.post(PATH, content=raw, headers=headers)).status_code == 401
        assert not services.model.calls


@pytest.mark.parametrize("offset", [-600, 600])
async def test_signed_expired_or_future_timestamp(offset):
    raw = raw_event()
    async with client_app() as (_, client, services):
        assert (await client.post(PATH, content=raw, headers=signed(raw, timestamp=int(time.time()) + offset))).status_code == 401
        assert not services.model.calls


async def test_body_tampering_and_duplicate_authentication_cannot_be_bypassed():
    raw = raw_event()
    async with client_app() as (app, client, services):
        assert (await client.post(PATH, content=raw, headers=signed(raw))).status_code == 202
        await app.state.webhook_service.queue.join()
        assert (await client.post(PATH, content=raw + b' ', headers=signed(raw))).status_code == 401
        assert (await client.post(PATH, content=raw, headers=signed(raw) | {"X-Feedback-Signature": "sha256=" + "0" * 64})).status_code == 401
        assert (await client.post(PATH, content=raw + b' ', headers=signed(raw + b' '))).status_code == 409
        assert len(services.model.calls) == 1


async def test_duplicate_headers_rejected_before_inference():
    raw = raw_event()
    headers = list(signed(raw).items()) + [("X-Feedback-Delivery-Id", "DELIVERY-1")]
    async with client_app() as (_, client, services):
        assert (await client.post(PATH, content=raw, headers=headers)).status_code == 401
        assert not services.model.calls


@pytest.mark.parametrize("changes", [
    {"event_type": "unsupported"}, {"feedback": {"id": "", "text": "ok"}},
    {"feedback": {"id": "x", "text": " "}}, {"feedback": {"id": "x", "text": "x" * 5001}},
    {"feedback": {"id": "x" * 101, "text": "ok"}}, {"source": "bad"}, {"business_type": "bad"},
    {"tenant_id": "other"}, {"credentials": "fake"}, {"tools": ["shell"]},
    {"feedback": {"id": "x", "text": "ok", "business_id": "other"}},
])
async def test_authenticated_invalid_payload_rejected(changes):
    raw = raw_event(**changes)
    async with client_app() as (_, client, services):
        assert (await client.post(PATH, content=raw, headers=signed(raw))).status_code == 422
        assert not services.model.calls


@pytest.mark.parametrize("config", [{"webhook_integration_id": None}, {"webhook_shared_secret": None}])
async def test_missing_configuration_fails_closed(config):
    raw = raw_event()
    async with client_app(**config) as (_, client, services):
        response = await client.post(PATH, content=raw, headers=signed(raw))
        assert response.status_code == 503 and response.json()["error"]["code"] == "WEBHOOK_NOT_CONFIGURED"
        assert not services.model.calls


async def test_parallel_duplicates_schedule_exactly_one_call():
    gate = asyncio.Event()
    raw = raw_event()
    async with client_app(services=harness(model=Model(gate=gate))) as (app, client, services):
        responses = await asyncio.gather(*(client.post(PATH, content=raw, headers=signed(raw)) for _ in range(10)))
        assert sorted(r.status_code for r in responses) == [200] * 9 + [202]
        await until(lambda: len(services.model.calls) == 1)
        gate.set()
        await app.state.webhook_service.queue.join()
        assert len(services.model.calls) == 1


async def test_signature_is_verified_before_json_validation():
    raw = b'{not valid json'
    async with client_app() as (_, client, services):
        bad = signed(raw) | {"X-Feedback-Signature": "sha256=" + "0" * 64}
        assert (await client.post(PATH, content=raw, headers=bad)).status_code == 401
        response = await client.post(PATH, content=raw, headers=signed(raw))
        assert response.status_code == 422
        assert not services.model.calls


async def test_unknown_and_expired_status_have_identical_controlled_responses():
    raw = raw_event()
    async with client_app() as (app, client, _):
        assert (await client.post(PATH, content=raw, headers=signed(raw))).status_code == 202
        await app.state.webhook_service.queue.join()
        app.state.webhook_service.store.events[(INTEGRATION, "DELIVERY-1")].expires_at = time.monotonic() - 1
        for delivery in ["DELIVERY-1", "never-seen"]:
            response = await client.get("/api/v1/ingest/events/" + delivery, headers=REST)
            assert response.status_code == 404 and response.json()["error"]["code"] == "WEBHOOK_EVENT_NOT_FOUND"


async def test_missing_t01_configuration_rejects_before_acknowledgment():
    from app.services.sentiment_service import SentimentService
    services = harness()
    services.sentiment = SentimentService(None)
    raw = raw_event()
    async with client_app(services=services) as (app, client, _):
        response = await client.post(PATH, content=raw, headers=signed(raw))
        assert response.status_code == 503 and response.json()["error"]["code"] == "GROQ_NOT_CONFIGURED"
        assert not app.state.webhook_service.store.events


@pytest.mark.parametrize("offset,accepted", [(-300, True), (300, True), (-300.1, False), (300.1, False)])
def test_timestamp_window_includes_exact_boundaries(offset, accepted):
    from starlette.datastructures import Headers
    from app.core.exceptions import ApplicationError
    from app.core.webhook_security import signed_headers
    from tests.helpers import settings
    from tests.t06_helpers import SECRET
    config = settings(webhook_integration_id=INTEGRATION, webhook_shared_secret=SECRET)
    stamp = 2000000000
    headers = Headers(signed(raw_event(), timestamp=stamp))
    if accepted:
        assert signed_headers(config, headers, now=stamp + offset).timestamp == str(stamp)
    else:
        with pytest.raises(ApplicationError):
            signed_headers(config, headers, now=stamp + offset)
