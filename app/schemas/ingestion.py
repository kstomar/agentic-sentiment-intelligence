"""External metadata is data, never authenticated ownership or model authority."""

from enum import StrEnum
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from app.core.exceptions import ErrorCode
from app.schemas.investigation import FeedbackID, FeedbackItem
from app.schemas.sentiment import BusinessType, FeedbackSource, SentimentRequest, SentimentResponse


class IngestionRequest(SentimentRequest):
    feedback_id: FeedbackID | None = None
    channel: Literal["website", "mobile_app", "support_platform", "external_api"]
    source: FeedbackSource = "customer_review"

    @field_validator("feedback_id")
    @classmethod
    def normalize_id(cls, value: str | None) -> str | None:
        if value is not None:
            SentimentRequest.require_nonblank_feedback(value)
            return value.strip()
        return None


class IngestionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    feedback_id: FeedbackID | None
    channel: Literal["website", "mobile_app", "support_platform", "external_api"]
    status: Literal["ANALYZED"] = "ANALYZED"
    analysis: SentimentResponse


class WebhookPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    event_type: Literal["customer.feedback.created"]
    feedback: FeedbackItem
    source: FeedbackSource = "customer_review"
    business_type: BusinessType = "general"


class EventState(StrEnum):
    ACCEPTED = "ACCEPTED"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class WebhookAcknowledgment(BaseModel):
    delivery_id: str
    status: Literal["ACCEPTED", "DUPLICATE"]
    message: str


class EventStatus(BaseModel):
    delivery_id: str
    status: EventState
    error_code: ErrorCode | None = None


class EventResult(BaseModel):
    """Owned durable result; feedback uses the existing normalized ingestion schema."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    delivery_id: str
    status: EventState
    integration_id: str | None
    event_type: Literal["customer.feedback.created"] | None
    feedback: IngestionRequest
    analysis: SentimentResponse | None
    error_code: ErrorCode | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None

    @model_validator(mode="after")
    def verify_outcome(self) -> "EventResult":
        if self.status == EventState.COMPLETED:
            if self.analysis is None or self.error_code is not None or self.completed_at is None:
                raise ValueError("Completed events require a validated analysis.")
            SentimentResponse.model_validate(self.analysis.model_dump(), context={"feedback_text": self.feedback.text})
        elif self.analysis is not None:
            raise ValueError("Unsuccessful events cannot contain an analysis.")
        if self.status == EventState.FAILED and (self.error_code is None or self.completed_at is None):
            raise ValueError("Failed events require a safe error and completion time.")
        return self
