"""Bounded configuration registry, immutable authenticated capabilities and policy.

Transport-independent. No request field or bare tenant string can authenticate a
caller. Registry verification is repeated at owner-sensitive service boundaries.
"""

import hashlib
import hmac
import json
import re
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

from pydantic import SecretStr

from app.core.exceptions import ApplicationError, ErrorCode

if TYPE_CHECKING:
    from app.core.config import Settings

IDENTIFIER = r"[A-Za-z0-9][A-Za-z0-9_-]{0,99}"
DEVELOPMENT_TENANT = "development"
DEVELOPMENT_CREDENTIAL = "legacy-app-key"


class Permission(StrEnum):
    ANALYZE = "sentiment:analyze"
    INVESTIGATE = "feedback:investigate"
    CHAT = "chat:analyze"
    BATCH_CREATE = "batch:create"
    BATCH_READ = "batch:read"
    INGEST = "feedback:ingest"
    EVENT_READ = "events:read"
    GMAIL_CONNECT = "gmail:connect"
    GMAIL_IMPORT = "gmail:import"
    GMAIL_READ = "gmail:read"


@dataclass(frozen=True, slots=True)
class Principal:
    tenant_id: str
    credential_id: str
    permissions: frozenset[Permission]
    kind: str
    _proof: bytes = field(repr=False)
    _authority: "TenantRegistry" = field(repr=False, compare=False)


_current: ContextVar[Principal | None] = ContextVar("authenticated_principal", default=None)


@contextmanager
def principal_context(principal: Principal | None) -> Iterator[None]:
    """Explicitly bind verified authority to this task, resetting on cancellation too."""
    token = _current.set(principal)
    try:
        yield
    finally:
        _current.reset(token)


def current_principal() -> Principal:
    principal = _current.get()
    if not isinstance(principal, Principal):
        raise ApplicationError(ErrorCode.AUTHENTICATION_FAILED)
    return principal


@dataclass(frozen=True, slots=True)
class _Credential:
    tenant_id: str
    credential_id: str
    permissions: frozenset[Permission]
    digest: bytes = field(repr=False)


@dataclass(frozen=True, slots=True)
class _Integration:
    tenant_id: str
    integration_id: str
    secret: SecretStr = field(repr=False)


def _identifier(value: object) -> str:
    if not isinstance(value, str) or re.fullmatch(IDENTIFIER, value) is None:
        raise ValueError
    return value


def _secret(value: object) -> str:
    # 32 random bytes encoded with token_urlsafe produce 43 characters. Syntax
    # cannot prove entropy: operators must generate these, never choose passwords.
    if not isinstance(value, str) or re.fullmatch(r"[A-Za-z0-9_-]{43,128}", value) is None:
        raise ValueError
    if len(set(value)) < 10:
        raise ValueError
    return value


def _rows(value: SecretStr | None) -> list[dict]:
    if value is None:
        return []
    raw = value.get_secret_value()
    if len(raw.encode()) > 65536:
        raise ValueError

    def unique_object(pairs: list[tuple[str, object]]) -> dict:
        result = {}
        for key, item in pairs:
            if key in result:
                raise ValueError
            result[key] = item
        return result

    def invalid_constant(value: str) -> None:
        raise ValueError

    result = json.loads(raw, object_pairs_hook=unique_object, parse_constant=invalid_constant)
    if not isinstance(result, list) or len(result) > 128 or any(not isinstance(row, dict) for row in result):
        raise ValueError
    return result


class TenantRegistry:
    """At most 32 configured businesses, 128 credentials and 128 integrations.

    Credentials are represented by hashes after construction. Proofs stay private
    in Python objects, never in schemas/logs. Matching claims against this registry
    also rejects mutated/forged principals and principals from unrelated registries.
    """

    def __init__(self, settings: "Settings") -> None:
        self.settings = settings
        self._credentials: dict[str, _Credential] = {}
        self._integrations: dict[str, _Integration] = {}
        self.tenant_limits_enabled = False
        try:
            self._configure()
        except (ValueError, TypeError, KeyError, RecursionError):
            # Do not propagate parser/record diagnostics containing secret input.
            raise ValueError("Invalid tenant security configuration.") from None

    def _configure(self) -> None:
        settings = self.settings
        credentials = _rows(settings.tenant_credentials_json)
        self.tenant_limits_enabled = bool(credentials)
        owners: set[str] = set()
        counts: Counter[str] = Counter()
        digests: set[bytes] = set()
        for row in credentials:
            if set(row) - {"tenant_id", "key_id", "api_key", "permissions"}:
                raise ValueError
            tenant = _identifier(row["tenant_id"])
            key_id = _identifier(row["key_id"])
            if tenant == DEVELOPMENT_TENANT or key_id == DEVELOPMENT_CREDENTIAL:
                raise ValueError
            secret = _secret(row["api_key"])
            raw_permissions = row.get("permissions", [p.value for p in Permission])
            if not isinstance(raw_permissions, list) or any(not isinstance(p, str) for p in raw_permissions):
                raise ValueError
            permissions = frozenset(Permission(p) for p in raw_permissions)
            if len(permissions) != len(raw_permissions):
                raise ValueError
            digest = hashlib.sha256(secret.encode()).digest()
            if key_id in self._credentials or digest in digests:
                raise ValueError
            self._credentials[key_id] = _Credential(tenant, key_id, permissions, digest)
            owners.add(tenant)
            counts[tenant] += 1
            digests.add(digest)
        if len(owners) > 32 or any(count > 8 for count in counts.values()):
            raise ValueError
        legacy = settings.legacy_auth_enabled
        if legacy and settings.app_api_key is not None:
            digest = hashlib.sha256(settings.app_api_key.get_secret_value().encode()).digest()
            if digest in digests:
                raise ValueError
            self._credentials[DEVELOPMENT_CREDENTIAL] = _Credential(
                DEVELOPMENT_TENANT, DEVELOPMENT_CREDENTIAL, frozenset(Permission), digest,
            )
            digests.add(digest)
        integration_digests: set[bytes] = set()
        for row in _rows(settings.webhook_integrations_json):
            if set(row) != {"integration_id", "tenant_id", "shared_secret"}:
                raise ValueError
            tenant = _identifier(row["tenant_id"])
            identifier = _identifier(row["integration_id"])
            secret = _secret(row["shared_secret"])
            digest = hashlib.sha256(secret.encode()).digest()
            if tenant not in owners or identifier in self._integrations or digest in integration_digests or digest in digests:
                raise ValueError
            self._integrations[identifier] = _Integration(tenant, identifier, SecretStr(secret))
            integration_digests.add(digest)
        if legacy and settings.webhook_integration_id is not None and settings.webhook_shared_secret is not None:
            identifier = settings.webhook_integration_id
            digest = hashlib.sha256(settings.webhook_shared_secret.get_secret_value().encode()).digest()
            if identifier in self._integrations or digest in integration_digests or digest in digests:
                raise ValueError
            self._integrations[identifier] = _Integration(DEVELOPMENT_TENANT, identifier, settings.webhook_shared_secret)
        if self.tenant_limits_enabled:
            # Headroom cannot exist with a global capacity of one. Legacy-only
            # development preserves T06's deliberately small test configurations.
            for value in [settings.model_max_concurrent_calls, settings.ingress_max_concurrent_requests,
                          settings.ingress_requests_per_minute, settings.batch_max_active_jobs,
                          settings.batch_max_retained_jobs, settings.batch_model_concurrency, settings.webhook_max_pending_events,
                          settings.webhook_max_concurrent_analyses, settings.webhook_max_retained_events]:
                if value < 2:
                    raise ValueError

    def limit(self, configured: int, global_limit: int) -> int:
        """Leave headroom for another tenant; legacy-only mode retains T06 limits."""
        return min(configured, global_limit - 1) if self.tenant_limits_enabled else global_limit

    @property
    def batch_active_limit(self) -> int:
        cap = self.limit(self.settings.tenant_max_active_batch_jobs, self.settings.batch_max_active_jobs)
        return min(cap, self.settings.batch_model_concurrency - 1) if self.tenant_limits_enabled else cap

    def authenticate(self, supplied_key: str | None) -> Principal:
        if not supplied_key:
            raise ApplicationError(ErrorCode.AUTHENTICATION_FAILED)
        if not self._credentials:
            raise ApplicationError(ErrorCode.APP_AUTH_NOT_CONFIGURED)
        digest = hashlib.sha256(supplied_key.encode()).digest()
        matched = None
        # Scan the entire bounded registry with fixed-size constant-time matches.
        for credential in self._credentials.values():
            if hmac.compare_digest(digest, credential.digest):
                matched = credential
        if matched is None:
            raise ApplicationError(ErrorCode.AUTHENTICATION_FAILED)
        return Principal(matched.tenant_id, matched.credential_id, matched.permissions, "api_key", digest, self)

    def require(self, principal: Principal | None = None, permission: Permission | None = None) -> Principal:
        principal = current_principal() if principal is None else principal
        if not isinstance(principal, Principal) or not isinstance(principal.credential_id, str) or not isinstance(principal._proof, bytes):
            raise ApplicationError(ErrorCode.AUTHENTICATION_FAILED)
        if principal.kind == "api_key":
            record = self._credentials.get(principal.credential_id)
            valid = record is not None and record.tenant_id == principal.tenant_id and record.permissions == principal.permissions and hmac.compare_digest(record.digest, principal._proof)
        else:
            record = self._integrations.get(principal.credential_id)
            valid = principal.kind == "webhook" and record is not None and record.tenant_id == principal.tenant_id and principal.permissions == frozenset({Permission.INGEST}) and hmac.compare_digest(hashlib.sha256(record.secret.get_secret_value().encode()).digest(), principal._proof)
        if not valid:
            raise ApplicationError(ErrorCode.AUTHENTICATION_FAILED)
        if permission is not None and permission not in principal.permissions:
            raise ApplicationError(ErrorCode.AUTHORIZATION_FAILED)
        return principal

    def integration(self, identifier: str) -> _Integration:
        if not self._integrations:
            raise ApplicationError(ErrorCode.WEBHOOK_NOT_CONFIGURED)
        integration = self._integrations.get(identifier)
        if integration is None:
            raise ApplicationError(ErrorCode.WEBHOOK_AUTHENTICATION_FAILED)
        return integration

    def _webhook_principal(self, identifier: str) -> Principal:
        """Internal verifier seam: call only after HMAC verification, never from JSON."""
        record = self.integration(identifier)
        digest = hashlib.sha256(record.secret.get_secret_value().encode()).digest()
        return Principal(record.tenant_id, record.integration_id, frozenset({Permission.INGEST}), "webhook", digest, self)
