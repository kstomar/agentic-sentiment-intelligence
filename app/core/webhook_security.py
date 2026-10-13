"""HMAC verification over original bytes; one server-configured development integration."""

import hashlib
import hmac
import re
import time
from dataclasses import dataclass, field, replace

from starlette.datastructures import Headers

from app.core.config import Settings
from app.core.exceptions import ApplicationError, ErrorCode
from app.core.tenant_auth import Principal, TenantRegistry

IDENTIFIER_PATTERN = r"[A-Za-z0-9][A-Za-z0-9_-]{0,99}"


@dataclass(frozen=True)
class SignedDelivery:
    integration_id: str
    delivery_id: str
    timestamp: str
    signature: str = field(repr=False)
    principal: Principal | None = field(default=None, repr=False)


def signed_headers(settings: Settings, headers: Headers, *, now: float | None = None, registry: TenantRegistry | None = None) -> SignedDelivery:
    """Reject configuration/header/replay failures before reading a request body."""
    registry = registry if registry is not None else TenantRegistry(settings)
    if not registry._integrations:
        raise ApplicationError(ErrorCode.WEBHOOK_NOT_CONFIGURED)
    names = ["x-feedback-integration-id", "x-feedback-delivery-id", "x-feedback-timestamp", "x-feedback-signature"]
    values = [headers.getlist(name) for name in names]
    if any(len(value) != 1 for value in values):
        raise ApplicationError(ErrorCode.WEBHOOK_AUTHENTICATION_FAILED)
    integration, delivery, timestamp, signature = [value[0] for value in values]
    valid = (
        re.fullmatch(IDENTIFIER_PATTERN, integration)
        and re.fullmatch(IDENTIFIER_PATTERN, delivery)
        and re.fullmatch(r"[1-9][0-9]{0,11}", timestamp)
        and re.fullmatch(r"sha256=[0-9a-f]{64}", signature)
    )
    if not valid:
        raise ApplicationError(ErrorCode.WEBHOOK_AUTHENTICATION_FAILED)
    registry.integration(integration)
    if abs((time.time() if now is None else now) - int(timestamp)) > settings.webhook_timestamp_tolerance_seconds:
        raise ApplicationError(ErrorCode.WEBHOOK_AUTHENTICATION_FAILED)
    return SignedDelivery(integration, delivery, timestamp, signature)


def authenticate_webhook(settings: Settings, headers: Headers, raw_body: bytes, *, registry: TenantRegistry | None = None) -> SignedDelivery:
    registry = registry if registry is not None else TenantRegistry(settings)
    delivery = signed_headers(settings, headers, registry=registry)
    canonical = f"{delivery.integration_id}.{delivery.timestamp}.{delivery.delivery_id}.".encode() + raw_body
    secret = registry.integration(delivery.integration_id).secret
    digest = hmac.new(secret.get_secret_value().encode(), canonical, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(delivery.signature, "sha256=" + digest):
        raise ApplicationError(ErrorCode.WEBHOOK_AUTHENTICATION_FAILED)
    return replace(delivery, principal=registry._webhook_principal(delivery.integration_id))


def verify_delivery(settings: Settings, delivery: SignedDelivery, raw_body: bytes, registry: TenantRegistry) -> SignedDelivery:
    """Reverify a typed delivery at a non-HTTP service boundary, using the same verifier."""
    return authenticate_webhook(settings, Headers({
        "X-Feedback-Integration-Id": delivery.integration_id,
        "X-Feedback-Delivery-Id": delivery.delivery_id,
        "X-Feedback-Timestamp": delivery.timestamp,
        "X-Feedback-Signature": delivery.signature,
    }), raw_body, registry=registry)
