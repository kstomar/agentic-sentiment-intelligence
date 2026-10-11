import pytest

from app.core.exceptions import ApplicationError
from app.schemas.investigation import ActionSelection, AnalyzedFeedback, InvestigationRequest, SentimentSummary
from app.schemas.sentiment import SentimentResponse
from app.tools.aggregation import aggregate_sentiment, aggregate_issues
from app.tools.evidence import retrieve_evidence, verify_findings
from tests.helpers import analysis


def rows():
    return [AnalyzedFeedback(feedback_id=i, analysis=SentimentResponse(**analysis(t, s, c))) for i,t,s,c in [
        ("B", "second", "NEGATIVE", "DELIVERY"), ("A", "first", "MIXED", "DELIVERY"),
        ("C", "third", "POSITIVE", "PRAISE")]]


def test_counts_order_and_unique_supporting_ids():
    results = rows()
    assert aggregate_sentiment(results).model_dump() == {"POSITIVE": 1, "NEGATIVE": 1, "NEUTRAL": 0, "MIXED": 1}
    issues = aggregate_issues(results)
    assert [(i.category.value, i.count, i.feedback_ids)for i in issues] == [("DELIVERY", 2, ["A", "B"]), ("PRAISE", 1, ["C"])]


@pytest.mark.parametrize("tamper", ["counts", "ids", "quotes"])
def test_evidence_verifier_rejects_tampering(tamper):
    results = rows()[:2]
    request = InvestigationRequest(question="q", feedback=[{"id": "B", "text": "second"}, {"id": "A", "text": "first"}])
    selection = ActionSelection(action="GENERAL_FEEDBACK_SUMMARY", category=None, sentiment=None, evidence_limit=3)
    summary = aggregate_sentiment(results)
    issues = aggregate_issues(results)
    evidence = retrieve_evidence(request.feedback, ["A", "B"], limit=3)
    if tamper == "counts": summary = SentimentSummary(POSITIVE=0, NEGATIVE=2, NEUTRAL=0, MIXED=0)
    if tamper == "ids": results[0] = results[0].model_copy(update={"feedback_id": "invented"})
    if tamper == "quotes": evidence[0] = evidence[0].model_copy(update={"text_excerpt": "invented"})
    with pytest.raises(ApplicationError):
        verify_findings(request, selection, results, summary, issues, evidence)
