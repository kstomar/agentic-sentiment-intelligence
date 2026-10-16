"""FastAPI composition, resource lifecycle, and safe HTTP error translation."""

import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from uuid import uuid4

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from app.api.v1.sentiment import router as sentiment_router
from app.api.v1.investigation import router as investigation_router
from app.api.v1.chat import router as chat_router
from app.api.v1.batch import router as batch_router
from app.agents.action_selector import create_action_selector
from app.core.config import Settings
from app.core.ingress_limits import IngressLimitMiddleware
from app.core.processing_limits import InvestigationAdmission, ModelAdmission
from app.core.tenant_auth import TenantRegistry
from app.api.v1.ingestion import router as ingestion_router
from app.api.v1.webhooks import router as webhook_router
from app.services.ingestion_service import IngestionService
from app.services.webhook_service import WebhookService
from app.core.exceptions import ERROR_MESSAGES, ApplicationError, ErrorCode
from app.schemas.errors import ErrorDetail, ErrorResponse, HealthResponse, ValidationIssue
from app.schemas.chat import CHAT_VALIDATION_MESSAGES
from app.services.sentiment_service import SentimentService, create_sentiment_service
from app.services.investigation_service import InvestigationService
from app.services.batch_service import BatchService
from app.storage.job_store import JobStore
from app.storage.postgres_job_store import PostgresJobStore
from app.storage.event_store import EventStore
from app.storage.postgres_event_store import PostgresEventStore
from app.api.v1.gmail import router as gmail_router
from app.integrations.google_gmail import GoogleGmail
from app.services.gmail_service import GmailService
from app.storage.gmail_store import GmailStore
from app.storage.gmail_message_store import GmailMessageStore
from app.storage.postgres_gmail_message_store import PostgresGmailMessageStore

logger = logging.getLogger("app")

ERROR_STATUS = {
    **{code: 502 for code in [ErrorCode.GMAIL_OAUTH_FAILED, ErrorCode.GMAIL_PROVIDER_ERROR, ErrorCode.GMAIL_RESPONSE_INVALID]},
    **{code: 400 for code in [ErrorCode.GMAIL_INVALID_STATE, ErrorCode.GMAIL_OAUTH_DENIED, ErrorCode.GMAIL_SCOPE_INVALID]},
    **{code: 409 for code in [ErrorCode.GMAIL_MAILBOX_CONFLICT, ErrorCode.GMAIL_ALREADY_CONNECTED,
                             ErrorCode.GMAIL_NOT_CONNECTED, ErrorCode.GMAIL_RECONNECT_REQUIRED]},
    ErrorCode.GMAIL_NOT_CONFIGURED: 503,
    ErrorCode.GMAIL_UNAVAILABLE: 503,
    ErrorCode.GMAIL_CAPACITY_EXCEEDED: 429,
    ErrorCode.GMAIL_RATE_LIMITED: 429,
    ErrorCode.GMAIL_TIMEOUT: 504,
    ErrorCode.GMAIL_SELECTION_INVALID: 422,
    ErrorCode.GMAIL_MESSAGE_INVALID: 422,
    ErrorCode.GMAIL_MESSAGE_TOO_LARGE: 413,
    ErrorCode.GMAIL_ATTACHMENTS_SKIPPED: 422,
    ErrorCode.GMAIL_JOB_NOT_FOUND: 404,
    ErrorCode.GMAIL_DISCONNECTED: 409,
    ErrorCode.AUTHORIZATION_FAILED: 403,
    ErrorCode.TENANT_CAPACITY_EXCEEDED: 429,
    ErrorCode.WEBHOOK_DELIVERY_COLLISION: 409,
    ErrorCode.AUTHENTICATION_FAILED: 401,
    ErrorCode.APP_AUTH_NOT_CONFIGURED: 503,
    ErrorCode.GROQ_NOT_CONFIGURED: 503,
    ErrorCode.GROQ_MODEL_UNSUPPORTED: 503,
    ErrorCode.GROQ_CONFIGURATION_ERROR: 503,
    ErrorCode.UPSTREAM_AUTHENTICATION_FAILED: 502,
    ErrorCode.UPSTREAM_RATE_LIMITED: 429,
    ErrorCode.UPSTREAM_TIMEOUT: 504,
    ErrorCode.UPSTREAM_UNAVAILABLE: 502,
    ErrorCode.UPSTREAM_REQUEST_REJECTED: 502,
    ErrorCode.INVALID_MODEL_RESPONSE: 502,
    ErrorCode.INVALID_ACTION_SELECTION: 502,
    ErrorCode.INVALID_GRAPH_STATE: 500,
    ErrorCode.EVIDENCE_VERIFICATION_FAILED: 502,
    ErrorCode.INVESTIGATION_TIMEOUT: 504,
    ErrorCode.VALIDATION_ERROR: 422,
    ErrorCode.INTERNAL_ERROR: 500,
    ErrorCode.BATCH_FILE_TOO_LARGE: 413,
    ErrorCode.BATCH_UNSUPPORTED_FORMAT: 415,
    ErrorCode.BATCH_INVALID_ENCODING: 422,
    ErrorCode.BATCH_INVALID_FILE: 422,
    ErrorCode.BATCH_INVALID_COLUMNS: 422,
    ErrorCode.BATCH_INVALID_IDS: 422,
    ErrorCode.BATCH_INVALID_TEXT: 422,
    ErrorCode.BATCH_EXTRACTION_LIMIT: 422,
    ErrorCode.BATCH_TOO_MANY_RECORDS: 422,
    ErrorCode.BATCH_NO_VALID_RECORDS: 422,
    ErrorCode.BATCH_CAPACITY_EXCEEDED: 429,
    ErrorCode.BATCH_JOB_NOT_FOUND: 404,
    ErrorCode.BATCH_JOB_TIMEOUT: 504,
    ErrorCode.BATCH_UNAVAILABLE: 503,
    ErrorCode.BATCH_REPORT_UNAVAILABLE: 500,
    ErrorCode.REQUEST_TOO_LARGE: 413,
    ErrorCode.REQUEST_BODY_TIMEOUT: 408,
    ErrorCode.INGRESS_CAPACITY_EXCEEDED: 429,
    ErrorCode.INGRESS_RATE_LIMITED: 429,
    ErrorCode.PROCESSING_CAPACITY_EXCEEDED: 429,
    ErrorCode.WEBHOOK_NOT_CONFIGURED: 503,
    ErrorCode.WEBHOOK_AUTHENTICATION_FAILED: 401,
    ErrorCode.WEBHOOK_DELIVERY_CONFLICT: 409,
    ErrorCode.WEBHOOK_CAPACITY_EXCEEDED: 429,
    ErrorCode.WEBHOOK_EVENT_NOT_FOUND: 404,
    ErrorCode.WEBHOOK_PROCESSING_TIMEOUT: 504,
    ErrorCode.WEBHOOK_UNAVAILABLE: 503,
}


def error_response(
    request: Request,
    code: ErrorCode,
    status_code: int,
    *,
    details: list[ValidationIssue] | None = None,
) -> JSONResponse:
    request_id = request.state.request_id
    logger.warning("request_rejected code=%s request_id=%s", code, request_id)
    payload = ErrorResponse(
        error=ErrorDetail(code=code, message=ERROR_MESSAGES[code], details=details),
        request_id=request_id,
    )
    return JSONResponse(
        status_code=status_code,
        content=payload.model_dump(mode="json", exclude_none=True),
        headers={"WWW-Authenticate": "HMAC" if code == ErrorCode.WEBHOOK_AUTHENTICATION_FAILED else "APIKey"} if status_code == 401 else None,
    )


def create_app(
    settings: Settings | None = None,
    *,
    sentiment_service: SentimentService | None = None,
    investigation_service: InvestigationService | None = None,
    gmail_transport: httpx.AsyncBaseTransport | None = None,
    batch_store: JobStore | None = None,
    event_store_factory: Callable[[TenantRegistry], EventStore] | None = None,
    gmail_message_store_factory: Callable[[GmailStore], GmailMessageStore] | None = None,
) -> FastAPI:
    """Create an independent app with injectable settings and a shared service."""
    settings = settings if settings is not None else Settings()
    registry = TenantRegistry(settings)
    logging.basicConfig(level=settings.log_level, format="%(levelname)s %(name)s %(message)s")
    # Provider/HTTP debug logs can contain payloads. Application logs contain
    # fixed codes and generated request IDs only, even at LOG_LEVEL=DEBUG.
    for name in [
        "groq", "httpx", "httpx2", "httpcore", "httpcore2",
        "langchain", "langchain_core", "langchain_groq", "langsmith", "langgraph",
        "uvicorn.access", "sqlalchemy", "psycopg", "alembic",
    ]:
        logging.getLogger(name).setLevel(logging.CRITICAL)

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        admission = ModelAdmission(settings.model_max_concurrent_calls, registry=registry, tenant_limit=settings.tenant_max_concurrent_models)
        application.state.model_admission = admission
        with httpx.Client(timeout=settings.groq_timeout_seconds) as sync_client:
            async with httpx.AsyncClient(timeout=settings.groq_timeout_seconds) as async_client:
                shared_sentiment = sentiment_service
                if shared_sentiment is None:
                    shared_sentiment = create_sentiment_service(
                        settings, http_client=sync_client, http_async_client=async_client, admission=admission
                    )
                shared_sentiment.configure_admission(admission)
                application.state.sentiment_service = shared_sentiment
                application.state.investigation_service = (
                    investigation_service if investigation_service is not None else InvestigationService(
                        create_action_selector(settings, http_client=sync_client, http_async_client=async_client, admission=admission),
                        shared_sentiment,
                        timeout_seconds=settings.investigation_timeout_seconds,
                    )
                )
                application.state.investigation_service.configure_admission(admission, InvestigationAdmission(registry))
                batches = BatchService(shared_sentiment, settings, registry=registry,
                    store=batch_store if batch_store is not None else PostgresJobStore(settings, registry))
                application.state.batch_service = batches
                ingestion = IngestionService(shared_sentiment)
                if event_store_factory is not None:
                    events = event_store_factory(registry)
                else:
                    if not isinstance(batches._store, PostgresJobStore):
                        raise ApplicationError(ErrorCode.WEBHOOK_UNAVAILABLE)
                    events = PostgresEventStore(batches._store, settings, registry)
                webhooks = WebhookService(ingestion, settings, registry=registry, store=events)
                application.state.ingestion_service = ingestion
                application.state.webhook_service = webhooks
                await batches.start()
                try:
                    await webhooks.start()
                    async with httpx.AsyncClient(transport=gmail_transport, timeout=settings.gmail_http_timeout_seconds,
                                                 follow_redirects=False, trust_env=False) as google_client:
                        messages_factory = gmail_message_store_factory
                        if messages_factory is None:
                            if not isinstance(batches._store, PostgresJobStore):
                                raise ApplicationError(ErrorCode.GMAIL_UNAVAILABLE)
                            messages_factory = lambda store: PostgresGmailMessageStore(batches._store, store)
                        gmail = GmailService(registry, ingestion, GoogleGmail(google_client, settings,
                            transport_mode='default' if gmail_transport is None else 'injected'), settings,
                            message_store_factory=messages_factory)
                        application.state.gmail_service = gmail
                        await gmail.start()
                        try:
                            yield
                        finally:
                            await gmail.close()
                finally:
                    await webhooks.close()
                    await batches.close()

    application = FastAPI(
        title="Agentic Sentiment Intelligence API",
        version="v1",
        description="Customer feedback analysis and sentiment intelligence API",
        docs_url="/docs" if settings.docs_enabled else None,
        redoc_url="/redoc" if settings.docs_enabled else None,
        openapi_url="/openapi.json" if settings.docs_enabled else None,
        lifespan=lifespan,
        debug=False,
    )
    application.state.settings = settings
    application.state.tenant_registry = registry
    application.add_middleware(
        IngressLimitMiddleware, settings=settings, registry=registry
    )

    @application.middleware("http")
    async def request_boundary(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request.state.request_id = uuid4().hex
        try:
            response = await call_next(request)
        except Exception:
            # Do not include exception text or a traceback: third-party errors
            # and validation exceptions can embed credentials or feedback.
            response = error_response(request, ErrorCode.INTERNAL_ERROR, 500)
        response.headers["X-Request-ID"] = request.state.request_id
        delivery = getattr(request.state, "ingestion_delivery_id", None)
        if delivery is not None:
            response.headers["X-Feedback-Delivery-Id"] = delivery
            response.headers["Location"] = f"/api/v1/ingest/events/{delivery}/result"
        if request.url.path.startswith(("/api/v1/batch/", "/api/v1/ingest/", "/api/v1/webhooks/", "/api/v1/integrations/gmail/")):
            response.headers["Cache-Control"] = "no-store"
            response.headers["Pragma"] = "no-cache"
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["Referrer-Policy"] = "no-referrer"
        return response

    @application.exception_handler(ApplicationError)
    async def application_error_handler(request: Request, error: ApplicationError) -> JSONResponse:
        return error_response(request, error.code, ERROR_STATUS.get(error.code, 500))

    @application.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, error: RequestValidationError) -> JSONResponse:
        messages = {
            "missing": "This field is required.",
            "string_type": "Must be a string.",
            "string_too_short": "Text must not be empty.",
            "string_too_long": "Text must contain at most 5000 characters.",
            "value_error": "Text must contain a non-whitespace character.",
            "literal_error": "Value is not one of the supported options.",
            "enum": "Value is not one of the supported options.",
            "extra_forbidden": "Unexpected request fields are not allowed.",
            "json_invalid": "Request body must contain valid JSON.",
        }
        issues = []
        for item in error.errors():
            locations = [
                str(part) for part in item["loc"]
                if isinstance(part, int) or part in {
                    "body", "text", "source", "business_type", "question", "feedback", "id",
                    "mode", "message", "feedback_text",
                    "feedback_id", "channel", "event_type", "delivery_id",
                    "max_messages",
                    "file", "text_column", "id_column", "date_column", "job_id", "page", "page_size",
                }
            ]
            field = locations[-1] if locations else "body"
            message = messages.get(item["type"], "Request body must match the documented schema.")
            if field in {"question", "message", "id", "feedback_id"}:
                if item["type"] == "string_too_long":
                    message = f"Must contain at most {100 if field in {'id', 'feedback_id'} else 500} characters."
                elif item["type"] in {"value_error", "string_too_short"}:
                    message = "Must contain a non-whitespace character."
            if item["type"] in {"too_short", "too_long"} and "feedback" in locations:
                message = "Feedback must contain between 1 and 10 records."
            if "query" in item["loc"] or "path" in item["loc"]:
                message = "Use the documented job ID format and pagination bounds."
            if item["type"] == "value_error" and field == "body":
                message = "Request fields must be valid and feedback IDs must be unique."
                if request.url.path == "/api/v1/chat":
                    reason = str(item.get("ctx", {}).get("error", ""))
                    if reason in CHAT_VALIDATION_MESSAGES.values():
                        message = reason
            issues.append(ValidationIssue(field=".".join(locations) or "body", code=item["type"], message=message))
        return error_response(request, ErrorCode.VALIDATION_ERROR, 422, details=issues)

    @application.exception_handler(HTTPException)
    async def http_error_handler(request: Request, error: HTTPException) -> JSONResponse:
        return error_response(request, ErrorCode.HTTP_ERROR, error.status_code)

    @application.get("/health", response_model=HealthResponse, tags=["health"])
    async def health() -> HealthResponse:
        """Process liveness only; no authentication or provider call."""
        return HealthResponse()

    application.include_router(sentiment_router, prefix="/api/v1")
    application.include_router(investigation_router, prefix="/api/v1")
    application.include_router(chat_router, prefix="/api/v1")
    application.include_router(batch_router, prefix="/api/v1")
    application.include_router(ingestion_router, prefix="/api/v1")
    application.include_router(webhook_router, prefix="/api/v1")
    application.include_router(gmail_router, prefix="/api/v1")
    return application


app = create_app()
