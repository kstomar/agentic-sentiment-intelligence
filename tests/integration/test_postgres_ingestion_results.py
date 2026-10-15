"""Real PostgreSQL ingestion/result, signed idempotency and restart regressions."""

import asyncio
from dataclasses import replace
from datetime import timedelta
import json

import pytest
from pydantic import ValidationError
from sqlalchemy import event as sql_event, func, select, text
from starlette.datastructures import Headers

from app.core.config import Settings
from app.core.exceptions import ApplicationError, ErrorCode as E
from app.core.tenant_auth import principal_context
from app.core.webhook_security import authenticate_webhook
from app.schemas.ingestion import EventState, WebhookPayload
from app.services.ingestion_service import normalize_event
from app.storage.event_store import Event
from app.storage.feedback_models import FeedbackEventRow as F
from app.storage.postgres_event_store import now
from tests.helpers import Model, analysis, harness, until
from tests.integration.test_postgres_batches import postgres_url, app_client
from tests.t06_helpers import raw_event
from tests.t07_helpers import (
    ALPHA_KEY, ALPHA_SECRET, ALPHA_SECOND_SECRET, BETA_KEY, BETA_SECRET,
    CREDENTIALS, api_headers, multi_settings, webhook_headers,
)

POST = '/api/v1/webhooks/feedback'
EVENT = '/api/v1/ingest/events/'
REVIEW = '  My order was five days late.\nSupport has not replied. 好评 😀  '
RAW = raw_event(feedback={'id': 'WEBHOOK-TEST-001', 'text': REVIEW}, source='customer_review', business_type='ecommerce')


async def send(client, raw=RAW, delivery='durable-1', **headers):
    return await client.post(POST, content=raw, headers=webhook_headers(raw, delivery=delivery, **headers))


def reservation(app, delivery='seeded', raw=RAW):
    identity = authenticate_webhook(app.state.settings, Headers(webhook_headers(raw, delivery=delivery)), raw,
                                     registry=app.state.tenant_registry)
    return Event(identity.principal, identity.integration_id, delivery,
                 __import__('hashlib').sha256(raw).digest(), normalize_event(WebhookPayload.model_validate_json(raw)))


async def test_original_analysis_feedback_repeated_get_and_restart(postgres_url):
    output = analysis(REVIEW, summary='Captured original provider result.', suggested_next_step='Review delivery and support.')
    services = harness(model=Model(outputs={REVIEW: output}))
    async with app_client(postgres_url, services=services) as (app, client, _):
        assert (await send(client)).status_code == 202
        await app.state.webhook_service.queue.join()
        status = await client.get(EVENT+'durable-1', headers=api_headers())
        assert status.json() == {'delivery_id':'durable-1','status':'COMPLETED','error_code':None}
        before = None
        for _ in range(3):
            response = await client.get(EVENT+'durable-1/result', headers=api_headers())
            assert response.status_code == 200
            value = response.json()
            assert value['feedback'] == {'text':REVIEW,'source':'customer_review','business_type':'ecommerce',
                                         'feedback_id':'WEBHOOK-TEST-001','channel':'external_api'}
            assert value['analysis'] == output and value['status'] == 'COMPLETED'
            assert value['completed_at'] and value['updated_at'] and value['created_at']
            assert value['integration_id'] == 'alpha-integration'
            assert value['event_type'] == 'customer.feedback.created'
            assert value['error_code'] is None
            assert response.headers['cache-control'] == 'no-store'
            assert response.headers['referrer-policy'] == 'no-referrer'
            before = value
        assert len(services.model.calls) == 1
        store = app.state.webhook_service.store
        with store.database.engine.connect() as connection:
            row = connection.execute(select(F.feedback,F.analysis,F.digest)).one()
            assert row.feedback['text'] == REVIEW and row.analysis == output
            assert len(row.digest) == 32
    async with app_client(postgres_url) as (app, client, after):
        response = await client.get(EVENT+'durable-1/result', headers=api_headers())
        assert response.status_code == 200 and response.json() == before
        assert (await send(client)).status_code == 200
        assert (await send(client, raw=RAW+b' ')).status_code == 409
        assert (await send(client, secret=BETA_SECRET)).status_code == 401
        assert not after.model.calls


@pytest.mark.parametrize('suffix',['','/result'])
@pytest.mark.parametrize('key',[None,'invalid',BETA_KEY])
async def test_result_status_authentication_and_foreign_owner(postgres_url,suffix,key):
    async with app_client(postgres_url) as (app,client,services):
        assert (await send(client)).status_code == 202
        await app.state.webhook_service.queue.join()
        response=await client.get(EVENT+'durable-1'+suffix,headers={} if key is None else api_headers(key))
        assert response.status_code == (404 if key==BETA_KEY else 401)
        assert REVIEW not in response.text and 'WEBHOOK-TEST-001' not in response.text
        assert len(services.model.calls)==1


@pytest.mark.parametrize('suffix',['','/result'])
async def test_unknown_event_and_permission_denial(postgres_url,suffix):
    credentials=[CREDENTIALS[0]|{'permissions':['feedback:ingest']},CREDENTIALS[1]]
    async with app_client(postgres_url,credentials=credentials) as (app,client,services):
        assert (await send(client)).status_code==202
        await app.state.webhook_service.queue.join()
        assert (await client.get(EVENT+'durable-1'+suffix,headers=api_headers())).status_code==403
        assert (await client.get(EVENT+'unknown'+suffix,headers=api_headers(BETA_KEY))).status_code==404
        with pytest.raises(ApplicationError) as error:
            app.state.webhook_service.store.get('durable-1',principal=app.state.tenant_registry.authenticate(ALPHA_KEY))
        assert error.value.code==E.AUTHORIZATION_FAILED
        with principal_context(None):
            with pytest.raises(ApplicationError):app.state.webhook_service.store.get('durable-1')


async def test_pending_processing_and_then_completed(postgres_url):
    gate=asyncio.Event();services=harness(model=Model(gate=gate))
    async with app_client(postgres_url,services=services) as (app,client,_):
        seeded=reservation(app)
        await asyncio.to_thread(app.state.webhook_service.store.reserve,seeded,kind='webhook')
        response=await client.get(EVENT+'seeded/result',headers=api_headers())
        assert response.status_code==202 and response.json()=={'delivery_id':'seeded','status':'ACCEPTED','error_code':None}
        assert (await send(client)).status_code==202
        await until(lambda:services.model.active==1)
        pending=await client.get(EVENT+'durable-1/result',headers=api_headers())
        status=await client.get(EVENT+'durable-1',headers=api_headers())
        assert pending.status_code==202 and pending.json()==status.json()
        assert pending.json()['status']=='PROCESSING' and 'analysis' not in pending.json()
        assert (await send(client)).status_code==200
        gate.set();await app.state.webhook_service.queue.join()
        assert (await client.get(EVENT+'durable-1/result',headers=api_headers())).json()['status']=='COMPLETED'
        assert len(services.model.calls)==1


@pytest.mark.parametrize('failure,code',[
    ('provider',E.UPSTREAM_UNAVAILABLE),('invalid',E.INVALID_MODEL_RESPONSE),
    ('unexpected',E.INTERNAL_ERROR),('timeout',E.WEBHOOK_PROCESSING_TIMEOUT),
])
async def test_failed_results_are_safe_and_durable_without_reanalysis(postgres_url,failure,code):
    model=Model(errors={REVIEW:ApplicationError(code)} if failure=='provider' else
                {REVIEW:RuntimeError('sensitive-private-exception')} if failure=='unexpected' else None,
                outputs={REVIEW:{'sentiment':'NEGATIVE'}} if failure=='invalid' else None,
                gate=asyncio.Event() if failure=='timeout' else None)
    async with app_client(postgres_url,services=harness(model=model),webhook_processing_timeout_seconds=.1) as (app,client,_):
        assert (await send(client)).status_code==202
        await app.state.webhook_service.queue.join()
        result=(await client.get(EVENT+'durable-1/result',headers=api_headers())).json()
        assert result['status']=='FAILED' and result['error_code']==code and result['analysis'] is None
        assert result['feedback']['text']==REVIEW and 'sensitive-private-exception' not in json.dumps(result)
        assert (await send(client)).status_code==200 and len(model.calls)==1
    async with app_client(postgres_url) as (_,client,services):
        assert (await client.get(EVENT+'durable-1/result',headers=api_headers())).json()==result
        assert (await send(client)).status_code==200 and not services.model.calls


@pytest.mark.parametrize('state',['ACCEPTED','PROCESSING'])
async def test_interrupted_event_terminalized_on_restart_without_model_retry(postgres_url,state):
    async with app_client(postgres_url) as (app,_,services):
        event=reservation(app)
        store=app.state.webhook_service.store
        assert await asyncio.to_thread(store.reserve,event,kind='webhook')
        if state=='PROCESSING':assert await asyncio.to_thread(store.processing,event)
        assert not services.model.calls
    async with app_client(postgres_url) as (_,client,services):
        value=(await client.get(EVENT+'seeded/result',headers=api_headers())).json()
        status=(await client.get(EVENT+'seeded',headers=api_headers())).json()
        assert value['status']==status['status']=='FAILED'
        assert value['error_code']==status['error_code']=='INGESTION_INTERRUPTED'
        assert value['analysis'] is None and value['feedback']['text']==REVIEW
        assert (await send(client,delivery='seeded')).status_code==200
        assert not services.model.calls


async def test_concurrent_duplicate_and_integration_tenant_scopes(postgres_url):
    async with app_client(postgres_url,tenant_max_concurrent_requests=8) as (app,client,services):
        responses=await asyncio.gather(*[send(client) for _ in range(6)])
        assert sorted(r.status_code for r in responses)==[200]*5+[202]
        assert (await send(client,integration='alpha-second',secret=ALPHA_SECOND_SECRET)).status_code==409
        assert (await send(client,integration='beta-integration',secret=BETA_SECRET)).status_code==202
        await app.state.webhook_service.queue.join()
        assert len(services.model.calls)==2
        assert (await client.get(EVENT+'durable-1/result',headers=api_headers(BETA_KEY))).json()['integration_id']=='beta-integration'
        with app.state.webhook_service.store.database.engine.connect() as connection:
            assert connection.scalar(select(func.count()).select_from(F))==2


async def test_changed_payload_and_invalid_signature_cannot_overwrite_or_create(postgres_url):
    async with app_client(postgres_url) as (app,client,services):
        assert (await send(client,secret=BETA_SECRET)).status_code==401
        assert (await send(client)).status_code==202
        await app.state.webhook_service.queue.join()
        prior=(await client.get(EVENT+'durable-1/result',headers=api_headers())).json()
        changed=raw_event(feedback={'id':'WEBHOOK-TEST-001','text':'Changed feedback.'})
        assert (await send(client,raw=changed)).status_code==409
        assert (await send(client,integration='beta-integration',secret=ALPHA_SECRET)).status_code==401
        invalid=raw_event(tenant_id='business_beta')
        assert (await send(client,raw=invalid,delivery='override')).status_code==422
        assert (await client.get(EVENT+'durable-1/result',headers=api_headers())).json()==prior
        assert len(services.model.calls)==1


async def test_direct_response_unchanged_and_result_url_survives_restart(postgres_url):
    payload={'text':REVIEW,'channel':'website','feedback_id':' DIRECT-1 ','source':'support_ticket','business_type':'software'}
    async with app_client(postgres_url) as (_,client,services):
        response=await client.post('/api/v1/ingest/feedback',json=payload,headers=api_headers())
        assert response.status_code==200
        assert response.json()=={'feedback_id':'DIRECT-1','channel':'website','status':'ANALYZED','analysis':analysis(REVIEW)}
        delivery=response.headers['x-feedback-delivery-id'];path=response.headers['location']
        assert path==EVENT+delivery+'/result'
        stored=await client.get(path,headers=api_headers())
        before=stored.json()
        assert before['feedback']['text']==REVIEW and before['feedback']['feedback_id']=='DIRECT-1'
        assert before['analysis']==response.json()['analysis'] and before['integration_id'] is None and before['event_type'] is None
        assert len(services.model.calls)==1
    async with app_client(postgres_url) as (_,client,services):
        assert (await client.get(path,headers=api_headers())).json()==before
        assert (await client.get(EVENT+delivery,headers=api_headers())).json()['status']=='COMPLETED'
        assert not services.model.calls


async def test_direct_failure_keeps_existing_error_and_exposes_persisted_event_header(postgres_url):
    services=harness(model=Model(errors={REVIEW:ApplicationError(E.UPSTREAM_UNAVAILABLE)}))
    async with app_client(postgres_url,services=services) as (_,client,_):
        response=await client.post('/api/v1/ingest/feedback',headers=api_headers(),json={'text':REVIEW,'channel':'external_api'})
        assert response.status_code==502 and response.json()['error']['code']=='UPSTREAM_UNAVAILABLE'
        value=(await client.get(response.headers['location'],headers=api_headers())).json()
        assert value['status']=='FAILED' and value['analysis'] is None
        assert value['error_code']=='UPSTREAM_UNAVAILABLE' and value['feedback']['text']==REVIEW
        assert len(services.model.calls)==1


async def test_database_insert_failure_does_not_acknowledge_or_classify(postgres_url,monkeypatch,caplog):
    from sqlalchemy.exc import OperationalError
    async with app_client(postgres_url) as (app,client,services):
        engine=app.state.webhook_service.store.database.engine
        def fail(conn,cursor,statement,parameters,context,executemany):
            if statement.startswith('INSERT INTO feedback_events'):
                raise OperationalError('private-sql',{},RuntimeError('private-db-password-and-feedback'))
        sql_event.listen(engine,'before_cursor_execute',fail)
        try:
            for request in (lambda:send(client),lambda:client.post('/api/v1/ingest/feedback',headers=api_headers(),json={'text':REVIEW,'channel':'website'})):
                response=await request()
                assert response.status_code==503 and response.json()['error']['code']=='WEBHOOK_UNAVAILABLE'
                assert 'private' not in response.text
            assert not services.model.calls and app.state.webhook_service.queue.empty()
        finally:sql_event.remove(engine,'before_cursor_execute',fail)
        assert 'private-db-password-and-feedback' not in caplog.text and REVIEW not in caplog.text
        assert (await send(client)).status_code==202
        await app.state.webhook_service.queue.join()


async def test_sql_owner_filter_and_no_secrets_in_columns_or_feedback(postgres_url):
    async with app_client(postgres_url) as (app,client,services):
        assert (await send(client)).status_code==202
        await app.state.webhook_service.queue.join()
        engine=app.state.webhook_service.store.database.engine;queries=[]
        def capture(conn,cursor,statement,parameters,context,executemany):
            if 'feedback_events' in statement:queries.append(statement)
        sql_event.listen(engine,'before_cursor_execute',capture)
        try:assert (await client.get(EVENT+'durable-1/result',headers=api_headers(BETA_KEY))).status_code==404
        finally:sql_event.remove(engine,'before_cursor_execute',capture)
        assert queries and all('feedback_events.tenant_id =' in q and 'feedback_events.delivery_id =' in q for q in queries)
        columns=set(F.__table__.columns.keys())
        assert not columns & {'api_key','secret','signature','token','principal','authorization','headers'}
        with engine.connect() as conn:
            saved=conn.execute(select(F.feedback,F.analysis)).one()
            public=json.dumps(saved.feedback)+json.dumps(saved.analysis)
            assert ALPHA_KEY not in public and ALPHA_SECRET not in public and BETA_KEY not in public


async def test_default_indefinite_result_and_explicit_retention_policy(postgres_url):
    async with app_client(postgres_url) as (app,client,_):
        assert (await send(client)).status_code==202
        await app.state.webhook_service.queue.join()
        engine=app.state.webhook_service.store.database.engine
        with engine.begin() as conn:
            conn.execute(F.__table__.update().values(created_at=now()-timedelta(days=500),completed_at=now()-timedelta(days=400)))
        assert (await client.get(EVENT+'durable-1/result',headers=api_headers())).status_code==200
    async with app_client(postgres_url) as (_,client,services):
        assert (await client.get(EVENT+'durable-1/result',headers=api_headers())).status_code==200
        assert (await send(client)).status_code==200 and not services.model.calls
    async with app_client(postgres_url,ingestion_result_ttl_seconds=600) as (_,client,_):
        assert (await client.get(EVENT+'durable-1/result',headers=api_headers())).status_code==404


async def test_retained_quota_is_durable_and_does_not_evict_history(postgres_url):
    async with app_client(postgres_url,tenant_max_retained_events=1) as (app,client,_):
        assert (await send(client)).status_code==202
        await app.state.webhook_service.queue.join()
    async with app_client(postgres_url,tenant_max_retained_events=1) as (_,client,services):
        assert (await send(client,delivery='other')).status_code==429
        assert (await send(client)).status_code==200
        assert (await client.get(EVENT+'durable-1/result',headers=api_headers())).status_code==200
        assert not services.model.calls


async def test_legacy_development_key_cannot_read_business_result(postgres_url):
    from tests.helpers import TEST_KEY
    async with app_client(postgres_url,app_env='development',development_auth_enabled=True) as (app,client,_):
        assert (await send(client)).status_code==202
        await app.state.webhook_service.queue.join()
        assert (await client.get(EVENT+'durable-1/result',headers=api_headers(TEST_KEY))).status_code==404


async def test_signed_service_cannot_substitute_another_feedback_body(postgres_url):
    async with app_client(postgres_url) as (app,_,services):
        identity=authenticate_webhook(app.state.settings,Headers(webhook_headers(RAW)),RAW,registry=app.state.tenant_registry)
        original=normalize_event(WebhookPayload.model_validate_json(RAW))
        for identity,request in [(identity,original.model_copy(update={'text':'Different.'})),(replace(identity,delivery_id='changed'),original)]:
            with pytest.raises(ApplicationError) as error:
                await app.state.webhook_service.submit(identity,RAW,request)
            assert error.value.code==E.WEBHOOK_AUTHENTICATION_FAILED
        assert not services.model.calls


def test_persistent_retention_cannot_undercut_replay_window():
    with pytest.raises(ValidationError):multi_settings(ingestion_result_ttl_seconds=599)
    assert multi_settings(ingestion_result_ttl_seconds=0).ingestion_result_ttl_seconds==0
    assert multi_settings(ingestion_result_ttl_seconds=600).ingestion_result_ttl_seconds==600


async def test_result_commit_failure_is_not_faked_and_restart_marks_interrupted(postgres_url,caplog):
    from sqlalchemy.exc import OperationalError
    async with app_client(postgres_url) as (app,client,services):
        engine=app.state.webhook_service.store.database.engine
        def fail(conn,cursor,statement,parameters,context,executemany):
            if statement.startswith('UPDATE feedback_events SET') and 'analysis=' in statement:
                raise OperationalError('sensitive query',{},RuntimeError('sensitive-response-and-password'))
        sql_event.listen(engine,'before_cursor_execute',fail)
        try:
            assert (await send(client)).status_code==202
            await app.state.webhook_service.queue.join()
            result=await client.get(EVENT+'durable-1/result',headers=api_headers())
            assert result.status_code==202 and result.json()['status']=='PROCESSING'
            assert len(services.model.calls)==1
            assert (await send(client,delivery='blocked')).status_code==503
        finally:sql_event.remove(engine,'before_cursor_execute',fail)
        assert 'sensitive-response-and-password' not in caplog.text
    async with app_client(postgres_url) as (_,client,services):
        result=(await client.get(EVENT+'durable-1/result',headers=api_headers())).json()
        assert result['status']=='FAILED' and result['error_code']=='INGESTION_INTERRUPTED'
        assert result['analysis'] is None
        assert (await send(client)).status_code==200 and not services.model.calls


async def test_shutdown_active_and_queued_events_are_failed_and_retained(postgres_url):
    services=harness(model=Model(gate=asyncio.Event()))
    async with app_client(postgres_url,services=services) as (app,client,_):
        assert (await send(client,delivery='active')).status_code==202
        await until(lambda:services.model.active==1)
        assert (await send(client,delivery='pending')).status_code==202
        assert app.state.webhook_service.queue.qsize()==1
    async with app_client(postgres_url) as (_,client,services):
        for delivery in ('active','pending'):
            result=(await client.get(EVENT+delivery+'/result',headers=api_headers())).json()
            assert result['status']=='FAILED' and result['error_code']=='WEBHOOK_UNAVAILABLE'
            assert result['feedback']['text']==REVIEW and result['analysis'] is None
            assert (await send(client,delivery=delivery)).status_code==200
        assert not services.model.calls


async def test_cancelled_reservation_does_not_leave_accepted_or_trigger_analysis(postgres_url,monkeypatch):
    import threading
    async with app_client(postgres_url) as (app,_,services):
        store=app.state.webhook_service.store;original=store.reserve
        entered=threading.Event();release=threading.Event()
        def blocked(*args,**kwargs):
            created=original(*args,**kwargs);entered.set()
            assert release.wait(5)
            return created
        monkeypatch.setattr(store,'reserve',blocked)
        identity=authenticate_webhook(app.state.settings,Headers(webhook_headers(RAW,delivery='cancelled')),RAW,registry=app.state.tenant_registry)
        task=asyncio.create_task(app.state.webhook_service.submit(identity,RAW,normalize_event(WebhookPayload.model_validate_json(RAW))))
        await until(entered.is_set)
        task.cancel();release.set()
        with pytest.raises(asyncio.CancelledError):await task
        principal=app.state.tenant_registry.authenticate(ALPHA_KEY)
        result=await asyncio.to_thread(store.get,'cancelled',principal=principal)
        assert result.status==EventState.FAILED and result.analysis is None and result.error_code==E.WEBHOOK_UNAVAILABLE
        assert app.state.webhook_service.queue.empty() and not services.model.calls


async def test_direct_cancellation_is_terminal_and_retrievable(postgres_url):
    services=harness(model=Model(gate=asyncio.Event()))
    async with app_client(postgres_url,services=services) as (app,client,_):
        task=asyncio.create_task(client.post('/api/v1/ingest/feedback',headers=api_headers(),json={'text':REVIEW,'channel':'website'}))
        await until(lambda:services.model.active==1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):await task
        with app.state.webhook_service.store.database.engine.connect() as conn:
            row=conn.execute(select(F.delivery_id,F.status,F.error_code)).one()
        assert row.status=='FAILED' and row.error_code=='WEBHOOK_UNAVAILABLE'
        assert (await client.get(EVENT+row.delivery_id+'/result',headers=api_headers())).status_code==200
        assert len(services.model.calls)==1


async def test_database_reservations_are_atomic_without_service_lock(postgres_url):
    async with app_client(postgres_url) as (app,_,services):
        store=app.state.webhook_service.store
        events=[reservation(app) for _ in range(4)]
        admitted=await asyncio.gather(*[asyncio.to_thread(store.reserve,e,kind='webhook') for e in events])
        assert admitted.count(True)==1 and admitted.count(False)==3
        with store.database.engine.connect() as conn:
            assert conn.scalar(select(func.count()).select_from(F))==1
        assert not services.model.calls


async def test_rotation_same_owner_preserves_event_result_and_digest(postgres_url):
    from tests.t07_helpers import ALPHA_ROTATED_KEY
    async with app_client(postgres_url) as (app,client,_):
        assert (await send(client)).status_code==202
        await app.state.webhook_service.queue.join()
        result=(await client.get(EVENT+'durable-1/result',headers=api_headers())).json()
    credentials=[CREDENTIALS[0]|{'key_id':'rotated','api_key':ALPHA_ROTATED_KEY},CREDENTIALS[1]]
    async with app_client(postgres_url,credentials=credentials) as (_,client,services):
        assert (await client.get(EVENT+'durable-1/result',headers=api_headers())).status_code==401
        assert (await client.get(EVENT+'durable-1/result',headers=api_headers(ALPHA_ROTATED_KEY))).json()==result
        assert (await send(client)).status_code==200 and not services.model.calls


def test_additive_migration_preserves_existing_batch_table_data(postgres_url):
    from uuid import uuid4
    from alembic import command
    from alembic.config import Config
    from sqlalchemy.engine import make_url
    from sqlalchemy.schema import CreateSchema,DropSchema
    from app.storage.database import ROOT,create_database_engine,upgrade_database
    from app.storage.batch_models import BatchJobRow as J
    schema='upgrade_'+uuid4().hex
    base=create_database_engine(postgres_url)
    with base.begin() as conn:conn.execute(CreateSchema(schema))
    scoped=make_url(postgres_url.get_secret_value()).update_query_dict({'options':'-csearch_path='+schema}).render_as_string(hide_password=False)
    engine=create_database_engine(scoped)
    try:
        config=Config(str(ROOT/'alembic.ini'))
        with engine.begin() as conn:
            config.attributes['connection']=conn;command.upgrade(config,'t09_batch_v2')
            conn.execute(J.__table__.insert().values(public_id='f'*32,tenant_id='business_alpha',options={},business_type='general',source='file_upload',status='PENDING',total=1,valid=1,invalid=0,skipped_blank_rows=0,processed=0,successful=0,failed=0,created_at=now(),updated_at=now()))
            before=dict(conn.execute(select(J.__table__)).mappings().one())
        upgrade_database(scoped);upgrade_database(scoped)
        with engine.connect() as conn:
            assert dict(conn.execute(select(J.__table__)).mappings().one())==before
            assert conn.scalar(select(func.count()).select_from(F))==0
            assert conn.scalar(text('select version_num from alembic_version'))=='gmail_incremental_v1'
    finally:
        engine.dispose()
        with base.begin() as conn:conn.execute(DropSchema(schema,cascade=True))
        base.dispose()
