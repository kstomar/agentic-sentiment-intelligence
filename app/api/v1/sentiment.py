"""Thin authenticated REST adapter for the shared sentiment service."""

from typing import Annotated, cast

from fastapi import APIRouter, Depends, Request

from app.core.security import require_permission
from app.core.tenant_auth import Permission
from app.schemas.errors import ErrorResponse
from app.schemas.sentiment import SentimentRequest, SentimentResponse
from app.services.sentiment_service import SentimentService

router = APIRouter(
    prefix="/sentiment",
    tags=["sentiment"],
    dependencies=[Depends(require_permission(Permission.ANALYZE))],
    responses={
        code: {"model": ErrorResponse}
        for code in [401, 403, 408, 413, 422, 429, 500, 502, 503, 504]
    },
)


def get_sentiment_service(request: Request) -> SentimentService:
    """Resolve an application-owned service; replaceable via dependency injection."""
    return cast(SentimentService, request.app.state.sentiment_service)


@router.post("/analyze", response_model=SentimentResponse, summary="Analyze customer feedback")
async def analyze_sentiment(
    payload: SentimentRequest,
    service: Annotated[SentimentService, Depends(get_sentiment_service)],
) -> SentimentResponse:
    """Classify feedback. Urgency is suggested triage, not a verified safety assessment."""
    return await service.analyze(payload)
