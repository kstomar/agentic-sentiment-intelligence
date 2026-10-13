"""Authenticated synchronous ingestion and owner-scoped stored event retrieval."""

import asyncio
from typing import Annotated, cast

from fastapi import APIRouter, Depends, Path, Request, Response

from app.core.security import require_api_key, require_permission
from app.core.tenant_auth import Permission, Principal
from app.core.webhook_security import IDENTIFIER_PATTERN
from app.schemas.errors import ErrorResponse
from app.schemas.ingestion import EventResult, EventStatus, IngestionRequest, IngestionResponse
from app.services.ingestion_service import IngestionService
from app.services.webhook_service import WebhookService

router = APIRouter(prefix="/ingest", tags=["ingestion"], dependencies=[Depends(require_api_key)],
    responses={code: {"model": ErrorResponse} for code in [401, 403, 404, 408, 413, 422, 429, 500, 502, 503, 504]})


@router.post("/feedback", response_model=IngestionResponse, summary="Analyze externally submitted feedback",
             responses={200: {"headers": {
                 "X-Feedback-Delivery-Id": {"schema": {"type": "string"}, "description": "Server-created persistent event ID."},
                 "Location": {"schema": {"type": "string"}, "description": "Owned result retrieval URL."}}}})
async def ingest(payload: IngestionRequest, request: Request,
                 principal: Annotated[Principal, Depends(require_permission(Permission.INGEST))]) -> IngestionResponse:
    service = cast(WebhookService, request.app.state.webhook_service)
    event = await service.reserve_direct(payload, principal=principal)
    if event is None:  # Explicit isolated test adapter; never a production fallback.
        return await cast(IngestionService, request.app.state.ingestion_service).analyze(payload)
    request.state.ingestion_delivery_id = event.delivery_id
    return await service.process_direct(event)


@router.get("/events/{delivery_id}", response_model=EventStatus, summary="Get an owned feedback event status")
async def event_status(delivery_id: Annotated[str, Path(pattern="^" + IDENTIFIER_PATTERN + "$")], request: Request,
                       principal: Annotated[Principal, Depends(require_permission(Permission.EVENT_READ))]) -> EventStatus:
    return await asyncio.to_thread(cast(WebhookService, request.app.state.webhook_service).status,
                                   delivery_id, principal=principal)


@router.get("/events/{delivery_id}/result", response_model=EventResult | EventStatus,
            responses={202: {"model": EventStatus}}, summary="Retrieve the original feedback and stored analysis")
async def event_result(delivery_id: Annotated[str, Path(pattern="^" + IDENTIFIER_PATTERN + "$")],
                       request: Request, response: Response,
                       principal: Annotated[Principal, Depends(require_permission(Permission.EVENT_READ))]) -> EventResult | EventStatus:
    result = await asyncio.to_thread(cast(WebhookService, request.app.state.webhook_service).result,
                                     delivery_id, principal=principal)
    if isinstance(result, EventStatus):
        response.status_code = 202
    return result
