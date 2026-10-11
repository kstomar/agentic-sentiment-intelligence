"""Deterministic counts, classification filters, and source-scoped explanations."""

from collections import defaultdict

from app.schemas.investigation import (
    ActionSelection, AnalyzedFeedback, FeedbackEvidence, InvestigationAction,
    IssueSummary, SentimentSummary,
)
from app.schemas.sentiment import Sentiment
from app.tools.statistics import count_sentiments, group_issue_ids


def aggregate_sentiment(results: list[AnalyzedFeedback]) -> SentimentSummary:
    return SentimentSummary.model_validate(count_sentiments(item.analysis.sentiment for item in results))


def aggregate_issues(results: list[AnalyzedFeedback]) -> list[IssueSummary]:
    """One unique record per category, descending count then category name."""
    return [
        IssueSummary(category=category, count=len(ids), feedback_ids=sorted(ids))
        for category, ids in group_issue_ids((item.analysis.issue_category, item.feedback_id) for item in results)
    ]


def matching_results(results: list[AnalyzedFeedback], selection: ActionSelection) -> list[AnalyzedFeedback]:
    """Issue actions default to complaints; evidence search uses exact optional filters."""
    complaint_action = selection.action in {
        InvestigationAction.ISSUE_FREQUENCY, InvestigationAction.GENERAL_FEEDBACK_SUMMARY,
    }
    sentiments = {selection.sentiment} if selection.sentiment else (
        {Sentiment.NEGATIVE, Sentiment.MIXED} if complaint_action else set(Sentiment)
    )
    return sorted(
        [item for item in results if item.analysis.sentiment in sentiments
         and (selection.category is None or item.analysis.issue_category == selection.category)],
        key=lambda item: item.feedback_id,
    )


def generate_insights(
    selection: ActionSelection,
    results: list[AnalyzedFeedback],
    summary: SentimentSummary,
    issues: list[IssueSummary],
    evidence: list[FeedbackEvidence],
) -> tuple[str, list[str]]:
    """Render verified calculations, never free-form model claims or business metrics."""
    overview = (
        f"Of {len(results)} submitted records, {summary.POSITIVE} were classified POSITIVE, "
        f"{summary.NEGATIVE} NEGATIVE, {summary.NEUTRAL} NEUTRAL, and {summary.MIXED} MIXED."
    )
    issue_text = "; ".join(f"{item.category.value}: {item.count}" for item in issues)
    complaints = (
        f"Negative or mixed records grouped by primary issue category: {issue_text}."
        if issues else "No negative or mixed records matched the selected issue filters."
    )
    if selection.action == InvestigationAction.SENTIMENT_OVERVIEW:
        return overview, []
    if selection.action == InvestigationAction.EVIDENCE_SEARCH:
        count = len(matching_results(results, selection))
        answer = (
            f"Found {count} records matching the selected classification filters. "
            f"Returning {len(evidence)} original source records."
        )
        return answer, []
    answer = complaints if selection.action == InvestigationAction.ISSUE_FREQUENCY else overview + " " + complaints
    if selection.action == InvestigationAction.GENERAL_FEEDBACK_SUMMARY:
        for label, sentiments in [
            ("Positive or mixed", {Sentiment.POSITIVE, Sentiment.MIXED}),
            ("Negative or mixed", {Sentiment.NEGATIVE, Sentiment.MIXED}),
        ]:
            aspects: dict[str, set[str]] = defaultdict(set)
            for item in results:
                for aspect in item.analysis.aspects:
                    if aspect.sentiment in sentiments:
                        aspects[aspect.name].add(item.feedback_id)
            names = sorted(aspects, key=lambda name: (-len(aspects[name]), name))[:5]
            if names:
                answer += f" {label} aspect labels (records): " + "; ".join(
                    f"{name}: {len(aspects[name])}" for name in names
                ) + "."
    recommendations = [
        "Consider reviewing the cited feedback and relevant business records before choosing a response."
    ] if issues else []
    return answer, recommendations
