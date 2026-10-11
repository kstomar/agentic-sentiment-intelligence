"""Read-only evidence retrieval and verification against request-owned records."""

from app.core.exceptions import ApplicationError, ErrorCode
from app.schemas.investigation import (
    ActionSelection, AnalyzedFeedback, FeedbackEvidence, FeedbackItem, InvestigationAction,
    InvestigationRequest, IssueSummary, SentimentSummary,
)
from app.schemas.sentiment import SentimentResponse
from app.tools.aggregation import aggregate_issues, aggregate_sentiment, matching_results


def evidence_ids(
    results: list[AnalyzedFeedback], selection: ActionSelection, issues: list[IssueSummary]
) -> list[str]:
    if selection.action == InvestigationAction.SENTIMENT_OVERVIEW:
        return []
    if selection.action == InvestigationAction.EVIDENCE_SEARCH:
        return [item.feedback_id for item in matching_results(results, selection)]
    if issues:
        return list(dict.fromkeys(identifier for issue in issues for identifier in issue.feedback_ids))
    if selection.action == InvestigationAction.GENERAL_FEEDBACK_SUMMARY:
        return sorted(item.feedback_id for item in results)
    return []


def retrieve_evidence(
    feedback: list[FeedbackItem], feedback_ids: list[str], *, limit: int
) -> list[FeedbackEvidence]:
    """Return bounded original records; never perform an external lookup."""
    originals = {item.id: item.text for item in feedback}
    if not 1 <= limit <= 10 or len(originals) != len(feedback):
        raise ApplicationError(ErrorCode.EVIDENCE_VERIFICATION_FAILED)
    if any(identifier not in originals for identifier in feedback_ids):
        raise ApplicationError(ErrorCode.EVIDENCE_VERIFICATION_FAILED)
    return [
        FeedbackEvidence(feedback_id=identifier, text_excerpt=originals[identifier])
        for identifier in list(dict.fromkeys(feedback_ids))[:limit]
    ]


def verify_findings(
    request: InvestigationRequest,
    selection: ActionSelection,
    results: list[AnalyzedFeedback],
    summary: SentimentSummary,
    issues: list[IssueSummary],
    evidence: list[FeedbackEvidence],
) -> None:
    """Recompute counts, ownership, filters, and exact source quotations."""
    originals = {item.id: item.text for item in request.feedback}
    ids = [item.feedback_id for item in results]
    if len(ids) != len(set(ids)) or set(ids) != set(originals):
        raise ApplicationError(ErrorCode.EVIDENCE_VERIFICATION_FAILED)
    try:
        for item in results:
            SentimentResponse.model_validate(
                item.analysis.model_dump(mode="json"), context={"feedback_text": originals[item.feedback_id]}
            )
        expected_summary = aggregate_sentiment(results)
        expected_issues = aggregate_issues(matching_results(results, selection)) if selection.action in {
            InvestigationAction.ISSUE_FREQUENCY, InvestigationAction.GENERAL_FEEDBACK_SUMMARY,
        } else []
        expected_evidence = retrieve_evidence(
            request.feedback, evidence_ids(results, selection, expected_issues), limit=selection.evidence_limit
        )
        valid = (
            summary == expected_summary
            and sum(summary.model_dump().values()) == len(originals)
            and issues == expected_issues
            and evidence == expected_evidence
            and all(
                item.feedback_id in originals and item.text_excerpt in originals[item.feedback_id]
                for item in evidence
            )
        )
    except (ValueError, TypeError, KeyError):
        raise ApplicationError(ErrorCode.EVIDENCE_VERIFICATION_FAILED) from None
    if not valid:
        raise ApplicationError(ErrorCode.EVIDENCE_VERIFICATION_FAILED)
