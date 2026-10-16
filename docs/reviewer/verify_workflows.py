"""Offline reviewer demonstration only; changes no application code or configuration.

Run from project root with .venv/bin/python docs/reviewer/verify_workflows.py.
Every network transport is mocked or ASGI-local; all credentials are fabricated.
Recorded results demonstrate plumbing and calculations, not provider accuracy.
"""
import asyncio
import json
import os
from pathlib import Path
import socket
import sys
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import httpx
from mcp import Client
from pydantic import SecretStr
from pytest import MonkeyPatch
from app.core.config import Settings
from app.storage.event_store import EventStore
from app.storage.gmail_message_store import MemoryGmailMessageStore


async def verify():
    with MonkeyPatch.context() as patch:
        for field in Settings.model_fields:
            patch.delenv(field.upper(), raising=False)
        for name in ['LANGCHAIN_API_KEY', 'LANGSMITH_API_KEY']:
            patch.delenv(name, raising=False)
        patch.setenv('LANGSMITH_TRACING', 'false')
        patch.setitem(Settings.model_config, 'env_file', None)
        def deny(*args, **kwargs):
            raise AssertionError('Live network forbidden in reviewer verification')
        async def deny_async(*args, **kwargs):
            deny()
        for name in ['connect', 'connect_ex']:
            patch.setattr(socket.socket, name, deny)
        patch.setattr(socket, 'getaddrinfo', deny)
        patch.setattr(httpx.HTTPTransport, 'handle_request', deny)
        patch.setattr(httpx.AsyncHTTPTransport, 'handle_async_request', deny_async)
        from app.main import create_app
        from app.storage.job_store import JobStore
        from app.agents.action_selector import create_action_selector
        from app.services.investigation_service import InvestigationService
        from app.services.sentiment_service import create_sentiment_service
        from app.mcp_server.server import create_mcp_server
        from app.schemas.sentiment import SentimentResponse
        from app.schemas.investigation import InvestigationResponse
        from tests.helpers import analysis, until, xlsx
        from tests.t07_helpers import CREDENTIALS, INTEGRATIONS, ALPHA_KEY, BETA_KEY, api_headers, webhook_headers
        from tests.t08_helpers import FakeGoogle

        texts = ['Excellent product quality.', 'Delivery was very late.',
                 'The package arrived today.', 'Excellent quality but late delivery.']
        polarities = ['POSITIVE', 'NEGATIVE', 'NEUTRAL', 'MIXED']
        categories = ['PRAISE', 'DELIVERY', 'OTHER', 'DELIVERY']
        aspects = [
            [{'name': 'product_quality', 'sentiment': 'POSITIVE'}],
            [{'name': 'delivery', 'sentiment': 'NEGATIVE'}],
            [{'name': 'package_arrival', 'sentiment': 'NEUTRAL'}],
            [{'name': 'product_quality', 'sentiment': 'POSITIVE'}, {'name': 'delivery', 'sentiment': 'NEGATIVE'}],
        ]
        summaries = ['Customer praised product quality.', 'Customer reported a late delivery.',
                     'Customer stated that the package arrived today.', 'Customer praised quality and complained about delivery.']
        recommendations = ['Acknowledge the positive feedback.', 'Review the reported delivery delay.',
                           'Request further context if analysis is needed.', 'Review delivery feedback while preserving product quality.']
        outputs = {text: analysis(text, sentiment, category, aspects=aspect, summary=summary, suggested_next_step=next_step)
                   for text, sentiment, category, aspect, summary, next_step in zip(texts, polarities, categories, aspects, summaries, recommendations)}
        actions = ['SENTIMENT_OVERVIEW', 'ISSUE_FREQUENCY', 'EVIDENCE_SEARCH', 'GENERAL_FEEDBACK_SUMMARY']
        wire = {'classifier_calls': 0, 'selector_calls': 0, 'all_native_strict': True}
        async def groq_reply(request):
            assert request.url.host == 'api.groq.com'
            payload = json.loads(request.content)
            spec = payload['response_format']
            assert spec['type'] == 'json_schema' and spec['json_schema']['strict'] is True
            assert payload['model'] == 'openai/gpt-oss-20b'
            data = json.loads(payload['messages'][-1]['content'])
            if 'action' in spec['json_schema']['schema']['properties']:
                assert set(data) == {'question', 'business_type'}
                selected = data['question'] if data['question'] in actions else actions[-1]
                result = {'action': selected, 'category': None, 'sentiment': None, 'evidence_limit': 3}
                wire['selector_calls'] += 1
            else:
                result = outputs[data['text']]
                wire['classifier_calls'] += 1
            return httpx.Response(200, json={'id': 'reviewer-mock', 'object': 'chat.completion',
                'created': 1, 'model': payload['model'], 'choices': [{'index': 0,
                'message': {'role': 'assistant', 'content': json.dumps(result)}, 'finish_reason': 'stop'}]})
        config = Settings(_env_file=None, app_env='test', development_auth_enabled=False,
            tenant_credentials_json=json.dumps(CREDENTIALS), webhook_integrations_json=json.dumps(INTEGRATIONS),
            groq_api_key=SecretStr('reviewer-fabricated-provider-key'), groq_max_retries=0,
            gmail_oauth_enabled=True, google_oauth_client_id=SecretStr('reviewer-fabricated-client'),
            google_oauth_client_secret=SecretStr('reviewer-fabricated-client-secret'),
            google_oauth_redirect_uri='https://api.example.test/api/v1/integrations/gmail/oauth/callback')
        observed = {}
        google = FakeGoogle()
        from tests.t08_helpers import ACCESS_A, message
        google.messages[ACCESS_A] = {'m1': message(texts[1])}
        with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(500))) as sync:
            async with httpx.AsyncClient(transport=httpx.MockTransport(groq_reply)) as upstream:
                def services():
                    sentiment = create_sentiment_service(config, http_client=sync, http_async_client=upstream)
                    investigation = InvestigationService(create_action_selector(config, http_client=sync,
                        http_async_client=upstream), sentiment)
                    return sentiment, investigation
                sentiment, investigation = services()
                app = create_app(config, sentiment_service=sentiment, investigation_service=investigation,
                                 gmail_transport=httpx.MockTransport(google), batch_store=JobStore(1800), gmail_message_store_factory=MemoryGmailMessageStore, event_store_factory=lambda r: EventStore(r.settings.webhook_max_retained_events, r.settings.webhook_event_ttl_seconds, r))
                (ROOT/'docs/reviewer/openapi.json').write_text(json.dumps(app.openapi(), indent=2)+'\n')
                async with app.router.lifespan_context(app):
                    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://reviewer.local') as client:
                        headers = api_headers()
                        assert (await client.get('/health')).status_code == 200
                        for text, expected in zip(texts, polarities):
                            r = await client.post('/api/v1/sentiment/analyze', headers=headers, json={'text': text})
                            assert r.status_code == 200
                            parsed = SentimentResponse.model_validate(r.json(), context={'feedback_text': text})
                            assert parsed.sentiment == expected
                        observed['A'] = {'status': 'PASSED', 'http_status': 200, 'classifications': polarities,
                            'real_adapter_mock_transport': True, 'native_strict_and_pydantic_evidence': 'PASSED'}
                        feedback = [{'id': str(i+1), 'text': text} for i, text in enumerate(texts)]
                        traces = {}
                        for action in actions:
                            r = await client.post('/api/v1/agent/investigate', headers=headers,
                                json={'question': action, 'feedback': feedback})
                            assert r.status_code == 200
                            parsed = InvestigationResponse.model_validate(r.json())
                            assert parsed.selected_action.action == action
                            assert parsed.sentiment_summary.model_dump() == dict(zip(polarities, [1]*4))
                            if action in {'ISSUE_FREQUENCY', 'GENERAL_FEEDBACK_SUMMARY'}:
                                assert [(i.category, i.count, i.feedback_ids) for i in parsed.top_issues] == [('DELIVERY', 2, ['2','4'])]
                            traces[action] = parsed.tools_used
                        observed['B'] = {'status': 'PASSED', 'routes': traces, 'sentiment_counts': dict(zip(polarities,[1]*4)), 'delivery_complaints': 2}
                        for mode in ['ANALYZE_TEXT', 'INVESTIGATE_FEEDBACK']:
                            body = {'mode': mode, 'message': 'Summarize supplied feedback'}
                            body.update({'feedback_text': texts[0]} if mode == 'ANALYZE_TEXT' else {'feedback': feedback})
                            r = await client.post('/api/v1/chat', headers=headers, json=body)
                            assert r.status_code == 200
                            data = r.json()
                            assert (data['sentiment_analysis'] is not None) == (mode == 'ANALYZE_TEXT')
                            assert (data['investigation'] is not None) == (mode == 'INVESTIGATE_FEEDBACK')
                        observed['C'] = {'status': 'PASSED', 'modes': ['ANALYZE_TEXT','INVESTIGATE_FEEDBACK'], 'http_status': 200}
                        principal = app.state.tenant_registry.authenticate(ALPHA_KEY)
                        batch_ids = []
                        reports = []
                        for extension in ['csv','xlsx']:
                            data = ('id,review\n'+'\n'.join(f'{i+1},{t}' for i,t in enumerate(texts))).encode() if extension == 'csv' else xlsx([['id','review'], *[[str(i+1),t] for i,t in enumerate(texts)]])
                            r = await client.post('/api/v1/batch/upload', headers=headers,
                                data={'text_column':'review','id_column':'id'}, files={'file':('reviewer.'+extension,data,'application/octet-stream')})
                            assert r.status_code == 202
                            job = r.json()['job_id'];batch_ids.append(job)
                            await until(lambda: app.state.batch_service.status(job,principal=principal).status in {'COMPLETED','PARTIAL_SUCCESS','FAILED'}, timeout=10)
                            path = '/api/v1/batch/jobs/'+job
                            assert (await client.get(path,headers=headers)).json()['status'] == 'COMPLETED'
                            report = (await client.get(path+'/report',headers=headers)).json()
                            assert report['successful_records'] == 4 and report['sentiment_percentages'] == dict(zip(polarities,[25]*4))
                            assert report['top_issues'][0]['count'] == 2
                            assert {item['name']: item['count'] for item in report['top_aspects']} == {'delivery':2,'product_quality':2,'package_arrival':1}
                            assert len((await client.get(path+'/results',headers=headers)).json()['results']) == 4
                            assert (await client.get(path+'/download',headers=headers)).status_code == 200
                            reports.append({'format':extension,'status':'COMPLETED','successful_records':4,'percentages':report['sentiment_percentages'],'top_issue_count':2,'aspect_counts':{item['name']:item['count'] for item in report['top_aspects']}})
                        observed['D'] = {'status':'PASSED','reports':reports}
                        # Local MCP owns a separate service instance without REST tenant authority.
                        mcp_sentiment, mcp_investigation = services()
                        server = create_mcp_server(config,sentiment_service=mcp_sentiment,investigation_service=mcp_investigation)
                        async with Client(server, mode='legacy',cache=None) as peer:
                            tools = sorted(t.name for t in (await peer.list_tools()).tools)
                            assert tools == ['analyze_feedback','investigate_feedback']
                            r = await peer.call_tool('analyze_feedback',{'text':texts[0]})
                            assert not r.is_error and r.structured_content['sentiment']=='POSITIVE'
                            r = await peer.call_tool('investigate_feedback',{'question':'ISSUE_FREQUENCY','feedback':feedback})
                            assert not r.is_error and r.structured_content['top_issues'][0]['count']==2
                        observed['E']={'status':'PASSED','tools':tools,'protocol':'official in-process client; subprocess stdio also passed in full suite'}
                        r = await client.post('/api/v1/ingest/feedback',headers=headers,json={'text':texts[1],'channel':'external_api'})
                        assert r.status_code==200 and r.json()['analysis']['sentiment']=='NEGATIVE'
                        observed['F']={'status':'PASSED','http_status':200,'sentiment':'NEGATIVE'}
                        raw=json.dumps({'event_type':'customer.feedback.created','feedback':{'id':'external-1','text':texts[1]}}).encode()
                        signed=webhook_headers(raw,delivery='reviewer-delivery')
                        r=await client.post('/api/v1/webhooks/feedback',headers=signed,content=raw)
                        assert r.status_code==202
                        await app.state.webhook_service.queue.join()
                        r=await client.post('/api/v1/webhooks/feedback',headers=signed,content=raw)
                        assert r.status_code==200 and r.json()['status']=='DUPLICATE'
                        state=await client.get('/api/v1/ingest/events/reviewer-delivery',headers=headers)
                        assert state.json()['status']=='COMPLETED'
                        observed['G']={'status':'PASSED','first_http':202,'retry_http':200,'retry_status':'DUPLICATE','event_status':'COMPLETED'}
                        path='/api/v1/batch/jobs/'+batch_ids[0]
                        foreign=await client.get(path+'/report',headers=api_headers(BETA_KEY))
                        owner=await client.get(path+'/report',headers=headers)
                        assert foreign.status_code==404 and owner.status_code==200
                        observed['H']={'status':'PASSED','foreign_http':404,'owner_http':200}
                        prefix='/api/v1/integrations/gmail'
                        r=await client.post(prefix+'/connect',headers=headers);assert r.status_code==200
                        state=parse_qs(urlsplit(r.json()['authorization_url']).query)['state'][0]
                        r=await client.get(prefix+'/oauth/callback',params={'state':state,'code':'alpha-code'});assert r.status_code==200
                        assert (await client.get(prefix+'/status',headers=headers)).json()['connected'] is True
                        r=await client.post(prefix+'/import',headers=headers,json={'max_messages':1});assert r.status_code==202
                        job=r.json()['job_id']
                        await until(lambda: app.state.gmail_service.job_status(job,principal).status in {'COMPLETED','PARTIAL_SUCCESS','FAILED'},timeout=10)
                        r=await client.get(prefix+'/imports/'+job,headers=headers);assert r.json()['successful_messages']==1
                        rows=(await client.get(prefix+'/imports/'+job+'/results',headers=headers)).json()['results']
                        assert rows[0]['analysis']['sentiment']=='NEGATIVE'
                        assert (await client.get(prefix+'/imports/'+job+'/results',headers=api_headers(BETA_KEY))).status_code==404
                        assert (await client.delete(prefix+'/disconnect',headers=headers)).status_code==200
                        assert (await client.get(prefix+'/status',headers=headers)).json()['connected'] is False
                        observed['I']={'status':'PASSED','oauth':'MOCKED','gmail':'MOCKED','job_status':'COMPLETED','successful_messages':1,'foreign_http':404,'disconnect':'PASSED'}
                observed['provider_wire']=wire
                assert wire['selector_calls']>0 and wire['classifier_calls']>0
        record={'verification':'OFFLINE_ONLY','live_google_requests':0,'live_groq_requests':0,
                'synthetic_classifier_outputs':True,'model_accuracy_measured':False,'workflows':observed}
        (ROOT/'docs/reviewer/workflow-results.json').write_text(json.dumps(record,indent=2)+'\n')
        print('Reviewer workflows A–I: 9 passed; actual ChatGroq strict adapter over mock HTTP; no live providers.')


if __name__=='__main__':
    asyncio.run(verify())
