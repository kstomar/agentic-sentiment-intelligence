"""Two typed MCP adapters over the existing analysis services, without HTTP calls."""

from dataclasses import dataclass

from mcp.server import MCPServer
from mcp.server.mcpserver import Context

from app.schemas.investigation import FeedbackBatch, InvestigationRequest, InvestigationResponse, QuestionText
from app.schemas.sentiment import (
    BusinessType, FeedbackSource, FeedbackText, SentimentRequest, SentimentResponse,
)
from app.services.investigation_service import InvestigationService
from app.services.sentiment_service import SentimentService


@dataclass(frozen=True, slots=True)
class AnalysisServices:
    """Lifespan-owned references only; no feedback, credentials, or job access."""

    sentiment: SentimentService
    investigation: InvestigationService


def register_tools(server: MCPServer[AnalysisServices]) -> None:
    """Register only approved processors; Context is injected, never a tool input."""

    @server.tool(structured_output=True)
    async def analyze_feedback(
        text: FeedbackText,
        ctx: Context[AnalysisServices, None],
        source: FeedbackSource = "manual",
        business_type: BusinessType = "general",
    ) -> SentimentResponse:
        """Classify one nonblank feedback text (at most 5000 characters) using T01.

        Sources and business types use the REST allowlists. Unknown arguments are
        rejected. Returns sentiment, primary issue category, suggested urgency,
        aspects, summary, suggested next step, and exact source evidence phrases.
        Classification and urgency are model inferences, not verified business
        facts or actions taken. Sends this text to the configured Groq provider.
        """
        request = SentimentRequest(text=text, source=source, business_type=business_type)
        return await ctx.request_context.lifespan_context.sentiment.analyze(request)

    @server.tool(structured_output=True)
    async def investigate_feedback(
        question: QuestionText,
        feedback: FeedbackBatch,
        ctx: Context[AnalysisServices, None],
        business_type: BusinessType = "general",
    ) -> InvestigationResponse:
        """Answer a question using the existing bounded T02 LangGraph workflow.

        Supply a nonblank question of at most 500 characters and 1–10 feedback
        records, each with a unique nonblank ID (at most 100 characters) and
        nonblank text (at most 5000 characters). Unknown arguments are rejected.
        Returns the existing verified findings, counts, supporting evidence,
        tools used, limitations, and tentative recommendations. Fail-fast on any
        record error; no memory or external records. Evidence may contain the
        original supplied text. Uses the configured Groq provider.
        """
        request = InvestigationRequest(question=question, feedback=feedback, business_type=business_type)
        return await ctx.request_context.lifespan_context.investigation.investigate(request)
