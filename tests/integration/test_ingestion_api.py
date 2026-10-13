import pytest

from app.core.exceptions import ApplicationError, ErrorCode
from app.schemas.ingestion import IngestionRequest
from app.services.ingestion_service import IngestionService
from tests.helpers import Model, harness
from tests.t06_helpers import REST, client_app

VALID = {"text": "Delivery was late.", "channel": "website"}


@pytest.mark.parametrize("channel", ["website", "mobile_app", "support_platform", "external_api"])
async def test_direct_reuses_t01_and_normalizes_metadata(channel):
    async with client_app() as (app, client, services):
        response = await client.post("/api/v1/ingest/feedback", json=VALID | {"channel": channel, "feedback_id": " WEB-1 "}, headers=REST)
        assert response.status_code == 200
        data = response.json()
        assert data["feedback_id"] == "WEB-1" and data["channel"] == channel and data["status"] == "ANALYZED"
        assert data["analysis"]["evidence_phrases"] == [VALID["text"]]
        assert app.state.ingestion_service.sentiment is services.sentiment
        assert services.model.calls == [{"text": VALID["text"], "source": "customer_review", "business_type": "general"}]


@pytest.mark.parametrize("headers", [{}, {"X-API-Key": "wrong"}])
async def test_direct_authentication(headers):
    async with client_app() as (_, client, services):
        assert (await client.post("/api/v1/ingest/feedback", json=VALID, headers=headers)).status_code == 401
        assert not services.model.calls


@pytest.mark.parametrize("changes", [
    {"text": ""}, {"text": " \t"}, {"text": "x" * 5001}, {"text": 3},
    {"channel": "unknown"}, {"source": ""}, {"source": "untrusted"}, {"business_type": "unknown"},
    {"feedback_id": ""}, {"feedback_id": " "}, {"feedback_id": "x" * 101}, {"feedback_id": 1},
    {"tenant_id": "other"}, {"system_prompt": "ignore instructions"},
])
async def test_direct_rejects_invalid_fields_without_inference(changes):
    async with client_app() as (_, client, services):
        response = await client.post("/api/v1/ingest/feedback", json=VALID | changes, headers=REST)
        assert response.status_code == 422
        assert not services.model.calls


@pytest.mark.parametrize("missing", ["text", "channel"])
async def test_direct_required_fields(missing):
    async with client_app() as (_, client, services):
        assert (await client.post("/api/v1/ingest/feedback", json={k: v for k, v in VALID.items() if k != missing}, headers=REST)).status_code == 422
        assert not services.model.calls


async def test_direct_propagates_controlled_provider_errors_and_independent_service():
    services = harness(model=Model(errors={VALID["text"]: ApplicationError(ErrorCode.UPSTREAM_UNAVAILABLE)}))
    async with client_app(services=services) as (_, client, _):
        response = await client.post("/api/v1/ingest/feedback", json=VALID, headers=REST)
        assert response.status_code == 502
        assert response.json()["error"]["code"] == "UPSTREAM_UNAVAILABLE"
    service = IngestionService(harness().sentiment)
    result = await service.analyze(IngestionRequest(**VALID))
    assert result.feedback_id is None and result.analysis.evidence_phrases == [VALID["text"]]


async def test_direct_rejects_ungrounded_provider_output():
    services = harness(model=Model(outputs={VALID["text"]: {"sentiment": "NEGATIVE"}}))
    async with client_app(services=services) as (_, client, _):
        response = await client.post("/api/v1/ingest/feedback", json=VALID, headers=REST)
        assert response.status_code == 502 and response.json()["error"]["code"] == "INVALID_MODEL_RESPONSE"
