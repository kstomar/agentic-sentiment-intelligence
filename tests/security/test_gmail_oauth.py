import asyncio
import base64
import hashlib
import time
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from app.core.exceptions import ApplicationError
from app.core.tenant_auth import principal_context
from app.integrations.google_gmail import SCOPE
from tests.helpers import until
from tests.t07_helpers import ALPHA_KEY, BETA_KEY, CREDENTIALS, api_headers
from tests.t08_helpers import ACCESS_A, ACCESS_B, CLIENT_SECRET, REFRESH_A, FakeGoogle, authorize, gmail_app

BASE = '/api/v1/integrations/gmail'


async def start(client, key=ALPHA_KEY):
    response = await client.post(BASE + '/connect', headers=api_headers(key))
    assert response.status_code == 200
    return parse_qs(urlsplit(response.json()['authorization_url']).query)


async def test_state_pkce_fixed_redirect_readonly_and_private_url_metadata():
    async with gmail_app() as (app, client, _, fake):
        a, b = await start(client), await start(client, BETA_KEY)
        assert a['state'] != b['state']
        assert a['scope'] == [SCOPE] and a['access_type'] == ['offline']
        assert a['redirect_uri'] == ['https://api.example.test/api/v1/integrations/gmail/oauth/callback']
        assert a['code_challenge_method'] == ['S256']
        pending = app.state.gmail_service.store._states[hashlib.sha256(a['state'][0].encode()).digest()]
        verifier = pending.verifier.get_secret_value()
        expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
        assert a['code_challenge'] == [expected]
        assert verifier not in str(a) and CLIENT_SECRET not in str(a)
        assert pending.owner.tenant_id == 'business_alpha' and not fake.requests


@pytest.mark.parametrize('path,method', [('/connect', 'POST'), ('/status', 'GET'), ('/disconnect', 'DELETE'),
    ('/import', 'POST'), ('/imports/'+'0'*32, 'GET'), ('/imports/'+'0'*32+'/results', 'GET')])
@pytest.mark.parametrize('key', [None, 'incorrect'], ids=['missing', 'invalid'])
async def test_protected_gmail_routes_authenticate_before_provider(path, method, key):
    async with gmail_app() as (_, client, _, fake):
        response = await client.request(method, BASE + path, headers={} if key is None else api_headers(key), json={})
        assert response.status_code == 401 and not fake.requests


@pytest.mark.parametrize('path,method', [('/connect', 'POST'), ('/status', 'GET'), ('/disconnect', 'DELETE'),
    ('/import', 'POST'), ('/imports/'+'0'*32, 'GET'), ('/imports/'+'0'*32+'/results', 'GET')])
async def test_gmail_permissions_do_not_come_from_request_fields(path, method):
    rows = [CREDENTIALS[0] | {'permissions': ['sentiment:analyze']}, CREDENTIALS[1]]
    async with gmail_app(credentials=rows) as (_, client, _, fake):
        response = await client.request(method, BASE + path, headers=api_headers(), json={'tenant_id': 'business_alpha'})
        assert response.status_code == 403 and not fake.requests


@pytest.mark.parametrize('overrides', [
    {'gmail_oauth_enabled': False}, {'google_oauth_client_id': None}, {'google_oauth_client_secret': None},
    {'google_oauth_redirect_uri': None}, {'google_oauth_redirect_uri': 'https://evil.example.test/other'},
    {'google_oauth_redirect_uri': 'http://localhost/api/v1/integrations/gmail/oauth/callback'},
    {'google_oauth_redirect_uri': 'https://api.example.test/api/v1/integrations/gmail/oauth/callback?tenant_id=x'},
    {'google_oauth_redirect_uri': 'https://user:password@api.example.test/api/v1/integrations/gmail/oauth/callback'},
])
async def test_configuration_failure_is_closed_and_other_apis_still_work(overrides):
    async with gmail_app(**overrides) as (_, client, _, fake):
        response = await client.post(BASE + '/connect', headers=api_headers())
        assert response.status_code == 503 and response.json()['error']['code'] == 'GMAIL_NOT_CONFIGURED'
        assert not fake.requests
        assert (await client.post('/api/v1/sentiment/analyze', headers=api_headers(), json={'text': 'Works.'})).status_code == 200


async def test_local_http_requires_explicit_nonproduction_mode():
    async with gmail_app(app_env='development', development_auth_enabled=False, gmail_allow_localhost_http=True,
                         google_oauth_redirect_uri='http://127.0.0.1:8000/api/v1/integrations/gmail/oauth/callback') as (_, client, _, _):
        assert (await client.post(BASE + '/connect', headers=api_headers())).status_code == 200
    async with gmail_app(gmail_allow_localhost_http=True, google_oauth_redirect_uri='http://localhost/api/v1/integrations/gmail/oauth/callback') as (_, client, _, _):
        assert (await client.post(BASE + '/connect', headers=api_headers())).status_code == 503


async def test_callback_consumes_state_without_api_key_and_never_returns_tokens(caplog):
    async with gmail_app() as (app, client, _, fake):
        params = await start(client)
        state = params['state'][0]
        response = await client.get(BASE + '/oauth/callback', params={'state': state, 'code': 'alpha-code'}, headers=api_headers(BETA_KEY))
        assert response.status_code == 200 and response.json() == {'status': 'CONNECTED'}
        assert response.headers['Cache-Control'] == 'no-store' and response.headers['Referrer-Policy'] == 'no-referrer'
        posted = parse_qs(fake.requests[0].content.decode())
        assert posted['grant_type'] == ['authorization_code'] and posted['client_secret'] == [CLIENT_SECRET]
        assert posted['redirect_uri'] == params['redirect_uri'] and len(posted['code_verifier'][0]) >= 43
        assert (await client.get(BASE + '/status', headers=api_headers())).json()['mailbox'] == 'alpha@example.test'
        assert (await client.get(BASE + '/status', headers=api_headers(BETA_KEY))).json()['connected'] is False
        assert (await client.get(BASE + '/oauth/callback', params={'state': state, 'code': 'alpha-code'})).status_code == 400
        assert len([r for r in fake.requests if r.url.path == '/token']) == 1
        assert not app.state.gmail_service.store._states and not app.state.gmail_service.store._flows
        for secret in [ACCESS_A, REFRESH_A, CLIENT_SECRET, state, 'alpha-code']:
            assert secret not in response.text and secret not in caplog.text


async def test_google_callback_with_state_code_issuer_and_scope_connects_once():
    async with gmail_app() as (_, client, _, fake):
        params = await start(client)
        query = {'state': params['state'][0], 'code': 'alpha-code',
                 'iss': 'https://accounts.google.com', 'scope': SCOPE}
        response = await client.get(BASE + '/oauth/callback', params=query)
        assert response.status_code == 200 and response.json() == {'status': 'CONNECTED'}
        assert response.headers['Cache-Control'] == 'no-store'
        assert response.headers['Referrer-Policy'] == 'no-referrer'
        posted = parse_qs(fake.requests[0].content.decode())
        assert posted['code'] == ['alpha-code'] and posted['redirect_uri'] == params['redirect_uri']
        assert (await client.get(BASE + '/oauth/callback', params=query)).status_code == 400
        assert len([r for r in fake.requests if r.url.path == '/token']) == 1


async def test_state_expiration_releases_capacity_and_rejects_replay():
    async with gmail_app(gmail_max_oauth_states=1) as (app, client, _, fake):
        params = await start(client)
        assert (await client.post(BASE + '/connect', headers=api_headers(BETA_KEY))).status_code == 429
        pending = next(iter(app.state.gmail_service.store._states.values()))
        pending.expires_at = time.monotonic()-1
        response = await client.get(BASE + '/oauth/callback', params={'state': params['state'][0], 'code': 'alpha-code'})
        assert response.status_code == 400 and not fake.requests and pending.verifier is None
        assert (await client.post(BASE + '/connect', headers=api_headers(BETA_KEY))).status_code == 200


async def test_parallel_callback_replay_does_not_exchange_twice():
    fake = FakeGoogle(); gate = asyncio.Event(); fake.gates['/token'] = gate
    async with gmail_app(fake=fake) as (_, client, _, _):
        params = await start(client)
        task = asyncio.create_task(client.get(BASE + '/oauth/callback', params={'state': params['state'][0], 'code': 'alpha-code'}))
        await until(lambda: len(fake.requests) == 1)
        replay = await client.get(BASE + '/oauth/callback', params={'state': params['state'][0], 'code': 'alpha-code'})
        assert replay.status_code == 400
        gate.set()
        assert (await task).status_code == 200
        assert len([r for r in fake.requests if r.url.path == '/token']) == 1


@pytest.mark.parametrize('extra', [{'tenant_id': 'business_beta'}, {'redirect_uri': 'https://evil.example.test'}, {'code': 'other', 'error': 'access_denied'}])
async def test_callback_cannot_select_tenant_or_redirect(extra):
    async with gmail_app() as (_, client, _, fake):
        params = await start(client)
        response = await client.get(BASE + '/oauth/callback', params={'state': params['state'][0], 'code': 'alpha-code'} | extra)
        assert response.status_code == 422 and not fake.requests


async def test_denial_consumes_state_and_unknown_or_missing_state_is_safe():
    async with gmail_app() as (_, client, _, fake):
        params = await start(client)
        response = await client.get(BASE + '/oauth/callback', params={'state': params['state'][0], 'error': 'access_denied', 'error_description': 'private description'})
        assert response.status_code == 400 and 'private description' not in response.text
        for state in [params['state'][0], 'invalid', 'x'*43]:
            assert (await client.get(BASE + '/oauth/callback', params={'state': state, 'code': 'alpha-code'})).status_code == 400
        assert (await client.get(BASE + '/oauth/callback', params={'code': 'alpha-code'})).status_code == 400
        assert not fake.requests


@pytest.mark.parametrize('change', [{'scope': 'https://www.googleapis.com/auth/gmail.modify'}, {'scope': SCOPE+' profile'}, {'scope': ''}, {'expires_in': True}, {'token_type': 'DPoP'}])
async def test_token_response_requires_exact_scope_and_bearer_contract(change):
    fake = FakeGoogle();fake.token_data.update(change)
    async with gmail_app(fake=fake) as (app, client, _, _):
        response = await authorize(client)
        assert response.status_code in {400, 502}
        assert not app.state.gmail_service.store._connections
        assert ACCESS_A not in response.text
        assert not any(r.url.path.endswith('/profile') for r in fake.requests)


async def test_token_exchange_not_retried_and_provider_errors_are_sanitized():
    fake = FakeGoogle();fake.failures['/token'] = [httpx.Response(500, json={'error': CLIENT_SECRET})]
    async with gmail_app(fake=fake) as (_, client, _, _):
        response = await authorize(client)
        assert response.status_code == 502 and CLIENT_SECRET not in response.text
        assert len(fake.requests) == 1


async def test_verified_mailbox_cannot_be_claimed_by_another_tenant():
    fake = FakeGoogle();fake.addresses[ACCESS_B] = fake.addresses[ACCESS_A]
    async with gmail_app(fake=fake) as (app, client, _, _):
        assert (await authorize(client)).status_code == 200
        response = await authorize(client, BETA_KEY, 'beta-code')
        assert response.status_code == 409 and 'alpha@example.test' not in response.text
        assert (await client.get(BASE + '/status', headers=api_headers(BETA_KEY))).json()['mailbox'] is None
        assert len(app.state.gmail_service.store._connections) == 1


async def test_disconnect_invalidates_pending_and_inflight_authorization():
    fake = FakeGoogle();gate = asyncio.Event();fake.gates['/token'] = gate
    async with gmail_app(fake=fake) as (app, client, _, _):
        params = await start(client)
        task = asyncio.create_task(client.get(BASE + '/oauth/callback', params={'state': params['state'][0], 'code': 'alpha-code'}))
        await until(lambda: len(fake.requests) == 1)
        assert (await client.delete(BASE + '/disconnect', headers=api_headers())).status_code == 200
        gate.set()
        assert (await task).status_code == 400
        assert not app.state.gmail_service.store._connections
        assert not app.state.gmail_service.store._flows


async def test_service_authority_required_and_callback_query_is_bounded():
    async with gmail_app() as (app, client, _, fake):
        with principal_context(None):
            with pytest.raises(ApplicationError): app.state.gmail_service.connect()
            with pytest.raises(ApplicationError): app.state.gmail_service.status()
        response = await client.get(BASE + '/oauth/callback?code='+'a'*8193)
        assert response.status_code == 413 and not fake.requests


async def test_google_http_capacity_is_immediate_and_bounded_across_callbacks():
    fake = FakeGoogle();gate = asyncio.Event();fake.gates['/token'] = gate
    async with gmail_app(fake=fake, gmail_http_max_concurrent_calls=1) as (app, client, _, _):
        a, b = await start(client), await start(client, BETA_KEY)
        task = asyncio.create_task(client.get(BASE + '/oauth/callback', params={'state': a['state'][0], 'code': 'alpha-code'}))
        await until(lambda: app.state.gmail_service.google.active == 1)
        denied = await client.get(BASE + '/oauth/callback', params={'state': b['state'][0], 'code': 'beta-code'})
        assert denied.status_code == 429 and len(fake.requests) == 1
        gate.set()
        assert (await task).status_code == 200
        assert app.state.gmail_service.google.active == 0


async def test_profile_address_is_verified_and_invalid_provider_identity_is_not_stored():
    fake = FakeGoogle();fake.addresses[ACCESS_A] = 'untrusted display <other@example.test>'
    async with gmail_app(fake=fake) as (app, client, _, _):
        response = await authorize(client)
        assert response.status_code == 502
        assert not app.state.gmail_service.store._connections
        assert 'other@example.test' not in response.text


async def test_duplicate_callback_parameters_do_not_bypass_single_state_policy():
    async with gmail_app() as (_, client, _, fake):
        params = await start(client)
        response = await client.get(BASE + '/oauth/callback', params=[('state', params['state'][0]), ('state', params['state'][0]), ('code', 'alpha-code')])
        assert response.status_code == 422 and not fake.requests


@pytest.mark.parametrize('issuer', [
    '', 'https://other.example.test', 'http://accounts.google.com',
    'https://accounts.google.com.evil.example.test', 'https://accounts.google.com/',
    'https://accounts.google.com:443', 'https://accounts.google.com@evil.example.test',
    'https://accounts.google.com?issuer=other', 'https://accounts.google.com#issuer',
    ' https://accounts.google.com', 'https://ACCOUNTS.google.com',
])
async def test_callback_rejects_nonexact_google_issuer_before_token_exchange(issuer):
    async with gmail_app() as (_, client, _, fake):
        params = await start(client)
        query = {'state': params['state'][0], 'code': 'alpha-code', 'iss': issuer, 'scope': SCOPE}
        response = await client.get(BASE + '/oauth/callback', params=query)
        assert response.status_code == 422 and response.json()['error']['code'] == 'VALIDATION_ERROR'
        assert not fake.requests
        # Invalid query metadata cannot consume a legitimate flow or change its issuer.
        query['iss'] = 'https://accounts.google.com'
        assert (await client.get(BASE + '/oauth/callback', params=query)).status_code == 200


@pytest.mark.parametrize('parameter', ['state', 'code', 'iss', 'scope'])
async def test_google_callback_rejects_duplicate_parameters_even_with_valid_issuer(parameter):
    async with gmail_app() as (_, client, _, fake):
        params = await start(client)
        query = {'state': params['state'][0], 'code': 'alpha-code',
                 'iss': 'https://accounts.google.com', 'scope': SCOPE}
        duplicated = list(query.items()) + [(parameter, query[parameter])]
        response = await client.get(BASE + '/oauth/callback', params=duplicated)
        assert response.status_code == 422 and not fake.requests


@pytest.mark.parametrize('parameter', ['redirect_uri', 'redirect', 'client_id', 'tenant_id', 'token_endpoint'])
async def test_google_callback_does_not_allow_redirect_or_authority_overrides(parameter):
    async with gmail_app() as (_, client, _, fake):
        params = await start(client)
        query = {'state': params['state'][0], 'code': 'alpha-code',
                 'iss': 'https://accounts.google.com', 'scope': SCOPE,
                 parameter: 'https://untrusted.example.test'}
        response = await client.get(BASE + '/oauth/callback', params=query)
        assert response.status_code == 422 and not fake.requests


@pytest.mark.parametrize('callback_scope,token_scope,expected', [
    (SCOPE, 'https://www.googleapis.com/auth/gmail.modify', 400),
    ('https://www.googleapis.com/auth/gmail.modify', SCOPE, 200),
])
async def test_google_callback_scope_is_metadata_and_token_scope_is_authoritative(callback_scope, token_scope, expected):
    fake = FakeGoogle(); fake.token_data['scope'] = token_scope
    async with gmail_app(fake=fake) as (app, client, _, _):
        params = await start(client)
        response = await client.get(BASE + '/oauth/callback', params={
            'state': params['state'][0], 'code': 'alpha-code',
            'iss': 'https://accounts.google.com', 'scope': callback_scope,
        })
        assert response.status_code == expected
        assert len([r for r in fake.requests if r.url.path == '/token']) == 1
        if expected == 400:
            assert response.json()['error']['code'] == 'GMAIL_SCOPE_INVALID'
            assert not app.state.gmail_service.store._connections
            assert not any(r.url.path.endswith('/profile') for r in fake.requests)
        else:
            assert response.json() == {'status': 'CONNECTED'}


async def test_google_denial_with_valid_issuer_still_consumes_state():
    async with gmail_app() as (_, client, _, fake):
        params = await start(client)
        query = {'state': params['state'][0], 'iss': 'https://accounts.google.com', 'scope': SCOPE}
        response = await client.get(BASE + '/oauth/callback', params=query | {'error': 'access_denied'})
        assert response.status_code == 400 and response.json()['error']['code'] == 'GMAIL_OAUTH_DENIED'
        replay = await client.get(BASE + '/oauth/callback', params=query | {'code': 'alpha-code'})
        assert replay.status_code == 400 and replay.json()['error']['code'] == 'GMAIL_INVALID_STATE'
        assert not fake.requests
