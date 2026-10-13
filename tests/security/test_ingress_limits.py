import asyncio
import json

import pytest

from app.core.ingress_limits import IngressLimitMiddleware
from app.schemas.ingestion import IngestionRequest
from tests.helpers import Model, harness, settings, until
from tests.t06_helpers import REST, client_app, raw_event, signed

LIMIT = 1024


def padded(payload, size):
    raw = json.dumps(payload, ensure_ascii=False).encode()
    assert len(raw) <= size
    return raw + b" " * (size - len(raw))


@pytest.mark.parametrize("path,payload", [
    ("/api/v1/sentiment/analyze", {"text": "Late delivery."}),
    ("/api/v1/agent/investigate", {"question": "Summarize", "feedback": [{"id": "1", "text": "Late delivery."}]}),
    ("/api/v1/chat", {"mode": "ANALYZE_TEXT", "message": "Analyze", "feedback_text": "Late delivery."}),
    ("/api/v1/ingest/feedback", {"text": "Late delivery.", "channel": "website"}),
])
@pytest.mark.parametrize("delta,expected", [(-1, 200), (0, 200), (1, 413)])
async def test_json_limits_before_parsing_preserve_existing_endpoints(path, payload, delta, expected):
    async with client_app(json_max_body_bytes=LIMIT) as (_, client, services):
        response = await client.post(path, content=padded(payload, LIMIT + delta), headers=REST | {"Content-Type": "application/json"})
        assert response.status_code == expected
        assert bool(services.model.calls) == (expected == 200)


@pytest.mark.parametrize("delta,expected", [(-1, 200), (0, 200), (1, 413)])
async def test_approved_default_four_mib_boundary(delta, expected):
    async with client_app() as (_, client, _):
        response = await client.post("/api/v1/sentiment/analyze", content=padded({"text": "Fine."}, 4194304 + delta), headers=REST | {"Content-Type": "application/json"})
        assert response.status_code == expected


@pytest.mark.parametrize("text,expected", [("好" * 300, 200), ("好" * 400, 413), ("😀" * 220, 200), ("😀" * 300, 413)])
async def test_byte_limit_counts_unicode_without_altering_text(text, expected):
    async with client_app(json_max_body_bytes=LIMIT) as (_, client, services):
        raw = json.dumps({"text": text}, ensure_ascii=False).encode()
        response = await client.post("/api/v1/sentiment/analyze", content=raw, headers=REST | {"Content-Type": "application/json"})
        assert response.status_code == expected
        if expected == 200:
            assert services.model.calls[0]["text"] == text and response.json()["evidence_phrases"] == [text]


@pytest.mark.parametrize("declared", [None, "1", "1024"])
async def test_chunked_actual_bytes_override_missing_or_misleading_length(declared):
    async def chunks():
        for chunk in [b'{"text":"Late delivery."}', b" " * 600, b" " * 600]:
            yield chunk
    async with client_app(json_max_body_bytes=LIMIT) as (_, client, services):
        headers = REST | {"Content-Type": "application/json"}
        if declared is not None:
            headers["Content-Length"] = declared
        response = await client.post("/api/v1/sentiment/analyze", content=chunks(), headers=headers)
        assert response.status_code == 413 and not services.model.calls


async def test_chunked_signed_unicode_bytes_preserved_and_separate_webhook_limit():
    raw = raw_event(feedback={"id": "1", "text": "好评 😀"})
    async def chunks():
        # Split UTF-8 byte sequences deliberately: verification must use exact original bytes.
        for i in range(0, len(raw), 7):
            yield raw[i:i + 7]
    async with client_app(json_max_body_bytes=LIMIT, webhook_max_body_bytes=2048) as (app, client, services):
        response = await client.post("/api/v1/webhooks/feedback", content=chunks(), headers=signed(raw) | {"Content-Length": "1"})
        assert response.status_code == 202
        await app.state.webhook_service.queue.join()
        assert services.model.calls[0]["text"] == "好评 😀"
        larger = raw + b" " * (2048 - len(raw))
        assert (await client.post("/api/v1/webhooks/feedback", content=larger, headers=signed(larger, delivery="two"))).status_code == 202
        assert (await client.post("/api/v1/webhooks/feedback", content=larger + b" ", headers=signed(larger + b" ", delivery="three"))).status_code == 413


async def test_authentication_precedes_body_consumption():
    calls = []
    async def downstream(scope, receive, send):
        raise AssertionError("Unauthorized request reached parser")
    async def receive():
        raise AssertionError("Unauthorized request body was read")
    async def send(message):
        calls.append(message)
    middleware = IngressLimitMiddleware(downstream, settings())
    await middleware({"type": "http", "method": "POST", "path": "/api/v1/batch/upload", "headers": []}, receive, send)
    assert calls[0]["status"] == 401


async def test_concurrent_multipart_intake_is_bounded_before_parsing():
    release = asyncio.Event()
    started = 0
    async def body():
        nonlocal started
        started += 1
        yield b"--qa\r\n"
        await release.wait()
        yield b"--qa--\r\n"
    async with client_app() as (_, client, services):
        headers = REST | {"Content-Type": "multipart/form-data; boundary=qa"}
        tasks = [asyncio.create_task(client.post("/api/v1/batch/upload", content=body(), headers=headers)) for _ in range(3)]
        try:
            await until(lambda: started == 3)
            response = await client.post("/api/v1/batch/upload", content=body(), headers=headers)
            assert response.status_code == 429 and started == 3
            assert not services.model.calls
        finally:
            release.set()
            await asyncio.gather(*tasks)


async def test_global_ingress_rate_is_bounded_health_remains_available():
    async with client_app(ingress_requests_per_minute=2) as (_, client, _):
        for _ in range(2):
            assert (await client.get("/api/v1/ingest/events/unknown", headers=REST)).status_code == 404
        response = await client.get("/api/v1/ingest/events/unknown", headers=REST)
        assert response.status_code == 429 and response.json()["error"]["code"] == "INGRESS_RATE_LIMITED"
        assert (await client.get("/health")).status_code == 200


async def test_body_read_deadline_releases_global_admission():
    async def slow():
        yield b"{"
        await asyncio.Event().wait()
    async with client_app(ingress_body_timeout_seconds=.02, ingress_max_concurrent_requests=1) as (_, client, _):
        response = await client.post("/api/v1/sentiment/analyze", content=slow(), headers=REST)
        assert response.status_code == 408
        assert (await client.post("/api/v1/sentiment/analyze", json={"text": "Fine."}, headers=REST)).status_code == 200


async def test_global_model_budget_shared_by_rest_ingestion_selector_and_webhook():
    gate = asyncio.Event()
    services = harness(model=Model(gate=gate))
    async with client_app(services=services, model_max_concurrent_calls=1) as (app, client, _):
        task = asyncio.create_task(client.post("/api/v1/sentiment/analyze", json={"text": "First."}, headers=REST))
        try:
            await until(lambda: services.model.active == 1)
            assert (await client.post("/api/v1/ingest/feedback", json={"text": "Second.", "channel": "website"}, headers=REST)).status_code == 429
            investigation = await client.post("/api/v1/agent/investigate", json={"question": "Summarize", "feedback": [{"id": "1", "text": "Second."}]}, headers=REST)
            assert investigation.status_code == 429 and not services.selector.calls
            raw = raw_event()
            assert (await client.post("/api/v1/webhooks/feedback", content=raw, headers=signed(raw))).status_code == 202
            await app.state.webhook_service.queue.join()
            assert app.state.webhook_service.status("DELIVERY-1").error_code == "PROCESSING_CAPACITY_EXCEEDED"
            assert len(services.model.calls) == 1 and services.model.peak == 1
        finally:
            gate.set()
            assert (await task).status_code == 200
        assert app.state.model_admission.active == 0


async def test_model_budget_released_on_cancellation():
    services = harness(model=Model(gate=asyncio.Event()))
    async with client_app(services=services, model_max_concurrent_calls=1) as (app, _, _):
        task = asyncio.create_task(app.state.ingestion_service.analyze(IngestionRequest(text="Wait.", channel="website")))
        await until(lambda: services.model.active == 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert app.state.model_admission.active == 0


async def test_streamed_webhook_uses_stricter_actual_byte_limit():
    raw = raw_event() + b" " * 16384
    async def chunks():
        for i in range(0, len(raw), 500):
            yield raw[i:i + 500]
    async with client_app() as (_, client, services):
        response = await client.post("/api/v1/webhooks/feedback", content=chunks(), headers=signed(raw) | {"Content-Length": "1"})
        assert response.status_code == 413 and not services.model.calls


async def test_global_intake_capacity_and_cancellation_release():
    read_started = asyncio.Event()
    async def waiting():
        read_started.set()
        yield b"{"
        await asyncio.Event().wait()
    async with client_app(ingress_max_concurrent_requests=1) as (_, client, _):
        task = asyncio.create_task(client.post("/api/v1/sentiment/analyze", content=waiting(), headers=REST))
        await read_started.wait()
        response = await client.get("/api/v1/ingest/events/unknown", headers=REST)
        assert response.status_code == 429 and response.json()["error"]["code"] == "INGRESS_CAPACITY_EXCEEDED"
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        response = await client.post("/api/v1/sentiment/analyze", json={"text": "Good."}, headers=REST)
        assert response.status_code == 200


@pytest.mark.parametrize("kind", ["actual_envelope", "file_only"])
async def test_real_batch_route_keeps_file_and_actual_envelope_limits_separate(kind):
    async with client_app() as (_, client, services):
        if kind == "actual_envelope":
            async def chunks():
                for _ in range(33):
                    yield b"x" * 65536
                yield b"x"
            response = await client.post("/api/v1/batch/upload", content=chunks(), headers=REST | {
                "Content-Type": "multipart/form-data; boundary=qa", "Content-Length": "1",
            })
        else:
            # Above the file limit but below the independent envelope allowance.
            response = await client.post("/api/v1/batch/upload", files={"file": ("data.csv", b"x" * (2097152 + 1), "text/csv")}, data={"text_column": "text"}, headers=REST)
        assert response.status_code == 413
        assert response.json()["error"]["code"] == "BATCH_FILE_TOO_LARGE"
        assert not services.model.calls
