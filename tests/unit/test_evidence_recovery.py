"""Exactly one private, fully validated grounding correction within T01 budgets."""
import asyncio
import json
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import groq
import httpx
import pytest
from langchain_core.exceptions import OutputParserException
from pydantic import ValidationError

from app.core.config import Settings
from app.core.exceptions import ApplicationError, ErrorCode as E
from app.core.processing_limits import ModelAdmission
from app.prompts.sentiment import EVIDENCE_RECOVERY_INSTRUCTION, SYSTEM_PROMPT
from app.schemas.sentiment import SentimentRequest, SentimentResponse
from app.services.sentiment_service import SentimentService, create_sentiment_service
from tests.helpers import SENSITIVE, analysis, harness, until
from tests.t07_helpers import ALPHA_KEY, BETA_KEY, api_headers, multi_app
from tests.unit.test_sentiment_service import provider_error


class SequenceModel:
    def __init__(self, values, *, hook=None):
        self.values = values
        self.hook = hook
        self.calls = []
        self.active = 0
        self.peak = 0

    async def ainvoke(self, messages):
        index = len(self.calls)
        self.calls.append(list(messages))
        self.active += 1
        self.peak = max(self.active, self.peak)
        try:
            if self.hook is not None:
                await self.hook(index)
            value = self.values[index]
            if isinstance(value, Exception):
                raise value
            return value
        finally:
            self.active -= 1


def recovery_records(caplog):
    return [r for r in caplog.records if r.name == 'app.sentiment']


async def test_valid_first_generation_requires_one_call_and_no_recovery(caplog):
    model = SequenceModel([analysis('Original feedback.')])
    result = await SentimentService(model).analyze(SentimentRequest(text='Original feedback.'))
    assert result.evidence_phrases == ['Original feedback.'] and len(model.calls) == 1
    assert not recovery_records(caplog)


@pytest.mark.parametrize('text,bad', [
    ('Delivery was very late.', 'Delivery was delayed.'),
    ('Two  spaces.', 'Two spaces.'),
    ('Curly “quotes”.', 'Curly "quotes".'),
    ('Café delivery.', 'Cafe\u0301 delivery.'),
    ('First line.\r\nSecond line.\t😀', 'First line. Second line. 😀'),
    ('Literal \\n and real\nnewline.', 'Literal \n and real newline.'),
])
async def test_one_grounding_correction_preserves_exact_input_and_schema(text, bad, caplog):
    caplog.set_level(logging.INFO, logger='app.sentiment')
    rejected = analysis(bad, summary=SENSITIVE)
    model = SequenceModel([rejected, analysis(text)])
    result = await SentimentService(model, max_retries=0).analyze(SentimentRequest(text=text))
    assert len(model.calls) == 2 and result.evidence_phrases == [text]
    assert all(phrase in text for phrase in result.evidence_phrases)
    assert model.calls[0][1] == model.calls[1][1]
    assert json.loads(model.calls[0][1][1])['text'] == text
    assert model.calls[0][0] == ('system', SYSTEM_PROMPT)
    assert model.calls[1][0] == ('system', SYSTEM_PROMPT + '\n' + EVIDENCE_RECOVERY_INSTRUCTION)
    assert all(len(messages) == 2 for messages in model.calls)
    assert SENSITIVE not in repr(model.calls[1])  # No rejected result or exception replay.
    records = recovery_records(caplog)
    assert [r.getMessage() for r in records] == [
        'sentiment_output_rejected category=exact_evidence_grounding stage=service fields=evidence_phrases',
        'sentiment_output_recovered category=exact_evidence_grounding',
    ]
    assert SENSITIVE not in caplog.text
    assert all(r.exc_info is None and r.stack_info is None for r in records)


@pytest.mark.parametrize('max_retries', [0, 2, 3])
async def test_two_grounding_failures_stop_after_two_calls(max_retries, caplog):
    caplog.set_level(logging.INFO, logger='app.sentiment')
    model = SequenceModel([analysis(SENSITIVE), analysis(SENSITIVE)])
    result = await SentimentService(model, max_retries=max_retries).analyze(SentimentRequest(text='Original.'))
    assert result.evidence_phrases == [] and len(model.calls) == 2
    assert len(recovery_records(caplog)) == 3 and SENSITIVE not in caplog.text
    assert all('sentiment_output_rejected' in r.getMessage() for r in recovery_records(caplog)[:2])
    assert recovery_records(caplog)[2].getMessage() == 'sentiment_output_sanitized category=exact_evidence_grounding retained=0 discarded=1'


@pytest.mark.parametrize('update', [
    {'sentiment': 'INVALID'}, {'urgency': 'INVALID'}, {'issue_category': 'INVALID'},
    {'aspects': [{'name': 'Invalid Name', 'sentiment': 'NEGATIVE'}]},
    {'summary': ' '}, {'evidence_phrases': [' ']}, {'evidence_phrases': ['x'] * 21},
    {'unexpected': SENSITIVE},
])
async def test_non_grounding_schema_failures_never_receive_a_correction(update):
    # Also include nonexact evidence: invalid fields must not qualify as an
    # otherwise valid result just because evidence is wrong too.
    model = SequenceModel([analysis('invented') | update])
    with pytest.raises(ApplicationError) as caught:
        await SentimentService(model, max_retries=3).analyze(SentimentRequest(text='Original.'))
    assert caught.value.code == E.INVALID_MODEL_RESPONSE and len(model.calls) == 1


@pytest.mark.parametrize('bad', [None, {}, 'free form', OutputParserException(SENSITIVE)])
async def test_non_schema_or_parser_failures_do_not_trigger_correction(bad):
    model = SequenceModel([bad])
    with pytest.raises(ApplicationError) as caught:
        await SentimentService(model, max_retries=3).analyze(SentimentRequest(text='Original.'))
    assert caught.value.code == E.INVALID_MODEL_RESPONSE and len(model.calls) == 1


async def test_adapter_grounding_exception_does_not_qualify_as_service_validation():
    try:
        SentimentResponse.model_validate(analysis('invented'), context={'feedback_text': 'Original.'})
    except ValidationError as error:
        model = SequenceModel([error])
    with pytest.raises(ApplicationError) as caught:
        await SentimentService(model).analyze(SentimentRequest(text='Original.'))
    assert caught.value.code == E.INVALID_MODEL_RESPONSE and len(model.calls) == 1


@pytest.mark.parametrize('second', [analysis('invented again'), analysis('Original.', urgency='INVALID'), None,
                                     OutputParserException(SENSITIVE)])
async def test_invalid_correction_never_creates_a_third_generation(second):
    model = SequenceModel([analysis('invented'), second])
    if second == analysis('invented again'):
        result = await SentimentService(model, max_retries=3).analyze(SentimentRequest(text='Original.'))
        assert result.evidence_phrases == [] and len(model.calls) == 2
        return
    with pytest.raises(ApplicationError) as caught:
        await SentimentService(model, max_retries=3).analyze(SentimentRequest(text='Original.'))
    assert caught.value.code == E.INVALID_MODEL_RESPONSE and len(model.calls) == 2


@pytest.mark.parametrize('status,code,count', [(401, E.UPSTREAM_AUTHENTICATION_FAILED, 1),
                                             (429, E.UPSTREAM_RATE_LIMITED, 3),
                                             (500, E.UPSTREAM_UNAVAILABLE, 3)])
async def test_provider_errors_before_grounding_keep_existing_retries(monkeypatch, status, code, count):
    monkeypatch.setattr('app.services.sentiment_service.asyncio.sleep', AsyncMock())
    model = SequenceModel([provider_error(status)] * count)
    with pytest.raises(ApplicationError) as caught:
        await SentimentService(model, max_retries=2).analyze(SentimentRequest(text='Original.'))
    assert caught.value.code == code and len(model.calls) == count


@pytest.mark.parametrize('status,code', [(401, E.UPSTREAM_AUTHENTICATION_FAILED), (429, E.UPSTREAM_RATE_LIMITED),
                                       (500, E.UPSTREAM_UNAVAILABLE)])
async def test_correction_provider_error_is_sanitized_without_another_retry(status, code, caplog):
    model = SequenceModel([analysis('invented'), provider_error(status)])
    with pytest.raises(ApplicationError) as caught:
        await SentimentService(model, max_retries=3).analyze(SentimentRequest(text='Original.'))
    assert caught.value.code == code and len(model.calls) == 2
    assert SENSITIVE not in str(caught.value) and SENSITIVE not in caplog.text
    assert not any('sentiment_output_recovered' in r.getMessage() for r in recovery_records(caplog))


@pytest.mark.parametrize('max_retries', [0, 2, 3])
async def test_transport_budget_plus_only_one_correction_does_not_multiply(monkeypatch, max_retries):
    sleep = AsyncMock()
    monkeypatch.setattr('app.services.sentiment_service.asyncio.sleep', sleep)
    model = SequenceModel([provider_error(429)] * max_retries + [analysis('invented'), analysis('Original.')])
    result = await SentimentService(model, max_retries=max_retries).analyze(SentimentRequest(text='Original.'))
    assert result.evidence_phrases == ['Original.'] and len(model.calls) == max_retries + 2
    assert sleep.await_count == max_retries
    assert all(EVIDENCE_RECOVERY_INSTRUCTION not in call[0][1] for call in model.calls[:-1])
    assert EVIDENCE_RECOVERY_INSTRUCTION in model.calls[-1][0][1]


async def test_recovery_shares_one_overall_timeout_and_releases_permit(monkeypatch):
    timeouts = []
    real_timeout = asyncio.timeout

    def observed_timeout(seconds):
        timeouts.append(seconds)
        return real_timeout(seconds)

    monkeypatch.setattr('app.services.sentiment_service.asyncio.timeout', observed_timeout)
    gate = asyncio.Event()

    async def hook(index):
        if index == 0:
            await asyncio.sleep(.01)
        else:
            await gate.wait()

    model = SequenceModel([analysis('invented'), analysis('Original.')], hook=hook)
    admission = ModelAdmission(1)
    with pytest.raises(ApplicationError) as caught:
        await SentimentService(model, timeout_seconds=.04, admission=admission).analyze(SentimentRequest(text='Original.'))
    assert caught.value.code == E.UPSTREAM_TIMEOUT and len(model.calls) == 2
    assert timeouts == [.04] and admission.active == model.active == 0


async def test_expired_deadline_does_not_start_the_correction(monkeypatch):
    clock = iter([0.0, 0.0, 2.0])
    monkeypatch.setattr('app.services.sentiment_service.time', SimpleNamespace(monotonic=lambda: next(clock)))
    model = SequenceModel([analysis('invented')])
    with pytest.raises(ApplicationError) as caught:
        await SentimentService(model, timeout_seconds=1).analyze(SentimentRequest(text='Original.'))
    assert caught.value.code == E.UPSTREAM_TIMEOUT and len(model.calls) == 1


@pytest.mark.parametrize('cancel', [False, True])
async def test_correction_holds_original_global_admission_and_releases_it(cancel):
    gate = asyncio.Event()

    async def hook(index):
        if index == 1:
            await gate.wait()

    model = SequenceModel([analysis('invented'), analysis('Original.')], hook=hook)
    admission = ModelAdmission(1)
    service = SentimentService(model, admission=admission)
    task = asyncio.create_task(service.analyze(SentimentRequest(text='Original.')))
    await until(lambda: len(model.calls) == 2)
    try:
        assert admission.active == model.active == model.peak == 1
        with pytest.raises(ApplicationError) as caught:
            await service.analyze(SentimentRequest(text='Rejected concurrent request.'))
        assert caught.value.code == E.PROCESSING_CAPACITY_EXCEEDED and len(model.calls) == 2
    finally:
        if cancel:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            gate.set()
            assert (await task).evidence_phrases == ['Original.']
    assert admission.active == model.active == 0


async def test_correction_keeps_tenant_permit_while_other_tenant_can_use_headroom():
    gate = asyncio.Event()

    async def hook(index):
        if index == 1:
            await gate.wait()

    model = SequenceModel([analysis('invented'), analysis('Alpha original.'), analysis('Beta original.')], hook=hook)
    async with multi_app(services=harness(model=model), model_max_concurrent_calls=2,
                         tenant_max_concurrent_models=1) as (app, client, _):
        task = asyncio.create_task(client.post('/api/v1/sentiment/analyze', headers=api_headers(ALPHA_KEY),
                                               json={'text': 'Alpha original.'}))
        await until(lambda: len(model.calls) == 2)
        try:
            assert app.state.model_admission.by_tenant == {'business_alpha': 1}
            response = await client.post('/api/v1/sentiment/analyze', headers=api_headers(ALPHA_KEY), json={'text': 'Other alpha.'})
            assert response.status_code == 429 and response.json()['error']['code'] == 'TENANT_CAPACITY_EXCEEDED'
            beta = await client.post('/api/v1/sentiment/analyze', headers=api_headers(BETA_KEY), json={'text': 'Beta original.'})
            assert beta.status_code == 200 and model.peak == 2
        finally:
            gate.set()
            assert (await task).status_code == 200
        assert not app.state.model_admission.by_tenant and app.state.model_admission.active == 0


async def test_direct_caller_mutation_cannot_change_original_recovery_feedback():
    request = SentimentRequest(text='Original feedback.')

    async def hook(index):
        if index == 0:
            request.text = 'Mutated by caller.'

    model = SequenceModel([analysis('invented'), analysis('Original feedback.')], hook=hook)
    result = await SentimentService(model).analyze(request)
    assert result.evidence_phrases == ['Original feedback.']
    assert all(json.loads(call[1][1])['text'] == 'Original feedback.' for call in model.calls)


async def test_actual_chatgroq_correction_keeps_native_strict_schema_and_private_input(caplog):
    caplog.set_level(logging.INFO, logger='app.sentiment')
    text = 'Café “excellent”.\r\nDelivery was late. 😀'
    requests = []

    async def respond(request):
        data = json.loads(request.content)
        requests.append(data)
        output = analysis('paraphrased ' + SENSITIVE) if len(requests) == 1 else analysis(text)
        return httpx.Response(200, json={'id': 'synthetic', 'object': 'chat.completion', 'created': 1,
            'model': 'openai/gpt-oss-20b', 'choices': [{'index': 0, 'message': {'role': 'assistant',
            'content': json.dumps(output)}, 'finish_reason': 'stop'}]})

    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(500))) as sync:
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            service = create_sentiment_service(Settings(_env_file=None, groq_api_key='fabricated', groq_max_retries=0),
                                               http_client=sync, http_async_client=client)
            result = await service.analyze(SentimentRequest(text=text))
    assert result.evidence_phrases == [text] and len(requests) == 2
    assert requests[0]['response_format'] == requests[1]['response_format']
    assert requests[1]['response_format']['json_schema']['strict'] is True
    assert requests[1]['response_format']['json_schema']['schema']['additionalProperties'] is False
    assert requests[0]['messages'][1] == requests[1]['messages'][1]
    assert all(json.loads(r['messages'][1]['content'])['text'] == text for r in requests)
    assert SENSITIVE not in repr(requests[1]) and SENSITIVE not in caplog.text and text not in caplog.text
