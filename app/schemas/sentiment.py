"""Strict analysis contracts shared by REST and future service consumers."""

import re
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator
from pydantic_core import PydanticCustomError

BusinessType = Literal["ecommerce", "restaurant", "software", "banking", "general"]
FeedbackSource = Literal["customer_review", "support_ticket", "email", "social_media", "manual"]
FeedbackText = Annotated[str, Field(strict=True, min_length=1, max_length=5000)]


class Sentiment(StrEnum):
    POSITIVE = "POSITIVE"
    NEGATIVE = "NEGATIVE"
    NEUTRAL = "NEUTRAL"
    MIXED = "MIXED"


class Urgency(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class IssueCategory(StrEnum):
    DELIVERY = "DELIVERY"
    PRODUCT_QUALITY = "PRODUCT_QUALITY"
    FOOD_QUALITY = "FOOD_QUALITY"
    BILLING = "BILLING"
    CUSTOMER_SUPPORT = "CUSTOMER_SUPPORT"
    TECHNICAL_ISSUE = "TECHNICAL_ISSUE"
    STAFF_BEHAVIOR = "STAFF_BEHAVIOR"
    FEATURE_REQUEST = "FEATURE_REQUEST"
    PRAISE = "PRAISE"
    OTHER = "OTHER"


class SentimentRequest(BaseModel):
    """Feedback and allowlisted context hints; no tenant identity is accepted."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    text: FeedbackText
    source: FeedbackSource = "manual"
    business_type: BusinessType = "general"

    @field_validator("text")
    @classmethod
    def require_nonblank_feedback(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Text must contain a non-whitespace character.")
        # Preserve the original text for exact evidence matching.
        return value


class Aspect(BaseModel):
    """An important feedback aspect with a normalized snake_case name."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    name: str = Field(description="Lowercase snake_case name, at most 64 characters.")
    sentiment: Sentiment

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        if len(value) > 64 or not re.fullmatch(r"[a-z][a-z0-9]*(?:_[a-z0-9]+)*", value):
            raise ValueError("Aspect names must be snake_case and at most 64 characters.")
        return value


class SentimentResponse(BaseModel):
    """Validated classification; urgency is suggested triage, not a safety assessment."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    sentiment: Sentiment
    issue_category: IssueCategory
    urgency: Urgency = Field(description="Suggested triage level, not a verified safety or risk assessment.")
    aspects: list[Aspect] = Field(description="At most 20 important aspects; empty when none can be identified.")
    summary: str = Field(description="Concise factual summary, at most 1000 characters.")
    suggested_next_step: str = Field(description="A recommendation, not an action taken; at most 1000 characters.")
    evidence_phrases: list[str] = Field(description="At most 20 exact, nonblank substrings of the original feedback.")

    # Validate bounds locally without relying on provider-specific support for
    # JSON Schema length/pattern keywords. Every schema field remains required.
    @field_validator("summary", "suggested_next_step")
    @classmethod
    def validate_summary_text(cls, value: str) -> str:
        value = value.strip()
        if not value or len(value) > 1000:
            raise ValueError("Analysis text must contain 1 to 1000 nonblank characters.")
        return value

    @field_validator("aspects")
    @classmethod
    def bound_aspects(cls, value: list[Aspect]) -> list[Aspect]:
        if len(value) > 20:
            raise ValueError("At most 20 aspects are allowed.")
        return value

    @field_validator("evidence_phrases")
    @classmethod
    def bound_evidence(cls, value: list[str]) -> list[str]:
        if len(value) > 20 or any(not phrase.strip() or len(phrase) > 5000 for phrase in value):
            raise ValueError("Evidence must contain at most 20 nonblank phrases of at most 5000 characters.")
        return value

    @model_validator(mode="after")
    def verify_evidence(self, info: ValidationInfo) -> Self:
        # The provider parser has no input context. The service always validates
        # again with feedback_text before returning a successful response.
        if info.context is not None and "feedback_text" in info.context:
            text = info.context["feedback_text"]
            if any(phrase not in text for phrase in self.evidence_phrases):
                raise PydanticCustomError(
                    "evidence_not_grounded",
                    "Evidence phrases must occur exactly in the submitted feedback.",
                )
        return self
