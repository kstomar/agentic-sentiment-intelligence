"""Real PostgreSQL ledger tests; Gmail and sentiment inference are synthetic/mocked."""
import asyncio
from contextlib import asynccontextmanager
from datetime import timedelta
from dataclasses import replace
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import event, func, select, text

from app.main import create_app
from app.core.exceptions import ApplicationError, ErrorCode as E
from app.schemas.batch import JobState
from app.storage.gmail_message_models import GmailMessageRow as G
from app.storage.gmail_message_store import now
from app.storage.gmail_store import GmailJob
from app.storage.postgres_gmail_message_store import PostgresGmailMessageStore
from tests.helpers import Model, harness, until
from tests.integration.test_postgres_batches import postgres_url
from tests.t07_helpers import ALPHA_KEY, ALPHA_ROTATED_KEY, BETA_KEY, CREDENTIALS, api_headers
from tests.t08_helpers import ACCESS_A, ACCESS_B, FakeGoogle, authorize, gmail_settings, message

BASE='/api/v1/integrations/gmail'


def mailbox(count):
    fake=FakeGoogle(); fake.page_size=100
    fake.messages[ACCESS_A]={f'm{i:04}':message(f'Synthetic review {i}.',mid=f'm{i:04}') for i in range(count)}
    return fake


@asynccontextmanager
async def pg_app(url,*,fake=None,services=None,**overrides):
    fake=fake or mailbox(1);services=services or harness()
    config=gmail_settings(**({'database_url':url,'batch_job_ttl_seconds':0,'gmail_max_messages_per_import':100}|overrides))
    app=create_app(config,sentiment_service=services.sentiment,investigation_service=services.investigation,
                   gmail_transport=httpx.MockTransport(fake))
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app),base_url='http://postgres-gmail.local') as client:
            yield app,client,services,fake


async def run_job(app,client,maximum=100,key=ALPHA_KEY):
    response=await client.post(BASE+'/import',headers=api_headers(key),json={'max_messages':maximum})
    assert response.status_code==202
    job=response.json()['job_id'];owner=app.state.tenant_registry.authenticate(key)
    await until(lambda:app.state.gmail_service.job_status(job,owner).status in {'COMPLETED','PARTIAL_SUCCESS','FAILED'},timeout=30)
    status=(await client.get(BASE+'/imports/'+job,headers=api_headers(key))).json()
    return job,status


def manual_job(app, key=ALPHA_KEY):
    owner=app.state.tenant_registry.authenticate(key)
    service=app.state.gmail_service;connection=service.store._connections[owner.tenant_id]
    job=GmailJob(uuid4().hex,owner,connection.mailbox,connection.version,100)
    service.store._jobs[job.job_id]=job
    return job,connection


def rows(app):
    engine=app.state.batch_service._store.engine
    with engine.connect() as conn:return conn.execute(select(G.__table__).order_by(G.message_id)).mappings().all()


async def test_250_messages_import_100_100_50_0_and_success_survives_restart(postgres_url):
    fake=mailbox(250);first_ids=[]
    async with pg_app(postgres_url,fake=fake) as (app,client,services,_):
        assert isinstance(app.state.gmail_service.messages,PostgresGmailMessageStore)
        assert (await authorize(client)).status_code==200
        for expected,previous,exhausted in [(100,0,False),(100,100,False),(50,200,True),(0,250,True)]:
            job,status=await run_job(app,client);first_ids.append(job)
            assert status['status']=='COMPLETED' and status['error_code'] is None
            assert status['selected_messages']==status['processed_messages']==status['successful_messages']==expected
            assert status['previously_processed_messages']==previous
            assert status['scan_exhausted']==exhausted and not status['scan_limit_reached']
            assert status['duplicate_messages']==status['deferred_messages']==0
        assert len(services.model.calls)==250
        assert len({c['text'] for c in services.model.calls})==250
        saved=rows(app)
        assert len(saved)==250 and all(r['status']=='SUCCEEDED' and r['attempts']==1 for r in saved)
        assert all(r['claim_token'] is None and r['claim_expires_at'] is None for r in saved)
    fake.messages[ACCESS_A]['m0250']=message('A new post-restart review.',mid='m0250')
    async with pg_app(postgres_url,fake=fake) as (app,client,services,_):
        assert (await authorize(client)).status_code==200
        job,status=await run_job(app,client)
        assert status['successful_messages']==status['selected_messages']==1
        assert status['previously_processed_messages']==250 and status['scan_exhausted']
        assert services.model.calls==[{'text':'A new post-restart review.','source':'email','business_type':'general'}]
        assert len(rows(app))==251
        assert (await client.get(BASE+'/imports/'+first_ids[0],headers=api_headers())).status_code==404
        result=(await client.get(BASE+'/imports/'+job+'/results',headers=api_headers())).json()['results'][0]
        assert result['message_id']=='m0250' and result['status']=='SUCCESS'


async def test_reordered_listing_and_repeated_ids_do_not_lose_new_messages(postgres_url):
    fake=mailbox(6);fake.page_size=2
    async with pg_app(postgres_url,fake=fake) as (app,client,services,_):
        await authorize(client)
        _,first=await run_job(app,client,maximum=2)
        assert first['successful_messages']==2
        fake.messages[ACCESS_A]=dict(reversed(list(fake.messages[ACCESS_A].items())))
        _,second=await run_job(app,client,maximum=2)
        _,third=await run_job(app,client,maximum=2)
        assert second['successful_messages']==third['successful_messages']==2
        assert len({c['text'] for c in services.model.calls})==len(services.model.calls)==6


async def test_scan_limit_is_not_reported_as_mailbox_exhaustion(postgres_url):
    fake=mailbox(8);fake.page_size=2
    async with pg_app(postgres_url,fake=fake,gmail_max_list_pages=1) as (app,client,services,_):
        await authorize(client)
        _,first=await run_job(app,client,maximum=1)
        assert first['successful_messages']==1
        _,second=await run_job(app,client,maximum=1)
        assert second['successful_messages']==1 and second['previously_processed_messages']==1
        _,third=await run_job(app,client,maximum=1)
        assert third['selected_messages']==0 and third['scan_limit_reached'] and not third['scan_exhausted']
        assert third['scanned_messages']==third['previously_processed_messages']==2
        assert len(services.model.calls)==2
    async with pg_app(postgres_url,fake=fake,gmail_max_list_pages=4) as (app,client,services,_):
        await authorize(client)
        _,status=await run_job(app,client,maximum=1)
        assert status['successful_messages']==1 and status['previously_processed_messages']==2
        assert len(services.model.calls)==1


async def test_failed_analysis_retry_cooldown_then_success_is_persistent(postgres_url):
    fake=mailbox(1);services=harness(model=Model(errors={'Synthetic review 0.':ApplicationError(E.UPSTREAM_UNAVAILABLE)}))
    async with pg_app(postgres_url,fake=fake,services=services) as (app,client,_s,_):
        await authorize(client)
        _,first=await run_job(app,client,maximum=1)
        assert first['failed_messages']==1 and rows(app)[0]['status']=='FAILED' and rows(app)[0]['attempts']==1
        _,blocked=await run_job(app,client,maximum=1)
        assert blocked['selected_messages']==0 and blocked['deferred_messages']==1
        assert len(services.model.calls)==1
        with app.state.batch_service._store.engine.begin() as conn:
            conn.execute(G.__table__.update().values(retry_at=now()-timedelta(seconds=1)))
        services.model.errors.clear()
        _,retried=await run_job(app,client,maximum=1)
        assert retried['successful_messages']==1 and len(services.model.calls)==2
        assert rows(app)[0]['status']=='SUCCEEDED' and rows(app)[0]['attempts']==2
    async with pg_app(postgres_url,fake=fake) as (app,client,services,_):
        await authorize(client)
        _,status=await run_job(app,client,maximum=1)
        assert status['previously_processed_messages']==1 and not services.model.calls


async def test_retry_budget_is_not_reset_by_new_jobs_or_restart(postgres_url):
    services=harness(model=Model(errors={'Synthetic review 0.':ApplicationError(E.UPSTREAM_UNAVAILABLE)}))
    async with pg_app(postgres_url,services=services,gmail_message_max_attempts=2) as (app,client,_s,_):
        await authorize(client)
        for _ in range(2):
            _,status=await run_job(app,client,maximum=1)
            assert status['failed_messages']==1
            with app.state.batch_service._store.engine.begin() as conn:
                conn.execute(G.__table__.update().values(retry_at=now()-timedelta(seconds=1)))
        assert len(services.model.calls)==2 and rows(app)[0]['attempts']==2
    async with pg_app(postgres_url,gmail_message_max_attempts=2) as (app,client,services,_):
        await authorize(client)
        _,status=await run_job(app,client,maximum=1)
        assert status['selected_messages']==0 and status['deferred_messages']==1
        assert rows(app)[0]['status']=='FAILED' and not services.model.calls


async def test_overlapping_imports_claim_disjoint_ids_and_hold_no_transaction_during_models(postgres_url):
    gate=asyncio.Event();services=harness(model=Model(gate=gate));fake=mailbox(4)
    async with pg_app(postgres_url,fake=fake,services=services,gmail_max_concurrent_imports=3,gmail_tenant_max_concurrent_imports=2) as (app,client,_s,_):
        await authorize(client)
        responses=await asyncio.gather(*[client.post(BASE+'/import',headers=api_headers(),json={'max_messages':2}) for _ in range(2)])
        assert all(r.status_code==202 for r in responses)
        await until(lambda:services.model.active==2,timeout=15)
        assert len({c['text'] for c in services.model.calls})==2
        with app.state.batch_service._store.engine.connect() as conn:
            assert conn.scalar(text("select count(*) from pg_stat_activity where datname=current_database() and application_name='sentiment_batch' and state='idle in transaction'"))==0
        gate.set();await until(lambda:not app.state.gmail_service._tasks,timeout=20)
        assert len(services.model.calls)==len({c['text'] for c in services.model.calls})==4
        assert services.model.peak<=2 and all(r['status']=='SUCCEEDED' for r in rows(app))


@pytest.mark.parametrize('state',['RESERVED','PROCESSING'])
async def test_expired_crash_claim_is_recovered_safely(postgres_url,state):
    async with pg_app(postgres_url) as (app,client,services,_):
        await authorize(client);job,connection=manual_job(app);tracker=app.state.gmail_service.messages
        page=await asyncio.to_thread(tracker.claim_page,job,connection,['m0000'],1)
        if state=='PROCESSING':assert await asyncio.to_thread(tracker.begin,job,connection,'m0000',page.claims['m0000'])
        with app.state.batch_service._store.engine.begin() as conn:
            conn.execute(G.__table__.update().values(claim_expires_at=now()-timedelta(minutes=5)))
        assert not services.model.calls
    async with pg_app(postgres_url) as (app,client,services,_):
        await authorize(client);_,status=await run_job(app,client,maximum=1)
        assert status['successful_messages']==1 and len(services.model.calls)==1
        assert rows(app)[0]['attempts']==(2 if state=='PROCESSING' else 1)


async def test_unexpired_claim_is_not_stolen_after_restart(postgres_url):
    async with pg_app(postgres_url) as (app,client,_,_f):
        await authorize(client);job,connection=manual_job(app)
        await asyncio.to_thread(app.state.gmail_service.messages.claim_page,job,connection,['m0000'],1)
    async with pg_app(postgres_url) as (app,client,services,_):
        await authorize(client);_,status=await run_job(app,client,maximum=1)
        assert status['selected_messages']==0 and status['deferred_messages']==1 and not services.model.calls
        assert rows(app)[0]['status']=='RESERVED'


async def test_atomic_page_reservation_and_fencing_tokens(postgres_url):
    async with pg_app(postgres_url) as (app,client,services,_):
        await authorize(client);tracker=app.state.gmail_service.messages
        contexts=[manual_job(app) for _ in range(4)]
        pages=await asyncio.gather(*[asyncio.to_thread(tracker.claim_page,j,c,['m0000'],1) for j,c in contexts])
        assert sum(len(p.claims) for p in pages)==1 and sum(p.deferred for p in pages)==3
        winner=next(i for i,p in enumerate(pages) if p.claims)
        old,connection=contexts[winner];old_token=pages[winner].claims['m0000']
        assert await asyncio.to_thread(tracker.begin,old,connection,'m0000',old_token)
        old.status=JobState.FAILED
        with app.state.batch_service._store.engine.begin() as conn:
            conn.execute(G.__table__.update().values(claim_expires_at=now()-timedelta(minutes=5)))
        fresh,_=manual_job(app)
        claim=await asyncio.to_thread(tracker.claim_page,fresh,connection,['m0000'],1)
        token=claim.claims['m0000'];assert token!=old_token
        assert not await asyncio.to_thread(tracker.finish,old,connection,'m0000',old_token,None)
        assert not await asyncio.to_thread(tracker.begin,fresh,connection,'m0000',old_token)
        assert await asyncio.to_thread(tracker.begin,fresh,connection,'m0000',token)
        assert await asyncio.to_thread(tracker.finish,fresh,connection,'m0000',token,None)
        assert rows(app)[0]['attempts']==2 and rows(app)[0]['status']=='SUCCEEDED'
        assert not services.model.calls


async def test_tenants_and_mailboxes_with_same_message_id_are_independent(postgres_url):
    fake=mailbox(1);fake.messages[ACCESS_B]={'m0000':message('Beta review.',mid='m0000')}
    async with pg_app(postgres_url,fake=fake) as (app,client,services,_):
        await authorize(client);await authorize(client,BETA_KEY,'beta-code')
        ja,sa=await run_job(app,client,1);jb,sb=await run_job(app,client,1,BETA_KEY)
        assert sa['successful_messages']==sb['successful_messages']==1 and len(rows(app))==2
        assert (await client.get(BASE+'/imports/'+ja+'/results',headers=api_headers(BETA_KEY))).status_code==404
        assert (await client.get(BASE+'/imports/'+jb,headers=api_headers())).status_code==404
        alpha_job,alpha_connection=manual_job(app);beta_job,beta_connection=manual_job(app,BETA_KEY)
        with pytest.raises(ApplicationError) as error:
            await asyncio.to_thread(app.state.gmail_service.messages.claim_page,beta_job,alpha_connection,['m0000'],1)
        assert error.value.code==E.GMAIL_JOB_NOT_FOUND
        assert len(services.model.calls)==2


async def test_same_tenant_can_change_mailbox_after_disconnect_without_identity_collision(postgres_url):
    fake=mailbox(1)
    async with pg_app(postgres_url,fake=fake) as (app,client,services,_):
        await authorize(client);await run_job(app,client,1)
        assert (await client.delete(BASE+'/disconnect',headers=api_headers())).status_code==200
        fake.addresses[ACCESS_A]='second@example.test'
        assert (await authorize(client)).status_code==200
        _,status=await run_job(app,client,1)
        saved=rows(app)
        assert status['successful_messages']==1 and len(services.model.calls)==2
        assert len(saved)==2 and len({r['mailbox_key'] for r in saved})==2
        assert all('@' not in r['mailbox_key'] for r in saved)


async def test_page_lookup_is_batched_and_auth_precedes_foreign_registry_access(postgres_url):
    async with pg_app(postgres_url) as (app,client,services,_):
        await authorize(client);job,connection=manual_job(app);queries=[]
        engine=app.state.batch_service._store.engine
        def capture(conn,cursor,statement,params,context,many):
            if statement.startswith('SELECT') and 'gmail_message_tracking' in statement:queries.append(statement)
        event.listen(engine,'before_cursor_execute',capture)
        try:
            result=await asyncio.to_thread(app.state.gmail_service.messages.claim_page,job,connection,[f'm{i}' for i in range(100)],100)
        finally:event.remove(engine,'before_cursor_execute',capture)
        assert len(result.claims)==100 and len(queries)==2
        lookup=next(q for q in queries if ' IN (' in q)
        assert 'tenant_id =' in lookup and 'mailbox_key =' in lookup and 'FOR UPDATE' in lookup
        assert not services.model.calls


async def test_duplicate_ids_across_listing_pages_do_not_consume_new_capacity(postgres_url):
    fake=mailbox(2)
    def listing(request):
        if request.url.path.endswith('/messages'):
            if request.url.params.get('pageToken') is None:
                return httpx.Response(200,json={'messages':[{'id':'m0000'},{'id':'m0000'}],'nextPageToken':'second'})
            return httpx.Response(200,json={'messages':[{'id':'m0000'},{'id':'m0001'}]})
    fake.hook=listing
    async with pg_app(postgres_url,fake=fake) as (app,client,services,_):
        await authorize(client);_,status=await run_job(app,client,maximum=2)
        assert status['successful_messages']==status['selected_messages']==2 and status['scanned_messages']==4
        assert len(services.model.calls)==len(rows(app))==2


async def test_bad_later_page_releases_unstarted_claims_for_another_job(postgres_url):
    fake=mailbox(2)
    def listing(request):
        if request.url.path.endswith('/messages'):
            mid='m0000' if request.url.params.get('pageToken') is None else 'm0001'
            return httpx.Response(200,json={'messages':[{'id':mid}],'nextPageToken':'repeated'})
    fake.hook=listing
    async with pg_app(postgres_url,fake=fake) as (app,client,services,_):
        await authorize(client);_,failed=await run_job(app,client,maximum=2)
        assert failed['status']=='FAILED' and failed['error_code']=='GMAIL_RESPONSE_INVALID'
        saved=rows(app)
        assert len(saved)==1 and saved[0]['status']=='PENDING' and saved[0]['attempts']==0 and saved[0]['claim_token'] is None
        assert not services.model.calls
        fake.hook=None
        _,retried=await run_job(app,client,maximum=2)
        assert retried['successful_messages']==2 and len(services.model.calls)==2


async def test_whole_job_timeout_releases_unstarted_claim_without_spending_attempt(postgres_url):
    gate=asyncio.Event();services=harness(model=Model(gate=gate));fake=mailbox(2)
    async with pg_app(postgres_url,fake=fake,services=services,gmail_import_timeout_seconds=.3) as (app,client,_s,_):
        await authorize(client);_,status=await run_job(app,client,maximum=2)
        assert status['status']=='FAILED' and status['error_code']=='GMAIL_TIMEOUT'
        saved={r['message_id']:r for r in rows(app)}
        assert saved['m0000']['status']=='FAILED' and saved['m0000']['attempts']==1
        assert saved['m0001']['status']=='PENDING' and saved['m0001']['attempts']==0
        assert all(r['claim_token'] is None for r in saved.values())
        assert app.state.model_admission.active==0
        gate.set();_,next_job=await run_job(app,client,maximum=1)
        assert next_job['successful_messages']==1 and next_job['deferred_messages']==1
        assert len(services.model.calls)==2


async def test_disconnect_preserves_history_and_releases_claims_using_verified_job_owner(postgres_url):
    gate=asyncio.Event();services=harness(model=Model(gate=gate));fake=mailbox(2)
    async with pg_app(postgres_url,fake=fake,services=services) as (app,client,_s,_):
        await authorize(client)
        response=await client.post(BASE+'/import',headers=api_headers(),json={'max_messages':2})
        assert response.status_code==202
        await until(lambda:services.model.active==1,timeout=15)
        assert (await client.delete(BASE+'/disconnect',headers=api_headers())).status_code==200
        saved=rows(app)
        assert len(saved)==2 and all(r['claim_token'] is None for r in saved)
        assert {r['status'] for r in saved}=={'FAILED','PENDING'}
        assert app.state.model_admission.active==0
        assert (await client.get(BASE+'/imports/'+response.json()['job_id'],headers=api_headers())).status_code==404
        await authorize(client);gate.set()
        _,next_job=await run_job(app,client,maximum=1)
        assert next_job['successful_messages']==1 and next_job['deferred_messages']==1
        assert len(services.model.calls)==2


async def test_registry_insert_failure_rolls_back_without_model_call_or_sensitive_logs(postgres_url,caplog):
    from sqlalchemy.exc import OperationalError
    async with pg_app(postgres_url) as (app,client,services,_):
        await authorize(client);engine=app.state.batch_service._store.engine
        def fail(conn,cursor,statement,parameters,context,many):
            if statement.startswith('INSERT INTO gmail_message_tracking'):
                raise OperationalError('private SQL',{},RuntimeError('private-email-or-token-marker'))
        event.listen(engine,'before_cursor_execute',fail)
        try:
            _,status=await run_job(app,client,maximum=1)
            assert status['status']=='FAILED' and status['error_code']=='GMAIL_UNAVAILABLE'
            assert not services.model.calls and rows(app)==[]
        finally:event.remove(engine,'before_cursor_execute',fail)
        assert 'private-email-or-token-marker' not in caplog.text
        _,next_job=await run_job(app,client,maximum=1)
        assert next_job['successful_messages']==1 and len(services.model.calls)==1


async def test_tracking_capacity_is_explicit_and_does_not_evict_successes(postgres_url):
    fake=mailbox(2)
    async with pg_app(postgres_url,fake=fake,gmail_tenant_max_dedup_records=1) as (app,client,services,_):
        await authorize(client);_,status=await run_job(app,client,maximum=2)
        assert status['status']=='PARTIAL_SUCCESS' and status['successful_messages']==1
        assert status['capacity_limit_reached'] and status['error_code']=='GMAIL_CAPACITY_EXCEEDED'
        assert not status['scan_exhausted']
        _,blocked=await run_job(app,client,maximum=1)
        assert blocked['status']=='FAILED' and blocked['selected_messages']==0 and blocked['capacity_limit_reached']
        assert rows(app)[0]['status']=='SUCCEEDED' and len(rows(app))==1 and len(services.model.calls)==1


async def test_job_expiry_and_key_rotation_do_not_remove_success_or_store_private_data(postgres_url):
    fake=mailbox(1)
    async with pg_app(postgres_url,fake=fake) as (app,client,services,_):
        await authorize(client);job,status=await run_job(app,client,maximum=1)
        held=app.state.gmail_service.store._jobs[job];held.expires_at=0
        assert (await client.get(BASE+'/imports/'+job,headers=api_headers())).status_code==404
        assert held.results==[]
        saved=rows(app)[0]
        assert 'alpha@example.test' not in str(saved) and 'Synthetic review' not in str(saved)
        assert not set(G.__table__.columns.keys()) & {'mailbox','email','text','body','analysis','access_token','refresh_token','subject','sender','headers'}
        assert len(services.model.calls)==1
    credentials=[CREDENTIALS[0]|{'key_id':'alpha-rotated','api_key':ALPHA_ROTATED_KEY},CREDENTIALS[1]]
    async with pg_app(postgres_url,fake=fake,credentials=credentials) as (app,client,services,_):
        assert (await authorize(client,ALPHA_ROTATED_KEY)).status_code==200
        _,status=await run_job(app,client,maximum=1,key=ALPHA_ROTATED_KEY)
        assert status['previously_processed_messages']==1 and not services.model.calls
        assert (await client.post(BASE+'/import',headers=api_headers(),json={'max_messages':1})).status_code==401


async def test_documented_1000_message_batch_configuration_reaches_all_messages(postgres_url):
    fake=mailbox(1000)
    async with pg_app(postgres_url,fake=fake,gmail_max_list_pages=10,
                      gmail_tenant_max_retained_imports=12,gmail_import_timeout_seconds=600) as (app,client,services,_):
        await authorize(client)
        for index in range(10):
            _,status=await run_job(app,client,maximum=100)
            assert status['selected_messages']==status['successful_messages']==100
            assert status['previously_processed_messages']==index*100
            assert not status['scan_limit_reached'] and not status['capacity_limit_reached']
        _,empty=await run_job(app,client,maximum=100)
        assert empty['selected_messages']==0 and empty['previously_processed_messages']==1000
        assert empty['scan_exhausted'] and not empty['scan_limit_reached']
        assert len(services.model.calls)==len({call['text'] for call in services.model.calls})==1000
        saved=rows(app)
        assert len(saved)==1000 and all(r['status']=='SUCCEEDED' and r['attempts']==1 for r in saved)
