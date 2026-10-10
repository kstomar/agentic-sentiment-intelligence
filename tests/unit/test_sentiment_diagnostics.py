"""Credential-free diagnostics; real adapter parsing with synthetic HTTP responses."""
import json
import logging
from unittest.mock import AsyncMock

import groq
import httpx
import pytest
from langchain_core.exceptions import OutputParserException
from pydantic import BaseModel, ValidationError

from app.core.config import Settings
from app.core.exceptions import ApplicationError, ErrorCode as E
from app.schemas.sentiment import SentimentRequest, SentimentResponse
from app.services.sentiment_service import SentimentService, create_sentiment_service
from tests.helpers import Model, SENSITIVE, analysis

PRIVATE = SENSITIVE + '\nforged_log_category=private'


def diagnostic(caplog, category, stage, fields, *, count=1):
    all_records = [r for r in caplog.records if r.name == 'app.sentiment']
    assert SENSITIVE not in repr([r.__dict__ for r in all_records])
    records = [r for r in all_records if r.levelno == logging.WARNING]
    assert len(records) == count
    for record in records:
        assert record.levelno == logging.WARNING
        assert record.getMessage() == (
            f'sentiment_output_rejected category={category} stage={stage} fields={fields}'
        )
        assert record.exc_info is None and record.stack_info is None
        assert SENSITIVE not in repr(record.__dict__)
    assert SENSITIVE not in caplog.text


async def reject(model, caplog, category, stage, fields):
    with pytest.raises(ApplicationError) as caught:
        await SentimentService(model, max_retries=3).analyze(SentimentRequest(text=PRIVATE))
    assert caught.value.code == E.INVALID_MODEL_RESPONSE
    assert SENSITIVE not in str(caught.value)
    expected = 2 if category == 'exact_evidence_grounding' and stage == 'service' else 1
    assert len(model.calls) == expected  # Only service-context grounding gets one correction.
    diagnostic(caplog, category, stage, fields, count=expected)


async def test_sdk_response_validation_is_distinct_and_not_retried(caplog):
    request = httpx.Request('POST', 'https://synthetic.invalid', headers={'Authorization': PRIVATE.replace('\n', '')})
    error = groq.APIResponseValidationError(
        httpx.Response(200, request=request), body={'private': PRIVATE}, message=PRIVATE,
    )
    await reject(Model(errors={PRIVATE: error}), caplog, 'groq_sdk_response_validation', 'adapter', 'response')


async def test_structured_output_parser_error_never_logs_response_or_exception(caplog):
    error = OutputParserException(PRIVATE, llm_output=PRIVATE)
    await reject(Model(errors={PRIVATE: error}), caplog, 'structured_output_parsing', 'adapter', 'response')


@pytest.mark.parametrize('result', [None, PRIVATE, [PRIVATE], 17])
async def test_unexpected_output_type_uses_no_dynamic_type_or_value(caplog, result):
    await reject(Model(outputs={PRIVATE: result}), caplog, 'unexpected_output_type', 'normalization', 'response')


@pytest.mark.parametrize('updates,fields', [
    ({'sentiment': PRIVATE}, 'sentiment'),
    ({'issue_category': PRIVATE}, 'issue_category'),
    ({'aspects': [{'name': PRIVATE, 'sentiment': 'NEGATIVE'}]}, 'aspects.name'),
    ({'aspects': [{'name': 'delivery', 'sentiment': PRIVATE}]}, 'aspects.sentiment'),
    ({'summary': ' '}, 'summary'),
    ({'evidence_phrases': [' ']}, 'evidence_phrases'),
    ({'evidence_phrases': [None]}, 'evidence_phrases'),
    ({PRIVATE: PRIVATE}, 'response'),
    ({'aspects': [{'name': 'delivery', 'sentiment': 'NEGATIVE', PRIVATE: PRIVATE}]}, 'response'),
    ({'summary': ' ', 'urgency': PRIVATE, PRIVATE: PRIVATE}, 'response,summary,urgency'),
])
async def test_schema_fields_are_allowlisted_and_extra_locations_never_echoed(caplog, updates, fields):
    await reject(Model(outputs={PRIVATE: analysis(PRIVATE) | updates}), caplog,
                 'pydantic_schema_validation', 'service', fields)


async def test_direct_adapter_pydantic_error_keeps_stage_and_fields(caplog):
    try:
        SentimentResponse.model_validate(analysis(PRIVATE) | {'sentiment': PRIVATE})
    except ValidationError as error:
        model = Model(errors={PRIVATE: error})
    await reject(model, caplog, 'pydantic_schema_validation', 'adapter', 'sentiment')


@pytest.mark.parametrize('evidence', ['INVENTED', 'PRIVATE', 'cafe\u0301'])
async def test_exact_evidence_failure_has_stable_category_without_quotes(caplog, evidence):
    model = Model(outputs={PRIVATE: analysis(PRIVATE, evidence_phrases=[evidence])})
    result = await SentimentService(model).analyze(SentimentRequest(text=PRIVATE))
    assert result.evidence_phrases == [] and len(model.calls) == 2
    diagnostic(caplog, 'exact_evidence_grounding', 'service', 'evidence_phrases', count=2)


@pytest.mark.parametrize('error_type', [ValueError, TypeError])
async def test_other_adapter_output_errors_preserve_safe_mapping(caplog, error_type):
    await reject(Model(errors={PRIVATE: error_type(PRIVATE)}), caplog,
                 'output_processing_error', 'adapter', 'response')


async def test_normalization_error_does_not_log_base_model_content(caplog):
    class BrokenOutput(BaseModel):
        private: str

        def model_dump(self, **kwargs):
            raise TypeError(PRIVATE)

    await reject(Model(outputs={PRIVATE: BrokenOutput(private=PRIVATE)}), caplog,
                 'output_processing_error', 'normalization', 'response')


async def test_success_logs_no_diagnostic(caplog):
    result = await SentimentService(Model(), max_retries=3).analyze(SentimentRequest(text=PRIVATE))
    assert result.evidence_phrases == [PRIVATE]
    assert not [r for r in caplog.records if r.name == 'app.sentiment']


@pytest.mark.parametrize('content,category,stage,fields', [
    ('not-json ' + PRIVATE, 'structured_output_parsing', 'adapter', 'response'),
    (json.dumps(analysis(PRIVATE) | {'sentiment': 'INVALID'}), 'pydantic_schema_validation', 'adapter', 'sentiment'),
    (json.dumps(analysis(PRIVATE, aspects=[{'name': 'Invalid Name', 'sentiment': 'NEGATIVE'}])),
     'pydantic_schema_validation', 'adapter', 'aspects.name'),
    (json.dumps(analysis(PRIVATE, summary='x' * 1001)), 'pydantic_schema_validation', 'adapter', 'summary'),
    (json.dumps(analysis(PRIVATE, evidence_phrases=['Invented quotation'])),
     'exact_evidence_grounding', 'service', 'evidence_phrases'),
])
async def test_actual_strict_chatgroq_parser_distinguishes_schema_json_and_grounding(
    caplog, content, category, stage, fields,
):
    requests = []

    async def respond(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={
            'id': 'synthetic', 'object': 'chat.completion', 'created': 1, 'model': 'openai/gpt-oss-20b',
            'choices': [{'index': 0, 'message': {'role': 'assistant', 'content': content}, 'finish_reason': 'stop'}],
        })

    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(500))) as sync:
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            settings = Settings(_env_file=None, groq_api_key='synthetic-not-a-credential', groq_max_retries=3)
            service = create_sentiment_service(settings, http_client=sync, http_async_client=client)
            if category == 'exact_evidence_grounding':
                result = await service.analyze(SentimentRequest(text=PRIVATE))
                assert result.evidence_phrases == []
            else:
                with pytest.raises(ApplicationError) as caught:
                    await service.analyze(SentimentRequest(text=PRIVATE))
                assert caught.value.code == E.INVALID_MODEL_RESPONSE
    expected = 2 if category == 'exact_evidence_grounding' else 1
    assert len(requests) == expected
    for request in requests:
        schema = request['response_format']
        assert schema['type'] == 'json_schema' and schema['json_schema']['strict'] is True
        assert schema['json_schema']['schema']['additionalProperties'] is False
    diagnostic(caplog, category, stage, fields, count=expected)


async def test_network_retry_then_invalid_output_stops_without_an_extra_call(monkeypatch, caplog):
    sleep = AsyncMock()
    monkeypatch.setattr('app.services.sentiment_service.asyncio.sleep', sleep)

    class SequenceModel:
        calls = 0

        async def ainvoke(self, messages):
            self.calls += 1
            if self.calls == 1:
                raise groq.APIConnectionError(request=httpx.Request('POST', 'https://synthetic.invalid'))
            raise OutputParserException(PRIVATE, llm_output=PRIVATE)

    model = SequenceModel()
    with pytest.raises(ApplicationError) as caught:
        await SentimentService(model, max_retries=3).analyze(SentimentRequest(text=PRIVATE))
    assert caught.value.code == E.INVALID_MODEL_RESPONSE and model.calls == 2
    sleep.assert_awaited_once_with(.5)
    diagnostic(caplog, 'structured_output_parsing', 'adapter', 'response')
