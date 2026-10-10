import asyncio
import json
from unittest.mock import AsyncMock

import groq
import httpx
import pytest

from app.core.config import Settings
from app.core.exceptions import ApplicationError, ErrorCode as E
from app.schemas.sentiment import SentimentRequest, SentimentResponse
from app.services.sentiment_service import SentimentService, create_sentiment_service
from tests.helpers import Model, SENSITIVE, analysis


def provider_error(status):
    request = httpx.Request("POST", "https://mock.invalid/chat")
    cls = {401: groq.AuthenticationError, 429: groq.RateLimitError, 500: groq.InternalServerError}[status]
    return cls(SENSITIVE, response=httpx.Response(status, request=request), body={"error": SENSITIVE})


@pytest.mark.parametrize("status,code,attempts", [(401, E.UPSTREAM_AUTHENTICATION_FAILED, 1),
                                                (429, E.UPSTREAM_RATE_LIMITED, 3),
                                                (500, E.UPSTREAM_UNAVAILABLE, 3)])
async def test_bounded_retries_and_permanent_failures(monkeypatch, status, code, attempts):
    monkeypatch.setattr("app.services.sentiment_service.asyncio.sleep", AsyncMock())
    model = Model(errors={"text": provider_error(status)})
    with pytest.raises(ApplicationError) as caught:
        await SentimentService(model, max_retries=2).analyze(SentimentRequest(text="text"))
    assert caught.value.code == code
    assert SENSITIVE not in str(caught.value)
    assert len(model.calls) == attempts


@pytest.mark.parametrize("error,code", [
    (groq.APIConnectionError(request=httpx.Request("GET", "https://mock.invalid")), E.UPSTREAM_UNAVAILABLE),
    (groq.APITimeoutError(request=httpx.Request("GET", "https://mock.invalid")), E.UPSTREAM_TIMEOUT),
    (RuntimeError(SENSITIVE), E.INTERNAL_ERROR),
])
async def test_network_timeout_and_unexpected_errors(error, code):
    with pytest.raises(ApplicationError) as caught:
        await SentimentService(Model(errors={"x": error}), max_retries=0).analyze(SentimentRequest(text="x"))
    assert caught.value.code == code
    assert SENSITIVE not in str(caught.value)


@pytest.mark.parametrize("result", [None, "free form", {}, analysis("invented")])
async def test_invalid_outputs_reject_or_sanitize_only_grounding_failure(result):
    model = Model(outputs={"x": result})
    if result == analysis("invented"):
        response = await SentimentService(model, max_retries=0).analyze(SentimentRequest(text="x"))
        assert response.evidence_phrases == [] and len(model.calls) == 2
        assert response.model_dump(exclude={"evidence_phrases"}) == {
            k: v for k, v in result.items() if k != "evidence_phrases"
        }
        return
    with pytest.raises(ApplicationError) as caught:
        await SentimentService(model, max_retries=0).analyze(SentimentRequest(text="x"))
    assert caught.value.code == E.INVALID_MODEL_RESPONSE


async def test_wall_clock_deadline_includes_model_wait():
    model = Model(gate=asyncio.Event())
    with pytest.raises(ApplicationError) as caught:
        await SentimentService(model, timeout_seconds=.02).analyze(SentimentRequest(text="x"))
    assert caught.value.code == E.UPSTREAM_TIMEOUT and len(model.calls) == 1
    assert model.active == 0


@pytest.mark.parametrize("configured,model_name,expected", [
    (False, "openai/gpt-oss-20b", E.GROQ_NOT_CONFIGURED),
    (True, "unsupported", E.GROQ_MODEL_UNSUPPORTED),
])
async def test_configuration_errors(configured, model_name, expected):
    config = Settings(_env_file=None, groq_api_key="fabricated" if configured else None, groq_model=model_name)
    with httpx.Client() as sync:
        async with httpx.AsyncClient() as async_client:
            service = create_sentiment_service(config, http_client=sync, http_async_client=async_client)
            with pytest.raises(ApplicationError) as caught:
                await service.analyze(SentimentRequest(text="x"))
    assert caught.value.code == expected


async def test_actual_chatgroq_adapter_strict_schema_with_mock_http():
    requests = []

    async def respond(request):
        payload = json.loads(request.content)
        requests.append(payload)
        text = json.loads(payload["messages"][-1]["content"])["text"]
        return httpx.Response(200, json={
            "id": "mock", "object": "chat.completion", "created": 1, "model": "openai/gpt-oss-20b",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": json.dumps(analysis(text))},
                         "finish_reason": "stop"}],
        })

    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(500))) as sync:
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as async_client:
            config = Settings(_env_file=None, groq_api_key="qa-not-a-real-key", groq_max_retries=0)
            service = create_sentiment_service(config, http_client=sync, http_async_client=async_client)
            result = await service.analyze(SentimentRequest(text="adapter-only"))
    assert isinstance(result, SentimentResponse)
    assert len(requests) == 1
    schema = requests[0]["response_format"]
    assert schema["type"] == "json_schema" and schema["json_schema"]["strict"] is True
    assert schema["json_schema"]["schema"]["additionalProperties"] is False
