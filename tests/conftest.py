from app.storage.event_store import EventStore
from app.storage.gmail_message_store import MemoryGmailMessageStore
from app.storage.job_store import JobStore
"""Offline-by-default fixtures with isolated services and no credential dependence."""

import json
import hashlib
import socket
from pathlib import Path

import httpx
import pytest
import pytest_asyncio

from app.main import create_app
from app.core.config import Settings
from app.core.tenant_auth import TenantRegistry, principal_context
from tests.helpers import TEST_KEY, harness, settings


@pytest.fixture(autouse=True)
def authenticated_service_context(offline):
    """Direct service/store regressions now run with verified development authority.

    HTTP requests replace this context with their own verified credential. Tests
    of missing authority explicitly clear it; production has no default principal.
    """
    registry = TenantRegistry(settings())
    with principal_context(registry.authenticate(TEST_KEY)):
        yield


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    for field in Settings.model_fields:
        monkeypatch.delenv(field.upper(), raising=False)
    for key in ["GROQ_API_KEY", "APP_API_KEY", "LANGCHAIN_API_KEY", "LANGSMITH_API_KEY"]:
        monkeypatch.setenv(key, "")
    monkeypatch.setenv("LANGSMITH_TRACING", "false")

    def deny(*args, **kwargs):
        raise AssertionError("Outbound network access is forbidden in QA tests")

    async def deny_async(*args, **kwargs):
        deny()

    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket.socket, "connect_ex", deny)
    monkeypatch.setattr(socket, "getaddrinfo", deny)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", deny)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", deny_async)


def pytest_make_parametrize_id(config, val, argname):
    if isinstance(val, (str, bytes)) and len(val) > 80:
        raw = val.encode() if isinstance(val, str) else val
        return f"{argname}-len{len(val)}-{hashlib.sha256(raw).hexdigest()[:8]}"
    return None


@pytest.fixture
def services():
    return harness()


@pytest_asyncio.fixture
async def api(services):
    app = create_app(settings(), sentiment_service=services.sentiment,
                     investigation_service=services.investigation, batch_store=JobStore(1800), gmail_message_store_factory=MemoryGmailMessageStore, event_store_factory=lambda r: EventStore(r.settings.webhook_max_retained_events, r.settings.webhook_event_ttl_seconds, r))
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://qa.local",
                                     headers={"X-API-Key": TEST_KEY}) as client:
            yield app, client, services


@pytest.fixture(scope="session")
def measurements():
    rows = []
    yield rows
    root = Path(__file__).resolve().parents[1]
    (root / "docs/qa/benchmark_results.json").write_text(json.dumps(rows, indent=2) + "\n")
