"""Request-scoped graph state; original feedback is stored in the request only."""

from typing import TypedDict

from app.schemas.investigation import (
    ActionSelection, AnalyzedFeedback, FeedbackEvidence, InvestigationRequest,
    InvestigationResponse, IssueSummary, SentimentSummary, ToolName,
)


class InvestigationState(TypedDict):
    request: InvestigationRequest
    selected_action: ActionSelection | None
    analysis_results: list[AnalyzedFeedback]
    sentiment_summary: SentimentSummary | None
    issue_summary: list[IssueSummary]
    evidence: list[FeedbackEvidence]
    tools_used: list[ToolName]
    response: InvestigationResponse | None
