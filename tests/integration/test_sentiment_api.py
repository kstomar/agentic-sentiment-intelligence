import pytest

from app.core.exceptions import ApplicationError, ErrorCode as E
from app.schemas.sentiment import SentimentResponse
from tests.helpers import SENSITIVE, analysis


@pytest.mark.parametrize("sentiment", ["POSITIVE", "NEGATIVE", "NEUTRAL", "MIXED"])
async def test_sentiment_classifications(api, sentiment):
    app, client, h = api
    h.model.outputs["sample"] = analysis("sample", sentiment)
    response = await client.post("/api/v1/sentiment/analyze", json={"text": "sample"})
    assert response.status_code == 200
    assert SentimentResponse.model_validate(response.json()).sentiment == sentiment
    assert app.state.sentiment_service is h.sentiment and len(h.model.calls) == 1


@pytest.mark.parametrize("field,values", [
    ("business_type", ["general", "ecommerce", "restaurant", "software", "banking"]),
    ("source", ["manual", "customer_review", "support_ticket", "email", "social_media"]),
])
async def test_existing_source_and_business_allowlists(api, field, values):
    _, client, h = api
    for value in values:
        response = await client.post("/api/v1/sentiment/analyze", json={"text": "sample", field: value})
        assert response.status_code == 200 and h.model.calls[-1][field] == value


@pytest.mark.parametrize("payload", [{}, {"text":""}, {"text":" "}, {"text":"x"*5001},
    {"text":"x","source":"invalid"}, {"text":"x","business_type":"invalid"}, {"text":"x","extra":"data"}])
async def test_request_validation_precedes_analysis(api, payload):
    _, client, h = api
    response = await client.post("/api/v1/sentiment/analyze", json=payload)
    assert response.status_code == 422 and not h.model.calls
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.parametrize("code,status", [(E.GROQ_NOT_CONFIGURED,503), (E.GROQ_MODEL_UNSUPPORTED,503),
    (E.UPSTREAM_AUTHENTICATION_FAILED,502),(E.UPSTREAM_RATE_LIMITED,429),(E.UPSTREAM_TIMEOUT,504),
    (E.UPSTREAM_UNAVAILABLE,502),(E.INVALID_MODEL_RESPONSE,502),(E.INTERNAL_ERROR,500)])
async def test_http_service_errors_are_sanitized(api, code, status, caplog):
    _, client, h = api
    h.model.errors[SENSITIVE] = ApplicationError(code)
    response = await client.post("/api/v1/sentiment/analyze", json={"text": SENSITIVE})
    assert response.status_code == status and response.json()["error"]["code"] == code
    assert SENSITIVE not in response.text and SENSITIVE not in caplog.text
    assert response.headers["X-Request-ID"] == response.json()["request_id"]


async def test_malformed_json_and_invented_evidence(api):
    _, client, h = api
    response = await client.post("/api/v1/sentiment/analyze", content=b'{"text":', headers={"Content-Type":"application/json"})
    assert response.status_code == 422 and not h.model.calls
    h.model.outputs["source"] = analysis("invented")
    response = await client.post("/api/v1/sentiment/analyze", json={"text":"source"})
    assert response.status_code == 200 and response.json()['evidence_phrases'] == []
    assert len(h.model.calls) == 2
