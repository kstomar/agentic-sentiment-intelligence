"""Bound authenticated intake before parsing; replay original bytes without transformation."""

import asyncio
import time
from collections import deque
from uuid import uuid4

from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config import Settings
from app.core.exceptions import ERROR_MESSAGES, ApplicationError, ErrorCode
from app.core.tenant_auth import Permission, Principal, TenantRegistry, principal_context
from app.core.webhook_security import authenticate_webhook, signed_headers
from app.schemas.errors import ErrorDetail, ErrorResponse

JSON_PATHS = {
    "/api/v1/sentiment/analyze", "/api/v1/agent/investigate", "/api/v1/chat",
    "/api/v1/ingest/feedback",
}
WEBHOOK_PATH = "/api/v1/webhooks/feedback"
UPLOAD_PATH = "/api/v1/batch/upload"
GMAIL_PREFIX = "/api/v1/integrations/gmail/"
GMAIL_CALLBACK = GMAIL_PREFIX + "oauth/callback"
INGRESS_STATUS = {
    ErrorCode.AUTHENTICATION_FAILED: 401, ErrorCode.APP_AUTH_NOT_CONFIGURED: 503,
    ErrorCode.WEBHOOK_NOT_CONFIGURED: 503, ErrorCode.WEBHOOK_AUTHENTICATION_FAILED: 401,
    ErrorCode.REQUEST_TOO_LARGE: 413, ErrorCode.BATCH_FILE_TOO_LARGE: 413,
    ErrorCode.REQUEST_BODY_TIMEOUT: 408, ErrorCode.INGRESS_CAPACITY_EXCEEDED: 429,
    ErrorCode.INGRESS_RATE_LIMITED: 429,
    ErrorCode.AUTHORIZATION_FAILED: 403, ErrorCode.TENANT_CAPACITY_EXCEEDED: 429,
}


class IngressLimitMiddleware:
    """Single-loop global admission, bounded rolling rate window, and bounded body buffers."""

    def __init__(self, app: ASGIApp, settings: Settings, registry: TenantRegistry | None = None) -> None:
        self.app = app
        self.settings = settings
        self.active = 0
        self.uploads = 0
        self.arrivals: deque[float] = deque()
        self.registry = registry if registry is not None else TenantRegistry(settings)
        self.tenant_active: dict[str, int] = {}
        self.tenant_uploads: dict[str, int] = {}
        self.tenant_arrivals: dict[str, deque[float]] = {}

    def _admit_tenant(self, principal: Principal, *, upload: bool) -> None:
        principal = self.registry.require(principal)
        owner = principal.tenant_id
        if not self.registry.tenant_limits_enabled:
            self.tenant_active[owner] = self.tenant_active.get(owner, 0) + 1
            if upload:
                self.tenant_uploads[owner] = self.tenant_uploads.get(owner, 0) + 1
            return
        if self.tenant_active.get(owner, 0) >= self.registry.limit(self.settings.tenant_max_concurrent_requests, self.settings.ingress_max_concurrent_requests):
            raise ApplicationError(ErrorCode.TENANT_CAPACITY_EXCEEDED)
        if upload and self.tenant_uploads.get(owner, 0) >= self.registry.limit(self.settings.tenant_max_active_batch_jobs, self.settings.batch_max_active_jobs):
            raise ApplicationError(ErrorCode.TENANT_CAPACITY_EXCEEDED)
        now = time.monotonic()
        for tenant, arrivals in list(self.tenant_arrivals.items()):
            while arrivals and arrivals[0] <= now - 60:
                arrivals.popleft()
            if not arrivals:
                del self.tenant_arrivals[tenant]
        arrivals = self.tenant_arrivals.get(owner, deque())
        if len(arrivals) >= self.registry.limit(self.settings.tenant_requests_per_minute, self.settings.ingress_requests_per_minute):
            raise ApplicationError(ErrorCode.TENANT_CAPACITY_EXCEEDED)
        arrivals.append(now)
        self.tenant_arrivals[owner] = arrivals
        self.tenant_active[owner] = self.tenant_active.get(owner, 0) + 1
        if upload:
            self.tenant_uploads[owner] = self.tenant_uploads.get(owner, 0) + 1

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = scope.get("path", "").rstrip("/")
        protected = path in JSON_PATHS or path == WEBHOOK_PATH or path.startswith("/api/v1/batch/") or path.startswith("/api/v1/ingest/events/") or path.startswith(GMAIL_PREFIX)
        if scope["type"] != "http" or not protected:
            await self.app(scope, receive, send)
            return
        admitted = False
        tenant_admitted = False
        principal: Principal | None = None
        upload = path == UPLOAD_PATH and scope["method"] == "POST"
        try:
            headers = Headers(scope=scope)
            if path == WEBHOOK_PATH:
                signed_headers(self.settings, headers, registry=self.registry)
            elif path == GMAIL_CALLBACK:
                if len(scope.get("query_string", b"")) > 8192:
                    raise ApplicationError(ErrorCode.REQUEST_TOO_LARGE)
            else:
                keys = headers.getlist("x-api-key")
                principal = self.registry.authenticate(keys[0] if len(keys) == 1 else None)
                permission = (
                    (Permission.GMAIL_CONNECT if path.endswith(("/connect", "/disconnect")) else
                     Permission.GMAIL_IMPORT if path.endswith("/import") else Permission.GMAIL_READ)
                    if path.startswith(GMAIL_PREFIX) else
                    Permission.ANALYZE if path == "/api/v1/sentiment/analyze" else
                    Permission.INVESTIGATE if path == "/api/v1/agent/investigate" else
                    Permission.CHAT if path == "/api/v1/chat" else
                    Permission.INGEST if path == "/api/v1/ingest/feedback" else
                    Permission.BATCH_CREATE if upload else
                    Permission.BATCH_READ if path.startswith("/api/v1/batch/") else Permission.EVENT_READ
                )
                self.registry.require(principal, permission)
                self._admit_tenant(principal, upload=upload)
                tenant_admitted = True
            if self.active >= self.settings.ingress_max_concurrent_requests or (upload and self.uploads >= self.settings.batch_max_active_jobs):
                raise ApplicationError(ErrorCode.INGRESS_CAPACITY_EXCEEDED)
            now = time.monotonic()
            while self.arrivals and self.arrivals[0] <= now - 60:
                self.arrivals.popleft()
            if len(self.arrivals) >= self.settings.ingress_requests_per_minute:
                raise ApplicationError(ErrorCode.INGRESS_RATE_LIMITED)
            self.arrivals.append(now)
            self.active += 1
            self.uploads += int(upload)
            admitted = True
            if scope["method"] == "POST":
                limit = (self.settings.batch_max_upload_bytes + 64 * 1024 if upload else
                         self.settings.webhook_max_body_bytes if path == WEBHOOK_PATH else self.settings.json_max_body_bytes)
                too_large = ErrorCode.BATCH_FILE_TOO_LARGE if upload else ErrorCode.REQUEST_TOO_LARGE
                lengths = headers.getlist("content-length")
                if lengths:
                    try:
                        declared = int(lengths[0]) if len(lengths) == 1 else -1
                    except ValueError:
                        declared = -1
                    if declared < 0 or declared > limit:
                        raise ApplicationError(too_large)
                buffer = bytearray()
                size = 0
                try:
                    async with asyncio.timeout(self.settings.ingress_body_timeout_seconds):
                        while True:
                            message = await receive()
                            if message["type"] == "http.disconnect":
                                return
                            chunk = message.get("body", b"")
                            size += len(chunk)
                            if size > limit:
                                raise ApplicationError(too_large)
                            buffer.extend(chunk)
                            if not message.get("more_body", False):
                                break
                except TimeoutError:
                    raise ApplicationError(ErrorCode.REQUEST_BODY_TIMEOUT) from None
                body = bytes(buffer)
                buffer.clear()
                if path == WEBHOOK_PATH:
                    identity = authenticate_webhook(self.settings, headers, body, registry=self.registry)
                    principal = self.registry.require(identity.principal, Permission.INGEST)
                    self._admit_tenant(principal, upload=False)
                    tenant_admitted = True
                delivered = False

                async def replay() -> Message:
                    nonlocal delivered
                    if not delivered:
                        delivered = True
                        return {"type": "http.request", "body": body, "more_body": False}
                    return await receive()

                scope.setdefault("state", {})["principal"] = principal
                with principal_context(principal):
                    await self.app(scope, replay, send)
            else:
                scope.setdefault("state", {})["principal"] = principal
                with principal_context(principal):
                    await self.app(scope, receive, send)
        except ApplicationError as error:
            request_id = scope.get("state", {}).get("request_id", uuid4().hex)
            status = INGRESS_STATUS.get(error.code)
            if status is None:
                raise
            payload = ErrorResponse(error=ErrorDetail(code=error.code, message=ERROR_MESSAGES[error.code]), request_id=request_id)
            response_headers = {"Connection": "close", "Cache-Control": "no-store"}
            if status == 401:
                response_headers["WWW-Authenticate"] = "HMAC" if path == WEBHOOK_PATH else "APIKey"
            await JSONResponse(payload.model_dump(mode="json", exclude_none=True), status_code=status, headers=response_headers)(scope, receive, send)
        finally:
            if tenant_admitted and principal is not None:
                owner = principal.tenant_id
                self.tenant_active[owner] -= 1
                if not self.tenant_active[owner]:
                    del self.tenant_active[owner]
                if upload:
                    self.tenant_uploads[owner] -= 1
                    if not self.tenant_uploads[owner]:
                        del self.tenant_uploads[owner]
            if admitted:
                self.active -= 1
                self.uploads -= int(upload)
