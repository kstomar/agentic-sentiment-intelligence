"""Incoming eligibility and partial batches; real PostgreSQL, synthetic providers."""
import httpx
import pytest
from sqlalchemy import event

from app.core.exceptions import ErrorCode as E
from tests.helpers import Model, analysis, harness
from tests.integration.test_postgres_batches import postgres_url
from tests.integration.test_postgres_gmail_incremental import pg_app, rows, run_job
from tests.t07_helpers import api_headers
from tests.t08_helpers import ACCESS_A, FakeGoogle, authorize, message

BASE = '/api/v1/integrations/gmail'


def feedback_mailbox(count, *, respect_query=True, page_size=2):
    fake = FakeGoogle()
    fake.respect_sent_filter = respect_query
    fake.page_size = page_size
    fake.messages[ACCESS_A] = {
        'sent1': message('Private outgoing reply.', mid='sent1', labelIds=['Label_feedback', 'SENT']),
        **{f'in{i}': message(f'Incoming feedback {i}.', mid=f'in{i}') for i in range(count)},
    }
    return fake


def gets(fake, *, minimal=None, mid=None):
    return [r for r in fake.requests if '/messages/' in r.url.path
            and (minimal is None or (r.url.params.get('format') == 'minimal') == minimal)
            and (mid is None or r.url.path.endswith('/' + mid))]


@pytest.mark.parametrize('respect_query', [True, False])
async def test_five_incoming_and_one_sent_selects_five_without_sent_claim_or_inference(postgres_url, respect_query):
    fake = feedback_mailbox(5, respect_query=respect_query, page_size=1)
    async with pg_app(postgres_url, fake=fake, gmail_max_list_pages=10) as (app, client, services, _):
        await authorize(client)
        job, status = await run_job(app, client, maximum=5)
        assert status['status'] == 'COMPLETED' and status['error_code'] is None
        assert status['selected_messages'] == status['processed_messages'] == status['successful_messages'] == 5
        assert status['skipped_messages'] == status['failed_messages'] == 0
        result = (await client.get(BASE + '/imports/' + job + '/results', headers=api_headers())).json()
        assert [r['message_id'] for r in result['results']] == [f'in{i}' for i in range(5)]
        assert [c['text'] for c in services.model.calls] == [f'Incoming feedback {i}.' for i in range(5)]
        assert len(rows(app)) == 5 and all(r['status'] == 'SUCCEEDED' for r in rows(app))
        assert not gets(fake, minimal=False, mid='sent1')
        assert len(gets(fake, minimal=True, mid='sent1')) == (0 if respect_query else 1)
        listings = [r for r in fake.requests if r.url.path.endswith('/messages')]
        assert len(listings) == (5 if respect_query else 6)
        assert all(r.url.params['q'] == 'newer_than:7d -in:sent' for r in listings)
        assert all(r.url.params['labelIds'] == 'Label_feedback' and r.url.params['includeSpamTrash'] == 'false' for r in listings)
        assert 'in:inbox' not in listings[0].url.params['q']
        assert all(r.url.params['fields'] == 'id,labelIds' for r in gets(fake, minimal=True))


@pytest.mark.parametrize('count', [0, 2])
@pytest.mark.parametrize('respect_query', [True, False])
async def test_fewer_or_zero_incoming_messages_complete_with_actual_count(postgres_url, count, respect_query):
    fake = feedback_mailbox(count, respect_query=respect_query)
    async with pg_app(postgres_url, fake=fake) as (app, client, services, _):
        await authorize(client)
        _, status = await run_job(app, client, maximum=3)
        assert status['status'] == 'COMPLETED' and status['error_code'] is None
        assert status['selected_messages'] == status['processed_messages'] == status['successful_messages'] == count
        assert status['scan_exhausted'] and not status['scan_limit_reached'] and not status['capacity_limit_reached']
        assert status['failed_messages'] == status['skipped_messages'] == status['duplicate_messages'] == 0
        assert len(services.model.calls) == len(rows(app)) == count
        assert not gets(fake, minimal=False, mid='sent1')


async def test_archived_incoming_and_mailbox_sender_header_are_not_excluded(postgres_url):
    fake = FakeGoogle()
    incoming = message('Archived forwarded feedback.', mid='archived', labelIds=['Label_feedback'])
    for header in incoming['payload']['headers']:
        if header['name'] == 'From':
            header['value'] = 'Mailbox alias <alpha@example.test>'
    fake.messages[ACCESS_A] = {'archived': incoming}
    async with pg_app(postgres_url, fake=fake) as (app, client, services, _):
        await authorize(client)
        _, status = await run_job(app, client, maximum=3)
        assert status['successful_messages'] == 1 and status['status'] == 'COMPLETED' and status['scan_exhausted']
        assert services.model.calls[0]['text'] == 'Archived forwarded feedback.'


async def test_incremental_2_2_1_0_and_restart_skip_success_without_metadata_fetch(postgres_url):
    fake = feedback_mailbox(5, respect_query=False)
    async with pg_app(postgres_url, fake=fake) as (app, client, services, _):
        await authorize(client)
        for expected in [2, 2, 1, 0]:
            _, status = await run_job(app, client, maximum=2)
            assert status['status'] == 'COMPLETED' and status['selected_messages'] == status['successful_messages'] == expected
            assert status['scan_exhausted'] == (expected < 2)
        assert len(services.model.calls) == len(rows(app)) == 5
        for i in range(5):
            assert len(gets(fake, minimal=True, mid=f'in{i}')) == 1
        assert all(r['attempts'] == 1 for r in rows(app))
    prior_gets = len(gets(fake))
    async with pg_app(postgres_url, fake=fake) as (app, client, services, _):
        await authorize(client)
        _, status = await run_job(app, client, maximum=3)
        assert status['selected_messages'] == status['processed_messages'] == 0 and status['status'] == 'COMPLETED'
        assert status['previously_processed_messages'] == 5 and status['scan_exhausted']
        assert not services.model.calls
        assert len(gets(fake)) == prior_gets + 1  # Only the query-leaked sent ID is label-checked.


async def test_all_ineligible_first_page_reports_limit_then_later_pages_can_fill(postgres_url):
    fake = feedback_mailbox(2, respect_query=False, page_size=1)
    async with pg_app(postgres_url, fake=fake, gmail_max_list_pages=1) as (app, client, services, _):
        await authorize(client)
        _, status = await run_job(app, client, maximum=2)
        assert status['status'] == 'COMPLETED' and status['selected_messages'] == status['processed_messages'] == 0
        assert status['scan_limit_reached'] and not status['scan_exhausted']
        assert not services.model.calls and not rows(app)
    async with pg_app(postgres_url, fake=fake, gmail_max_list_pages=3) as (app, client, services, _):
        await authorize(client)
        _, status = await run_job(app, client, maximum=2)
        assert status['successful_messages'] == 2 and status['status'] == 'COMPLETED'
        assert not status['scan_limit_reached'] and len(services.model.calls) == 2


async def test_eligible_incoming_invalid_model_result_remains_failed_not_sent_skip(postgres_url, caplog):
    fake = feedback_mailbox(1, respect_query=False)
    services = harness(model=Model(outputs={'Incoming feedback 0.': analysis('Incoming feedback 0.', urgency='INVALID')}))
    async with pg_app(postgres_url, fake=fake, services=services) as (app, client, _, _):
        await authorize(client)
        job, status = await run_job(app, client, maximum=3)
        result = (await client.get(BASE + '/imports/' + job + '/results', headers=api_headers())).json()['results']
        assert status['status'] == 'FAILED' and status['selected_messages'] == status['failed_messages'] == 1
        assert status['skipped_messages'] == status['successful_messages'] == 0
        assert result[0]['message_id'] == 'in0' and result[0]['error_code'] == 'INVALID_MODEL_RESPONSE'
        assert result[0]['analysis'] is None and len(services.model.calls) == 1
        saved = rows(app)
        assert len(saved) == 1 and saved[0]['status'] == 'FAILED' and saved[0]['last_error'] == E.INVALID_MODEL_RESPONSE
        assert saved[0]['attempts'] == 1
        assert 'category=pydantic_schema_validation stage=service fields=urgency' in caplog.text
        _, retry = await run_job(app, client, maximum=3)
        assert retry['selected_messages'] == 0 and retry['deferred_messages'] == 1
        assert len(services.model.calls) == 1  # Existing cooldown is retained.


@pytest.mark.parametrize('race_stage', ['preflight', 'body'])
async def test_sent_label_added_after_selection_is_rejected_before_inference(postgres_url, race_stage):
    fake = FakeGoogle()
    full_count = 0

    def change_labels(request):
        nonlocal full_count
        if '/messages/' in request.url.path and request.url.params.get('format') == 'full':
            full_count += 1
            if full_count == (1 if race_stage == 'preflight' else 2):
                fake.messages[ACCESS_A]['m1']['labelIds'].append('SENT')

    fake.hook = change_labels
    async with pg_app(postgres_url, fake=fake) as (app, client, services, _):
        await authorize(client)
        job, status = await run_job(app, client, maximum=1)
        result = (await client.get(BASE + '/imports/' + job + '/results', headers=api_headers())).json()['results']
        assert not services.model.calls and status['skipped_messages'] == 1
        assert result[0]['error_code'] == 'GMAIL_SELECTION_INVALID' and result[0]['analysis'] is None
        assert rows(app)[0]['status'] == 'FAILED'  # No fake durable success for a race.


@pytest.mark.parametrize('payload,code', [
    ({'id': 'wrong', 'labelIds': ['Label_feedback']}, 'GMAIL_RESPONSE_INVALID'),
    ({'id': 'm1', 'labelIds': 'SENT'}, 'GMAIL_RESPONSE_INVALID'),
    ({'id': 'm1', 'labelIds': [None]}, 'GMAIL_RESPONSE_INVALID'),
    ({'id': 'm1', 'labelIds': ['x' * 129]}, 'GMAIL_RESPONSE_INVALID'),
    (None, 'GMAIL_PROVIDER_ERROR'),
])
async def test_invalid_minimal_metadata_or_204_cannot_become_empty_success(postgres_url, payload, code, caplog):
    fake = FakeGoogle()
    fake.hook = lambda r: (httpx.Response(204) if payload is None else httpx.Response(200, json=payload)) \
        if r.url.params.get('format') == 'minimal' else None
    async with pg_app(postgres_url, fake=fake) as (app, client, services, _):
        await authorize(client)
        _, status = await run_job(app, client, maximum=3)
        assert status['status'] == 'FAILED' and status['error_code'] == code and not status['scan_exhausted']
        assert not services.model.calls and not rows(app)
        assert 'operation=messages.get' in caplog.text


async def test_success_prefilter_is_one_owner_scoped_sql_lookup_per_page(postgres_url):
    fake = feedback_mailbox(2)
    async with pg_app(postgres_url, fake=fake) as (app, client, services, _):
        await authorize(client)
        await run_job(app, client, maximum=2)
        engine = app.state.batch_service._store.engine
        statements = []

        def capture(conn, cursor, statement, parameters, context, executemany):
            if statement.lstrip().startswith('SELECT') and 'gmail_message_tracking' in statement:
                statements.append(statement)

        event.listen(engine, 'before_cursor_execute', capture)
        try:
            _, status = await run_job(app, client, maximum=3)
        finally:
            event.remove(engine, 'before_cursor_execute', capture)
        assert status['previously_processed_messages'] == 2 and status['selected_messages'] == 0
        lookups = [s for s in statements if s.startswith('SELECT gmail_message_tracking.message_id ')]
        assert len(lookups) == 1 and ' IN ' in lookups[0]
        assert 'tenant_id =' in lookups[0] and 'mailbox_key =' in lookups[0]
        assert len(statements) == 2  # One batched prefilter plus existing terminal claim cleanup.
        assert len(services.model.calls) == 2
