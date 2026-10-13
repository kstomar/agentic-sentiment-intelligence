import asyncio

import pytest

from app.core.exceptions import ApplicationError, ErrorCode
from app.core.tenant_auth import TenantRegistry, principal_context
from app.schemas.batch import UploadOptions
from app.services.batch_service import BatchService
from app.storage.job_store import JobStore
from tests.helpers import Model, harness, until
from tests.t07_helpers import (
    ALPHA_KEY, ALPHA_ROTATED_KEY, BETA_KEY, CREDENTIALS,
    api_headers, multi_app, multi_settings,
)


async def upload(client, key=ALPHA_KEY, text='Alpha private synthetic review.'):
    return await client.post('/api/v1/batch/upload', headers=api_headers(key),
        files={'file': ('reviews.csv', ('review\n' + text + '\n').encode(), 'text/csv')},
        data={'text_column': 'review', 'business_type': 'ecommerce'})


@pytest.mark.parametrize('suffix', ['', '/report', '/results', '/download'])
async def test_owner_can_read_but_foreign_and_missing_are_identical_404(suffix):
    async with multi_app() as (app, client, _):
        accepted = await upload(client)
        assert accepted.status_code == 202
        job = accepted.json()['job_id']
        alpha = app.state.tenant_registry.authenticate(ALPHA_KEY)
        await until(lambda: app.state.batch_service.status(job, principal=alpha).status == 'COMPLETED')
        own = await client.get('/api/v1/batch/jobs/' + job + suffix, headers=api_headers())
        assert own.status_code == 200
        foreign = await client.get('/api/v1/batch/jobs/' + job + suffix, headers=api_headers(BETA_KEY))
        absent = await client.get('/api/v1/batch/jobs/' + '0' * 32 + suffix, headers=api_headers(BETA_KEY))
        assert foreign.status_code == absent.status_code == 404
        assert foreign.json()['error'] == absent.json()['error']
        assert 'Alpha private synthetic review.' not in foreign.text


@pytest.mark.parametrize('method', ['status', 'report', 'results', 'download'])
async def test_service_and_store_enforce_ownership_without_http(method):
    async with multi_app() as (app, client, _):
        job = (await upload(client)).json()['job_id']
        registry = app.state.tenant_registry
        alpha, beta = registry.authenticate(ALPHA_KEY), registry.authenticate(BETA_KEY)
        service = app.state.batch_service
        with pytest.raises(ApplicationError) as error:
            getattr(service, method)(job, principal=beta)
        assert error.value.code == ErrorCode.BATCH_JOB_NOT_FOUND
        with pytest.raises(ApplicationError) as error:
            service._store.get(job, principal=beta)
        assert error.value.code == ErrorCode.BATCH_JOB_NOT_FOUND
        with principal_context(None):
            with pytest.raises(ApplicationError) as error: getattr(service, method)(job)
            assert error.value.code == ErrorCode.AUTHENTICATION_FAILED
            with pytest.raises(ApplicationError): service._store.get(job)
            with pytest.raises(ApplicationError): _ = service._store.jobs
        with principal_context(beta):
            assert job not in service._store.jobs
        assert service._store.get(job, principal=alpha).owner.tenant_id == 'business_alpha'


async def test_rotation_shares_ownership_and_quota_but_not_other_tenant_access():
    credentials = CREDENTIALS + [CREDENTIALS[0] | {'key_id': 'alpha_rotated', 'api_key': ALPHA_ROTATED_KEY}]
    gate = asyncio.Event()
    services = harness(model=Model(gate=gate))
    async with multi_app(credentials=credentials, services=services) as (app, client, _):
        first = await upload(client)
        assert first.status_code == 202
        job = first.json()['job_id']
        await until(lambda: services.model.active == 1)
        assert (await upload(client, ALPHA_ROTATED_KEY)).status_code == 429
        assert (await client.get('/api/v1/batch/jobs/' + job, headers=api_headers(ALPHA_ROTATED_KEY))).status_code == 200
        assert (await client.get('/api/v1/batch/jobs/' + job, headers=api_headers(BETA_KEY))).status_code == 404
        gate.set()
        alpha = app.state.tenant_registry.authenticate(ALPHA_ROTATED_KEY)
        await until(lambda: app.state.batch_service.status(job, principal=alpha).status == 'COMPLETED')
        assert (await client.get('/api/v1/batch/jobs/' + job + '/download', headers=api_headers(ALPHA_ROTATED_KEY))).status_code == 200
    revoked = TenantRegistry(multi_settings(credentials=[credentials[1], credentials[2]]))
    with pytest.raises(ApplicationError): revoked.authenticate(ALPHA_KEY)
    assert revoked.authenticate(ALPHA_ROTATED_KEY).tenant_id == 'business_alpha'


async def test_concurrent_business_jobs_have_independent_owners():
    gate = asyncio.Event()
    services = harness(model=Model(gate=gate))
    async with multi_app(services=services) as (app, client, _):
        a, b = await asyncio.gather(upload(client, ALPHA_KEY, 'Alpha.'), upload(client, BETA_KEY, 'Beta.'))
        assert a.status_code == b.status_code == 202
        await until(lambda: services.model.active == 2)
        a_id, b_id = a.json()['job_id'], b.json()['job_id']
        for owner, own, foreign in [(ALPHA_KEY, a_id, b_id), (BETA_KEY, b_id, a_id)]:
            assert (await client.get('/api/v1/batch/jobs/' + own, headers=api_headers(owner))).status_code == 200
            assert (await client.get('/api/v1/batch/jobs/' + foreign, headers=api_headers(owner))).status_code == 404
        gate.set()


async def test_expiration_erases_data_and_releases_owner_retention_quota():
    config = multi_settings(tenant_max_retained_batch_jobs=1)
    registry = TenantRegistry(config)
    alpha, beta = registry.authenticate(ALPHA_KEY), registry.authenticate(BETA_KEY)
    clock = [0.]
    store = JobStore(5, clock=lambda: clock[0], registry=registry)
    service = BatchService(harness().sentiment, config, store=store, registry=registry)
    try:
        job = await service.submit(b'review\nprivate', 'data.csv', 'text/csv', UploadOptions(text_column='review'), principal=alpha)
        await until(lambda: service.status(job.job_id, principal=alpha).status == 'COMPLETED')
        held = store.get(job.job_id, principal=alpha)
        with pytest.raises(ApplicationError) as error:
            await service.submit(b'review\nfine', 'data.csv', 'text/csv', UploadOptions(text_column='review'), principal=alpha)
        assert error.value.code == ErrorCode.TENANT_CAPACITY_EXCEEDED
        clock[0] = 5
        for principal in [alpha, beta]:
            with pytest.raises(ApplicationError) as error: service.status(job.job_id, principal=principal)
            assert error.value.code == ErrorCode.BATCH_JOB_NOT_FOUND
        assert held.records == [] and held.results == [] and held.report is None
        assert (await service.submit(b'review\nnew', 'data.csv', 'text/csv', UploadOptions(text_column='review'), principal=alpha)).job_id != job.job_id
    finally:
        await service.close()


async def test_untrusted_query_header_csv_metadata_cannot_select_owner():
    async with multi_app() as (app, client, _):
        response = await client.post('/api/v1/batch/upload?tenant_id=business_beta', headers=api_headers() | {'X-Tenant-ID': 'business_beta'},
            files={'file': ('reviews.csv', b'review,tenant_id\nFine.,business_beta', 'text/csv')}, data={'text_column': 'review', 'business_type': 'banking'})
        assert response.status_code == 202
        job = response.json()['job_id']
        alpha = app.state.tenant_registry.authenticate(ALPHA_KEY)
        assert app.state.batch_service._store.get(job, principal=alpha).owner.tenant_id == 'business_alpha'
        assert (await client.get('/api/v1/batch/jobs/' + job, headers=api_headers(BETA_KEY))).status_code == 404


async def test_no_untrusted_authority_rebind_of_existing_store():
    async with multi_app() as (app, client, _):
        assert (await upload(client)).status_code == 202
        wrong = multi_settings(credentials=[CREDENTIALS[0] | {'api_key': ALPHA_ROTATED_KEY}, CREDENTIALS[1]])
        with pytest.raises(ApplicationError) as error:
            BatchService(harness().sentiment, wrong, store=app.state.batch_service._store)
        assert error.value.code == ErrorCode.AUTHENTICATION_FAILED
