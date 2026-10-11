"""Explicit stateless chat modes with shared T01/T02 validation contracts."""

from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.investigation import FeedbackBatch, InvestigationRequest, InvestigationResponse, QuestionText
from app.schemas.sentiment import BusinessType, FeedbackText, SentimentRequest, SentimentResponse

CHAT_VALIDATION_MESSAGES = {
    "text_required": "ANALYZE_TEXT requires feedback_text in the current request.",
    "feedback_required": "INVESTIGATE_FEEDBACK requires feedback records in the current request.",
    "mode_conflict": "Supply only feedback_text for ANALYZE_TEXT or feedback for INVESTIGATE_FEEDBACK.",
}


class ChatMode(StrEnum):
    ANALYZE_TEXT = "ANALYZE_TEXT"
    INVESTIGATE_FEEDBACK = "INVESTIGATE_FEEDBACK"


class ChatRequest(BaseModel):
    """Every request contains its own feedback; history and identity fields are rejected."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    mode: ChatMode
    message: QuestionText
    feedback_text: FeedbackText | None = None
    feedback: FeedbackBatch | None = None
    business_type: BusinessType = "general"

    @field_validator("message")
    @classmethod
    def require_message(cls, value: str) -> str:
        return InvestigationRequest.require_question(value)

    @field_validator("feedback_text")
    @classmethod
    def require_nonblank_feedback(cls, value: str | None) -> str | None:
        return SentimentRequest.require_nonblank_feedback(value) if value is not None else None

    @model_validator(mode="after")
    def validate_mode_payload(self) -> Self:
        if self.mode == ChatMode.ANALYZE_TEXT:
            if self.feedback is not None:
                raise ValueError(CHAT_VALIDATION_MESSAGES["mode_conflict"])
            if self.feedback_text is None:
                raise ValueError(CHAT_VALIDATION_MESSAGES["text_required"])
            SentimentRequest(text=self.feedback_text, business_type=self.business_type)
        else:
            if self.feedback_text is not None:
                raise ValueError(CHAT_VALIDATION_MESSAGES["mode_conflict"])
            if self.feedback is None:
                raise ValueError(CHAT_VALIDATION_MESSAGES["feedback_required"])
            InvestigationRequest(
                question=self.message, business_type=self.business_type, feedback=self.feedback
            )
        return self


class ChatResponse(BaseModel):
    """One typed envelope with exactly one populated result and explicit limitations."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    mode: ChatMode
    answer: str = Field(min_length=1, max_length=4000)
    sentiment_analysis: SentimentResponse | None = None
    investigation: InvestigationResponse | None = None
    limitations: list[str] = Field(max_length=11)

    @model_validator(mode="after")
    def validate_mode_result(self) -> Self:
        if self.mode == ChatMode.ANALYZE_TEXT:
            if self.sentiment_analysis is None or self.investigation is not None:
                raise ValueError("Text-mode responses require only sentiment_analysis.")
        else:
            if self.investigation is None or self.sentiment_analysis is not None:
                raise ValueError("Investigation-mode responses require only investigation.")
            if self.answer != self.investigation.answer:
                raise ValueError("The conversation must preserve the verified investigation answer.")
            if not set(self.investigation.limitations).issubset(self.limitations):
                raise ValueError("The conversation must preserve investigation limitations.")
        return self
