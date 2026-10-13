import json

import pytest
from mcp import Client

from app.core.config import Settings
from app.core.exceptions import ApplicationError, ErrorCode
from app.core.tenant_auth import TenantRegistry
from app.mcp_server.server import create_mcp_server
from tests.helpers import TEST_KEY, harness, until
from tests.t06_helpers import INTEGRATION, SECRET, raw_event, signed
from tests.t07_helpers import ALPHA_KEY, BETA_KEY, api_headers, multi_app, multi_settings, webhook_headers
from tests.security.test_batch_tenant_isolation import upload

PAYLOADS = [
    ('/api/v1/sentiment/analyze', {'text': 'Synthetic feedback.', 'business_type': 'banking'}),
    ('/api/v1/agent/investigate', {'question': 'Summarize', 'feedback': [{'id': 'business_beta', 'text': 'Synthetic feedback.'}]}),
    ('/api/v1/chat', {'mode': 'ANALYZE_TEXT', 'message': 'Analyze', 'feedback_text': 'Synthetic feedback.'}),
    ('/api/v1/chat', {'mode': 'INVESTIGATE_FEEDBACK', 'message': 'Summarize', 'feedback': [{'id': 'business_beta', 'text': 'Synthetic feedback.'}]}),
    ('/api/v1/ingest/feedback', {'text': 'Synthetic feedback.', 'channel': 'external_api', 'feedback_id': 'business_beta'}),
]


@pytest.mark.parametrize('key', [ALPHA_KEY, BETA_KEY], ids=['alpha', 'beta'])
@pytest.mark.parametrize('path,payload', PAYLOADS)
async def test_each_business_can_use_existing_stateless_and_ingestion_contracts(key, path, payload):
    async with multi_app() as (_, client, services):
        response = await client.post(path, json=payload, headers=api_headers(key))
        assert response.status_code == 200
        assert ALPHA_KEY not in response.text and BETA_KEY not in response.text
        assert all(set(call) == {'text', 'source', 'business_type'} for call in services.model.calls)
        assert all(set(call) == {'question', 'business_type'} for call in services.selector.calls)


@pytest.mark.parametrize('path,payload', PAYLOADS)
async def test_request_identity_claims_cannot_override_registry(path, payload):
    async with multi_app() as (_, client, services):
        response = await client.post(path, json=payload | {'tenant_id': 'business_beta'}, headers=api_headers())
        assert response.status_code == 422 and not services.model.calls and not services.selector.calls


async def test_legacy_mode_is_a_separate_tenant_when_real_businesses_are_configured():
    config = multi_settings(app_env='development', development_auth_enabled=True,
                            webhook_integration_id=INTEGRATION, webhook_shared_secret=SECRET)
    async with multi_app(config=config) as (app, client, _):
        a = await upload(client)
        dev = await upload(client, TEST_KEY, 'Development-owned synthetic feedback.')
        assert a.status_code == dev.status_code == 202
        a_id, dev_id = a.json()['job_id'], dev.json()['job_id']
        assert (await client.get('/api/v1/batch/jobs/' + a_id, headers=api_headers(TEST_KEY))).status_code == 404
        assert (await client.get('/api/v1/batch/jobs/' + dev_id, headers=api_headers())).status_code == 404
        assert (await client.get('/api/v1/batch/jobs/' + dev_id, headers=api_headers(TEST_KEY))).status_code == 200
        raw = raw_event()
        assert (await client.post('/api/v1/webhooks/feedback', content=raw, headers=signed(raw))).status_code == 202
        assert (await client.get('/api/v1/ingest/events/DELIVERY-1', headers=api_headers())).status_code == 404
        assert (await client.get('/api/v1/ingest/events/DELIVERY-1', headers=api_headers(TEST_KEY))).status_code == 200


async def test_production_ignores_both_legacy_mechanisms_even_if_flag_true():
    config = multi_settings(development_auth_enabled=True, webhook_integration_id=INTEGRATION, webhook_shared_secret=SECRET)
    raw = raw_event()
    async with multi_app(config=config) as (_, client, services):
        assert (await client.post('/api/v1/sentiment/analyze', json={'text': 'x'}, headers=api_headers(TEST_KEY))).status_code == 401
        assert (await client.post('/api/v1/webhooks/feedback', content=raw, headers=signed(raw))).status_code == 401
        assert not services.model.calls


@pytest.mark.protocol
async def test_mcp_remains_stateless_launcher_authorized_without_tenant_arguments_or_registry_disclosure():
    services = harness()
    server = create_mcp_server(multi_settings(), sentiment_service=services.sentiment, investigation_service=services.investigation)
    async with Client(server, mode='legacy', cache=None) as client:
        listing = await client.list_tools()
        assert {tool.name for tool in listing.tools} == {'analyze_feedback', 'investigate_feedback'}
        assert ALPHA_KEY not in str(listing) and BETA_KEY not in str(listing)
        for tool in listing.tools:
            assert 'tenant_id' not in tool.input_schema['properties']
            assert 'api_key' not in tool.input_schema['properties']
        denied = await client.call_tool('analyze_feedback', {'text': 'x', 'tenant_id': 'business_alpha'})
        assert denied.is_error and not services.model.calls
        accepted = await client.call_tool('analyze_feedback', {'text': 'Trusted launcher data.'})
        assert not accepted.is_error
