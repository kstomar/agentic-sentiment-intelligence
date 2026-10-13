import asyncio
import json
import time
from dataclasses import replace

import pytest
from starlette.datastructures import Headers

from app.core.exceptions import ApplicationError, ErrorCode
from app.core.tenant_auth import principal_context
from app.core.webhook_security import authenticate_webhook
from app.schemas.ingestion import IngestionRequest
from tests.helpers import Model, harness, until
from tests.t06_helpers import raw_event
from tests.t07_helpers import (
    ALPHA_KEY, ALPHA_SECOND_SECRET, ALPHA_SECRET, BETA_KEY, BETA_SECRET,
    api_headers, multi_app, multi_settings, webhook_headers,
)

PATH = '/api/v1/webhooks/feedback'
STATUS = '/api/v1/ingest/events/'


async def test_integrations_map_to_distinct_businesses_with_same_delivery_id():
    services = harness(model=Model(errors={'Beta failure.': ApplicationError(ErrorCode.UPSTREAM_UNAVAILABLE)}))
    a = raw_event(feedback={'id': 'A', 'text': 'Alpha.'})
    b = raw_event(feedback={'id': 'B', 'text': 'Beta failure.'})
    async with multi_app(services=services) as (app, client, _):
        ra = await client.post(PATH, content=a, headers=webhook_headers(a))
        assert ra.status_code == 202
        before = await client.get(STATUS + 'same-delivery', headers=api_headers(BETA_KEY))
        assert before.status_code == 404
        rb = await client.post(PATH, content=b, headers=webhook_headers(b, integration='beta-integration', secret=BETA_SECRET))
        assert rb.status_code == 202
        await app.state.webhook_service.queue.join()
        sa = (await client.get(STATUS + 'same-delivery', headers=api_headers())).json()
        sb = (await client.get(STATUS + 'same-delivery', headers=api_headers(BETA_KEY))).json()
        assert sa == {'delivery_id': 'same-delivery', 'status': 'COMPLETED', 'error_code': None}
        assert sb == {'delivery_id': 'same-delivery', 'status': 'FAILED', 'error_code': 'UPSTREAM_UNAVAILABLE'}
        assert len(services.model.calls) == 2
        store = app.state.webhook_service.store
        alpha, beta = (app.state.tenant_registry.authenticate(key) for key in [ALPHA_KEY, BETA_KEY])
        assert store.get('same-delivery', principal=alpha).owner.tenant_id == 'business_alpha'
        assert store.get('same-delivery', principal=beta).owner.tenant_id == 'business_beta'


@pytest.mark.parametrize('integration,secret', [('beta-integration', ALPHA_SECRET), ('alpha-integration', BETA_SECRET)],
                         ids=['wrong-secret-for-beta', 'wrong-secret-for-alpha'])
async def test_changing_integration_identity_cannot_transplant_a_signature(integration, secret):
    raw = raw_event()
    async with multi_app() as (app, client, services):
        response = await client.post(PATH, content=raw, headers=webhook_headers(raw, integration=integration, secret=secret))
        assert response.status_code == 401
        assert not app.state.webhook_service.store._events and not services.model.calls
        assert not app.state.model_admission.by_tenant


@pytest.mark.parametrize('changes', [{'tenant_id': 'business_beta'}, {'business_id': 'business_beta'}, {'feedback': {'id': 'x', 'text': 'ok', 'tenant_id': 'business_beta'}}])
async def test_signed_body_cannot_override_tenant_authority(changes):
    raw = raw_event(**changes)
    async with multi_app() as (app, client, services):
        assert (await client.post(PATH, content=raw, headers=webhook_headers(raw))).status_code == 422
        assert not app.state.webhook_service.store._events and not services.model.calls


async def test_same_owner_different_integration_collision_is_explicit_and_preserves_first_event():
    raw = raw_event()
    async with multi_app() as (app, client, services):
        assert (await client.post(PATH, content=raw, headers=webhook_headers(raw))).status_code == 202
        response = await client.post(PATH, content=raw, headers=webhook_headers(raw, integration='alpha-second', secret=ALPHA_SECOND_SECRET))
        assert response.status_code == 409 and response.json()['error']['code'] == 'WEBHOOK_DELIVERY_COLLISION'
        await app.state.webhook_service.queue.join()
        assert len(services.model.calls) == 1
        assert (await client.get(STATUS + 'same-delivery', headers=api_headers())).status_code == 200


async def test_same_integration_retry_conflict_auth_and_foreign_tenant_are_independent():
    raw = raw_event()
    async with multi_app() as (app, client, services):
        assert (await client.post(PATH, content=raw, headers=webhook_headers(raw))).status_code == 202
        await app.state.webhook_service.queue.join()
        assert (await client.post(PATH, content=raw, headers=webhook_headers(raw))).status_code == 200
        conflicting = raw + b' '
        assert (await client.post(PATH, content=conflicting, headers=webhook_headers(conflicting))).status_code == 409
        assert (await client.post(PATH, content=raw, headers=webhook_headers(raw, secret=BETA_SECRET))).status_code == 401
        assert (await client.post(PATH, content=raw, headers=webhook_headers(raw, integration='beta-integration', secret=BETA_SECRET))).status_code == 202
        await app.state.webhook_service.queue.join()
        assert len(services.model.calls) == 2


async def test_concurrent_reused_delivery_ids_are_atomic_per_tenant():
    raw = raw_event()
    # Admit all five retries per owner; the independent ingress quota is tested
    # separately. This test asserts duplicate reservation under concurrency.
    async with multi_app(tenant_max_concurrent_requests=8) as (app, client, services):
        replies = await asyncio.gather(*[
            client.post(PATH, content=raw, headers=webhook_headers(raw, integration=integration, secret=secret))
            for integration, secret in [('alpha-integration', ALPHA_SECRET), ('beta-integration', BETA_SECRET)]
            for _ in range(5)
        ])
        assert sum(r.status_code == 202 for r in replies) == 2
        assert sum(r.status_code == 200 for r in replies) == 8
        await app.state.webhook_service.queue.join()
        assert len(services.model.calls) == 2


async def test_direct_status_and_store_need_verified_owner_and_permission():
    raw = raw_event()
    async with multi_app() as (app, client, _):
        assert (await client.post(PATH, content=raw, headers=webhook_headers(raw))).status_code == 202
        service = app.state.webhook_service
        beta = app.state.tenant_registry.authenticate(BETA_KEY)
        with pytest.raises(ApplicationError) as error: service.status('same-delivery', principal=beta)
        assert error.value.code == ErrorCode.WEBHOOK_EVENT_NOT_FOUND
        with pytest.raises(ApplicationError) as error: service.store.get('same-delivery', principal=beta)
        assert error.value.code == ErrorCode.WEBHOOK_EVENT_NOT_FOUND
        with principal_context(None):
            with pytest.raises(ApplicationError): service.status('same-delivery')
            with pytest.raises(ApplicationError): service.store.get('same-delivery')
            with pytest.raises(ApplicationError): _ = service.store.events
        with principal_context(beta):
            assert not service.store.events


async def test_forged_or_modified_delivery_context_cannot_bypass_service_hmac():
    raw = raw_event()
    async with multi_app() as (app, _, services):
        service = app.state.webhook_service
        identity = authenticate_webhook(app.state.settings, Headers(webhook_headers(raw)), raw, registry=app.state.tenant_registry)
        request = IngestionRequest(text='Synthetic.', channel='external_api')
        for forged in ['alpha-integration', replace(identity, delivery_id='different'), replace(identity, integration_id='beta-integration')]:
            with pytest.raises(ApplicationError): service.accept(forged, raw, request)
        assert not services.model.calls and not service.store._events


async def test_event_expiry_removes_tenant_reservation_and_allows_fresh_delivery():
    raw = raw_event()
    async with multi_app() as (app, client, services):
        assert (await client.post(PATH, content=raw, headers=webhook_headers(raw))).status_code == 202
        await app.state.webhook_service.queue.join()
        alpha = app.state.tenant_registry.authenticate(ALPHA_KEY)
        event = app.state.webhook_service.store.get('same-delivery', principal=alpha)
        assert event.request is None
        event.expires_at = time.monotonic() - 1
        assert (await client.get(STATUS + 'same-delivery', headers=api_headers())).status_code == 404
        assert (await client.post(PATH, content=raw, headers=webhook_headers(raw))).status_code == 202
        await app.state.webhook_service.queue.join()
        assert len(services.model.calls) == 2
