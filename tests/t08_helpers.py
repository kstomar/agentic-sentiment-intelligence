from app.storage.event_store import EventStore
from app.storage.gmail_message_store import MemoryGmailMessageStore
from app.storage.job_store import JobStore
"""Synthetic mailboxes/tokens and actual adapter calls through HTTPX MockTransport."""

import asyncio
import base64
import copy
import json
from contextlib import asynccontextmanager
from urllib.parse import parse_qs, urlsplit

import httpx

from app.main import create_app
from app.integrations.google_gmail import SCOPE
from tests.helpers import harness, until
from tests.t07_helpers import ALPHA_KEY, api_headers, multi_settings

ACCESS_A = 'fabricated-google-alpha-access-token'
ACCESS_B = 'fabricated-google-beta-access-token'
REFRESH_A = 'fabricated-google-alpha-refresh-token'
REFRESH_B = 'fabricated-google-beta-refresh-token'
CLIENT_SECRET = 'fabricated-google-client-secret-not-a-real-credential'


def part(text='Delivery was late.', mime='text/plain', charset='utf-8', **extra):
    raw = text.encode(charset)
    return {'partId': '0', 'mimeType': mime, 'filename': '',
            'headers': [{'name': 'Content-Type', 'value': mime + '; charset=' + charset}],
            'body': {'size': len(raw), 'data': base64.urlsafe_b64encode(raw).rstrip(b'=').decode()}} | extra


def message(text='Delivery was late.', mid='m1', payload=None, **extra):
    payload = copy.deepcopy(payload) if payload is not None else part(text)
    payload.setdefault('headers', []).extend([
        {'name': 'Subject', 'value': 'Fabricated subject private sentinel'},
        {'name': 'From', 'value': 'Synthetic Sender <sender@example.test>'},
    ])
    return {'id': mid, 'threadId': 'thread1', 'internalDate': '1700000000000',
            'labelIds': ['Label_feedback'], 'payload': payload} | extra


def gmail_settings(**overrides):
    return multi_settings(**({'gmail_oauth_enabled': True,
        'google_oauth_client_id': 'fabricated-client.apps.googleusercontent.com',
        'google_oauth_client_secret': CLIENT_SECRET,
        'google_oauth_redirect_uri': 'https://api.example.test/api/v1/integrations/gmail/oauth/callback'} | overrides))


class FakeGoogle:
    def __init__(self):
        self.requests = []
        self.messages = {ACCESS_A: {'m1': message()}, ACCESS_B: {'m1': message('Beta feedback.')}}
        self.addresses = {ACCESS_A: 'alpha@example.test', ACCESS_B: 'beta@example.test'}
        self.token_data = {}
        self.failures = {}
        self.page_size = 2
        self.respect_sent_filter = True
        self.label_name = 'customer-feedback'
        self.gates = {}
        self.hook = None

    async def __call__(self, request):
        self.requests.append(request)
        path = request.url.path
        gate = self.gates.get(path)
        if gate is not None:
            await gate.wait()
        if self.hook is not None:
            value = self.hook(request)
            if value is not None:
                return value
        failures = self.failures.get(path)
        if failures:
            item = failures.pop(0)
            if isinstance(item, Exception): raise item
            if isinstance(item, httpx.Response): return item
            return httpx.Response(item, json={'error': {'errors': [{'reason': 'userRateLimitExceeded'}]}})
        if path == '/token':
            data = parse_qs(request.content.decode())
            code = data.get('code', [''])[0]
            refresh = data.get('refresh_token', [''])[0]
            beta = code == 'beta-code' or refresh == REFRESH_B
            result = {'access_token': ACCESS_B if beta else ACCESS_A,
                      'refresh_token': REFRESH_B if beta else REFRESH_A,
                      'expires_in': 3600, 'token_type': 'Bearer', 'scope': SCOPE}
            result.update(self.token_data)
            return httpx.Response(200, json=result)
        token = request.headers.get('Authorization', '').removeprefix('Bearer ')
        assert request.url.host == 'gmail.googleapis.com'
        if path.endswith('/profile'):
            return httpx.Response(200, json={'emailAddress': self.addresses[token]})
        if path.endswith('/labels'):
            return httpx.Response(200, json={'labels': [{'id': 'Label_feedback', 'name': self.label_name}]})
        if path.endswith('/messages'):
            ids = list(self.messages[token])
            if self.respect_sent_filter and '-in:sent' in request.url.params.get('q', ''):
                ids = [mid for mid in ids if not isinstance(self.messages[token][mid].get('labelIds'), list)
                       or 'SENT' not in self.messages[token][mid]['labelIds']]
            offset = int(request.url.params.get('pageToken', '0'))
            take = min(self.page_size, int(request.url.params['maxResults']))
            selected = ids[offset:offset+take]
            result = {'messages': [{'id': mid} for mid in selected]}
            if offset+take < len(ids): result['nextPageToken'] = str(offset+take)
            return httpx.Response(200, json=result)
        if '/messages/' in path:
            assert '/attachments/' not in path
            mid = path.rsplit('/', 1)[1]
            result = copy.deepcopy(self.messages[token][mid])
            if request.url.params.get('format') == 'minimal':
                return httpx.Response(200, json={key: result[key] for key in ('id', 'labelIds') if key in result})
            if 'attachmentId,data' not in request.url.params['fields']:
                stack = [result['payload']]
                while stack:
                    value = stack.pop()
                    value.get('body', {}).pop('data', None)
                    stack.extend(value.get('parts', []))
            return httpx.Response(200, json=result)
        raise AssertionError('Unexpected fixed-provider operation')


@asynccontextmanager
async def gmail_app(*, fake=None, services=None, **overrides):
    fake = fake if fake is not None else FakeGoogle()
    services = services if services is not None else harness()
    app = create_app(gmail_settings(**overrides), sentiment_service=services.sentiment,
        investigation_service=services.investigation, gmail_transport=httpx.MockTransport(fake), batch_store=JobStore(1800), gmail_message_store_factory=MemoryGmailMessageStore, event_store_factory=lambda r: EventStore(r.settings.webhook_max_retained_events, r.settings.webhook_event_ttl_seconds, r))
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://qa.local') as client:
            yield app, client, services, fake


async def authorize(client, key=ALPHA_KEY, code='alpha-code'):
    response = await client.post('/api/v1/integrations/gmail/connect', headers=api_headers(key))
    assert response.status_code == 200
    params = parse_qs(urlsplit(response.json()['authorization_url']).query)
    response = await client.get('/api/v1/integrations/gmail/oauth/callback', params={'state': params['state'][0], 'code': code})
    return response


async def import_job(app, client, maximum=20, key=ALPHA_KEY):
    response = await client.post('/api/v1/integrations/gmail/import', headers=api_headers(key), json={'max_messages': maximum})
    assert response.status_code == 202
    job = response.json()['job_id']
    principal = app.state.tenant_registry.authenticate(key)
    await until(lambda: app.state.gmail_service.job_status(job, principal).status in {'COMPLETED', 'PARTIAL_SUCCESS', 'FAILED'})
    return job
