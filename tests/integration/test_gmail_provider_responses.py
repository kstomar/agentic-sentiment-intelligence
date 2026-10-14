"""Realistic bounded Gmail responses over MockTransport; never live mailbox access."""

import httpx
import pytest

from tests.helpers import analysis
from tests.t07_helpers import api_headers
from tests.t08_helpers import ACCESS_A, FakeGoogle, authorize, gmail_app, import_job, message

BASE = '/api/v1/integrations/gmail'


async def test_valid_large_label_list_imports_only_the_configured_label():
    fake = FakeGoogle()
    label_id = 'Label_7272185735677952091'
    body = 'Synthetic customer feedback: delivery was late.'
    fake.messages[ACCESS_A] = {'19a12345abcd': message(body, mid='19a12345abcd', labelIds=[label_id])}
    labels = [{'id': f'Label_{i}', 'name': f'Unrelated-{i}'} for i in range(1000)]
    labels.append({'id': label_id, 'name': 'customer-feedback'})
    fake.hook = lambda request: httpx.Response(200, json={'labels': labels}) if request.url.path.endswith('/labels') else None
    async with gmail_app(fake=fake) as (app, client, services, _):
        assert (await authorize(client)).status_code == 200
        job = await import_job(app, client, maximum=1)
        status = (await client.get(BASE+'/imports/'+job, headers=api_headers())).json()
        assert status['status'] == 'COMPLETED' and status['selected_messages'] == status['successful_messages'] == 1
        result = (await client.get(BASE+'/imports/'+job+'/results', headers=api_headers())).json()['results'][0]
        assert result['analysis'] == analysis(body) and result['status'] == 'SUCCESS'
        assert services.model.calls == [{'text': body, 'source': 'email', 'business_type': 'general'}]
        listing = [r for r in fake.requests if r.url.path.endswith('/messages')]
        assert len(listing) == 1 and listing[0].url.params['labelIds'] == label_id
        assert listing[0].url.params['q'] == 'newer_than:7d -in:sent'
        assert listing[0].url.params['includeSpamTrash'] == 'false'


async def test_non_json_provider_outage_is_not_a_success_schema_error():
    fake = FakeGoogle()
    fake.failures['/gmail/v1/users/me/labels'] = [httpx.Response(503, text='private upstream failure')] * 2
    async with gmail_app(fake=fake) as (app, client, services, _):
        assert (await authorize(client)).status_code == 200
        job = await import_job(app, client, maximum=1)
        status = (await client.get(BASE+'/imports/'+job, headers=api_headers())).json()
        assert status['status'] == 'FAILED' and status['selected_messages'] == 0
        assert status['error_code'] == 'GMAIL_PROVIDER_ERROR'
        assert not services.model.calls
        assert len([r for r in fake.requests if r.url.path.endswith('/labels')]) == 2
        assert (await client.get(BASE+'/status', headers=api_headers())).json()['connected'] is True


@pytest.mark.parametrize('payload', [{}, {'labels': []}, {'labels': [{'id':'INBOX','name':'INBOX'},
    {'id':'Label_7','name':'Different-feedback-label'}]}])
async def test_missing_label_is_configuration_failure_not_invalid_response(payload,caplog):
    fake=FakeGoogle()
    fake.hook=lambda request:httpx.Response(200,json=payload) if request.url.path.endswith('/labels') else None
    async with gmail_app(fake=fake) as (app,client,services,_):
        assert (await authorize(client)).status_code==200
        job=await import_job(app,client,maximum=1)
        result=(await client.get(BASE+'/imports/'+job,headers=api_headers())).json()
        assert result['status']=='FAILED' and result['error_code']=='GMAIL_SELECTION_INVALID'
        assert result['selected_messages']==result['processed_messages']==0
        assert not services.model.calls and not any('/messages' in r.url.path for r in fake.requests)
        assert 'operation=labels.list stage=label_selection' in caplog.text
        assert (await client.get(BASE+'/status',headers=api_headers())).json()['connected'] is True


@pytest.mark.parametrize('payload',[{}, {'resultSizeEstimate':0}, {'messages':[]}, {'messages':[],'resultSizeEstimate':0}])
async def test_valid_google_empty_message_responses_complete_without_inference(payload):
    fake=FakeGoogle()
    fake.hook=lambda request:httpx.Response(200,json=payload) if request.url.path.endswith('/messages') else None
    async with gmail_app(fake=fake) as (app,client,services,_):
        assert (await authorize(client)).status_code==200
        job=await import_job(app,client,maximum=1)
        result=(await client.get(BASE+'/imports/'+job,headers=api_headers())).json()
        assert result['status']=='COMPLETED' and result['error_code'] is None
        assert all(result[field]==0 for field in ('selected_messages','processed_messages','successful_messages','failed_messages','skipped_messages','duplicate_messages'))
        assert (await client.get(BASE+'/imports/'+job+'/results',headers=api_headers())).json()['results']==[]
        assert not services.model.calls and not any('/messages/' in r.url.path for r in fake.requests)


@pytest.mark.parametrize('payload,stage',[
    ([], 'response_shape'), ({'error':{'message':'private provider text'}}, 'response_shape'),
    ({'labels':None},'label_list'), ({'labels':{}},'label_list'),
    ({'labels':[None]},'label_row'), ({'labels':[{'id':'Label_7','name':None}]},'label_row'),
    ({'labels':[{'id':7,'name':'customer-feedback'}]},'label_id'),
    ({'labels':[{'id':'../private-label','name':'customer-feedback'}]},'label_id'),
])
async def test_malformed_label_responses_remain_rejected_and_diagnostics_are_safe(payload,stage,caplog):
    from tests.t08_helpers import REFRESH_A,CLIENT_SECRET
    fake=FakeGoogle()
    fake.hook=lambda request:httpx.Response(200,json=payload) if request.url.path.endswith('/labels') else None
    async with gmail_app(fake=fake) as (app,client,services,_):
        assert (await authorize(client)).status_code==200
        job=await import_job(app,client,maximum=1)
        response=await client.get(BASE+'/imports/'+job,headers=api_headers())
        assert response.json()['error_code']=='GMAIL_RESPONSE_INVALID' and response.json()['selected_messages']==0
        assert not services.model.calls
        assert f'operation=labels.list stage={stage} status=200 code=GMAIL_RESPONSE_INVALID' in caplog.text
        for private in (ACCESS_A,REFRESH_A,CLIENT_SECRET,'private provider text','../private-label'):
            assert private not in caplog.text and private not in response.text


@pytest.mark.parametrize('content,stage',[(b'not-json','json'),(b'x'*300000,'response_bytes')])
async def test_malformed_or_oversized_success_body_remains_invalid(content,stage,caplog):
    fake=FakeGoogle()
    fake.failures['/gmail/v1/users/me/labels']=[httpx.Response(200,content=content)]
    async with gmail_app(fake=fake) as (app,client,services,_):
        assert (await authorize(client)).status_code==200
        job=await import_job(app,client,maximum=1)
        result=(await client.get(BASE+'/imports/'+job,headers=api_headers())).json()
        assert result['status']=='FAILED' and result['error_code']=='GMAIL_RESPONSE_INVALID'
        assert f'operation=labels.list stage={stage}' in caplog.text and not services.model.calls


@pytest.mark.parametrize('status,error,code,connected,retries',[
    (401,None,'GMAIL_RECONNECT_REQUIRED',False,1),
    (403,{'errors':[{'reason':'insufficientPermissions'}]},'GMAIL_RECONNECT_REQUIRED',False,1),
    (403,{'details':[{'reason':'ACCESS_TOKEN_SCOPE_INSUFFICIENT'}]},'GMAIL_RECONNECT_REQUIRED',False,1),
    (403,{'errors':[{'reason':'accessNotConfigured','message':'private provider detail'}]},'GMAIL_PROVIDER_ERROR',True,1),
    (403,{'details':[{'reason':'SERVICE_DISABLED'}]},'GMAIL_PROVIDER_ERROR',True,1),
    (403,{'errors':[{'reason':'domainPolicy'}]},'GMAIL_PROVIDER_ERROR',True,1),
    (403,{'errors':[{'reason':'userRateLimitExceeded'}]},'GMAIL_RATE_LIMITED',True,2),
    (403,{'errors':[{'reason':'quotaExceeded'}]},'GMAIL_RATE_LIMITED',True,2),
    (429,None,'GMAIL_RATE_LIMITED',True,2),
    (500,None,'GMAIL_PROVIDER_ERROR',True,2),
    (400,{'message':'private provider detail'},'GMAIL_PROVIDER_ERROR',True,1),
])
async def test_http_auth_configuration_rate_and_server_errors_are_distinct(status,error,code,connected,retries,caplog):
    fake=FakeGoogle()
    response=httpx.Response(status,json={'error':error}) if error is not None else httpx.Response(status,text='private provider detail')
    fake.failures['/gmail/v1/users/me/labels']=[response]*retries
    async with gmail_app(fake=fake) as (app,client,services,_):
        assert (await authorize(client)).status_code==200
        job=await import_job(app,client,maximum=1)
        value=(await client.get(BASE+'/imports/'+job,headers=api_headers())).json()
        assert value['status']=='FAILED' and value['selected_messages']==0 and value['error_code']==code
        assert (await client.get(BASE+'/status',headers=api_headers())).json()['connected'] is connected
        assert not services.model.calls
        assert len([r for r in fake.requests if r.url.path.endswith('/labels')])==retries
        assert f'operation=labels.list stage=http_status status={status} code={code}' in caplog.text
        assert 'private provider detail' not in caplog.text


@pytest.mark.parametrize('payload,stage',[
    ({'messages':None},'message_list'), ({'messages':{}},'message_list'),
    ({'messages':[{'id':f'm{i}'} for i in range(21)]},'message_list'),
    ({'messages':[None]},'message_row'), ({'messages':[{'id':None}]},'message_id'),
    ({'messages':[{'id':'private/untrusted/id'}]},'message_id'),
    ({'nextPageToken':23},'page_token'), ({'nextPageToken':''},'page_token'),
    ({'messages':[],'nextPageToken':'same-page'},'page_token'),
])
async def test_message_listing_validation_is_diagnosed_before_selection(payload,stage,caplog):
    fake=FakeGoogle()
    fake.hook=lambda request:httpx.Response(200,json=payload) if request.url.path.endswith('/messages') else None
    async with gmail_app(fake=fake) as (app,client,services,_):
        assert (await authorize(client)).status_code==200
        job=await import_job(app,client,maximum=1)
        value=(await client.get(BASE+'/imports/'+job,headers=api_headers())).json()
        assert value['status']=='FAILED' and value['error_code']=='GMAIL_RESPONSE_INVALID'
        assert value['selected_messages']==0 and not services.model.calls
        assert f'operation=messages.list stage={stage}' in caplog.text
        assert 'private/untrusted/id' not in caplog.text and 'same-page' not in caplog.text


@pytest.mark.parametrize('token_change,code',[
    ({'expires_in':True},'GMAIL_RESPONSE_INVALID'),
    ({'access_token':''},'GMAIL_RESPONSE_INVALID'),
    ({'scope':'https://www.googleapis.com/auth/gmail.modify'},'GMAIL_SCOPE_INVALID'),
])
async def test_invalid_refresh_response_is_distinguished_from_label_response(token_change,code,caplog):
    import time
    fake=FakeGoogle()
    async with gmail_app(fake=fake) as (app,client,services,_):
        assert (await authorize(client)).status_code==200
        connection=app.state.gmail_service.store._connections['business_alpha']
        connection.tokens.expires_at=time.monotonic()-1
        fake.token_data.update(token_change)
        job=await import_job(app,client,maximum=1)
        value=(await client.get(BASE+'/imports/'+job,headers=api_headers())).json()
        assert value['status']=='FAILED' and value['error_code']==code and value['selected_messages']==0
        assert not services.model.calls and not any(r.url.path.endswith('/labels') for r in fake.requests)
        assert f'operation=oauth.refresh stage=tokens status=200 code={code}' in caplog.text
        assert connection.tokens.access is connection.tokens.refresh is None


async def test_selection_still_rejects_a_broad_system_label():
    fake=FakeGoogle()
    fake.hook=lambda request:httpx.Response(200,json={'labels':[{'id':'INBOX','name':'INBOX'}]}) if request.url.path.endswith('/labels') else None
    async with gmail_app(fake=fake,gmail_feedback_label='INBOX') as (app,client,services,_):
        assert (await authorize(client)).status_code==200
        job=await import_job(app,client,maximum=1)
        value=(await client.get(BASE+'/imports/'+job,headers=api_headers())).json()
        assert value['status']=='FAILED' and value['error_code']=='GMAIL_SELECTION_INVALID'
        assert not services.model.calls and not any('/messages' in r.url.path for r in fake.requests)


async def test_invalid_label_count_stays_bounded(caplog):
    fake=FakeGoogle()
    labels=[{'id':'L','name':'x'}]*10001
    response=httpx.Response(200,json={'labels':labels})
    assert len(response.content)<262144
    fake.hook=lambda request:response if request.url.path.endswith('/labels') else None
    async with gmail_app(fake=fake) as (app,client,services,_):
        assert (await authorize(client)).status_code==200
        job=await import_job(app,client,maximum=1)
        value=(await client.get(BASE+'/imports/'+job,headers=api_headers())).json()
        assert value['error_code']=='GMAIL_RESPONSE_INVALID' and not services.model.calls
        assert 'operation=labels.list stage=label_list' in caplog.text
