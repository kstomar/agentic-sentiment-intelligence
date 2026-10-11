"""Authenticated thin HTTP adapter for request-local investigations."""

from typing import Annotated, cast

from fastapi import APIRouter, Depends, Request

from app.core.security import require_permission
from app.core.tenant_auth import Permission
from app.schemas.errors import ErrorResponse
from app.schemas.investigation import InvestigationRequest, InvestigationResponse
from app.services.investigation_service import InvestigationService

router = APIRouter(
    prefix="/agent",
    tags=["investigation"],
    dependencies=[Depends(require_permission(Permission.INVESTIGATE))],
    responses={code: {"model": ErrorResponse} for code in [401, 403, 408, 413, 422, 429, 500, 502, 503, 504]},
)


def get_investigation_service(request: Request) -> InvestigationService:
    return cast(InvestigationService, request.app.state.investigation_service)


@router.post("/investigate", response_model=InvestigationResponse, summary="Investigate submitted feedback")
async def investigate_feedback(
    payload: InvestigationRequest,
    service: Annotated[InvestigationService, Depends(get_investigation_service)],
) -> InvestigationResponse:
    """Answer a bounded question using at most ten request-supplied records."""
    return await service.investigate(payload)
