import asyncio
import threading
import time
from collections import deque

import pytest

from app.core.exceptions import ApplicationError, ErrorCode
from app.core.ingress_limits import IngressLimitMiddleware
from app.schemas.batch import UploadOptions
from app.services.sentiment_service import SentimentService
from tests.helpers import Model, harness, until
from tests.t06_helpers import raw_event
from tests.t07_helpers import ALPHA_KEY, ALPHA_SECRET, BETA_KEY, BETA_SECRET, api_headers, multi_app, webhook_headers
from tests.t07_helpers import CREDENTIALS


async def analyze(client, key, text):
    return await client.post('/api/v1/sentiment/analyze', headers=api_headers(key), json={'text': text})


async def test_one_business_model_saturation_leaves_capacity_for_other_business():
    gate = asyncio.Event()
    services = harness(model=Model(gate=gate))
    async with multi_app(services=services) as (app, client, _):
        tasks = [asyncio.create_task(analyze(client, ALPHA_KEY, f'Alpha {i}')) for i in range(2)]
        try:
            await until(lambda: services.model.active == 2)
            rejected = await analyze(client, ALPHA_KEY, 'Third alpha')
            assert rejected.status_code == 429 and rejected.json()['error']['code'] == 'TENANT_CAPACITY_EXCEEDED'
            beta = asyncio.create_task(analyze(client, BETA_KEY, 'Beta retained capacity'))
            tasks.append(beta)
            await until(lambda: services.model.active == 3)
            assert any(c['text'] == 'Beta retained capacity' for c in services.model.calls)
            assert app.state.model_admission.by_tenant == {'business_alpha': 2, 'business_beta': 1}
        finally:
            gate.set()
            assert all(r.status_code == 200 for r in await asyncio.gather(*tasks))
        assert app.state.model_admission.active == 0 and not app.state.model_admission.by_tenant


async def test_global_model_cap_still_applies_with_two_tenants():
    gate = asyncio.Event()
    services = harness(model=Model(gate=gate))
    async with multi_app(services=services) as (app, client, _):
        tasks = [asyncio.create_task(analyze(client, key, f'Synthetic {i}')) for i, key in enumerate([ALPHA_KEY, ALPHA_KEY, BETA_KEY, BETA_KEY])]
        try:
            await until(lambda: services.model.active == 4)
            response = await analyze(client, ALPHA_KEY, 'Beyond global capacity')
            assert response.status_code == 429 and response.json()['error']['code'] == 'PROCESSING_CAPACITY_EXCEEDED'
            assert app.state.model_admission.active == services.model.peak == 4
        finally:
            gate.set()
            await asyncio.gather(*tasks)


async def test_cancellation_releases_model_and_tenant_ingress_capacity():
    services = harness(model=Model(gate=asyncio.Event()))
    async with multi_app(services=services, tenant_max_concurrent_models=1) as (app, client, _):
        task = asyncio.create_task(analyze(client, ALPHA_KEY, 'Cancelled'))
        await until(lambda: services.model.active == 1)
        assert (await analyze(client, ALPHA_KEY, 'Busy')).status_code == 429
        task.cancel()
        with pytest.raises(asyncio.CancelledError): await task
        assert app.state.model_admission.active == 0 and not app.state.model_admission.by_tenant
        services.model.gate.set()
        assert (await analyze(client, ALPHA_KEY, 'After cancel')).status_code == 200


async def test_provider_deadline_releases_owner_model_budget():
    model = Model(gate=asyncio.Event())
    services = harness(model=model)
    services.sentiment = SentimentService(model, timeout_seconds=.02, max_retries=0)
    async with multi_app(services=services, tenant_max_concurrent_models=1) as (app, client, _):
        response = await analyze(client, ALPHA_KEY, 'Will time out')
        assert response.status_code == 504
        assert app.state.model_admission.active == 0 and not app.state.model_admission.by_tenant
        model.gate.set()
        assert (await analyze(client, ALPHA_KEY, 'After timeout')).status_code == 200


async def test_investigation_lifetime_quota_covers_chat_and_releases():
    gate = asyncio.Event()
    services = harness(model=Model(gate=gate))
    async with multi_app(services=services) as (app, client, _):
        payload = {'question': 'Summarize', 'feedback': [{'id': 'a', 'text': 'Review.'}]}
        task = asyncio.create_task(client.post('/api/v1/agent/investigate', json=payload, headers=api_headers()))
        tasks = [task]
        try:
            await until(lambda: services.model.active == 1)
            response = await client.post('/api/v1/chat', json={'mode': 'INVESTIGATE_FEEDBACK', 'message': 'Summarize', 'feedback': payload['feedback']}, headers=api_headers())
            assert response.status_code == 429 and len(services.selector.calls) == 1
            beta = asyncio.create_task(client.post('/api/v1/agent/investigate', json=payload, headers=api_headers(BETA_KEY)))
            tasks.append(beta)
            await until(lambda: services.model.active == 2)
            assert len(services.selector.calls) == 2
        finally:
            gate.set()
            assert all(r.status_code == 200 for r in await asyncio.gather(*tasks))
        assert not app.state.investigation_service._investigation_admission.active


async def test_batch_owner_capacity_and_cancellation_safe_parse_reservations(monkeypatch):
    started = threading.Event()
    release = threading.Event()
    async with multi_app() as (app, _, _):
        service = app.state.batch_service
        alpha = app.state.tenant_registry.authenticate(ALPHA_KEY)
        beta = app.state.tenant_registry.authenticate(BETA_KEY)
        original = service._parser.parse
        def parse(data, *args):
            if b'blocked' in data:
                started.set()
                release.wait(2)
            return original(data, *args)
        monkeypatch.setattr(service._parser, 'parse', parse)
        async def submit(principal, text):
            return await service.submit(('review\n' + text).encode(), 'data.csv', 'text/csv', UploadOptions(text_column='review'), principal=principal)
        task = asyncio.create_task(submit(alpha, 'blocked'))
        try:
            await until(started.is_set)
            task.cancel()
            with pytest.raises(asyncio.CancelledError): await task
            with pytest.raises(ApplicationError) as error: await submit(alpha, 'second')
            assert error.value.code == ErrorCode.TENANT_CAPACITY_EXCEEDED
            assert (await submit(beta, 'beta works')).job_id
            assert service._tenant_reservations == {'business_alpha': 1}
            release.set()
            await until(lambda: not service._tenant_reservations)
            assert (await submit(alpha, 'after parse cancellation')).job_id
        finally:
            release.set()


async def test_webhook_pending_and_worker_quotas_do_not_block_second_business():
    gate = asyncio.Event()
    services = harness(model=Model(gate=gate))
    async with multi_app(services=services) as (app, client, _):
        raw = raw_event(feedback={'id': 'a', 'text': 'Alpha event.'})
        assert (await client.post('/api/v1/webhooks/feedback', content=raw, headers=webhook_headers(raw, delivery='a-active'))).status_code == 202
        await until(lambda: services.model.active == 1)
        for i in range(5):
            assert (await client.post('/api/v1/webhooks/feedback', content=raw, headers=webhook_headers(raw, delivery=f'a-pending-{i}'))).status_code == 202
        rejected = await client.post('/api/v1/webhooks/feedback', content=raw, headers=webhook_headers(raw, delivery='a-too-many'))
        assert rejected.status_code == 429 and rejected.json()['error']['code'] == 'TENANT_CAPACITY_EXCEEDED'
        beta_raw = raw_event(feedback={'id': 'b', 'text': 'Beta event.'})
        assert (await client.post('/api/v1/webhooks/feedback', content=beta_raw, headers=webhook_headers(beta_raw, delivery='b-active', integration='beta-integration', secret=BETA_SECRET))).status_code == 202
        await until(lambda: services.model.active == 2)
        assert app.state.webhook_service._active == {'business_alpha': 1, 'business_beta': 1}
        assert [c['text'] for c in services.model.calls] == ['Alpha event.', 'Beta event.']
        gate.set()
        await app.state.webhook_service.queue.join()
        assert len(services.model.calls) == 7 and not app.state.webhook_service._active


async def test_global_webhook_pending_cap_still_rejects():
    gate = asyncio.Event()
    services = harness(model=Model(gate=gate))
    async with multi_app(services=services, webhook_max_pending_events=2, tenant_max_pending_events=1) as (app, client, _):
        raw = raw_event()
        for owner, integration, secret in [('a', 'alpha-integration', ALPHA_SECRET), ('b', 'beta-integration', BETA_SECRET)]:
            assert (await client.post('/api/v1/webhooks/feedback', content=raw, headers=webhook_headers(raw, delivery=owner+'-active', integration=integration, secret=secret))).status_code == 202
        await until(lambda: services.model.active == 2)
        for owner, integration, secret in [('a', 'alpha-integration', ALPHA_SECRET), ('b', 'beta-integration', BETA_SECRET)]:
            assert (await client.post('/api/v1/webhooks/feedback', content=raw, headers=webhook_headers(raw, delivery=owner+'-pending', integration=integration, secret=secret))).status_code == 202
        response = await client.post('/api/v1/webhooks/feedback', content=raw, headers=webhook_headers(raw, delivery='overflow'))
        assert response.status_code == 429 and response.json()['error']['code'] == 'WEBHOOK_CAPACITY_EXCEEDED'
        gate.set()
        await app.state.webhook_service.queue.join()


async def test_owner_rate_limit_and_expiry_are_bounded_and_use_verified_identity():
    async with multi_app(tenant_requests_per_minute=2) as (app, client, _):
        for _ in range(2):
            assert (await client.get('/api/v1/ingest/events/missing', headers=api_headers())).status_code == 404
        response = await client.get('/api/v1/ingest/events/missing?tenant_id=business_beta', headers=api_headers() | {'X-Tenant-ID': 'business_beta'})
        assert response.status_code == 429
        assert (await client.get('/api/v1/ingest/events/missing', headers=api_headers(BETA_KEY))).status_code == 404
        middleware = app.middleware_stack
        while not isinstance(middleware, IngressLimitMiddleware): middleware = middleware.app
        assert set(middleware.tenant_arrivals) == {'business_alpha', 'business_beta'}
        middleware.tenant_arrivals = {owner: deque([time.monotonic()-61]) for owner in middleware.tenant_arrivals}
        assert (await client.get('/api/v1/ingest/events/missing', headers=api_headers())).status_code == 404
        assert set(middleware.tenant_arrivals) == {'business_alpha'}
        for _ in range(3):
            assert (await client.get('/api/v1/ingest/events/missing', headers=api_headers('invalid'))).status_code == 401
        assert len(middleware.tenant_arrivals['business_alpha']) == 1


async def test_per_owner_intake_does_not_admit_spoofed_slow_body_concurrency():
    release = asyncio.Event()
    started = asyncio.Event()
    async def slow():
        started.set()
        yield b'{'
        await release.wait()
        yield b'"text":"Fine."}'
    async with multi_app(tenant_max_concurrent_requests=1) as (_, client, _):
        task = asyncio.create_task(client.post('/api/v1/sentiment/analyze', content=slow(), headers=api_headers() | {'Content-Type': 'application/json'}))
        try:
            await started.wait()
            assert (await analyze(client, ALPHA_KEY, 'Busy')).status_code == 429
            assert (await analyze(client, BETA_KEY, 'Other tenant')).status_code == 200
        finally:
            release.set()
            assert (await task).status_code == 200


async def test_per_tenant_body_timeout_releases_intake_for_following_request():
    async def slow():
        yield b'{'
        await asyncio.Event().wait()
    async with multi_app(tenant_max_concurrent_requests=1, ingress_body_timeout_seconds=.02) as (_, client, _):
        response = await client.post('/api/v1/sentiment/analyze', content=slow(), headers=api_headers())
        assert response.status_code == 408
        assert (await analyze(client, ALPHA_KEY, 'After body timeout')).status_code == 200


async def test_webhook_terminal_retention_quota_preserves_other_owner_capacity():
    raw = raw_event()
    async with multi_app(tenant_max_retained_events=2) as (app, client, _):
        for i in range(2):
            assert (await client.post('/api/v1/webhooks/feedback', content=raw, headers=webhook_headers(raw, delivery=f'a-{i}'))).status_code == 202
            await app.state.webhook_service.queue.join()
        response = await client.post('/api/v1/webhooks/feedback', content=raw, headers=webhook_headers(raw, delivery='a-full'))
        assert response.status_code == 429 and response.json()['error']['code'] == 'TENANT_CAPACITY_EXCEEDED'
        assert (await client.post('/api/v1/webhooks/feedback', content=raw, headers=webhook_headers(raw, delivery='b-still-works', integration='beta-integration', secret=BETA_SECRET))).status_code == 202
        await app.state.webhook_service.queue.join()


async def test_global_http_intake_cap_still_bounds_three_verified_tenants():
    gate = asyncio.Event()
    services = harness(model=Model(gate=gate))
    gamma_key = ALPHA_KEY + 'gamma'
    credentials = CREDENTIALS + [{'tenant_id': 'business_gamma', 'key_id': 'gamma_key', 'api_key': gamma_key}]
    async with multi_app(credentials=credentials, services=services, ingress_max_concurrent_requests=2) as (_, client, _):
        tasks = [asyncio.create_task(analyze(client, key, 'Blocked')) for key in [ALPHA_KEY, BETA_KEY]]
        try:
            await until(lambda: services.model.active == 2)
            response = await analyze(client, gamma_key, 'Beyond global ingress')
            assert response.status_code == 429 and response.json()['error']['code'] == 'INGRESS_CAPACITY_EXCEEDED'
        finally:
            gate.set()
            await asyncio.gather(*tasks)
