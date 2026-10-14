"""Real PostgreSQL-only persistence/recovery tests; no SQLite or live inference."""
import asyncio
from contextlib import asynccontextmanager
from datetime import timedelta
import json
import os
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import func, select, text
from pydantic import SecretStr
from sqlalchemy.engine import make_url
from sqlalchemy.schema import CreateSchema, DropSchema

from app.core.exceptions import ApplicationError, ErrorCode as E
from app.core.tenant_auth import TenantRegistry
from app.main import create_app
from app.schemas.batch import UploadOptions
from app.storage.batch_models import BatchJobRow as J, BatchRecordRow as R
from app.storage.database import REVISION, create_database_engine, upgrade_database
from app.storage.postgres_job_store import PostgresJobStore, now
from tests.helpers import Model, analysis, harness, until, xlsx
from tests.t07_helpers import ALPHA_KEY, ALPHA_ROTATED_KEY, BETA_KEY, CREDENTIALS, api_headers, multi_settings


@pytest.fixture
def postgres_url():
    raw=os.environ.get('T09_TEST_DATABASE_URL')
    if not raw:pytest.skip('T09_TEST_DATABASE_URL is required for real PostgreSQL tests')
    parsed=make_url(raw)
    if parsed.drivername!='postgresql+psycopg' or not parsed.database.endswith('_test'):
        pytest.fail('Use a dedicated PostgreSQL database whose name ends in _test')
    engine=create_database_engine(raw)
    schema='t09_'+uuid4().hex
    with engine.begin() as connection:connection.execute(CreateSchema(schema))
    scoped=parsed.update_query_dict({'options':'-csearch_path='+schema}).render_as_string(hide_password=False)
    try:
        upgrade_database(scoped)
        yield SecretStr(scoped)
    finally:
        with engine.begin() as connection:connection.execute(DropSchema(schema,cascade=True))
        engine.dispose()


@asynccontextmanager
async def app_client(url, *, services=None, **overrides):
    services=services or harness()
    config=multi_settings(database_url=url,batch_job_ttl_seconds=0,**overrides)
    app=create_app(config,sentiment_service=services.sentiment,investigation_service=services.investigation)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app),base_url='http://postgres-test.local') as client:
            yield app,client,services


async def upload(client, data=b'id,review\nA,First review.\nB,Second review.', *, extension='csv',fields=None,key=ALPHA_KEY):
    return await client.post('/api/v1/batch/upload',headers=api_headers(key),
        data=fields or {'text_column':'review','id_column':'id'},files={'file':('synthetic.'+extension,data,'application/octet-stream')})


async def terminal(app,job,key=ALPHA_KEY):
    owner=app.state.tenant_registry.authenticate(key)
    await until(lambda:app.state.batch_service.status(job,principal=owner).status in {'COMPLETED','PARTIAL_SUCCESS','FAILED'},timeout=15)


@pytest.mark.parametrize('extension',['csv','xlsx'])
async def test_postgres_upload_commit_restart_report_results_and_download(postgres_url,extension):
    data=b'id,review\nA,First review.\nB,Second review.' if extension=='csv' else xlsx([['id','review'],['A','First review.'],['B','Second review.']])
    async with app_client(postgres_url) as (app,client,services):
        response=await upload(client,data,extension=extension)
        assert response.status_code==202
        job=response.json()['job_id'];assert len(job)==32
        await terminal(app,job)
        path='/api/v1/batch/jobs/'+job
        before={suffix:(await client.get(path+suffix,headers=api_headers())).json() for suffix in ['','/report','/results','/download']}
        assert before['']['successful_records']==2
        assert len(services.model.calls)==2
        engine=app.state.batch_service._store.engine
        with engine.connect() as connection:
            assert connection.scalar(select(func.count()).select_from(J))==1
            assert connection.scalar(select(func.count()).select_from(R).where(R.status=='SUCCESS'))==2
            assert connection.scalar(select(func.count()).select_from(R).where(R.raw_text.is_not(None)))==0
    second=harness()
    async with app_client(postgres_url,services=second) as (_,client,_):
        for suffix,value in before.items():
            response=await client.get(path+suffix,headers=api_headers())
            assert response.status_code==200 and response.json()==value
        assert not second.model.calls
        page=(await client.get(path+'/results?page=2&page_size=1',headers=api_headers())).json()
        assert len(page['results'])==1 and page['results'][0]['feedback_id']=='B'


async def test_postgres_100_record_interruption_keeps_40_commits_and_recovers_60(postgres_url):
    class StopAfter40(Model):
        async def ainvoke(self,messages):
            if len(self.calls)>=40:
                await asyncio.Event().wait()
            return await super().ainvoke(messages)
    model=StopAfter40();services=harness(model=model)
    async with app_client(postgres_url,services=services) as (app,client,_):
        data=('id,review\n'+'\n'.join(f'{i},Synthetic review {i}.' for i in range(100))).encode()
        response=await upload(client,data);assert response.status_code==202
        job=response.json()['job_id'];owner=app.state.tenant_registry.authenticate(ALPHA_KEY)
        await until(lambda:app.state.batch_service.status(job,principal=owner).processed_records==40,timeout=15)
        assert app.state.batch_service.status(job,principal=owner).status=='RUNNING'
    resumed=harness()
    async with app_client(postgres_url,services=resumed) as (app,client,_):
        await terminal(app,job)
        response=await client.get('/api/v1/batch/jobs/'+job+'/download',headers=api_headers())
        value=response.json();assert response.status_code==200
        assert value['report']['processed_records']==value['report']['successful_records']==100
        assert len(value['results'])==100 and len(resumed.model.calls)==60
        assert {c['text'] for c in resumed.model.calls}=={f'Synthetic review {i}.' for i in range(40,100)}


async def test_postgres_stale_crash_claim_is_recovered_without_repeating_committed_rows(postgres_url):
    config=multi_settings(database_url=postgres_url,batch_job_ttl_seconds=0)
    registry=TenantRegistry(config);owner=registry.authenticate(ALPHA_KEY)
    store=PostgresJobStore(config,registry);store.start()
    from app.services.file_parser import FileParser
    records=FileParser(max_bytes=4096,max_records=100,max_text=5000,max_extracted=4096).parse(b'id,review\nA,First.\nB,Second.','a.csv','text/csv',UploadOptions(text_column='review',id_column='id')).records
    job=store.add(UploadOptions(text_column='review',id_column='id'),records,0,principal=owner)
    store.running(job)
    token,_=store.claim(job,'A')
    from app.schemas.batch import BatchResult
    result=BatchResult(**records[0].meta.model_dump(),status='SUCCESS',attempted=True,**analysis('First.'))
    store.save_result(job,records[0],result,token)
    store.claim(job,'B')
    # Abrupt process death leaves PROCESSING in PostgreSQL; emulate elapsed lease.
    with store.engine.begin() as connection:
        connection.execute(R.__table__.update().where(R.feedback_id=='B').values(claim_expires_at=now()-timedelta(seconds=1)))
    store.close()  # Repository close doesn't pause DB rows; no BatchService graceful hook.
    fresh=harness()
    async with app_client(postgres_url,services=fresh) as (app,client,_):
        await terminal(app,job.job_id)
        assert [c['text'] for c in fresh.model.calls]==['Second.']
        report=(await client.get('/api/v1/batch/jobs/'+job.job_id+'/report',headers=api_headers())).json()
        assert report['successful_records']==2 and report['failed_records']==0


async def test_postgres_concurrent_claims_and_stale_writer_fencing(postgres_url):
    config=multi_settings(database_url=postgres_url,batch_job_ttl_seconds=0)
    registry=TenantRegistry(config);store=PostgresJobStore(config,registry);store.start()
    from app.schemas.batch import ParsedRecord,RecordMetadata
    record=ParsedRecord(meta=RecordMetadata(feedback_id='A',source_row=2),text='Only review.')
    job=store.add(UploadOptions(text_column='review'),[record],0,principal=registry.authenticate(ALPHA_KEY))
    try:
        claims=await asyncio.gather(*(asyncio.to_thread(store.claim,job,'A') for _ in range(4)))
        assert sum(token is not None for token,_ in claims)==1
        old=next(token for token,_ in claims if token)
        with store.engine.begin() as connection:connection.execute(R.__table__.update().values(claim_expires_at=now()-timedelta(seconds=1)))
        new,_=store.claim(job,'A');assert new and new!=old
        from app.schemas.batch import BatchResult
        result=BatchResult(**record.meta.model_dump(),status='SUCCESS',attempted=True,**analysis(record.text))
        with pytest.raises(ApplicationError):store.save_result(job,record,result,old)
        store.save_result(job,record,result,new)
        assert store.get(job.job_id,principal=registry.authenticate(ALPHA_KEY)).snapshot().processed_records==1
    finally:store.close()


@pytest.mark.parametrize('suffix',['','/report','/results','/download'])
async def test_postgres_foreign_and_unknown_job_access_denied_after_restart(postgres_url,suffix):
    async with app_client(postgres_url) as (app,client,_):
        job=(await upload(client)).json()['job_id'];await terminal(app,job)
    async with app_client(postgres_url) as (_,client,_):
        path='/api/v1/batch/jobs/'+job+suffix
        foreign=await client.get(path,headers=api_headers(BETA_KEY))
        unknown=await client.get('/api/v1/batch/jobs/'+'0'*32+suffix,headers=api_headers(BETA_KEY))
        assert foreign.status_code==unknown.status_code==404
        assert foreign.json()['error']==unknown.json()['error']
        assert (await client.get(path,headers=api_headers())).status_code==200


async def test_postgres_partial_failures_invalid_rows_and_report_math(postgres_url):
    services=harness(model=Model(errors={'bad':ApplicationError(E.UPSTREAM_RATE_LIMITED)}))
    async with app_client(postgres_url,services=services) as (app,client,_):
        job=(await upload(client,b'id,review\nA,good\nB,bad\nC,')).json()['job_id'];await terminal(app,job)
        path='/api/v1/batch/jobs/'+job
        report=(await client.get(path+'/report',headers=api_headers())).json()
        assert report['status']=='PARTIAL_SUCCESS'
        assert (report['total_records'],report['processed_records'],report['successful_records'],report['failed_records'])==(3,3,1,2)
        assert sum(report['sentiment_percentages'].values())==100
        assert report['valid_records']==report['attempted_records']==2
        assert len(services.model.calls)==2


@pytest.mark.parametrize('data',[b'id,review\nA,x\nA,y',b'id,review\nA,',b'id,other\nA,x'])
async def test_postgres_validation_contract_and_duplicate_ids(postgres_url,data):
    async with app_client(postgres_url) as (app,client,services):
        response=await upload(client,data)
        assert response.status_code==422 and not services.model.calls
        if data==b'id,review\nA,':
            assert response.json()['error']['code']=='BATCH_NO_VALID_RECORDS'
        with app.state.batch_service._store.engine.connect() as connection:
            assert connection.scalar(select(func.count()).select_from(J))==0


async def test_postgres_database_failure_never_acknowledges_uncommitted_job(postgres_url,monkeypatch,caplog):
    async with app_client(postgres_url) as (app,client,services):
        store=app.state.batch_service._store
        from sqlalchemy.exc import OperationalError
        original=store.engine.dialect.do_execute
        def fail(cursor,statement,parameters,context=None):
            if statement.lstrip().startswith('INSERT INTO batch_jobs'):
                raise OperationalError('sensitive-fake-sql',{},RuntimeError('sensitive-fake-password'))
            return original(cursor,statement,parameters,context)
        monkeypatch.setattr(store.engine.dialect,'do_execute',fail)
        response=await upload(client)
        assert response.status_code==503 and response.json()['error']['code']=='BATCH_UNAVAILABLE'
        assert 'sensitive-fake' not in response.text+caplog.text
        assert not services.model.calls and app.state.batch_service._reservations==0
        with store.engine.connect() as connection:
            assert connection.scalar(select(func.count()).select_from(J))==0


async def test_postgres_default_retention_is_indefinite_and_configured_policy_is_explicit(postgres_url):
    async with app_client(postgres_url) as (app,client,_):
        job=(await upload(client)).json()['job_id'];await terminal(app,job)
        with app.state.batch_service._store.engine.begin() as connection:
            connection.execute(J.__table__.update().values(completed_at=now()-timedelta(days=30)))
        await asyncio.to_thread(app.state.batch_service._store._purge)
        assert (await client.get('/api/v1/batch/jobs/'+job+'/download',headers=api_headers())).status_code==200
    config=multi_settings(database_url=postgres_url,batch_job_ttl_seconds=60)
    services=harness();app=create_app(config,sentiment_service=services.sentiment,investigation_service=services.investigation)
    async with app.router.lifespan_context(app):
        owner=app.state.tenant_registry.authenticate(ALPHA_KEY)
        with pytest.raises(ApplicationError) as error:app.state.batch_service.status(job,principal=owner)
        assert error.value.code==E.BATCH_JOB_NOT_FOUND
        with app.state.batch_service._store.engine.connect() as connection:
            assert connection.scalar(select(func.count()).select_from(R))==0


async def test_postgres_second_coordinator_fails_closed(postgres_url):
    async with app_client(postgres_url) as (_,_,_):
        config=multi_settings(database_url=postgres_url,batch_job_ttl_seconds=0)
        store=PostgresJobStore(config,TenantRegistry(config))
        with pytest.raises(ApplicationError) as error:await asyncio.to_thread(store.start)
        assert error.value.code==E.BATCH_UNAVAILABLE


async def test_postgres_credential_rotation_and_recovery_authority(postgres_url):
    gate=asyncio.Event();services=harness(model=Model(gate=gate))
    async with app_client(postgres_url,services=services) as (app,client,_):
        job=(await upload(client)).json()['job_id'];await until(lambda:services.model.active==1)
    credentials=[CREDENTIALS[1],CREDENTIALS[0]|{'key_id':'rotated','api_key':ALPHA_ROTATED_KEY}]
    async with app_client(postgres_url,credentials=credentials) as (app,client,services):
        await terminal(app,job,ALPHA_ROTATED_KEY)
        path='/api/v1/batch/jobs/'+job+'/download'
        assert (await client.get(path,headers=api_headers(ALPHA_ROTATED_KEY))).status_code==200
        assert (await client.get(path,headers=api_headers(ALPHA_KEY))).status_code==401
        assert len(services.model.calls)==2


def test_postgres_migration_repeat_is_idempotent_and_types_are_postgresql(postgres_url):
    upgrade_database(postgres_url)
    engine=create_database_engine(postgres_url)
    try:
        with engine.connect() as connection:
            assert connection.scalar(text('select version_num from alembic_version'))==REVISION
            kinds=dict(connection.execute(text("select column_name,data_type from information_schema.columns where table_schema=current_schema() and table_name='batch_records'")).all())
            assert kinds['aspects']==kinds['evidence_phrases']=='jsonb'
    finally:engine.dispose()


async def test_postgres_pending_outcomes_are_not_exposed_as_success_and_no_open_network_transaction(postgres_url):
    services=harness(model=Model(gate=asyncio.Event()))
    async with app_client(postgres_url,services=services) as (app,client,_):
        response=await upload(client);assert response.status_code==202
        job=response.json()['job_id'];await until(lambda:services.model.active==1)
        path='/api/v1/batch/jobs/'+job
        assert (await client.get(path+'/results',headers=api_headers())).json()['total_results']==0
        assert (await client.get(path+'/report',headers=api_headers())).status_code==202
        assert (await client.get(path+'/download',headers=api_headers())).status_code==202
        with app.state.batch_service._store.engine.connect() as connection:
            assert connection.scalar(select(func.count()).select_from(R).where(R.raw_text.is_not(None)))==2
            assert connection.scalar(select(J.processed))==0
            assert connection.scalar(text("select count(*) from pg_stat_activity where application_name='sentiment_batch' and pid<>pg_backend_pid() and datname=current_database() and state='idle in transaction'"))==0
        services.model.gate.set();await terminal(app,job)


async def test_postgres_unexpired_crash_claim_waits_before_recovery(postgres_url):
    config=multi_settings(database_url=postgres_url,batch_job_ttl_seconds=0)
    registry=TenantRegistry(config);store=PostgresJobStore(config,registry);store.start()
    from app.schemas.batch import ParsedRecord,RecordMetadata
    record=ParsedRecord(meta=RecordMetadata(feedback_id='A',source_row=2),text='Lease guarded.')
    job=store.add(UploadOptions(text_column='review'),[record],0,principal=registry.authenticate(ALPHA_KEY))
    store.running(job);store.claim(job,'A');store.close()
    async with app_client(postgres_url) as (app,client,services):
        await asyncio.sleep(.05)
        assert not services.model.calls
        with app.state.batch_service._store.engine.begin() as connection:
            connection.execute(R.__table__.update().values(claim_expires_at=now()-timedelta(seconds=1)))
        await terminal(app,job.job_id)
        assert [c['text'] for c in services.model.calls]==['Lease guarded.']


async def test_postgres_result_write_failure_preserves_success_and_resumes_without_first_record(postgres_url,monkeypatch):
    first=harness()
    async with app_client(postgres_url,services=first) as (app,client,_):
        store=app.state.batch_service._store;original=store.save_result;failed=asyncio.Event();loop=asyncio.get_running_loop()
        def fail(job,record,result,token):
            if record.meta.feedback_id=='B':
                loop.call_soon_threadsafe(failed.set)
                raise ApplicationError(E.BATCH_UNAVAILABLE)
            return original(job,record,result,token)
        monkeypatch.setattr(store,'save_result',fail)
        response=await upload(client);job=response.json()['job_id']
        # Event is bound to this loop before the threaded callback accesses it.
        await asyncio.wait_for(failed.wait(),timeout=5)
        owner=app.state.tenant_registry.authenticate(ALPHA_KEY)
        await until(lambda:app.state.batch_service.status(job,principal=owner).status=='PENDING')
        assert app.state.batch_service.status(job,principal=owner).successful_records==1
    resumed=harness()
    async with app_client(postgres_url,services=resumed) as (app,_,_):
        await terminal(app,job)
        assert [c['text'] for c in resumed.model.calls]==['Second review.']


async def test_postgres_owner_without_processing_permission_is_not_recovered(postgres_url):
    first=harness(model=Model(gate=asyncio.Event()))
    async with app_client(postgres_url,services=first) as (app,client,_):
        job=(await upload(client)).json()['job_id'];await until(lambda:first.model.active==1)
    credentials=[CREDENTIALS[0]|{'permissions':['batch:read']},CREDENTIALS[1]]
    async with app_client(postgres_url,credentials=credentials) as (_,client,services):
        await asyncio.sleep(.05)
        response=await client.get('/api/v1/batch/jobs/'+job,headers=api_headers())
        assert response.status_code==200 and response.json()['status']=='PENDING'
        assert not services.model.calls
    async with app_client(postgres_url) as (app,_,services):
        await terminal(app,job);assert len(services.model.calls)==2


async def test_postgres_retained_tenant_quota_survives_restart(postgres_url):
    async with app_client(postgres_url,tenant_max_retained_batch_jobs=1) as (app,client,_):
        job=(await upload(client)).json()['job_id'];await terminal(app,job)
    async with app_client(postgres_url,tenant_max_retained_batch_jobs=1) as (app,client,_):
        assert (await upload(client)).status_code==429
        beta=await upload(client,key=BETA_KEY);assert beta.status_code==202
        await terminal(app,beta.json()['job_id'],BETA_KEY)
        assert (await client.get('/api/v1/batch/jobs/'+job+'/download',headers=api_headers())).status_code==200


async def test_postgres_fatal_provider_failure_stops_remaining_calls_and_commits_failures(postgres_url):
    services=harness(model=Model(errors={'First review.':ApplicationError(E.UPSTREAM_AUTHENTICATION_FAILED)}))
    async with app_client(postgres_url,services=services) as (app,client,_):
        job=(await upload(client)).json()['job_id'];await terminal(app,job)
        result=(await client.get('/api/v1/batch/jobs/'+job+'/download',headers=api_headers())).json()
        assert result['report']['status']=='FAILED' and result['report']['failed_records']==2
        assert len(services.model.calls)==1 and [r['attempted'] for r in result['results']]==[True,False]


async def test_postgres_whole_job_timeout_settles_outcomes_and_wipes_pending_text(postgres_url):
    services=harness(model=Model(gate=asyncio.Event()))
    config=multi_settings(database_url=postgres_url,batch_job_ttl_seconds=0,batch_job_timeout_seconds=.05)
    app=create_app(config,sentiment_service=services.sentiment,investigation_service=services.investigation)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app),base_url='http://pg.local') as client:
            job=(await upload(client)).json()['job_id'];await terminal(app,job)
            report=(await client.get('/api/v1/batch/jobs/'+job+'/report',headers=api_headers())).json()
            assert report['status']=='FAILED' and report['error_code']=='BATCH_JOB_TIMEOUT'
            assert report['attempted_records']==1 and report['unattempted_valid_records']==1
            with app.state.batch_service._store.engine.connect() as connection:
                assert connection.scalar(select(func.count()).select_from(R).where(R.raw_text.is_not(None)))==0


async def test_postgres_dates_business_hint_and_custom_source_survive_restart(postgres_url):
    async with app_client(postgres_url) as (app,client,_):
        response=await upload(client,b'id,review,date\nA,Good.,2026-11-03\nB,Okay.,invalid',fields={
            'text_column':'review','id_column':'id','date_column':'date','business_type':'ecommerce','source':'custom_import'})
        job=response.json()['job_id'];await terminal(app,job)
    async with app_client(postgres_url) as (_,client,services):
        result=(await client.get('/api/v1/batch/jobs/'+job+'/download',headers=api_headers())).json()
        assert result['report']['business_type']=='ecommerce' and result['report']['source']=='custom_import'
        assert result['report']['invalid_date_records']==1
        assert result['results'][0]['normalized_date']=='2026-11-03' and result['results'][1]['date_status']=='INVALID'
        assert not services.model.calls


def test_postgres_connection_failure_is_sanitized():
    config=multi_settings(database_url='postgresql+psycopg://invalid:sensitive_fake_value@127.0.0.1:1/unavailable',batch_job_ttl_seconds=0)
    store=PostgresJobStore(config,TenantRegistry(config))
    with pytest.raises(ApplicationError) as error:store.start()
    assert error.value.code==E.BATCH_UNAVAILABLE and 'sensitive_fake_value' not in str(error.value)


async def test_postgres_recovery_and_upload_scheduling_never_duplicate_job_workers(postgres_url):
    services=harness(model=Model(gate=asyncio.Event()))
    async with app_client(postgres_url,services=services) as (app,client,_):
        service=app.state.batch_service
        response=await upload(client);job=response.json()['job_id']
        await until(lambda:services.model.active==1)
        await asyncio.gather(*(service._recover() for _ in range(3)))
        # Explicit duplicate scheduling must preserve the existing worker/inputs.
        active=service._store._jobs[job]
        service._spawn(active)
        assert len(service._tasks)==len(service._active_ids)==1
        services.model.gate.set();await terminal(app,job)
        assert len(services.model.calls)==2


async def test_postgres_foreign_lookup_is_scoped_in_sql_before_child_rows(postgres_url):
    from sqlalchemy import event
    async with app_client(postgres_url) as (app,client,_):
        job=(await upload(client)).json()['job_id'];await terminal(app,job)
        statements=[]
        def capture(connection,cursor,statement,parameters,context,executemany):
            statements.append(statement)
        engine=app.state.batch_service._store.engine
        event.listen(engine,'before_cursor_execute',capture)
        try:
            response=await client.get('/api/v1/batch/jobs/'+job+'/download',headers=api_headers(BETA_KEY))
            assert response.status_code==404
        finally:event.remove(engine,'before_cursor_execute',capture)
        assert any('batch_jobs.tenant_id =' in s and 'batch_jobs.public_id =' in s for s in statements)
        assert not any('FROM batch_records' in s for s in statements)


def test_postgres_start_requires_explicit_migration_no_implicit_tables(postgres_url):
    parsed=make_url(postgres_url.get_secret_value());schema='unmigrated_'+uuid4().hex
    engine=create_database_engine(postgres_url)
    with engine.begin() as connection:connection.execute(CreateSchema(schema))
    scoped=SecretStr(parsed.update_query_dict({'options':'-csearch_path='+schema}).render_as_string(hide_password=False))
    config=multi_settings(database_url=scoped,batch_job_ttl_seconds=0)
    store=PostgresJobStore(config,TenantRegistry(config))
    try:
        with pytest.raises(ApplicationError) as error:store.start()
        assert error.value.code==E.BATCH_UNAVAILABLE
        check=create_database_engine(scoped)
        with check.connect() as connection:
            assert connection.scalar(text('select count(*) from information_schema.tables where table_schema=current_schema()'))==0
        check.dispose()
        upgrade_database(scoped);store.start();assert store.available
    finally:
        store.close()
        with engine.begin() as connection:connection.execute(DropSchema(schema,cascade=True))
        engine.dispose()


async def test_postgres_stale_recovery_snapshot_cannot_reopen_terminal_job(postgres_url):
    async with app_client(postgres_url) as (app,client,services):
        job=(await upload(client)).json()['job_id'];await terminal(app,job)
        owner=app.state.tenant_registry.authenticate(ALPHA_KEY)
        store=app.state.batch_service._store
        snapshot=store.get(job,principal=owner)
        with store.engine.connect() as connection:
            completed=connection.scalar(select(J.completed_at).where(J.public_id==job))
        assert store.running(snapshot) is False
        app.state.batch_service._spawn(snapshot)
        await until(lambda:job not in app.state.batch_service._active_ids)
        assert len(services.model.calls)==2
        with store.engine.connect() as connection:
            row=connection.execute(select(J.status,J.completed_at).where(J.public_id==job)).one()
            assert row.status=='COMPLETED' and row.completed_at==completed


async def test_postgres_default_composition_keeps_existing_stateless_webhook_and_gmail_workflows(postgres_url):
    from tests.t07_helpers import webhook_headers
    from tests.t08_helpers import FakeGoogle, authorize, gmail_settings, import_job
    services=harness();google=FakeGoogle()
    app=create_app(gmail_settings(database_url=postgres_url,batch_job_ttl_seconds=0),
        sentiment_service=services.sentiment,investigation_service=services.investigation,
        gmail_transport=httpx.MockTransport(google))
    async with app.router.lifespan_context(app):
        assert isinstance(app.state.batch_service._store,PostgresJobStore)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app),base_url='http://pg-coexist.local') as client:
            requests=[('/api/v1/sentiment/analyze',{'text':'Synthetic feedback.'}),
                ('/api/v1/agent/investigate',{'question':'Main issues?','feedback':[{'id':'A','text':'Synthetic feedback.'}]}),
                ('/api/v1/chat',{'mode':'ANALYZE_TEXT','message':'Analyze','feedback_text':'Synthetic feedback.'}),
                ('/api/v1/chat',{'mode':'INVESTIGATE_FEEDBACK','message':'Main issues?','feedback':[{'id':'A','text':'Synthetic feedback.'}]}),
                ('/api/v1/ingest/feedback',{'text':'Synthetic feedback.','channel':'external_api'})]
            for path,payload in requests:
                assert (await client.post(path,headers=api_headers(),json=payload)).status_code==200
            raw=json.dumps({'event_type':'customer.feedback.created','feedback':{'id':'A','text':'Synthetic feedback.'}}).encode()
            assert (await client.post('/api/v1/webhooks/feedback',headers=webhook_headers(raw,delivery='pg-coexist'),content=raw)).status_code==202
            await app.state.webhook_service.queue.join()
            assert (await client.get('/api/v1/ingest/events/pg-coexist',headers=api_headers())).json()['status']=='COMPLETED'
            assert (await authorize(client)).status_code==200
            gmail_job=await import_job(app,client,maximum=1)
            assert (await client.get('/api/v1/integrations/gmail/imports/'+gmail_job+'/results',headers=api_headers())).json()['results'][0]['status']=='SUCCESS'
            batch=(await upload(client)).json()['job_id'];await terminal(app,batch)
            assert (await client.get('/api/v1/batch/jobs/'+batch+'/download',headers=api_headers())).status_code==200


async def test_postgres_create_only_principal_can_process_but_cannot_read_results(postgres_url):
    credentials=[CREDENTIALS[0]|{'permissions':['batch:create']},CREDENTIALS[1]]
    async with app_client(postgres_url,credentials=credentials) as (app,client,services):
        response=await upload(client);assert response.status_code==202
        job=response.json()['job_id'];store=app.state.batch_service._store
        def complete():
            with store.engine.connect() as connection:
                return connection.scalar(select(J.status).where(J.public_id==job))=='COMPLETED'
        await until(complete,timeout=10)
        assert len(services.model.calls)==2
        for suffix in ['','/report','/results','/download']:
            assert (await client.get('/api/v1/batch/jobs/'+job+suffix,headers=api_headers())).status_code==403
        owner=app.state.tenant_registry.authenticate(ALPHA_KEY)
        with pytest.raises(ApplicationError) as error:store.get(job,principal=owner)
        assert error.value.code==E.AUTHORIZATION_FAILED
