import asyncio

import pytest

from app.core.exceptions import ApplicationError, ErrorCode as E
from app.schemas.investigation import InvestigationRequest
from app.services.investigation_service import InvestigationService
from app.agents.action_selector import ActionSelector
from tests.helpers import Model, SelectionModel, harness


@pytest.mark.parametrize("action,optional_tools", [
    ("SENTIMENT_OVERVIEW", []), ("ISSUE_FREQUENCY", ["aggregate_issues", "retrieve_evidence"]),
    ("EVIDENCE_SEARCH", ["retrieve_evidence"]),
    ("GENERAL_FEEDBACK_SUMMARY", ["aggregate_issues", "retrieve_evidence"]),
])
async def test_all_four_conditional_routes(action, optional_tools):
    h = harness(action=action)
    result = await h.investigation.investigate(InvestigationRequest(
        question="Summarize the supplied feedback", feedback=[{"id": "B", "text": "second"}, {"id": "A", "text": "first"}]))
    assert result.selected_action.action == action
    assert result.tools_used == ["analyze_feedback_items", "aggregate_sentiment", *optional_tools, "generate_insights"]
    assert result.sentiment_summary.NEGATIVE == result.total_feedback == 2
    assert {e.feedback_id for e in result.evidence} == (set() if action == "SENTIMENT_OVERVIEW" else {"A", "B"})
    assert [r["text"] for r in h.model.calls] == ["second", "first"]
    assert len(h.selector.calls) == 1


async def test_graph_fail_fast_and_no_cross_request_state():
    h = harness(model=Model(errors={"bad": ApplicationError(E.UPSTREAM_RATE_LIMITED)}))
    with pytest.raises(ApplicationError):
        await h.investigation.investigate(InvestigationRequest(question="q", feedback=[
            {"id": "A", "text": "bad"}, {"id": "B", "text": "never-run"}]))
    assert len(h.model.calls) == 1
    result = await h.investigation.investigate(InvestigationRequest(question="new q", feedback=[{"id": "C", "text": "new"}]))
    assert result.total_feedback == 1 and [e.feedback_id for e in result.evidence] == ["C"]


async def test_whole_graph_timeout():
    h = harness(model=Model(gate=asyncio.Event()))
    service = InvestigationService(ActionSelector(h.selector), h.sentiment, timeout_seconds=.02)
    with pytest.raises(ApplicationError) as caught:
        await service.investigate(InvestigationRequest(question="q", feedback=[{"id": "A", "text": "x"}]))
    assert caught.value.code == E.INVESTIGATION_TIMEOUT and h.model.active == 0
