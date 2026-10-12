"""Local stdio MCP composition, shared service lifespan, and sanitized tool boundary."""

import logging
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
from mcp.server import MCPServer
from mcp.server.mcpserver import Context
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import CallToolResult, InputRequiredResult
from pydantic import ValidationError

from app.agents.action_selector import create_action_selector
from app.core.config import Settings
from app.core.exceptions import ERROR_MESSAGES, ApplicationError, ErrorCode
from app.mcp_server.tools import AnalysisServices, register_tools
from app.schemas.investigation import InvestigationRequest
from app.schemas.sentiment import SentimentRequest
from app.services.investigation_service import InvestigationService
from app.services.sentiment_service import SentimentService, create_sentiment_service

logger = logging.getLogger("app.mcp")

REQUEST_MODELS = {
    "analyze_feedback": SentimentRequest,
    "investigate_feedback": InvestigationRequest,
}
INPUT_GUIDANCE = {
    "analyze_feedback": "Supply nonblank text of at most 5000 characters and allowed source/business_type values; omit unknown fields.",
    "investigate_feedback": "Supply a nonblank question of at most 500 characters and 1–10 feedback records with unique nonblank IDs and valid text; omit unknown fields.",
}


def _service_error(error: Exception) -> ErrorCode:
    """Recover known service codes through SDK wrappers, never their message text."""
    current: BaseException | None = error
    for _ in range(8):
        if isinstance(current, ApplicationError):
            return current.code
        current = current.__cause__ if current is not None else None
    return ErrorCode.INTERNAL_ERROR


class AnalysisMCPServer(MCPServer[AnalysisServices]):
    """Use the public call_tool seam to validate before SDK coercion/error echoing."""

    def __init__(self, *, max_concurrent_calls: int, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._max_concurrent_calls = max_concurrent_calls
        self._active_calls = 0

    async def call_tool(
        self, name: str, arguments: dict[str, Any], context: Context[AnalysisServices, Any] | None = None,
    ) -> CallToolResult | InputRequiredResult:
        model = REQUEST_MODELS.get(name)
        if model is None:
            raise ToolError("VALIDATION_ERROR: Unknown tool. Discover the two supported tools with tools/list.") from None
        try:
            # Enforce full REST validators, extra='forbid', and real JSON arrays
            # before the SDK's more permissive function argument parsing runs.
            model.model_validate(arguments)
        except (ValidationError, ValueError, TypeError):
            raise ToolError(f"VALIDATION_ERROR: {INPUT_GUIDANCE[name]}") from None
        if self._active_calls >= self._max_concurrent_calls:
            raise ToolError("MCP_BUSY: Concurrent tool-call capacity is full. Retry after an active call finishes.") from None
        self._active_calls += 1
        try:
            return await super().call_tool(name, arguments, context)
        except Exception as error:
            code = _service_error(error)
            logger.warning("mcp_tool_rejected code=%s", code.value)
            raise ToolError(f"{code.value}: {ERROR_MESSAGES[code]}") from None
        finally:
            self._active_calls -= 1


def create_mcp_server(
    settings: Settings | None = None, *, sentiment_service: SentimentService | None = None,
    investigation_service: InvestigationService | None = None,
) -> AnalysisMCPServer:
    """Build without network calls; injected services remain owned by their caller."""
    settings = settings if settings is not None else Settings()
    # SDK validation/traceback logs can contain peer data. Application diagnostics
    # below use fixed codes only, including when LOG_LEVEL=DEBUG.
    for name in (
        "mcp", "groq", "httpx", "httpx2", "httpcore", "httpcore2", "langchain",
        "langchain_core", "langchain_groq", "langsmith", "langgraph",
    ):
        logging.getLogger(name).setLevel(logging.CRITICAL)

    @asynccontextmanager
    async def lifespan(server: MCPServer[AnalysisServices]) -> AsyncIterator[AnalysisServices]:
        with httpx.Client(timeout=settings.groq_timeout_seconds) as sync_client:
            async with httpx.AsyncClient(timeout=settings.groq_timeout_seconds) as async_client:
                shared_sentiment = sentiment_service
                if shared_sentiment is None:
                    shared_sentiment = create_sentiment_service(
                        settings, http_client=sync_client, http_async_client=async_client,
                    )
                shared_investigation = investigation_service
                if shared_investigation is None:
                    shared_investigation = InvestigationService(
                        create_action_selector(settings, http_client=sync_client, http_async_client=async_client),
                        shared_sentiment, timeout_seconds=settings.investigation_timeout_seconds,
                    )
                yield AnalysisServices(shared_sentiment, shared_investigation)

    server = AnalysisMCPServer(
        name="Agentic Sentiment Intelligence", version="0.1.0",
        instructions=(
            "Analyze only feedback supplied in this call. Use analyze_feedback for one text or "
            "investigate_feedback for 1–10 records and a question. Results are model classifications "
            "and tentative suggestions, not verified business facts. No batch lookup, memory, or external actions."
        ),
        lifespan=lifespan, debug=False, log_level="CRITICAL", subscriptions=False,
        max_concurrent_calls=settings.mcp_max_concurrent_calls,
    )
    register_tools(server)
    return server


def main() -> int:
    """Reserve stdout for protocol frames; startup/transport failures are sanitized."""
    logging.basicConfig(
        level=logging.WARNING, format="%(levelname)s %(name)s %(message)s", stream=sys.stderr, force=True,
    )
    try:
        create_mcp_server().run(transport="stdio")
    except KeyboardInterrupt:
        return 0
    except Exception:
        logger.error("mcp_server_stopped code=INTERNAL_ERROR")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
