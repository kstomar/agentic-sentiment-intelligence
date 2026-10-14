"""Messages-list wire contract and fail-closed handling of unexplained HTTP 204."""

import httpx
import pytest

from app.core.exceptions import ApplicationError, ErrorCode as E
from app.integrations.google_gmail import GoogleGmail
from tests.t07_helpers import api_headers
from tests.t08_helpers import FakeGoogle, authorize, gmail_app, import_job

BASE = '/api/v1/integrations/gmail'


async def test_messages_list_204_fails_with_actual_safe_request_metadata(caplog):
    fake = FakeGoogle()
    fake.hook = lambda request: httpx.Response(204) if request.url.path.endswith('/messages') else None
    async with gmail_app(fake=fake) as (app, client, services, _):
        assert (await authorize(client)).status_code == 200
        job = await import_job(app, client, maximum=1)
        response = await client.get(BASE+'/imports/'+job, headers=api_headers())
        value = response.json()
        assert value['status'] == 'FAILED' and value['error_code'] == 'GMAIL_PROVIDER_ERROR'
        assert all(value[field] == 0 for field in ('selected_messages','processed_messages','successful_messages','failed_messages','skipped_messages','duplicate_messages'))
        result = (await client.get(BASE+'/imports/'+job+'/results', headers=api_headers())).json()
        assert result['status'] == 'FAILED' and result['results'] == []
        assert not services.model.calls and not any('/messages/' in r.url.path for r in fake.requests)
        assert len([r for r in fake.requests if r.url.path.endswith('/messages')]) == 1
        assert (await client.get(BASE+'/status', headers=api_headers())).json()['connected'] is True
        assert 'operation=messages.list stage=http_status status=204 code=GMAIL_PROVIDER_ERROR' in caplog.text
        assert 'method=GET host=gmail.googleapis.com response_bytes=0 transport=injected' in caplog.text


@pytest.mark.parametrize('maximum,page', [(1,None),(7,'private-synthetic-page-token')])
async def test_messages_list_actual_wire_request_matches_google_contract(maximum,page):
    from pydantic import SecretStr
    from tests.t08_helpers import gmail_settings
    seen=[]
    async def handler(request):
        seen.append(request)
        assert request.method=='GET'
        assert request.url.scheme=='https' and request.url.host=='gmail.googleapis.com'
        assert request.url.path=='/gmail/v1/users/me/messages'
        expected={'labelIds':'Label_123456','q':'newer_than:14d -in:sent','includeSpamTrash':'false',
                  'maxResults':str(maximum),'fields':'messages(id,threadId),nextPageToken'}
        if page is not None:expected['pageToken']=page
        assert dict(request.url.params)==expected
        assert request.content==b''
        assert request.headers['Accept']=='application/json'
        assert request.headers['Accept-Encoding']=='identity'
        assert request.headers['Authorization']=='Bearer fabricated-access-token'
        assert not any(name in request.headers for name in ('Origin','X-HTTP-Method-Override','If-None-Match','If-Modified-Since'))
        return httpx.Response(200,json={'messages':[{'id':'19abc123','threadId':'19abc123'}]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler),trust_env=False,follow_redirects=False) as client:
        google=GoogleGmail(client,gmail_settings(gmail_search_days=14),transport_mode='injected')
        result=await google.list_page(SecretStr('fabricated-access-token'),'Label_123456',maximum,page)
        assert result=={'messages':[{'id':'19abc123','threadId':'19abc123'}]} and len(seen)==1


@pytest.mark.parametrize('status',[202,204,205,206])
async def test_non_200_responses_with_json_do_not_become_empty_or_successful_imports(status,caplog):
    fake=FakeGoogle()
    payload={'messages':[{'id':'m1','threadId':'thread1'}]}
    fake.hook=lambda request:httpx.Response(status,json=payload) if request.url.path.endswith('/messages') else None
    async with gmail_app(fake=fake) as (app,client,services,_):
        assert (await authorize(client)).status_code==200
        job=await import_job(app,client,maximum=1)
        value=(await client.get(BASE+'/imports/'+job,headers=api_headers())).json()
        assert value['status']=='FAILED' and value['error_code']=='GMAIL_PROVIDER_ERROR'
        assert value['selected_messages']==value['processed_messages']==0
        assert not services.model.calls
        assert f'operation=messages.list stage=http_status status={status}' in caplog.text
        assert 'method=GET host=gmail.googleapis.com' in caplog.text
        assert not any('/messages/' in r.url.path for r in fake.requests)


async def test_200_empty_body_is_not_a_valid_empty_json_listing():
    fake=FakeGoogle()
    fake.hook=lambda request:httpx.Response(200) if request.url.path.endswith('/messages') else None
    async with gmail_app(fake=fake) as (app,client,services,_):
        assert (await authorize(client)).status_code==200
        job=await import_job(app,client,maximum=1)
        value=(await client.get(BASE+'/imports/'+job,headers=api_headers())).json()
        assert value['status']=='FAILED' and value['error_code']=='GMAIL_RESPONSE_INVALID'
        assert value['selected_messages']==0 and not services.model.calls


async def test_response_length_diagnostic_measures_bytes_without_logging_headers_or_payload(caplog):
    from tests.t08_helpers import ACCESS_A,REFRESH_A,CLIENT_SECRET
    private_body=b'private-email-body-must-not-be-logged'
    fake=FakeGoogle()
    fake.hook=lambda request:httpx.Response(204,content=private_body,
        headers={'Content-Length':'987654','Location':'https://private.example.test/secret','X-Private-Header':ACCESS_A}) if request.url.path.endswith('/messages') else None
    async with gmail_app(fake=fake) as (app,client,services,_):
        assert (await authorize(client)).status_code==200
        job=await import_job(app,client,maximum=1)
        value=(await client.get(BASE+'/imports/'+job,headers=api_headers())).json()
        assert value['status']=='FAILED' and not services.model.calls
        assert f'response_bytes={len(private_body)} transport=injected' in caplog.text
        for private in (private_body.decode(),'987654','private.example.test',ACCESS_A,REFRESH_A,CLIENT_SECRET,'Label_feedback'):
            assert private not in caplog.text


async def test_diagnostics_observe_request_after_hooks_instead_of_assuming_get(caplog):
    from pydantic import SecretStr
    from tests.t08_helpers import gmail_settings
    async def hook(request):request.method='HEAD'
    async def handler(request):
        assert request.method=='HEAD'
        return httpx.Response(204)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler),event_hooks={'request':[hook]},trust_env=False) as client:
        google=GoogleGmail(client,gmail_settings(),transport_mode='injected')
        with pytest.raises(ApplicationError) as error:
            await google.list_page(SecretStr('fabricated-secret'),'Label_private',1,None)
        assert error.value.code==E.GMAIL_PROVIDER_ERROR
        assert 'method=HEAD host=gmail.googleapis.com response_bytes=0 transport=injected' in caplog.text
        assert 'fabricated-secret' not in caplog.text and 'Label_private' not in caplog.text


async def test_default_app_google_client_ignores_proxy_environment_and_preserves_tls(monkeypatch):
    import ssl
    from app.main import create_app
    from app.storage.event_store import EventStore
    from app.storage.gmail_message_store import MemoryGmailMessageStore
    from app.storage.job_store import JobStore
    from tests.helpers import harness
    from tests.t08_helpers import gmail_settings
    for name in ('HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','http_proxy','https_proxy','all_proxy'):
        monkeypatch.setenv(name,'http://synthetic-proxy.invalid:8080')
    services=harness();config=gmail_settings()
    app=create_app(config,sentiment_service=services.sentiment,investigation_service=services.investigation,
        batch_store=JobStore(1800),gmail_message_store_factory=MemoryGmailMessageStore, event_store_factory=lambda r:EventStore(r.settings.webhook_max_retained_events,r.settings.webhook_event_ttl_seconds,r))
    async with app.router.lifespan_context(app):
        google=app.state.gmail_service.google;client=google.client
        assert google.transport_mode=='default'
        assert client.trust_env is False and client.follow_redirects is False
        # Inspect the installed locked HTTPX transport without making a network request.
        assert isinstance(client._transport,httpx.AsyncHTTPTransport) and client._mounts=={}
        pool=client._transport._pool
        assert pool._ssl_context.verify_mode==ssl.CERT_REQUIRED and pool._ssl_context.check_hostname
        assert pool._http1 is True and pool._http2 is False
        assert (client.timeout.connect,client.timeout.read,client.timeout.write,client.timeout.pool)==(config.gmail_http_timeout_seconds,)*4


def test_diagnostic_metadata_never_echoes_arbitrary_custom_client_values(caplog):
    from app.integrations.google_gmail import provider_failure
    failure=provider_failure('messages.list','http_status',E.GMAIL_PROVIDER_ERROR,204,
        method='private-method',host='private-host.invalid',response_bytes='private-length',transport='private-transport')
    assert failure.code==E.GMAIL_PROVIDER_ERROR
    assert 'method=OTHER host=OTHER response_bytes=None transport=unspecified' in caplog.text
    assert all(private not in caplog.text for private in ('private-method','private-host','private-length','private-transport'))
