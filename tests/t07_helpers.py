from app.storage.event_store import EventStore
from app.storage.gmail_message_store import MemoryGmailMessageStore
from app.storage.job_store import JobStore
"""Fabricated tenant credentials for offline security tests, never provider keys."""

import hashlib
import hmac
import json
import time
from contextlib import asynccontextmanager

import httpx

from app.main import create_app
from tests.helpers import harness, settings

ALPHA_KEY = 'qa_ALPHA_private_random_example_0123456789_ABCDEFGHIJKLMNOPQRSTUVWXYZ'
ALPHA_ROTATED_KEY = 'qa_ALPHA_rotated_random_example_9876543210_ZYXWVUTSRQPONMLKJIHGFEDCBA'
BETA_KEY = 'qa_BETA_private_random_example_0123456789_ABCDEFGHIJKLMNOPQRSTUVWXYZ'
ALPHA_SECRET = 'qa_ALPHA_webhook_secret_example_0123456789_ABCDEFGHIJKLMNOPQRSTUVWXYZ'
ALPHA_SECOND_SECRET = 'qa_ALPHA_second_webhook_example_0123456789_ABCDEFGHIJKLMNOPQRSTUVWXYZ'
BETA_SECRET = 'qa_BETA_webhook_secret_example_0123456789_ABCDEFGHIJKLMNOPQRSTUVWXYZ'
CREDENTIALS = [
    {'tenant_id': 'business_alpha', 'key_id': 'alpha_key', 'api_key': ALPHA_KEY},
    {'tenant_id': 'business_beta', 'key_id': 'beta_key', 'api_key': BETA_KEY},
]
INTEGRATIONS = [
    {'tenant_id': 'business_alpha', 'integration_id': 'alpha-integration', 'shared_secret': ALPHA_SECRET},
    {'tenant_id': 'business_alpha', 'integration_id': 'alpha-second', 'shared_secret': ALPHA_SECOND_SECRET},
    {'tenant_id': 'business_beta', 'integration_id': 'beta-integration', 'shared_secret': BETA_SECRET},
]


def multi_settings(*, credentials=None, integrations=None, **overrides):
    values = {
        'app_env': 'production', 'development_auth_enabled': False,
        'tenant_credentials_json': json.dumps(CREDENTIALS if credentials is None else credentials),
        'webhook_integrations_json': json.dumps(INTEGRATIONS if integrations is None else integrations),
    } | overrides
    return settings(**values)


def api_headers(key=ALPHA_KEY):
    return {'X-API-Key': key}


def webhook_headers(raw, delivery='same-delivery', integration='alpha-integration', secret=ALPHA_SECRET):
    stamp = str(int(time.time()))
    canonical = f'{integration}.{stamp}.{delivery}.'.encode() + raw
    return {
        'X-Feedback-Integration-Id': integration, 'X-Feedback-Delivery-Id': delivery,
        'X-Feedback-Timestamp': stamp,
        'X-Feedback-Signature': 'sha256=' + hmac.new(secret.encode(), canonical, hashlib.sha256).hexdigest(),
        'Content-Type': 'application/json',
    }


@asynccontextmanager
async def multi_app(*, services=None, config=None, **overrides):
    services = harness() if services is None else services
    config = multi_settings(**overrides) if config is None else config
    app = create_app(config, sentiment_service=services.sentiment, investigation_service=services.investigation, batch_store=JobStore(1800), gmail_message_store_factory=MemoryGmailMessageStore, event_store_factory=lambda r: EventStore(r.settings.webhook_max_retained_events, r.settings.webhook_event_ttl_seconds, r))
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://qa.local') as client:
            yield app, client, services
