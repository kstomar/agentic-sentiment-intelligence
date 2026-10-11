"""Small acyclic StateGraph with validated, question-dependent conditional edges."""

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from pydantic import BaseModel, ValidationError

from app.agents.action_selector import Selector
from app.agents.state import InvestigationState
from app.core.exceptions import ApplicationError, ErrorCode
from app.schemas.investigation import ActionSelection, InvestigationAction, InvestigationResponse, SentimentSummary
from app.services.sentiment_service import SentimentService
from app.tools.aggregation import aggregate_issues, aggregate_sentiment, generate_insights, matching_results
from app.tools.evidence import evidence_ids, retrieve_evidence, verify_findings
from app.tools.feedback_analysis import analyze_feedback_items


def selected(state: InvestigationState) -> ActionSelection:
    if state["selected_action"] is None:
        raise ApplicationError(ErrorCode.INVALID_GRAPH_STATE)
    return state["selected_action"]


def summary(state: InvestigationState) -> SentimentSummary:
    if state["sentiment_summary"] is None:
        raise ApplicationError(ErrorCode.INVALID_GRAPH_STATE)
    return state["sentiment_summary"]


def build_feedback_graph(selector: Selector, sentiment_service: SentimentService) -> CompiledStateGraph:
    """Compile once; invocation state, including all feedback, is never checkpointed."""

    async def select_action(state: InvestigationState) -> dict[str, object]:
        request = state["request"]
        # Deliberately do not pass state, review data, IDs, or tool outputs.
        value = await selector.select(request.question, request.business_type)
        try:
            if isinstance(value, BaseModel):
                value = value.model_dump(mode="json")
            selection = ActionSelection.model_validate(value)
        except (ValidationError, ValueError, TypeError):
            raise ApplicationError(ErrorCode.INVALID_ACTION_SELECTION) from None
        return {"selected_action": selection}

    async def analyze(state: InvestigationState) -> dict[str, object]:
        results = await analyze_feedback_items(state["request"], sentiment_service)
        return {
            "analysis_results": results,
            "sentiment_summary": aggregate_sentiment(results),
            "tools_used": ["analyze_feedback_items", "aggregate_sentiment"],
        }

    async def route(state: InvestigationState) -> InvestigationAction:
        return selected(state).action

    async def issues(state: InvestigationState) -> dict[str, object]:
        return {
            "issue_summary": aggregate_issues(matching_results(state["analysis_results"], selected(state))),
            "tools_used": [*state["tools_used"], "aggregate_issues"],
        }

    async def evidence(state: InvestigationState) -> dict[str, object]:
        selection = selected(state)
        return {
            "evidence": retrieve_evidence(
                state["request"].feedback,
                evidence_ids(state["analysis_results"], selection, state["issue_summary"]),
                limit=selection.evidence_limit,
            ),
            "tools_used": [*state["tools_used"], "retrieve_evidence"],
        }

    async def verify(state: InvestigationState) -> dict[str, object]:
        verify_findings(
            state["request"], selected(state), state["analysis_results"], summary(state),
            state["issue_summary"], state["evidence"],
        )
        return {}

    async def insights(state: InvestigationState) -> dict[str, object]:
        selection = selected(state)
        answer, recommendations = generate_insights(
            selection, state["analysis_results"], summary(state), state["issue_summary"], state["evidence"]
        )
        limitations = [
            "Findings are based only on the submitted feedback; no external records or historical trends were checked.",
            "Sentiments, categories, and aspects are model classifications, not independently verified business facts.",
            "Issue frequencies count NEGATIVE or MIXED records by their single primary category under the selected filters.",
            "Recommendations are tentative suggestions, not observed facts, safety assessments, or actions taken.",
        ]
        if selection.action != InvestigationAction.SENTIMENT_OVERVIEW:
            limitations.append(
                f"Evidence contains at most {selection.evidence_limit} matching records; "
                "sentiment totals cover all submitted records."
            )
        if selection.action == InvestigationAction.EVIDENCE_SEARCH:
            limitations.append(
                "Evidence search uses exact assigned category/sentiment filters, not unrestricted semantic search."
            )
        return {
            "response": InvestigationResponse(
                question=state["request"].question,
                selected_action=selection,
                answer=answer,
                total_feedback=len(state["request"].feedback),
                sentiment_summary=summary(state),
                top_issues=state["issue_summary"],
                evidence=state["evidence"],
                tools_used=[*state["tools_used"], "generate_insights"],
                limitations=limitations,
                recommendations=recommendations,
            ),
        }

    graph = StateGraph(InvestigationState)
    graph.add_node("select_action", select_action)
    graph.add_node("analyze_feedback", analyze)
    graph.add_node("aggregate_issues", issues)
    graph.add_node("retrieve_evidence", evidence)
    graph.add_node("verify_evidence", verify)
    graph.add_node("generate_insights", insights)
    graph.add_edge(START, "select_action")
    graph.add_edge("select_action", "analyze_feedback")
    graph.add_conditional_edges("analyze_feedback", route, {
        InvestigationAction.SENTIMENT_OVERVIEW: "verify_evidence",
        InvestigationAction.ISSUE_FREQUENCY: "aggregate_issues",
        InvestigationAction.EVIDENCE_SEARCH: "retrieve_evidence",
        InvestigationAction.GENERAL_FEEDBACK_SUMMARY: "aggregate_issues",
    })
    graph.add_edge("aggregate_issues", "retrieve_evidence")
    graph.add_edge("retrieve_evidence", "verify_evidence")
    graph.add_edge("verify_evidence", "generate_insights")
    graph.add_edge("generate_insights", END)
    return graph.compile(checkpointer=None, store=None, cache=None, debug=False)
