"""Independent entry point for bounded, request-scoped feedback investigations."""

import asyncio

from langgraph.errors import GraphRecursionError
from langsmith import tracing_context
from pydantic import ValidationError

from app.agents.action_selector import ActionSelector, Selector
from app.core.processing_limits import InvestigationAdmission, ModelAdmission
from app.agents.feedback_graph import build_feedback_graph
from app.agents.state import InvestigationState
from app.core.exceptions import ApplicationError, ErrorCode
from app.schemas.investigation import InvestigationRequest, InvestigationResponse
from app.services.sentiment_service import SentimentService
from app.tools.aggregation import generate_insights
from app.tools.evidence import verify_findings


class InvestigationService:
    """One selector call, at most ten sequential T01 analyses, no recursive loops."""

    def __init__(
        self, selector: Selector, sentiment_service: SentimentService, *, timeout_seconds: float = 120
    ) -> None:
        if not 0 < timeout_seconds <= 300:
            raise ValueError("Invalid investigation timeout.")
        self._timeout_seconds = timeout_seconds
        self._selector = selector
        self._investigation_admission: InvestigationAdmission | None = None
        self._graph = build_feedback_graph(selector, sentiment_service)

    def configure_admission(self, admission: ModelAdmission, investigations: InvestigationAdmission | None = None) -> None:
        """Bind the selector to the same application budget as its classifier."""
        if isinstance(self._selector, ActionSelector):
            self._selector.configure_admission(admission)
        self._investigation_admission = investigations

    async def investigate(self, request: InvestigationRequest) -> InvestigationResponse:
        if self._investigation_admission is None:
            return await self._investigate(request)
        async with self._investigation_admission.claim():
            return await self._investigate(request)

    async def _investigate(self, request: InvestigationRequest) -> InvestigationResponse:
        # Enforce the same bounds for non-HTTP callers, including constructed
        # or mutated Pydantic instances that bypassed ordinary input validation.
        try:
            request = InvestigationRequest.model_validate(request.model_dump(mode="json"))
        except (ValidationError, ValueError, TypeError, AttributeError):
            raise ApplicationError(ErrorCode.VALIDATION_ERROR) from None
        state: InvestigationState = {
            "request": request,
            "selected_action": None,
            "analysis_results": [],
            "sentiment_summary": None,
            "issue_summary": [],
            "evidence": [],
            "tools_used": [],
            "response": None,
        }
        try:
            # No checkpoint, cache, tracing, thread ID, or state retained on self.
            async with asyncio.timeout(self._timeout_seconds):
                with tracing_context(enabled=False):
                    final = await self._graph.ainvoke(state, config={"recursion_limit": 12})
            value = final["response"]
            if not isinstance(value, InvestigationResponse):
                raise ApplicationError(ErrorCode.INVALID_GRAPH_STATE)
            response = InvestigationResponse.model_validate(value.model_dump(mode="json"))
            if (
                response.question != request.question
                or response.total_feedback != len(request.feedback)
                or response.selected_action != final["selected_action"]
                or response.tools_used != [*final["tools_used"], "generate_insights"]
            ):
                raise ApplicationError(ErrorCode.INVALID_GRAPH_STATE)
            verify_findings(
                request, response.selected_action, final["analysis_results"],
                response.sentiment_summary, response.top_issues, response.evidence,
            )
            answer, recommendations = generate_insights(
                response.selected_action, final["analysis_results"], response.sentiment_summary,
                response.top_issues, response.evidence,
            )
            if response.answer != answer or response.recommendations != recommendations:
                raise ApplicationError(ErrorCode.EVIDENCE_VERIFICATION_FAILED)
            return response
        except ApplicationError:
            raise
        except TimeoutError:
            raise ApplicationError(ErrorCode.INVESTIGATION_TIMEOUT) from None
        except (GraphRecursionError, ValidationError, KeyError, TypeError, ValueError, AttributeError):
            raise ApplicationError(ErrorCode.INVALID_GRAPH_STATE) from None
        except Exception:
            raise ApplicationError(ErrorCode.INTERNAL_ERROR) from None
