"""Remove only nonexact quotes after correction; keep strict validation and budgets."""
import asyncio
import copy
import json
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from langchain_core.exceptions import OutputParserException
from pydantic import ValidationError

from app.core.config import Settings
from app.core.exceptions import ApplicationError, ErrorCode as E
from app.core.processing_limits import ModelAdmission
from app.schemas.sentiment import SentimentRequest, SentimentResponse
from app.services.sentiment_service import SentimentService, create_sentiment_service
from tests.helpers import SENSITIVE, analysis, until
from tests.unit.test_evidence_recovery import SequenceModel
from tests.unit.test_sentiment_service import provider_error

TEXT = 'Café arrived  late.\r\nThanks. 😀'


def records(caplog):
    return [r for r in caplog.records if r.name == 'app.sentiment']


def assert_private_logs(caplog):
    assert TEXT not in caplog.text and SENSITIVE not in caplog.text
    assert SENSITIVE not in repr([r.__dict__ for r in records(caplog)])
    assert all(r.exc_info is None and r.stack_info is None for r in records(caplog))


@pytest.mark.parametrize('correct_first', [True, False])
async def test_valid_generation_needs_no_sanitization(correct_first, caplog):
    caplog.set_level(logging.INFO, logger='app.sentiment')
    values = [analysis(TEXT)] if correct_first else [analysis(SENSITIVE), analysis(TEXT)]
    model = SequenceModel(values)
    result = await SentimentService(model, max_retries=0).analyze(SentimentRequest(text=TEXT))
    assert result.evidence_phrases == [TEXT] and len(model.calls) == (1 if correct_first else 2)
    assert not any('sentiment_output_sanitized' in r.getMessage() for r in records(caplog))
    if not correct_first:
        assert records(caplog)[-1].getMessage() == 'sentiment_output_recovered category=exact_evidence_grounding'
    assert_private_logs(caplog)


async def test_only_exact_phrases_survive_in_order_without_mutating_other_fields(caplog):
    caplog.set_level(logging.INFO, logger='app.sentiment')
    corrected = analysis(TEXT, evidence_phrases=['Café', 'Cafe\u0301', 'arrived late.', 'arrived  late.',
                                               'Café', 'Thanks.', 'thanks.', SENSITIVE],
                         summary='Customer reports delayed arrival.', suggested_next_step='Review delivery.',
                         urgency='HIGH', sentiment='MIXED', category='DELIVERY',
                         aspects=[{'name': 'delivery_time', 'sentiment': 'NEGATIVE'}])
    original = copy.deepcopy(corrected)
    model = SequenceModel([analysis(SENSITIVE), corrected])
    result = await SentimentService(model, max_retries=3).analyze(SentimentRequest(text=TEXT))
    assert result.evidence_phrases == ['Café', 'arrived  late.', 'Café', 'Thanks.']
    assert all(phrase in TEXT for phrase in result.evidence_phrases)
    assert corrected == original
    assert result.model_dump(exclude={'evidence_phrases'}) == {k: v for k, v in original.items() if k != 'evidence_phrases'}
    assert len(model.calls) == 2
    assert [r.getMessage() for r in records(caplog)] == [
        'sentiment_output_rejected category=exact_evidence_grounding stage=service fields=evidence_phrases',
        'sentiment_output_rejected category=exact_evidence_grounding stage=service fields=evidence_phrases',
        'sentiment_output_sanitized category=exact_evidence_grounding retained=4 discarded=4',
    ]
    assert_private_logs(caplog)


@pytest.mark.parametrize('bad', ['invented', 'CafE', 'Café arrived late.', 'Cafe\u0301', 'Thanks. 😀extra'])
async def test_all_nonexact_phrases_become_empty_without_quote_repair(bad, caplog):
    caplog.set_level(logging.INFO, logger='app.sentiment')
    model = SequenceModel([analysis(SENSITIVE), analysis(bad)])
    result = await SentimentService(model).analyze(SentimentRequest(text=TEXT))
    assert result.evidence_phrases == [] and len(model.calls) == 2
    assert records(caplog)[-1].getMessage() == 'sentiment_output_sanitized category=exact_evidence_grounding retained=0 discarded=1'
    # Validator itself still rejects the original nonexact phrase.
    with pytest.raises(ValidationError):
        SentimentResponse.model_validate(analysis(bad), context={'feedback_text': TEXT})
    assert_private_logs(caplog)


async def test_initial_empty_evidence_remains_valid_without_correction_or_sanitization(caplog):
    model = SequenceModel([analysis(TEXT, evidence_phrases=[])])
    result = await SentimentService(model).analyze(SentimentRequest(text=TEXT))
    assert result.evidence_phrases == [] and len(model.calls) == 1 and not records(caplog)


BAD_UPDATES = [
    {'sentiment': 'INVALID'}, {'issue_category': 'INVALID'}, {'urgency': 'INVALID'},
    {'aspects': [{'name': 'Invalid Name', 'sentiment': 'NEGATIVE'}]},
    {'aspects': [{'name': 'delivery', 'sentiment': 'INVALID'}]},
    {'aspects': [None]}, {'aspects': [{'name': 'delivery', 'sentiment': 'NEGATIVE'}] * 21},
    {'summary': ' '}, {'summary': 'x' * 1001}, {'suggested_next_step': ''},
    {'evidence_phrases': [' ', 'invented']}, {'evidence_phrases': [None, 'invented']},
    {'evidence_phrases': ['invented'] * 21}, {'evidence_phrases': ['x' * 5001]},
    {'extra': SENSITIVE},
]


@pytest.mark.parametrize('updates', BAD_UPDATES)
@pytest.mark.parametrize('phase', ['initial', 'correction'])
async def test_any_other_validation_failure_remains_rejected(updates, phase, caplog):
    caplog.set_level(logging.INFO, logger='app.sentiment')
    invalid = analysis('invented') | updates
    values = [invalid] if phase == 'initial' else [analysis('invented'), invalid]
    model = SequenceModel(values)
    with pytest.raises(ApplicationError) as caught:
        await SentimentService(model, max_retries=3).analyze(SentimentRequest(text=TEXT))
    assert caught.value.code == E.INVALID_MODEL_RESPONSE and len(model.calls) == len(values)
    assert not any('sentiment_output_sanitized' in r.getMessage() for r in records(caplog))
    assert_private_logs(caplog)


@pytest.mark.parametrize('field', list(SentimentResponse.model_fields))
async def test_missing_fields_are_not_filled_in_or_sanitized(field, caplog):
    invalid = analysis('invented')
    del invalid[field]
    model = SequenceModel([analysis('invented'), invalid])
    with pytest.raises(ApplicationError) as caught:
        await SentimentService(model).analyze(SentimentRequest(text=TEXT))
    assert caught.value.code == E.INVALID_MODEL_RESPONSE and len(model.calls) == 2
    assert not any('sentiment_output_sanitized' in r.getMessage() for r in records(caplog))


@pytest.mark.parametrize('error,code', [(OutputParserException(SENSITIVE), E.INVALID_MODEL_RESPONSE),
                                       (provider_error(429), E.UPSTREAM_RATE_LIMITED), (None, E.INVALID_MODEL_RESPONSE)])
async def test_parser_type_and_provider_failures_on_correction_never_sanitize(error, code, caplog):
    model = SequenceModel([analysis('invented'), error])
    with pytest.raises(ApplicationError) as caught:
        await SentimentService(model, max_retries=3).analyze(SentimentRequest(text=TEXT))
    assert caught.value.code == code and len(model.calls) == 2
    assert not any('sentiment_output_sanitized' in r.getMessage() for r in records(caplog))
    assert_private_logs(caplog)


async def test_complete_sanitized_result_is_revalidated_with_original_context(monkeypatch):
    real_validate = SentimentResponse.model_validate
    validations = []

    @classmethod
    def capture(cls, obj, **kwargs):
        validations.append((copy.deepcopy(obj), copy.deepcopy(kwargs)))
        return real_validate(obj, **kwargs)

    monkeypatch.setattr(SentimentResponse, 'model_validate', capture)
    model = SequenceModel([analysis('invented'), analysis(TEXT, evidence_phrases=['Café', 'invented'])])
    result = await SentimentService(model).analyze(SentimentRequest(text=TEXT))
    assert len(validations) == 3
    assert all(kwargs['context'] == {'feedback_text': TEXT} for _, kwargs in validations)
    assert validations[2][0]['evidence_phrases'] == ['Café']
    assert result.model_dump() == real_validate(validations[2][0], context={'feedback_text': TEXT}).model_dump()


async def test_failed_final_validation_returns_no_success_or_sanitized_log(monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger='app.sentiment')
    real_validate = SentimentResponse.model_validate

    @classmethod
    def reject_sanitized(cls, obj, **kwargs):
        if obj.get('evidence_phrases') == []:
            # Simulate final validation finding an additional defect. No bypass.
            return real_validate({**obj, 'sentiment': 'INVALID'}, **kwargs)
        return real_validate(obj, **kwargs)

    monkeypatch.setattr(SentimentResponse, 'model_validate', reject_sanitized)
    model = SequenceModel([analysis('invented'), analysis('invented')])
    with pytest.raises(ApplicationError) as caught:
        await SentimentService(model).analyze(SentimentRequest(text=TEXT))
    assert caught.value.code == E.INVALID_MODEL_RESPONSE and len(model.calls) == 2
    assert not any('sentiment_output_sanitized' in r.getMessage() for r in records(caplog))


@pytest.mark.parametrize('expire_after_validation', [False, True])
async def test_sanitization_cannot_return_past_original_deadline(monkeypatch, expire_after_validation, caplog):
    caplog.set_level(logging.INFO, logger='app.sentiment')
    times = [0, 0, 0, 0, 2] if expire_after_validation else [0, 0, 0, 2]
    clock = iter(times)
    monkeypatch.setattr('app.services.sentiment_service.time', SimpleNamespace(monotonic=lambda: next(clock)))
    model = SequenceModel([analysis('invented'), analysis('invented')])
    admission = ModelAdmission(1)
    with pytest.raises(ApplicationError) as caught:
        await SentimentService(model, timeout_seconds=1, admission=admission).analyze(SentimentRequest(text=TEXT))
    assert caught.value.code == E.UPSTREAM_TIMEOUT and len(model.calls) == 2 and admission.active == 0
    assert not any('sentiment_output_sanitized' in r.getMessage() for r in records(caplog))


@pytest.mark.parametrize('cancel', [False, True])
async def test_sanitization_uses_original_admission_and_cancellation_budget(cancel):
    gate = asyncio.Event()

    async def hook(index):
        if index == 1:
            await gate.wait()

    model = SequenceModel([analysis('invented'), analysis('invented')], hook=hook)
    admission = ModelAdmission(1)
    service = SentimentService(model, admission=admission)
    task = asyncio.create_task(service.analyze(SentimentRequest(text=TEXT)))
    await until(lambda: len(model.calls) == 2)
    try:
        assert admission.active == model.active == model.peak == 1
        with pytest.raises(ApplicationError) as caught:
            await service.analyze(SentimentRequest(text='Must be rejected.'))
        assert caught.value.code == E.PROCESSING_CAPACITY_EXCEEDED and len(model.calls) == 2
    finally:
        if cancel:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            gate.set()
            assert (await task).evidence_phrases == []
    assert admission.active == model.active == 0


async def test_existing_provider_budget_is_not_extended_for_sanitization(monkeypatch):
    monkeypatch.setattr('app.services.sentiment_service.asyncio.sleep', AsyncMock())
    model = SequenceModel([provider_error(429), provider_error(500), analysis('invented'), analysis('invented')])
    result = await SentimentService(model, max_retries=2).analyze(SentimentRequest(text=TEXT))
    assert result.evidence_phrases == [] and len(model.calls) == 4


async def test_actual_strict_adapter_sanitizes_corrected_output_without_a_third_request(caplog):
    caplog.set_level(logging.INFO, logger='app.sentiment')
    requests = []

    async def respond(request):
        requests.append(json.loads(request.content))
        output = analysis(SENSITIVE) if len(requests) == 1 else analysis(TEXT, evidence_phrases=['Café', SENSITIVE])
        return httpx.Response(200, json={'id': 'synthetic', 'object': 'chat.completion', 'created': 1,
            'model': 'openai/gpt-oss-20b', 'choices': [{'index': 0, 'message': {'role': 'assistant',
            'content': json.dumps(output)}, 'finish_reason': 'stop'}]})

    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(500))) as sync:
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            service = create_sentiment_service(Settings(_env_file=None, groq_api_key='fabricated', groq_max_retries=0),
                                               http_client=sync, http_async_client=client)
            result = await service.analyze(SentimentRequest(text=TEXT))
    assert result.evidence_phrases == ['Café'] and len(requests) == 2
    assert requests[0]['response_format'] == requests[1]['response_format']
    assert requests[1]['response_format']['json_schema']['strict'] is True
    assert requests[1]['response_format']['json_schema']['schema']['additionalProperties'] is False
    assert requests[0]['messages'][1] == requests[1]['messages'][1]
    assert 'sentiment_output_sanitized category=exact_evidence_grounding retained=1 discarded=1' in caplog.text
    assert_private_logs(caplog)
