"""Sanitized results are one successful logical Gmail attempt, with no extra call."""
import logging

import pytest

from tests.helpers import analysis, harness
from tests.integration.test_postgres_batches import postgres_url
from tests.integration.test_postgres_gmail_incremental import pg_app, rows, run_job
from tests.t07_helpers import api_headers
from tests.t08_helpers import FakeGoogle, authorize
from tests.unit.test_evidence_recovery import SequenceModel

BASE = '/api/v1/integrations/gmail'
TEXT = 'Delivery was late.'


@pytest.mark.parametrize('retained', [[], ['Delivery']])
async def test_sanitized_gmail_success_uses_one_attempt_and_survives_restart(postgres_url, retained, caplog):
    caplog.set_level(logging.INFO, logger='app.sentiment')
    corrected = analysis(TEXT, evidence_phrases=retained + ['nonexact private quote'])
    model = SequenceModel([analysis('nonexact private quote'), corrected])
    async with pg_app(postgres_url, fake=FakeGoogle(), services=harness(model=model)) as (app, client, _, _):
        await authorize(client)
        job, status = await run_job(app, client, maximum=3)
        result = (await client.get(BASE + '/imports/' + job + '/results', headers=api_headers())).json()['results'][0]
        assert status['status'] == 'COMPLETED' and status['successful_messages'] == status['selected_messages'] == 1
        assert result['status'] == 'SUCCESS' and result['analysis']['evidence_phrases'] == retained
        assert result['analysis']['summary'] == corrected['summary'] and result['error_code'] is None
        assert len(model.calls) == 2 and len(rows(app)) == 1
        assert rows(app)[0]['status'] == 'SUCCEEDED' and rows(app)[0]['attempts'] == 1
        assert rows(app)[0]['claim_token'] is None
        _, again = await run_job(app, client, maximum=3)
        assert again['selected_messages'] == 0 and again['previously_processed_messages'] == 1
        assert len(model.calls) == 2
        assert 'sentiment_output_sanitized category=exact_evidence_grounding' in caplog.text
        assert 'nonexact private quote' not in caplog.text and TEXT not in caplog.text
    async with pg_app(postgres_url, fake=FakeGoogle()) as (app, client, services, _):
        await authorize(client)
        _, status = await run_job(app, client, maximum=3)
        assert status['selected_messages'] == 0 and status['previously_processed_messages'] == 1
        assert not services.model.calls and rows(app)[0]['attempts'] == 1


@pytest.mark.parametrize('updates', [{'urgency': 'INVALID'}, {'issue_category': 'INVALID'},
                                    {'aspects': [{'name': 'Invalid Name', 'sentiment': 'NEGATIVE'}]}])
async def test_gmail_additional_schema_errors_remain_failed_and_cooldown_blocked(postgres_url, updates, caplog):
    caplog.set_level(logging.INFO, logger='app.sentiment')
    model = SequenceModel([analysis('invented'), analysis('invented') | updates])
    async with pg_app(postgres_url, fake=FakeGoogle(), services=harness(model=model)) as (app, client, _, _):
        await authorize(client)
        job, status = await run_job(app, client, maximum=3)
        result = (await client.get(BASE + '/imports/' + job + '/results', headers=api_headers())).json()['results'][0]
        assert status['status'] == 'FAILED' and status['failed_messages'] == 1 and status['successful_messages'] == 0
        assert result['error_code'] == 'INVALID_MODEL_RESPONSE' and result['analysis'] is None
        assert rows(app)[0]['status'] == 'FAILED' and rows(app)[0]['attempts'] == 1
        _, again = await run_job(app, client, maximum=3)
        assert again['selected_messages'] == 0 and again['deferred_messages'] == 1
        assert len(model.calls) == 2
        assert 'sentiment_output_sanitized' not in caplog.text
