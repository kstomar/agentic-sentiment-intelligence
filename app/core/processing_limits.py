"""Single-event-loop model admission shared by classifier and selector calls."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from app.core.exceptions import ApplicationError, ErrorCode
from app.core.tenant_auth import TenantRegistry


class ModelAdmission:
    """Reject excess logical model operations immediately; never queue callers."""

    def __init__(self, limit: int, *, registry: TenantRegistry | None = None, tenant_limit: int = 2) -> None:
        self.limit = limit
        self.active = 0
        self.registry = registry
        self.tenant_limit = tenant_limit
        self.by_tenant: dict[str, int] = {}

    @asynccontextmanager
    async def claim(self) -> AsyncIterator[None]:
        principal = self.registry.require() if self.registry is not None else None
        if self.active >= self.limit:
            raise ApplicationError(ErrorCode.PROCESSING_CAPACITY_EXCEEDED)
        owner = principal.tenant_id if principal is not None else None
        if owner is not None and self.registry is not None:
            if self.by_tenant.get(owner, 0) >= self.registry.limit(self.tenant_limit, self.limit):
                raise ApplicationError(ErrorCode.TENANT_CAPACITY_EXCEEDED)
            self.by_tenant[owner] = self.by_tenant.get(owner, 0) + 1
        self.active += 1
        try:
            yield
        finally:
            self.active -= 1
            if owner is not None:
                self.by_tenant[owner] -= 1
                if not self.by_tenant[owner]:
                    del self.by_tenant[owner]


class InvestigationAdmission:
    """Bound a tenant's entire graph lifetime without holding a model permit."""

    def __init__(self, registry: TenantRegistry) -> None:
        self.registry = registry
        self.active: dict[str, int] = {}

    @asynccontextmanager
    async def claim(self) -> AsyncIterator[None]:
        principal = self.registry.require()
        owner = principal.tenant_id
        limit = self.registry.settings.tenant_max_concurrent_investigations
        if self.registry.tenant_limits_enabled and self.active.get(owner, 0) >= limit:
            raise ApplicationError(ErrorCode.TENANT_CAPACITY_EXCEEDED)
        self.active[owner] = self.active.get(owner, 0) + 1
        try:
            yield
        finally:
            self.active[owner] -= 1
            if not self.active[owner]:
                del self.active[owner]
