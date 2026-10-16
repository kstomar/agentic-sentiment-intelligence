"""Raw-byte signed trigger; API-key authentication deliberately does not apply."""

from typing import Annotated, cast

from fastapi import APIRouter, Request, Response, Security
from fastapi.security import APIKeyHeader

from app.core.webhook_security import authenticate_webhook
from app.schemas.errors import ErrorResponse
from app.schemas.ingestion import WebhookAcknowledgment, WebhookPayload
from app.services.ingestion_service import normalize_event
from app.services.webhook_service import WebhookService

signature_header = APIKeyHeader(name="X-Feedback-Signature", scheme_name="FeedbackHMAC",
    description="HMAC-SHA256 over integration.timestamp.delivery.original_body; all four signed headers are required. See docs/WEBHOOK_INTEGRATION.md.", auto_error=False)
router = APIRouter(prefix="/webhooks", tags=["webhooks"],
    responses={code: {"model": ErrorResponse} for code in [401, 408, 409, 413, 422, 429, 500, 503]})


@router.post("/feedback", response_model=WebhookAcknowledgment, status_code=202,
    responses={200: {"model": WebhookAcknowledgment}}, summary="Accept a signed feedback-created event",
    openapi_extra={"parameters": [{"name": name, "in": "header", "required": True, "schema": {"type": "string"}} for name in ["X-Feedback-Integration-Id", "X-Feedback-Delivery-Id", "X-Feedback-Timestamp"]]})
async def webhook(payload: WebhookPayload, request: Request, response: Response,
                  signature: Annotated[str | None, Security(signature_header)] = None) -> WebhookAcknowledgment:
    raw = await request.body()
    identity = authenticate_webhook(request.app.state.settings, request.headers, raw, registry=request.app.state.tenant_registry)
    ack = await cast(WebhookService, request.app.state.webhook_service).submit(
        identity, raw, normalize_event(payload),
    )
    if ack.status == "DUPLICATE":
        response.status_code = 200
    return ack
