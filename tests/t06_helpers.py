from app.storage.event_store import EventStore
from app.storage.gmail_message_store import MemoryGmailMessageStore
from app.storage.job_store import JobStore
"""Synthetic integration credentials and local ASGI clients only."""

import hashlib
import hmac
import json
import time
from contextlib import asynccontextmanager

import httpx

from app.main import create_app
from tests.helpers import TEST_KEY, harness, settings

INTEGRATION = "qa-development-integration"
SECRET = "fabricated-webhook-secret-for-offline-tests-only"
PAYLOAD = {"event_type": "customer.feedback.created", "feedback": {"id": "REVIEW-1", "text": "Delivery was late."}}


def raw_event(**overrides):
    return json.dumps(PAYLOAD | overrides, ensure_ascii=False).encode()


def signed(raw, delivery="DELIVERY-1", timestamp=None, integration=INTEGRATION):
    stamp = str(int(time.time()) if timestamp is None else timestamp)
    canonical = f"{integration}.{stamp}.{delivery}.".encode() + raw
    return {
        "X-Feedback-Integration-Id": integration, "X-Feedback-Delivery-Id": delivery,
        "X-Feedback-Timestamp": stamp,
        "X-Feedback-Signature": "sha256=" + hmac.new(SECRET.encode(), canonical, hashlib.sha256).hexdigest(),
        "Content-Type": "application/json",
    }


@asynccontextmanager
async def client_app(*, services=None, **overrides):
    services = services if services is not None else harness()
    config = settings(**({"webhook_integration_id": INTEGRATION, "webhook_shared_secret": SECRET} | overrides))
    app = create_app(config, sentiment_service=services.sentiment, investigation_service=services.investigation, batch_store=JobStore(1800), gmail_message_store_factory=MemoryGmailMessageStore, event_store_factory=lambda r: EventStore(r.settings.webhook_max_retained_events, r.settings.webhook_event_ttl_seconds, r))
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://qa.local") as client:
            yield app, client, services


REST = {"X-API-Key": TEST_KEY}
