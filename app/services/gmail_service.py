"""Tenant-owned OAuth and explicit bounded Gmail imports over existing T01 logic."""

import asyncio
import base64
import hashlib
import re
import secrets
import time
from collections.abc import Callable
from typing import Any, TypeVar
from urllib.parse import urlencode
from uuid import uuid4

from pydantic import SecretStr
from anyio import CancelScope

from app.core.config import Settings
from app.core.exceptions import ApplicationError, ErrorCode as E
from app.core.tenant_auth import Permission, Principal, TenantRegistry, principal_context
from app.integrations.gmail_mime import extract, preflight
from app.integrations.google_gmail import AUTH_URL, SCOPE, GoogleGmail, identifier, provider_failure
from app.schemas.batch import JobState
from app.schemas.gmail import (
    GmailAccepted, GmailConnect, GmailConnectionStatus, GmailDisconnected,
    GmailImportRequest, GmailJobStatus, GmailResult, GmailResults,
)
from app.schemas.ingestion import IngestionRequest
from app.services.ingestion_service import IngestionService
from app.storage.gmail_store import Connection, GmailJob, GmailStore, OAuthState
from app.storage.gmail_message_store import GmailMessageStore

T = TypeVar('T')

TERMINAL = {JobState.COMPLETED, JobState.PARTIAL_SUCCESS, JobState.FAILED}
SKIPPED = {E.GMAIL_MESSAGE_INVALID, E.GMAIL_MESSAGE_TOO_LARGE, E.GMAIL_ATTACHMENTS_SKIPPED, E.GMAIL_SELECTION_INVALID}
FATAL = {E.GMAIL_RECONNECT_REQUIRED, E.GMAIL_SCOPE_INVALID, E.GMAIL_RATE_LIMITED, E.GMAIL_TIMEOUT,
         E.GMAIL_PROVIDER_ERROR, E.GMAIL_CAPACITY_EXCEEDED, E.GROQ_NOT_CONFIGURED, E.GROQ_MODEL_UNSUPPORTED,
         E.GROQ_CONFIGURATION_ERROR, E.UPSTREAM_AUTHENTICATION_FAILED, E.UPSTREAM_REQUEST_REJECTED}


class GmailService:
    def __init__(self, registry: TenantRegistry, ingestion: IngestionService, google: GoogleGmail, settings: Settings,
                 *, message_store_factory: Callable[[GmailStore], GmailMessageStore]) -> None:
        self.registry, self.ingestion, self.google, self.settings = registry, ingestion, google, settings
        self.store = GmailStore(registry)
        self.messages = message_store_factory(self.store)
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._cleaner: asyncio.Task[None] | None = None
        self._closing = False
        self._callbacks: set[asyncio.Task] = set()
        self._disconnecting: set[str] = set()

    async def _db(self, function: Callable[..., T], *args: Any) -> T:
        if not self.messages.persistent:
            return function(*args)
        task = asyncio.create_task(asyncio.to_thread(function, *args))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            with CancelScope(shield=True):
                await asyncio.gather(task, return_exceptions=True)
            raise

    async def start(self) -> None:
        if self._cleaner is None:
            self._cleaner = asyncio.create_task(self._sweep())

    async def close(self) -> None:
        self._closing = True
        tasks = [*self._tasks.values(), *self._callbacks]
        if self._cleaner is not None:
            tasks.append(self._cleaner)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()
        self._callbacks.clear()
        self._cleaner = None
        self.store._clear()

    async def _sweep(self) -> None:
        while True:
            await asyncio.sleep(max(.01, min(30, self.settings.gmail_import_ttl_seconds / 2,
                                            self.settings.gmail_oauth_state_ttl_seconds / 2,
                                            self.settings.gmail_connection_ttl_seconds / 2)))
            self.store._purge()

    def _ready(self) -> None:
        if self._closing:
            raise ApplicationError(E.GMAIL_UNAVAILABLE)
        if not self.settings.gmail_configured:
            raise ApplicationError(E.GMAIL_NOT_CONFIGURED)
        self.store._purge()

    def _usable(self, connection: Connection) -> bool:
        now = time.monotonic()
        tokens = connection.tokens
        if now >= connection.expires_at or (now >= tokens.expires_at and
            (tokens.refresh is None or (tokens.refresh_expires_at is not None and now >= tokens.refresh_expires_at))):
            connection.invalidate()
        return connection.active and tokens.access is not None

    def connect(self, principal: Principal | None = None) -> GmailConnect:
        owner = self.registry.require(principal, Permission.GMAIL_CONNECT)
        self._ready()
        tenant = owner.tenant_id
        if tenant in self._disconnecting:
            raise ApplicationError(E.GMAIL_CAPACITY_EXCEEDED)
        existing = self.store._connections.get(tenant)
        if existing is not None and self._usable(existing):
            raise ApplicationError(E.GMAIL_ALREADY_CONNECTED)
        if tenant in self.store._flows or len(self.store._flows) >= self.settings.gmail_max_oauth_states:
            raise ApplicationError(E.GMAIL_CAPACITY_EXCEEDED)
        if existing is None and len(self.store._connections) >= self.settings.gmail_max_connections:
            raise ApplicationError(E.GMAIL_CAPACITY_EXCEEDED)
        state = secrets.token_urlsafe(32)
        verifier = secrets.token_urlsafe(64)
        pending = OAuthState(owner, SecretStr(verifier), time.monotonic() + self.settings.gmail_oauth_state_ttl_seconds)
        self.store._states[hashlib.sha256(state.encode()).digest()] = pending
        self.store._flows[tenant] = pending
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
        assert self.settings.google_oauth_client_id is not None
        params = {'client_id': self.settings.google_oauth_client_id.get_secret_value(),
                  'redirect_uri': self.settings.google_oauth_redirect_uri, 'response_type': 'code',
                  'scope': SCOPE, 'state': state, 'code_challenge': challenge, 'code_challenge_method': 'S256',
                  'access_type': 'offline', 'prompt': 'consent', 'include_granted_scopes': 'false'}
        return GmailConnect(authorization_url=AUTH_URL + '?' + urlencode(params),
                            expires_in_seconds=self.settings.gmail_oauth_state_ttl_seconds)

    async def callback(self, state: str | None, code: str | None, error: str | None) -> None:
        self._ready()
        if not isinstance(state, str) or re.fullmatch(r'[A-Za-z0-9_-]{43,128}', state) is None:
            raise ApplicationError(E.GMAIL_INVALID_STATE)
        pending = self.store._states.pop(hashlib.sha256(state.encode()).digest(), None)
        if pending is None or pending.cancelled or pending.consumed or pending.expires_at <= time.monotonic():
            if pending is not None:
                pending.verifier = None
                if self.store._flows.get(pending.owner.tenant_id) is pending:
                    self.store._flows.pop(pending.owner.tenant_id, None)
            raise ApplicationError(E.GMAIL_INVALID_STATE)
        pending.consumed = True  # Atomic consume before any provider await.
        callback_task = asyncio.current_task()
        if callback_task is not None:
            self._callbacks.add(callback_task)
        bundle = None
        try:
            owner = self.registry.require(pending.owner, Permission.GMAIL_CONNECT)
            if error is not None:
                raise ApplicationError(E.GMAIL_OAUTH_DENIED)
            if not isinstance(code, str) or not 1 <= len(code) <= 2048 or any(ord(c) < 33 or ord(c) > 126 for c in code):
                raise ApplicationError(E.GMAIL_OAUTH_FAILED)
            if pending.verifier is None:
                raise ApplicationError(E.GMAIL_INVALID_STATE)
            async with asyncio.timeout(2 * self.settings.gmail_http_timeout_seconds + 1):
                bundle = await self.google.exchange(code, pending.verifier)
                pending.verifier = None
                assert bundle.access is not None
                mailbox = await self.google.profile(bundle.access)
            if pending.cancelled or self.store._flows.get(owner.tenant_id) is not pending or self._closing or owner.tenant_id in self._disconnecting:
                raise ApplicationError(E.GMAIL_INVALID_STATE)
            other = self.store._mailboxes.get(mailbox)
            old = self.store._connections.get(owner.tenant_id)
            if (other is not None and other != owner.tenant_id) or (old is not None and old.mailbox != mailbox):
                raise ApplicationError(E.GMAIL_MAILBOX_CONFLICT)
            if old is None and len(self.store._connections) >= self.settings.gmail_max_connections:
                raise ApplicationError(E.GMAIL_CAPACITY_EXCEEDED)
            if any(j.owner.tenant_id == owner.tenant_id and j.status not in TERMINAL for j in self.store._jobs.values()):
                raise ApplicationError(E.GMAIL_CAPACITY_EXCEEDED)
            if old is not None:
                old.invalidate()
            self.store._connections[owner.tenant_id] = Connection(owner.tenant_id, mailbox, uuid4().hex,
                bundle, time.monotonic() + self.settings.gmail_connection_ttl_seconds)
            self.store._mailboxes[mailbox] = owner.tenant_id
            bundle = None  # Ownership transferred to the private connection store.
        except asyncio.CancelledError:
            pending.cancelled = True
            raise
        except TimeoutError:
            raise ApplicationError(E.GMAIL_TIMEOUT) from None
        except ApplicationError:
            raise
        except Exception:
            raise ApplicationError(E.GMAIL_OAUTH_FAILED) from None
        finally:
            if callback_task is not None:
                self._callbacks.discard(callback_task)
            if bundle is not None:
                bundle.clear()
            pending.verifier = None
            if self.store._flows.get(pending.owner.tenant_id) is pending:
                self.store._flows.pop(pending.owner.tenant_id, None)

    def status(self, principal: Principal | None = None) -> GmailConnectionStatus:
        owner = self.registry.require(principal, Permission.GMAIL_READ)
        self._ready()
        connection = self.store._connections.get(owner.tenant_id)
        if connection is None:
            return GmailConnectionStatus(connected=False, connection_status='DISCONNECTED')
        connected = self._usable(connection)
        return GmailConnectionStatus(connected=connected, mailbox=connection.mailbox,
                                     connection_status='CONNECTED' if connected else 'RECONNECT_REQUIRED')

    async def disconnect(self, principal: Principal | None = None) -> GmailDisconnected:
        owner = self.registry.require(principal, Permission.GMAIL_CONNECT)
        self._ready()
        if owner.tenant_id in self._disconnecting:
            raise ApplicationError(E.GMAIL_CAPACITY_EXCEEDED)
        self._disconnecting.add(owner.tenant_id)
        try:
            return await self._disconnect(owner)
        finally:
            self._disconnecting.discard(owner.tenant_id)

    async def _disconnect(self, owner: Principal) -> GmailDisconnected:
        pending = self.store._flows.get(owner.tenant_id)
        if pending is not None:
            pending.cancelled = True
            pending.verifier = None
            for key, value in list(self.store._states.items()):
                if value is pending:
                    del self.store._states[key]
            if not pending.consumed:
                self.store._flows.pop(owner.tenant_id, None)
        connection = self.store._connections.pop(owner.tenant_id, None)
        if connection is not None:
            connection.invalidate()
            self.store._mailboxes.pop(connection.mailbox, None)
        tasks = [task for key, task in self._tasks.items()
                 if (job := self.store._jobs.get(key)) is not None and job.owner.tenant_id == owner.tenant_id]
        for task in tasks:
            task.cancel()
        try:
            await asyncio.gather(*tasks, return_exceptions=True)
        finally:
            for key, job in list(self.store._jobs.items()):
                if job.owner.tenant_id == owner.tenant_id:
                    job.results.clear()
                    del self.store._jobs[key]
        return GmailDisconnected()

    def _live(self, connection: Connection) -> None:
        if self.store._connections.get(connection.tenant_id) is not connection or not self._usable(connection):
            raise ApplicationError(E.GMAIL_RECONNECT_REQUIRED)

    async def _access(self, connection: Connection) -> SecretStr:
        self._live(connection)
        if time.monotonic() >= connection.tokens.expires_at:
            async with connection.lock:
                self._live(connection)
                if time.monotonic() >= connection.tokens.expires_at:
                    try:
                        refreshed = await self.google.refresh(connection.tokens)
                    except ApplicationError as error:
                        if error.code in {E.GMAIL_RECONNECT_REQUIRED, E.GMAIL_SCOPE_INVALID, E.GMAIL_RESPONSE_INVALID}:
                            connection.invalidate()
                        raise
                    try:
                        self._live(connection)
                    except ApplicationError:
                        refreshed.clear()
                        raise
                    connection.tokens.clear()
                    connection.tokens = refreshed
        assert connection.tokens.access is not None
        return connection.tokens.access

    def submit(self, request: GmailImportRequest, principal: Principal | None = None) -> GmailAccepted:
        owner = self.registry.require(principal, Permission.GMAIL_IMPORT)
        self._ready()
        if not self.messages.available:
            raise ApplicationError(E.GMAIL_UNAVAILABLE)
        if owner.tenant_id in self._disconnecting:
            raise ApplicationError(E.GMAIL_CAPACITY_EXCEEDED)
        request = GmailImportRequest.model_validate(request.model_dump(exclude_unset=True))
        maximum = request.max_messages if 'max_messages' in request.model_fields_set else self.settings.gmail_max_messages_per_import
        if maximum > self.settings.gmail_max_messages_per_import:
            raise ApplicationError(E.VALIDATION_ERROR)
        connection = self.store._connections.get(owner.tenant_id)
        if connection is None:
            raise ApplicationError(E.GMAIL_NOT_CONNECTED)
        self._live(connection)
        if self.ingestion.sentiment.configuration_error is not None:
            raise ApplicationError(self.ingestion.sentiment.configuration_error)
        jobs = list(self.store._jobs.values())
        active = [job for job in jobs if job.status not in TERMINAL]
        owned = [job for job in jobs if job.owner.tenant_id == owner.tenant_id]
        tenant_active = min(self.settings.gmail_tenant_max_concurrent_imports, self.settings.gmail_max_concurrent_imports - 1)
        if (len(active) >= self.settings.gmail_max_concurrent_imports or len(jobs) >= self.settings.gmail_max_retained_imports
            or sum(job.status not in TERMINAL for job in owned) >= tenant_active
            or len(owned) >= min(self.settings.gmail_tenant_max_retained_imports, self.settings.gmail_max_retained_imports - 1)):
            raise ApplicationError(E.GMAIL_CAPACITY_EXCEEDED)
        job = GmailJob(uuid4().hex, owner, connection.mailbox, connection.version, maximum)
        self.store._jobs[job.job_id] = job
        task = asyncio.create_task(self._run(job, connection))
        self._tasks[job.job_id] = task
        task.add_done_callback(lambda done: self._tasks.pop(job.job_id, None))
        return GmailAccepted(job_id=job.job_id)

    def job_status(self, job_id: str, principal: Principal | None = None) -> GmailJobStatus:
        principal = self.registry.require(principal, Permission.GMAIL_READ)
        self._ready()
        return self.store.job(job_id, principal).snapshot()

    def results(self, job_id: str, principal: Principal | None = None) -> GmailResults:
        principal = self.registry.require(principal, Permission.GMAIL_READ)
        self._ready()
        job = self.store.job(job_id, principal)
        return GmailResults(job_id=job.job_id, status=job.status, results=[row.model_copy(deep=True) for row in job.results])

    async def _select(self, connection: Connection, job: GmailJob) -> tuple[str, list[str]]:
        label = await self.google.label(await self._access(connection))
        ids: list[str] = []
        seen_ids: set[str] = set()
        seen_pages: set[str] = set()
        page = None
        # Metadata scan size is independent of the requested NEW-message count.
        # At most server_max_messages * max_list_pages IDs enter memory per job.
        page_size = self.settings.gmail_max_messages_per_import
        for index in range(self.settings.gmail_max_list_pages):
            data = await self.google.list_page(await self._access(connection), label, page_size, page)
            rows = data.get('messages', [])
            if not isinstance(rows, list) or len(rows) > page_size:
                raise provider_failure('messages.list', 'message_list', status=200)
            job.scanned += len(rows)
            candidates = []
            for row in rows:
                if not isinstance(row, dict):
                    raise provider_failure('messages.list', 'message_row', status=200)
                try:
                    mid = identifier(row.get('id'))
                except ApplicationError:
                    raise provider_failure('messages.list', 'message_id', status=200) from None
                if mid not in seen_ids:
                    seen_ids.add(mid); candidates.append(mid)
            next_page = data.get('nextPageToken')
            if next_page is not None:
                if not isinstance(next_page, str) or not 1 <= len(next_page) <= 2048 or next_page in seen_pages:
                    raise provider_failure('messages.list', 'page_token', status=200)
                seen_pages.add(next_page)
            if candidates:
                completed = await self._db(self.messages.completed_ids, job, connection, candidates)
                job.previously_processed += len(completed)
                candidates = [mid for mid in candidates if mid not in completed]
                offset = 0
                # Check only enough new candidates to fill the remaining slots.
                # Busy claims may lose an admission race, so continue through the
                # page tail before requesting another bounded listing page.
                while offset < len(candidates) and len(ids) < job.maximum:
                    eligible = []
                    while offset < len(candidates) and len(eligible) < job.maximum - len(ids):
                        mid = candidates[offset]; offset += 1
                        labels = await self.google.message_labels(await self._access(connection), mid)
                        if 'SENT' not in labels:
                            eligible.append(mid)
                    if eligible:
                        result = await self._db(self.messages.claim_page, job, connection, eligible, job.maximum-len(ids))
                        job.claims.update(result.claims); ids.extend(result.claims)
                        job.previously_processed += result.completed; job.deferred += result.deferred
                        if result.capacity_limited:
                            job.capacity_limit_reached = True
                            break
                if job.capacity_limit_reached:
                    break
            if len(ids) == job.maximum:
                break
            if next_page is None:
                job.scan_exhausted = True
                break
            if index + 1 == self.settings.gmail_max_list_pages:
                job.scan_limit_reached = True
            page = next_page
        return label, ids

    async def _message(self, job: GmailJob, connection: Connection, label: str, mid: str) -> GmailResult:
        message: dict = {}
        feedback = None
        try:
            message = await self.google.message(await self._access(connection), mid, body=False)
            if message.get('id') != mid:
                raise provider_failure('messages.get', 'message_identity', status=200)
            preflight(message, label, self.settings.gmail_max_message_body_bytes)
            message.clear()
            message = await self.google.message(await self._access(connection), mid, body=True)
            if message.get('id') != mid:
                raise provider_failure('messages.get', 'message_identity', status=200)
            feedback = extract(message, label, self.settings.gmail_max_message_body_bytes)
            thread_id = identifier(message['threadId']) if 'threadId' in message else None
            self._live(connection)
            response = await self.ingestion.analyze(IngestionRequest(text=feedback.text,
                channel='external_api', source='email', business_type=self.settings.gmail_business_type))
            self._live(connection)
            return GmailResult(message_id=mid, thread_id=thread_id, status='SUCCESS', analysis=response.analysis)
        finally:
            message.clear()
            feedback = None

    async def _run(self, job: GmailJob, connection: Connection) -> None:
        job.status = JobState.RUNNING
        ids: list[str] = []
        try:
            with principal_context(job.owner):
                async with asyncio.timeout(self.settings.gmail_import_timeout_seconds):
                    label, ids = await self._select(connection, job)
                    job.selected = len(ids)
                    if job.capacity_limit_reached:
                        job.error_code = E.GMAIL_CAPACITY_EXCEEDED
                    for mid in ids:
                        self._live(connection)
                        token = job.claims[mid]
                        if not await self._db(self.messages.begin, job, connection, mid, token):
                            job.results.append(GmailResult(message_id=mid, status='DUPLICATE'))
                            continue
                        try:
                            row = await self._message(job, connection, label, mid)
                            if not await self._db(self.messages.finish, job, connection, mid, token, None):
                                raise ApplicationError(E.GMAIL_UNAVAILABLE)
                        except ApplicationError as error:
                            await self._db(self.messages.finish, job, connection, mid, token, error.code)
                            if error.code in FATAL or error.code == E.GMAIL_UNAVAILABLE:
                                raise
                            row = GmailResult(message_id=mid, status='SKIPPED' if error.code in SKIPPED else 'FAILED', error_code=error.code)
                        job.results.append(row)
        except asyncio.CancelledError:
            job.error_code = E.GMAIL_DISCONNECTED if not connection.active else E.GMAIL_UNAVAILABLE
            raise
        except TimeoutError:
            job.error_code = E.GMAIL_TIMEOUT
        except ApplicationError as error:
            job.error_code = error.code
            if error.code in {E.GMAIL_RECONNECT_REQUIRED, E.GMAIL_SCOPE_INVALID}:
                connection.invalidate()
        except Exception:
            job.error_code = E.INTERNAL_ERROR
        finally:
            # Await DB work even under ASGI/worker cancellation. Release only this
            # job's still-owned claims; successful ledger entries remain intact.
            with CancelScope(shield=True):
                try:
                    await self._db(self.messages.release_job, job, connection, job.error_code or E.GMAIL_UNAVAILABLE)
                except ApplicationError:
                    job.error_code = E.GMAIL_UNAVAILABLE
            job.claims.clear()
            if job.error_code is not None:
                for mid in ids[len(job.results):]:
                    job.results.append(GmailResult(message_id=mid, status='FAILED', error_code=job.error_code))
            successes = sum(row.status == 'SUCCESS' for row in job.results)
            failures = any(row.status in {'FAILED', 'SKIPPED'} for row in job.results)
            job.status = (JobState.PARTIAL_SUCCESS if successes and (failures or job.error_code) else
                          JobState.FAILED if failures or job.error_code else JobState.COMPLETED)
            job.expires_at = time.monotonic() + self.settings.gmail_import_ttl_seconds
