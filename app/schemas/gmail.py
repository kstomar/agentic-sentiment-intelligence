"""Public Gmail contracts contain no OAuth token/verifier or complete email body."""

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.exceptions import ErrorCode
from app.schemas.batch import JobState
from app.schemas.sentiment import SentimentResponse


class GmailModel(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class GmailConnect(GmailModel):
    authorization_url: str
    expires_in_seconds: float


class GmailConnectionStatus(GmailModel):
    connected: bool
    mailbox: str | None = None
    scope: Literal["gmail.readonly"] = "gmail.readonly"
    connection_status: Literal["CONNECTED", "DISCONNECTED", "RECONNECT_REQUIRED"]


class GmailDisconnected(GmailModel):
    status: Literal["DISCONNECTED"] = "DISCONNECTED"


class GmailOAuthComplete(GmailModel):
    status: Literal["CONNECTED"] = "CONNECTED"


class GmailImportRequest(GmailModel):
    max_messages: int = Field(default=20, strict=True, ge=1, le=100)


class GmailAccepted(GmailModel):
    job_id: str
    status: Literal["PENDING"] = "PENDING"
    message: Literal["Gmail feedback import accepted."] = "Gmail feedback import accepted."


class GmailResult(GmailModel):
    integration: Literal["gmail"] = "gmail"
    message_id: str
    thread_id: str | None = None
    status: Literal["SUCCESS", "FAILED", "SKIPPED", "DUPLICATE"]
    analysis: SentimentResponse | None = None
    error_code: ErrorCode | None = None

    @model_validator(mode="after")
    def consistent_outcome(self) -> Self:
        if self.status == 'SUCCESS':
            if self.analysis is None or self.error_code is not None:
                raise ValueError('A successful message requires validated analysis only.')
        elif self.analysis is not None or ((self.status == 'DUPLICATE') != (self.error_code is None)):
            raise ValueError('Message status, analysis and error code must agree.')
        return self


class GmailJobStatus(GmailModel):
    job_id: str
    status: JobState
    selected_messages: int
    processed_messages: int
    successful_messages: int
    failed_messages: int
    skipped_messages: int
    duplicate_messages: int
    error_code: ErrorCode | None = None
    scanned_messages: int = 0
    previously_processed_messages: int = 0
    deferred_messages: int = 0
    scan_exhausted: bool = False
    scan_limit_reached: bool = False
    capacity_limit_reached: bool = False


class GmailResults(GmailModel):
    job_id: str
    status: JobState
    results: list[GmailResult] = Field(max_length=100)
