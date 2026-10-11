"""Bounded investigation, allowlisted action, and source-backed result contracts."""

from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.sentiment import (
    BusinessType, FeedbackText, IssueCategory, Sentiment, SentimentRequest, SentimentResponse,
)

FeedbackID = Annotated[str, Field(strict=True, min_length=1, max_length=100)]
QuestionText = Annotated[str, Field(strict=True, min_length=1, max_length=500)]
Count = Annotated[int, Field(strict=True, ge=0, le=10)]
ToolName = Literal[
    "analyze_feedback_items", "aggregate_sentiment", "aggregate_issues",
    "retrieve_evidence", "generate_insights",
]


class FeedbackItem(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    id: FeedbackID
    text: FeedbackText

    @field_validator("id", "text")
    @classmethod
    def require_nonblank(cls, value: str) -> str:
        return SentimentRequest.require_nonblank_feedback(value)


FeedbackBatch = Annotated[list[FeedbackItem], Field(min_length=1, max_length=10)]


class InvestigationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    question: QuestionText
    business_type: BusinessType = "general"
    feedback: FeedbackBatch

    @field_validator("question")
    @classmethod
    def require_question(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Question must contain a non-whitespace character.")
        return value

    @model_validator(mode="after")
    def unique_ids(self) -> Self:
        if len({item.id for item in self.feedback}) != len(self.feedback):
            raise ValueError("Feedback IDs must be unique.")
        return self


class InvestigationAction(StrEnum):
    SENTIMENT_OVERVIEW = "SENTIMENT_OVERVIEW"
    ISSUE_FREQUENCY = "ISSUE_FREQUENCY"
    EVIDENCE_SEARCH = "EVIDENCE_SEARCH"
    GENERAL_FEEDBACK_SUMMARY = "GENERAL_FEEDBACK_SUMMARY"


class ActionSelection(BaseModel):
    """All provider fields are required; null represents an unused filter."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    action: InvestigationAction
    category: IssueCategory | None
    sentiment: Sentiment | None
    evidence_limit: int = Field(strict=True, description="Number of source records to return, from 1 to 10.")

    @field_validator("evidence_limit")
    @classmethod
    def bound_evidence(cls, value: int) -> int:
        if not 1 <= value <= 10:
            raise ValueError("Evidence limit must be between 1 and 10.")
        return value

    @model_validator(mode="after")
    def compatible_filters(self) -> Self:
        if self.action in {
            InvestigationAction.SENTIMENT_OVERVIEW,
            InvestigationAction.GENERAL_FEEDBACK_SUMMARY,
        } and (self.category is not None or self.sentiment is not None):
            raise ValueError("Overview actions do not accept category or sentiment filters.")
        if self.action == InvestigationAction.ISSUE_FREQUENCY and self.sentiment not in {
            None, Sentiment.NEGATIVE, Sentiment.MIXED,
        }:
            raise ValueError("Issue frequency accepts only negative or mixed sentiment filters.")
        return self


class AnalyzedFeedback(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    feedback_id: FeedbackID
    analysis: SentimentResponse


class SentimentSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    POSITIVE: Count
    NEGATIVE: Count
    NEUTRAL: Count
    MIXED: Count


class IssueSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    category: IssueCategory
    count: int = Field(strict=True, ge=1, le=10)
    feedback_ids: list[FeedbackID] = Field(min_length=1, max_length=10)

    @model_validator(mode="after")
    def consistent_count(self) -> Self:
        if self.count != len(set(self.feedback_ids)) or self.count != len(self.feedback_ids):
            raise ValueError("Issue counts must match unique feedback IDs.")
        return self


class FeedbackEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    feedback_id: FeedbackID
    text_excerpt: str = Field(strict=True, min_length=1, max_length=5000)


class InvestigationResponse(BaseModel):
    """Observed classifications are distinct from tentative recommendations."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    question: str = Field(min_length=1, max_length=500)
    selected_action: ActionSelection
    answer: str = Field(min_length=1, max_length=4000)
    total_feedback: int = Field(strict=True, ge=1, le=10)
    sentiment_summary: SentimentSummary
    top_issues: list[IssueSummary] = Field(max_length=10)
    evidence: list[FeedbackEvidence] = Field(max_length=10)
    tools_used: list[ToolName] = Field(min_length=1, max_length=5)
    limitations: list[str] = Field(min_length=1, max_length=10)
    recommendations: list[str] = Field(max_length=3)

    @model_validator(mode="after")
    def consistent_totals(self) -> Self:
        if sum(self.sentiment_summary.model_dump().values()) != self.total_feedback:
            raise ValueError("Sentiment totals must match the submitted record count.")
        if len(set(self.tools_used)) != len(self.tools_used):
            raise ValueError("Tool names must be unique.")
        if len({issue.category for issue in self.top_issues}) != len(self.top_issues):
            raise ValueError("Issue categories must be unique.")
        if len({item.feedback_id for item in self.evidence}) != len(self.evidence):
            raise ValueError("Evidence records must be unique.")
        if len(self.evidence) > self.selected_action.evidence_limit:
            raise ValueError("Evidence must respect the selected limit.")
        return self
