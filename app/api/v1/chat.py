"""Authenticated conversational adapter using the existing application services."""

from typing import Annotated, cast

from fastapi import APIRouter, Depends, Request

from app.core.security import require_permission
from app.core.tenant_auth import Permission
from app.schemas.chat import ChatRequest, ChatResponse
from app.schemas.errors import ErrorResponse
from app.services.conversation_service import ConversationService
from app.services.investigation_service import InvestigationService
from app.services.sentiment_service import SentimentService

router = APIRouter(
    tags=["chat"],
    dependencies=[Depends(require_permission(Permission.CHAT))],
    responses={code: {"model": ErrorResponse} for code in [401, 403, 408, 413, 422, 429, 500, 502, 503, 504]},
)


def get_conversation_service(request: Request) -> ConversationService:
    """Create a lightweight coordinator over the same lifespan-owned instances."""
    return ConversationService(
        cast(SentimentService, request.app.state.sentiment_service),
        cast(InvestigationService, request.app.state.investigation_service),
    )


@router.post("/chat", response_model=ChatResponse, summary="Analyze or investigate feedback conversationally")
async def chat(
    payload: ChatRequest,
    service: Annotated[ConversationService, Depends(get_conversation_service)],
) -> ChatResponse:
    """Use an explicit mode and current feedback; no chat history is retained."""
    return await service.respond(payload)
