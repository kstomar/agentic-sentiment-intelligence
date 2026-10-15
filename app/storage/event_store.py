"""Bounded, process-local reservations; terminal metadata expires, active work never evicts."""

import time
from dataclasses import dataclass, field
from collections.abc import Mapping
from types import MappingProxyType
from uuid import uuid4

from app.core.exceptions import ApplicationError, ErrorCode
from app.core.tenant_auth import Permission, Principal, TenantRegistry
from app.schemas.ingestion import EventState, EventStatus, IngestionRequest


@dataclass
class Event:
    owner: Principal = field(repr=False)
    integration_id: str
    delivery_id: str
    digest: bytes = field(repr=False)
    request: IngestionRequest | None = field(repr=False)
    status: EventState = EventState.ACCEPTED
    error_code: ErrorCode | None = None
    expires_at: float | None = None
    operation_id: str = field(default_factory=lambda: uuid4().hex, repr=False)

    def public_status(self) -> EventStatus:
        return EventStatus(delivery_id=self.delivery_id, status=self.status, error_code=self.error_code)


class EventStore:
    def __init__(self, maximum: int, ttl: float, registry: TenantRegistry) -> None:
        self.maximum = maximum
        self.ttl = ttl
        self.registry = registry
        self._events: dict[tuple[str, str], Event] = {}

    @property
    def events(self) -> Mapping[tuple[str, str], Event]:
        """Owner-filtered inspection; original integration/delivery keys retained."""
        principal = self.registry.require(permission=Permission.EVENT_READ)
        self._purge()
        return MappingProxyType({(e.integration_id, e.delivery_id): e for e in self._events.values() if e.owner.tenant_id == principal.tenant_id})

    def get(self, delivery_id: str, *, principal: Principal | None = None) -> Event:
        principal = self.registry.require(principal, Permission.EVENT_READ)
        self._purge()
        event = self._events.get((principal.tenant_id, delivery_id))
        if event is None:
            raise ApplicationError(ErrorCode.WEBHOOK_EVENT_NOT_FOUND)
        return event

    def _purge(self) -> None:
        now = time.monotonic()
        for key, event in list(self._events.items()):
            if event.expires_at is not None and now >= event.expires_at:
                event.request = None
                del self._events[key]

    def _finish(self, event: Event, error: ErrorCode | None = None) -> None:
        event.request = None
        event.error_code = error
        event.status = EventState.FAILED if error else EventState.COMPLETED
        event.expires_at = time.monotonic() + self.ttl

    def _clear(self) -> None:
        for event in self._events.values():
            event.request = None
        self._events.clear()
