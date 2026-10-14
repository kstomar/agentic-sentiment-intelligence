import asyncio
import time
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from app.core.exceptions import ErrorCode as E
from tests.helpers import Model, harness, until
from tests.t07_helpers import ALPHA_KEY, BETA_KEY, api_headers
from tests.t08_helpers import ACCESS_A, ACCESS_B, FakeGoogle, authorize, gmail_app, import_job, message

BASE = '/api/v1/integrations/gmail'


async def test_import_admission_is_async_bounded_and_each_tenant_keeps_capacity():
    gate = asyncio.Event();services = harness(model=Model(gate=gate))
    async with gmail_app(services=services) as (app, client, _, _):
        await authorize(client)
        await authorize(client, BETA_KEY, 'beta-code')
        first = await client.post(BASE + '/import', headers=api_headers(), json={})
        assert first.status_code == 202 and first.json()['status'] == 'PENDING'
        await until(lambda: services.model.active == 1)
        assert (await client.post(BASE + '/import', headers=api_headers(), json={})).status_code == 429
        second = await client.post(BASE + '/import', headers=api_headers(BETA_KEY), json={})
        assert second.status_code == 202
        await until(lambda: services.model.active == 2)
        assert len(app.state.gmail_service._tasks) == 2
        assert app.state.model_admission.by_tenant == {'business_alpha': 1, 'business_beta': 1}
        assert (await client.post(BASE + '/import', headers=api_headers(BETA_KEY), json={})).status_code == 429
        gate.set()
        await until(lambda: not app.state.gmail_service._tasks)
        assert not app.state.model_admission.by_tenant


async def test_gmail_uses_existing_shared_model_budget_and_never_bypasses_it():
    gate = asyncio.Event();services = harness(model=Model(gate=gate))
    async with gmail_app(services=services) as (app, client, _, _):
        await authorize(client)
        calls = [asyncio.create_task(client.post('/api/v1/sentiment/analyze', headers=api_headers(), json={'text': f'Active {i}'})) for i in range(2)]
        try:
            await until(lambda: services.model.active == 2)
            job = await import_job(app, client)
            owner = app.state.tenant_registry.authenticate(ALPHA_KEY)
            result = app.state.gmail_service.results(job, owner).results[0]
            assert result.status == 'FAILED' and result.error_code == E.TENANT_CAPACITY_EXCEEDED
            assert len(services.model.calls) == 2 and app.state.model_admission.by_tenant == {'business_alpha': 2}
        finally:
            gate.set()
            await asyncio.gather(*calls)


async def test_deadline_releases_model_capacity_and_preserves_controlled_failed_outcome():
    services = harness(model=Model(gate=asyncio.Event()))
    async with gmail_app(services=services, gmail_import_timeout_seconds=.02) as (app, client, _, fake):
        await authorize(client)
        job = await import_job(app, client)
        owner = app.state.tenant_registry.authenticate(ALPHA_KEY)
        status = app.state.gmail_service.job_status(job, owner)
        assert status.status == 'FAILED' and status.error_code == E.GMAIL_TIMEOUT
        assert status.failed_messages == status.selected_messages == 1
        assert app.state.model_admission.active == 0 and not app.state.model_admission.by_tenant
        fake.messages[ACCESS_A] = {'m2': message('Next feedback.', mid='m2')}
        services.model.gate.set()
        next_job = await import_job(app, client)
        assert app.state.gmail_service.job_status(next_job, owner).status == 'COMPLETED'


async def test_disconnect_cancels_only_owner_jobs_wipes_tokens_results_and_duplicates():
    gate = asyncio.Event();services = harness(model=Model(gate=gate))
    async with gmail_app(services=services) as (app, client, _, fake):
        await authorize(client)
        await authorize(client, BETA_KEY, 'beta-code')
        response = await client.post(BASE + '/import', headers=api_headers(), json={})
        await until(lambda: services.model.active == 1)
        store = app.state.gmail_service.store
        connection = store._connections['business_alpha']
        held_job = store._jobs[response.json()['job_id']]
        assert (await client.delete(BASE + '/disconnect', headers=api_headers())).status_code == 200
        assert connection.tokens.access is connection.tokens.refresh is None
        assert not any(job.owner.tenant_id == 'business_alpha' for job in store._jobs.values()) and held_job.results == []
        # Disconnect releases active claims without erasing retry/success metadata.
        records = app.state.gmail_service.messages._records
        assert records and not any(row.status in {'RESERVED','PROCESSING'} for row in records.values())
        assert services.model.active == 0 and app.state.model_admission.active == 0
        assert (await client.get(BASE + '/status', headers=api_headers(BETA_KEY))).json()['connected'] is True
        assert (await client.post(BASE + '/import', headers=api_headers(), json={})).status_code == 409
        assert not any('revoke' in request.url.path for request in fake.requests)


async def test_disconnect_during_google_read_releases_http_capacity():
    fake = FakeGoogle();fake.gates['/gmail/v1/users/me/labels'] = asyncio.Event()
    async with gmail_app(fake=fake) as (app, client, services, _):
        await authorize(client)
        assert (await client.post(BASE + '/import', headers=api_headers(), json={})).status_code == 202
        await until(lambda: app.state.gmail_service.google.active == 1)
        await client.delete(BASE + '/disconnect', headers=api_headers())
        assert app.state.gmail_service.google.active == 0 and not services.model.calls
        assert not app.state.gmail_service._tasks


async def test_shutdown_cancels_inflight_callback_and_clears_all_secret_state():
    fake = FakeGoogle();fake.gates['/token'] = asyncio.Event()
    async with gmail_app(fake=fake) as (app, client, _, _):
        response = await client.post(BASE + '/connect', headers=api_headers())
        state = parse_qs(urlsplit(response.json()['authorization_url']).query)['state'][0]
        pending = next(iter(app.state.gmail_service.store._states.values()))
        task = asyncio.create_task(app.state.gmail_service.callback(state, 'alpha-code', None))
        await until(lambda: app.state.gmail_service.google.active == 1)
        await app.state.gmail_service.close()
        with pytest.raises(asyncio.CancelledError): await task
        assert pending.verifier is None and pending.cancelled
        assert not app.state.gmail_service.store._states and not app.state.gmail_service.store._connections
        assert not app.state.gmail_service._callbacks and app.state.gmail_service.google.active == 0


async def test_hard_connection_expiration_clears_tokens_and_requires_same_mailbox_reconnect():
    async with gmail_app() as (app, client, _, fake):
        await authorize(client)
        connection = app.state.gmail_service.store._connections['business_alpha']
        connection.expires_at = time.monotonic()-1
        status = (await client.get(BASE + '/status', headers=api_headers())).json()
        assert status['connection_status'] == 'RECONNECT_REQUIRED' and connection.tokens.refresh is None
        fake.addresses[ACCESS_A] = 'different@example.test'
        assert (await authorize(client)).status_code == 409
        fake.addresses[ACCESS_A] = 'alpha@example.test'
        assert (await authorize(client)).status_code == 200
        assert app.state.gmail_service.store._connections['business_alpha'] is not connection


async def test_google_can_omit_refresh_token_and_connection_is_access_only_until_expiry():
    fake = FakeGoogle()
    fake.hook = lambda req: httpx.Response(200, json={'access_token': ACCESS_A, 'expires_in': 3600, 'scope': 'https://www.googleapis.com/auth/gmail.readonly', 'token_type': 'Bearer'}) if req.url.path == '/token' else None
    async with gmail_app(fake=fake) as (app, client, _, _):
        assert (await authorize(client)).status_code == 200
        connection = app.state.gmail_service.store._connections['business_alpha']
        assert connection.tokens.refresh is None
        await import_job(app, client)
        connection.tokens.expires_at = time.monotonic()-1
        assert (await client.get(BASE + '/status', headers=api_headers())).json()['connection_status'] == 'RECONNECT_REQUIRED'
        assert len([r for r in fake.requests if r.url.path == '/token']) == 1


async def test_connection_and_retained_job_capacities_are_bounded():
    async with gmail_app(gmail_max_connections=1) as (_, client, _, _):
        await authorize(client)
        assert (await client.post(BASE + '/connect', headers=api_headers(BETA_KEY))).status_code == 429
    async with gmail_app(gmail_max_retained_imports=2) as (app, client, _, _):
        await authorize(client)
        await authorize(client, BETA_KEY, 'beta-code')
        await import_job(app, client)
        assert (await client.post(BASE + '/import', headers=api_headers(), json={})).status_code == 429
        await import_job(app, client, key=BETA_KEY)
        assert len(app.state.gmail_service.store._jobs) == 2


async def test_periodic_cleanup_erases_idle_jobs_and_expired_oauth_states():
    async with gmail_app(gmail_import_ttl_seconds=.04, gmail_oauth_state_ttl_seconds=.04) as (app, client, _, _):
        await authorize(client)
        job = await import_job(app, client)
        held = app.state.gmail_service.store._jobs[job]
        await until(lambda: job not in app.state.gmail_service.store._jobs)
        assert held.results == []
        await client.post(BASE + '/connect', headers=api_headers(BETA_KEY))
        pending = next(iter(app.state.gmail_service.store._states.values()))
        await until(lambda: not app.state.gmail_service.store._states)
        assert pending.verifier is None and pending.cancelled


async def test_dedup_store_capacity_fails_closed_without_evicting_existing_records():
    async with gmail_app(gmail_max_dedup_records=2, gmail_tenant_max_dedup_records=1) as (app, client, services, fake):
        await authorize(client)
        await import_job(app, client)
        original = dict(app.state.gmail_service.messages._records)
        fake.messages[ACCESS_A] = {'m2': message('Other review.', mid='m2')}
        job = await import_job(app, client)
        owner = app.state.tenant_registry.authenticate(ALPHA_KEY)
        assert app.state.gmail_service.job_status(job, owner).error_code == E.GMAIL_CAPACITY_EXCEEDED
        assert app.state.gmail_service.messages._records == original and len(services.model.calls) == 1
