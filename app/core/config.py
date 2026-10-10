"""Environment-based settings without mandatory startup credentials."""

from pathlib import Path
from typing import Literal, Self
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Read environment variables and an optional, ignored local .env file."""

    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[2] / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
        hide_input_in_errors=True,
    )

    app_env: Literal["development", "test", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    api_docs_enabled: bool | None = None
    app_api_key: SecretStr | None = None
    development_auth_enabled: bool | None = None
    tenant_credentials_json: SecretStr | None = None
    webhook_integrations_json: SecretStr | None = None
    tenant_max_concurrent_requests: int = Field(default=4, ge=1, le=64)
    tenant_requests_per_minute: int = Field(default=60, ge=1, le=5000)
    tenant_max_concurrent_investigations: int = Field(default=1, ge=1, le=16)
    tenant_max_concurrent_models: int = Field(default=2, ge=1, le=16)
    tenant_max_active_batch_jobs: int = Field(default=1, ge=1, le=8)
    tenant_max_retained_batch_jobs: int = Field(default=5, ge=1, le=50)
    tenant_max_pending_events: int = Field(default=5, ge=1, le=500)
    tenant_max_concurrent_webhook_analyses: int = Field(default=1, ge=1, le=8)
    tenant_max_retained_events: int = Field(default=20, ge=1, le=5000)
    groq_api_key: SecretStr | None = None
    groq_model: str = Field(default="openai/gpt-oss-20b", min_length=1, max_length=200)
    groq_timeout_seconds: float = Field(default=30, gt=0, le=120)
    groq_max_retries: int = Field(default=2, ge=0, le=3)
    investigation_timeout_seconds: float = Field(default=120, gt=0, le=300)
    mcp_max_concurrent_calls: int = Field(default=2, ge=1, le=8)
    json_max_body_bytes: int = Field(default=4 * 1024**2, ge=1024, le=16 * 1024**2)
    ingress_max_concurrent_requests: int = Field(default=16, ge=1, le=128)
    ingress_requests_per_minute: int = Field(default=120, ge=1, le=10000)
    ingress_body_timeout_seconds: float = Field(default=15, gt=0, le=120)
    model_max_concurrent_calls: int = Field(default=4, ge=1, le=32)
    webhook_integration_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,99}$")
    webhook_shared_secret: SecretStr | None = None
    webhook_max_body_bytes: int = Field(default=16384, ge=1024, le=1024**2)
    webhook_timestamp_tolerance_seconds: float = Field(default=300, gt=0, le=3600)
    webhook_max_pending_events: int = Field(default=20, ge=1, le=1000)
    webhook_max_concurrent_analyses: int = Field(default=2, ge=1, le=16)
    webhook_event_ttl_seconds: float = Field(default=1800, gt=0, le=86400)
    ingestion_result_ttl_seconds: float = Field(default=0, ge=0, le=31536000)
    webhook_max_retained_events: int = Field(default=100, ge=1, le=10000)
    webhook_processing_timeout_seconds: float = Field(default=60, gt=0, le=300)
    batch_max_upload_bytes: int = Field(default=2 * 1024**2, ge=1, le=16 * 1024**2)
    batch_max_records: int = Field(default=100, ge=1, le=1000)
    batch_max_text_chars: int = Field(default=5000, ge=1, le=5000)
    batch_max_active_jobs: int = Field(default=3, ge=1, le=10)
    batch_model_concurrency: int = Field(default=2, ge=1, le=8)
    batch_job_ttl_seconds: float = Field(default=0, ge=0, le=31536000)
    batch_job_timeout_seconds: float = Field(default=600, gt=0, le=3600)
    batch_max_retained_jobs: int = Field(default=20, ge=1, le=100)
    batch_max_extracted_bytes: int = Field(default=16 * 1024**2, ge=1, le=64 * 1024**2)
    database_url: SecretStr | None = None
    gmail_oauth_enabled: bool = False
    google_oauth_client_id: SecretStr | None = Field(default=None, max_length=256)
    google_oauth_client_secret: SecretStr | None = Field(default=None, max_length=4096)
    google_oauth_redirect_uri: str | None = None
    gmail_allow_localhost_http: bool = False
    gmail_feedback_label: str = Field(default="customer-feedback", min_length=1, max_length=128)
    gmail_search_days: int = Field(default=7, ge=1, le=30)
    gmail_business_type: Literal["ecommerce", "restaurant", "software", "banking", "general"] = "general"
    gmail_max_messages_per_import: int = Field(default=20, ge=1, le=100)
    gmail_max_message_body_bytes: int = Field(default=16384, ge=1, le=65536)
    gmail_max_concurrent_imports: int = Field(default=2, ge=2, le=8)
    gmail_tenant_max_concurrent_imports: int = Field(default=1, ge=1, le=4)
    gmail_max_retained_imports: int = Field(default=20, ge=2, le=100)
    gmail_tenant_max_retained_imports: int = Field(default=5, ge=1, le=50)
    gmail_import_ttl_seconds: float = Field(default=1800, gt=0, le=86400)
    gmail_import_timeout_seconds: float = Field(default=120, gt=0, le=600)
    gmail_oauth_state_ttl_seconds: float = Field(default=600, gt=0, le=1800)
    gmail_max_oauth_states: int = Field(default=64, ge=1, le=128)
    gmail_max_connections: int = Field(default=33, ge=1, le=128)
    gmail_connection_ttl_seconds: float = Field(default=28800, gt=0, le=86400)
    gmail_max_dedup_records: int = Field(default=10000, ge=2, le=10000)
    gmail_tenant_max_dedup_records: int = Field(default=1000, ge=1, le=10000)
    gmail_message_max_attempts: int = Field(default=3, ge=1, le=10)
    gmail_message_retry_delay_seconds: float = Field(default=60, gt=0, le=86400)
    gmail_http_timeout_seconds: float = Field(default=10, gt=0, le=30)
    gmail_http_max_concurrent_calls: int = Field(default=4, ge=1, le=16)
    gmail_http_max_retries: int = Field(default=1, ge=0, le=2)
    gmail_max_provider_response_bytes: int = Field(default=262144, ge=1024, le=1048576)
    gmail_max_list_pages: int = Field(default=5, ge=1, le=10)

    @model_validator(mode="before")
    @classmethod
    def protect_security_error_inputs(cls, data: object) -> object:
        """Mask even structured Pydantic root-error input before validation.

        hide_input_in_errors protects ordinary text; retaining SecretStr objects
        in the input dictionary also protects errors() diagnostics/repr. Do not
        copy this dictionary: the validator's recorded input must be redacted too.
        """
        if isinstance(data, dict):
            secret_names = {"app_api_key", "groq_api_key", "webhook_shared_secret",
                            "tenant_credentials_json", "webhook_integrations_json",
                            "google_oauth_client_id", "google_oauth_client_secret", "database_url"}
            invalid = False
            for name, value in list(data.items()):
                if isinstance(name, str) and name.lower() in secret_names and value is not None:
                    raw = value.get_secret_value() if isinstance(value, SecretStr) else value
                    if isinstance(raw, str):
                        data[name] = SecretStr(raw) if raw.strip() else None
                    else:
                        data[name] = SecretStr("<invalid-security-value>")
                        invalid = True
            if invalid:
                raise ValueError("Invalid secret configuration.")
        return data

    @field_validator("app_api_key", "groq_api_key", "webhook_shared_secret", "webhook_integration_id", "tenant_credentials_json", "webhook_integrations_json", mode="before")
    @classmethod
    def empty_secret_is_unconfigured(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @model_validator(mode="after")
    def bounded_job_capacity(self) -> Self:
        if self.batch_max_retained_jobs < self.batch_max_active_jobs:
            raise ValueError("Retained job capacity must cover active job capacity.")
        # Future-dated accepted timestamps can remain valid for twice the skew tolerance.
        if self.webhook_event_ttl_seconds < 2 * self.webhook_timestamp_tolerance_seconds:
            raise ValueError("Webhook retention must cover the full timestamp acceptance window.")
        if 0 < self.ingestion_result_ttl_seconds < 2 * self.webhook_timestamp_tolerance_seconds:
            raise ValueError("Persistent ingestion retention must cover the full timestamp acceptance window.")
        if self.webhook_max_retained_events < self.webhook_max_pending_events + self.webhook_max_concurrent_analyses:
            raise ValueError("Retained webhook capacity must cover pending events and active workers.")
        if self.webhook_shared_secret is not None and len(self.webhook_shared_secret.get_secret_value().encode()) < 32:
            raise ValueError("Webhook shared secrets must contain at least 32 bytes.")
        from app.core.tenant_auth import TenantRegistry
        TenantRegistry(self)  # Invalid security configuration aborts startup; no fallback.
        return self

    @property
    def gmail_configured(self) -> bool:
        if not self.gmail_oauth_enabled or not self.google_oauth_client_id or not self.google_oauth_client_secret:
            return False
        try:
            if not self.google_oauth_redirect_uri or len(self.google_oauth_redirect_uri) > 2048 or any(ord(c) < 33 for c in self.google_oauth_redirect_uri):
                return False
            uri = urlsplit(self.google_oauth_redirect_uri or "")
            valid = (uri.path == "/api/v1/integrations/gmail/oauth/callback" and uri.hostname
                     and not uri.username and not uri.password and not uri.query and not uri.fragment)
            local = self.app_env != "production" and self.gmail_allow_localhost_http and uri.hostname in {"localhost", "127.0.0.1", "::1"}
            return bool(valid and (uri.scheme == "https" or (uri.scheme == "http" and local))
                        and (uri.port is None or 1 <= uri.port <= 65535)
                        and self.gmail_feedback_label.strip())
        except ValueError:
            return False

    @property
    def legacy_auth_enabled(self) -> bool:
        """Preserve old dev setups; business registries require explicit opt-in."""
        return self.app_env != "production" and (
            self.development_auth_enabled is True or
            (self.development_auth_enabled is None and self.tenant_credentials_json is None)
        )

    @property
    def docs_enabled(self) -> bool:
        if self.api_docs_enabled is not None:
            return self.api_docs_enabled
        return self.app_env != "production"
