"""T01 correction is one logical Gmail attempt; durable success/failure is preserved."""
import pytest
from sqlalchemy import update

from app.core.exceptions import ErrorCode as E
from app.storage.gmail_message_models import GmailMessageRow as G
from app.storage.gmail_message_store import now
from datetime import timedelta
from tests.helpers import analysis, harness
from tests.integration.test_postgres_batches import postgres_url
from tests.integration.test_postgres_gmail_incremental import pg_app, rows, run_job
from tests.t07_helpers import api_headers
from tests.t08_helpers import FakeGoogle, authorize
from tests.unit.test_evidence_recovery import SequenceModel

BASE = '/api/v1/integrations/gmail'


async def test_gmail_corrected_analysis_commits_one_attempt_and_deduplicates_after_restart(postgres_url):
    text = 'Delivery was late.'
    model = SequenceModel([analysis('invented'), analysis(text)])
    async with pg_app(postgres_url, fake=FakeGoogle(), services=harness(model=model)) as (app, client, _, _):
        await authorize(client)
        job, status = await run_job(app, client, maximum=3)
        result = (await client.get(BASE + '/imports/' + job + '/results', headers=api_headers())).json()['results']
        assert status['status'] == 'COMPLETED' and status['selected_messages'] == status['successful_messages'] == 1
        assert result[0]['status'] == 'SUCCESS' and result[0]['analysis']['evidence_phrases'] == [text]
        assert len(model.calls) == 2
        saved = rows(app)
        assert len(saved) == 1 and saved[0]['status'] == 'SUCCEEDED' and saved[0]['attempts'] == 1
        assert saved[0]['claim_token'] is None
        _, repeated = await run_job(app, client, maximum=3)
        assert repeated['selected_messages'] == 0 and repeated['previously_processed_messages'] == 1
        assert len(model.calls) == 2
    async with pg_app(postgres_url, fake=FakeGoogle()) as (app, client, services, _):
        await authorize(client)
        _, status = await run_job(app, client, maximum=3)
        assert status['selected_messages'] == 0 and status['previously_processed_messages'] == 1
        assert not services.model.calls and rows(app)[0]['attempts'] == 1


async def test_gmail_two_invalid_generations_spend_one_attempt_and_keep_explicit_cooldown(postgres_url):
    text = 'Delivery was late.'
    # A correction with an additional schema error must remain a failed attempt;
    # grounding-only corrections now qualify for deterministic sanitization.
    model = SequenceModel([analysis('invented'), analysis('invented', urgency='INVALID'),
                           analysis('invented'), analysis(text)])
    async with pg_app(postgres_url, fake=FakeGoogle(), services=harness(model=model)) as (app, client, _, _):
        await authorize(client)
        job, status = await run_job(app, client, maximum=3)
        result = (await client.get(BASE + '/imports/' + job + '/results', headers=api_headers())).json()['results'][0]
        assert status['status'] == 'FAILED' and status['failed_messages'] == 1
        assert result['analysis'] is None and result['error_code'] == 'INVALID_MODEL_RESPONSE'
        assert len(model.calls) == 2
        assert rows(app)[0]['status'] == 'FAILED' and rows(app)[0]['attempts'] == 1
        assert rows(app)[0]['last_error'] == E.INVALID_MODEL_RESPONSE
        _, blocked = await run_job(app, client, maximum=3)
        assert blocked['selected_messages'] == 0 and blocked['deferred_messages'] == 1 and len(model.calls) == 2
        with app.state.batch_service._store.engine.begin() as connection:
            connection.execute(update(G).values(retry_at=now() - timedelta(seconds=1)))
        _, retry = await run_job(app, client, maximum=3)
        assert retry['successful_messages'] == 1 and len(model.calls) == 4
        assert rows(app)[0]['status'] == 'SUCCEEDED' and rows(app)[0]['attempts'] == 2
