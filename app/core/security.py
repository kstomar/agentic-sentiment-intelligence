"""Replaceable single-key development authentication, without tenant claims."""

from typing import Annotated, cast
from collections.abc import Callable

from fastapi import Depends, Request, Security
from fastapi.security import APIKeyHeader

from app.core.config import Settings
from app.core.tenant_auth import Permission, Principal, TenantRegistry

api_key_header = APIKeyHeader(
    name="X-API-Key",
    scheme_name="DevelopmentAPIKey",
    description="Business API credential; legacy APP_API_KEY is development-only and owns only the development tenant.",
    auto_error=False,
)


def require_api_key(
    request: Request,
    supplied_key: Annotated[str | None, Security(api_key_header)],
) -> Principal:
    """Reject unauthenticated access before invoking the analysis service."""
    registry = cast(TenantRegistry, request.app.state.tenant_registry)
    principal = getattr(request.state, "principal", None)
    return registry.require(principal) if principal is not None else registry.authenticate(supplied_key)


def verify_api_key(settings: Settings, supplied_key: str | None) -> Principal:
    """Shared by early ASGI admission and the documented route dependency."""
    return TenantRegistry(settings).authenticate(supplied_key)


def require_permission(permission: Permission) -> Callable[..., Principal]:
    def dependency(request: Request, principal: Annotated[Principal, Depends(require_api_key)]) -> Principal:
        return request.app.state.tenant_registry.require(principal, permission)
    return dependency
