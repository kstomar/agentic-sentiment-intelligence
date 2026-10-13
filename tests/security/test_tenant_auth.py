import copy
import json
from dataclasses import FrozenInstanceError, replace

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.core.exceptions import ApplicationError, ErrorCode
from app.core.tenant_auth import DEVELOPMENT_TENANT, Permission, TenantRegistry, principal_context
from tests.helpers import TEST_KEY, settings
from tests.t07_helpers import (
    ALPHA_KEY, ALPHA_ROTATED_KEY, BETA_KEY, CREDENTIALS, INTEGRATIONS,
    api_headers, multi_app, multi_settings,
)


@pytest.mark.parametrize('key,owner,key_id', [(ALPHA_KEY, 'business_alpha', 'alpha_key'), (BETA_KEY, 'business_beta', 'beta_key')], ids=['alpha', 'beta'])
def test_registry_authenticates_immutable_principal_without_secret_repr(key, owner, key_id):
    registry = TenantRegistry(multi_settings())
    principal = registry.authenticate(key)
    assert (principal.tenant_id, principal.credential_id) == (owner, key_id)
    assert principal.permissions == frozenset(Permission)
    assert key not in repr(principal) and key not in repr(registry.settings)
    with pytest.raises(FrozenInstanceError):
        principal.tenant_id = 'someone_else'


@pytest.mark.parametrize('key', [None, '', 'invalid', TEST_KEY], ids=['missing', 'empty', 'invalid', 'legacy-disabled'])
def test_production_rejects_invalid_and_legacy_credentials(key):
    registry = TenantRegistry(multi_settings(development_auth_enabled=True))
    with pytest.raises(ApplicationError) as error:
        registry.authenticate(key)
    assert error.value.code == ErrorCode.AUTHENTICATION_FAILED


@pytest.mark.parametrize('raw', ['{}', 'null', 'false', '[1]', '[{}]', '[', 'NaN', '[{"tenant_id":"business_alpha","tenant_id":"business_beta"}]'])
def test_malformed_registry_fails_closed_without_echoing_input(raw):
    with pytest.raises(ValidationError) as error:
        multi_settings(tenant_credentials_json=raw)
    assert 'Invalid tenant security configuration.' in str(error.value)
    assert ALPHA_KEY not in str(error.value)


@pytest.mark.parametrize('mutation', [
    'duplicate_id', 'duplicate_key', 'key_other_tenant', 'bad_tenant', 'bad_id', 'short_key',
    'constant_key', 'extra_field', 'bad_permission', 'duplicate_permission', 'bad_permission_type',
    'reserved_tenant', 'reserved_key_id', 'unknown_integration_owner', 'duplicate_integration',
    'duplicate_integration_secret', 'bad_integration_id', 'short_integration_secret',
    'api_secret_reused_as_webhook', 'too_many_tenant_credentials',
])
def test_invalid_or_ambiguous_security_configuration_rejected(mutation):
    credentials = copy.deepcopy(CREDENTIALS)
    integrations = copy.deepcopy(INTEGRATIONS)
    if mutation == 'duplicate_id': credentials[1]['key_id'] = credentials[0]['key_id']
    elif mutation == 'duplicate_key': credentials[1]['api_key'] = credentials[0]['api_key']
    elif mutation == 'key_other_tenant': credentials.append(credentials[0] | {'tenant_id': 'business_beta', 'key_id': 'other'})
    elif mutation == 'bad_tenant': credentials[0]['tenant_id'] = '../other'
    elif mutation == 'bad_id': credentials[0]['key_id'] = 'invalid id'
    elif mutation == 'short_key': credentials[0]['api_key'] = 'password'
    elif mutation == 'constant_key': credentials[0]['api_key'] = 'a' * 43
    elif mutation == 'extra_field': credentials[0]['superuser'] = True
    elif mutation == 'bad_permission': credentials[0]['permissions'] = ['admin:all']
    elif mutation == 'duplicate_permission': credentials[0]['permissions'] = ['batch:read', 'batch:read']
    elif mutation == 'bad_permission_type': credentials[0]['permissions'] = 'batch:read'
    elif mutation == 'reserved_tenant': credentials[0]['tenant_id'] = DEVELOPMENT_TENANT
    elif mutation == 'reserved_key_id': credentials[0]['key_id'] = 'legacy-app-key'
    elif mutation == 'unknown_integration_owner': integrations[0]['tenant_id'] = 'unknown'
    elif mutation == 'duplicate_integration': integrations[1]['integration_id'] = integrations[0]['integration_id']
    elif mutation == 'duplicate_integration_secret': integrations[2]['shared_secret'] = integrations[0]['shared_secret']
    elif mutation == 'bad_integration_id': integrations[0]['integration_id'] = 'bad.id'
    elif mutation == 'short_integration_secret': integrations[0]['shared_secret'] = 'short'
    elif mutation == 'api_secret_reused_as_webhook': integrations[0]['shared_secret'] = credentials[0]['api_key']
    elif mutation == 'too_many_tenant_credentials':
        credentials = [credentials[0] | {'key_id': f'alpha_{i}', 'api_key': ALPHA_KEY + str(i)} for i in range(9)] + [credentials[1]]
    with pytest.raises(ValidationError) as error:
        multi_settings(credentials=credentials, integrations=integrations)
    assert ALPHA_KEY not in str(error.value)


@pytest.mark.parametrize('raw', ['[]' * 40000, '[{"tenant_id":"business_alpha","key_id":"a","api_key":"' + ALPHA_KEY + '","api_key":"' + BETA_KEY + '"}]'])
def test_registry_byte_bound_and_duplicate_json_properties(raw):
    with pytest.raises(ValidationError):
        multi_settings(tenant_credentials_json=raw)


def test_registry_count_limits_and_tenant_bound():
    rows = [{'tenant_id': f'tenant_{i}', 'key_id': f'key_{i}', 'api_key': ALPHA_KEY + str(i)} for i in range(33)]
    with pytest.raises(ValidationError):
        multi_settings(credentials=rows, integrations=[])
    rows = rows[:1] * 129
    with pytest.raises(ValidationError):
        multi_settings(credentials=rows, integrations=[])


def test_settings_reads_json_from_environment_without_unmasking(monkeypatch):
    monkeypatch.setenv('TENANT_CREDENTIALS_JSON', json.dumps(CREDENTIALS))
    monkeypatch.setenv('WEBHOOK_INTEGRATIONS_JSON', json.dumps(INTEGRATIONS))
    config = Settings(_env_file=None, app_env='production', development_auth_enabled=False)
    assert TenantRegistry(config).authenticate(ALPHA_KEY).tenant_id == 'business_alpha'
    assert ALPHA_KEY not in repr(config)


@pytest.mark.parametrize('field,value', [
    ('tenant_credentials_json', json.dumps([{'api_key': ALPHA_KEY}])),
    ('webhook_integrations_json', json.dumps([{'shared_secret': ALPHA_KEY}])),
    ('webhook_shared_secret', 'private-short-secret'),
])
def test_pydantic_structured_configuration_errors_do_not_echo_secret_input(field, value):
    with pytest.raises(ValidationError) as error:
        Settings(_env_file=None, **{field: value})
    assert value not in str(error.value) and ALPHA_KEY not in repr(error.value.errors())
    assert 'private-short-secret' not in repr(error.value.errors())
    assert ALPHA_KEY not in error.value.json() and 'private-short-secret' not in error.value.json()


@pytest.mark.parametrize('field', ['model_max_concurrent_calls', 'ingress_max_concurrent_requests', 'batch_model_concurrency', 'webhook_max_concurrent_analyses'])
def test_business_mode_rejects_global_budgets_without_tenant_headroom(field):
    with pytest.raises(ValidationError): multi_settings(**{field: 1})


def test_legacy_is_an_explicit_owning_principal_and_cannot_be_ambiguous():
    registry = TenantRegistry(settings())
    assert registry.authenticate(TEST_KEY).tenant_id == DEVELOPMENT_TENANT
    with pytest.raises(ApplicationError):
        TenantRegistry(settings(development_auth_enabled=False)).authenticate(TEST_KEY)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, app_env='development', development_auth_enabled=True,
                 app_api_key=ALPHA_KEY, tenant_credentials_json=json.dumps(CREDENTIALS))


def test_business_registry_disables_implicit_development_fallback():
    config = Settings(_env_file=None, app_env='development', app_api_key=TEST_KEY,
                      tenant_credentials_json=json.dumps(CREDENTIALS))
    with pytest.raises(ApplicationError): TenantRegistry(config).authenticate(TEST_KEY)
    explicit = config.model_copy(update={'development_auth_enabled': True})
    assert TenantRegistry(explicit).authenticate(TEST_KEY).tenant_id == DEVELOPMENT_TENANT


def test_forged_claims_or_unrelated_registry_cannot_be_used_as_authority():
    registry = TenantRegistry(multi_settings())
    alpha = registry.authenticate(ALPHA_KEY)
    for forged in [replace(alpha, tenant_id='business_beta'), replace(alpha, credential_id='beta_key'),
                   replace(alpha, _proof=b'wrong'), 'business_alpha']:
        with pytest.raises(ApplicationError) as error:
            registry.require(forged)
        assert error.value.code == ErrorCode.AUTHENTICATION_FAILED
    other = TenantRegistry(multi_settings(credentials=[CREDENTIALS[0] | {'api_key': ALPHA_ROTATED_KEY}, CREDENTIALS[1]]))
    with pytest.raises(ApplicationError):
        registry.require(other.authenticate(ALPHA_ROTATED_KEY))
    with principal_context(None):
        with pytest.raises(ApplicationError): registry.require()


@pytest.mark.parametrize('method,path', [
    ('POST', '/api/v1/sentiment/analyze'), ('POST', '/api/v1/agent/investigate'),
    ('POST', '/api/v1/chat'), ('POST', '/api/v1/batch/upload'), ('POST', '/api/v1/ingest/feedback'),
    ('GET', '/api/v1/batch/jobs/' + '0' * 32),
    ('GET', '/api/v1/batch/jobs/' + '0' * 32 + '/report'),
    ('GET', '/api/v1/batch/jobs/' + '0' * 32 + '/results'),
    ('GET', '/api/v1/batch/jobs/' + '0' * 32 + '/download'),
    ('GET', '/api/v1/ingest/events/missing'),
])
async def test_missing_permissions_are_403_on_every_protected_operation(method, path):
    credentials = [CREDENTIALS[0] | {'permissions': []}, CREDENTIALS[1]]
    async with multi_app(credentials=credentials) as (_, client, services):
        response = await client.request(method, path, headers=api_headers(), json={})
        assert response.status_code == 403 and response.json()['error']['code'] == 'AUTHORIZATION_FAILED'
        assert not services.model.calls and not services.selector.calls


@pytest.mark.parametrize('key', [None, 'wrong', TEST_KEY], ids=['missing', 'invalid', 'legacy-disabled'])
async def test_http_missing_invalid_or_legacy_in_production_cannot_infer_or_leak(key, caplog):
    async with multi_app() as (_, client, services):
        response = await client.post('/api/v1/sentiment/analyze', json={'text': 'Synthetic.'}, headers={} if key is None else api_headers(key))
        assert response.status_code == 401 and not services.model.calls
        assert ALPHA_KEY not in response.text and BETA_KEY not in response.text
    assert ALPHA_KEY not in caplog.text and BETA_KEY not in caplog.text
