"""Stateless coordination of existing analysis services, without new model calls."""

from typing import cast

from pydantic import ValidationError

from app.core.exceptions import ApplicationError, ErrorCode
from app.schemas.chat import ChatMode, ChatRequest, ChatResponse
from app.schemas.investigation import FeedbackItem, InvestigationRequest
from app.schemas.sentiment import SentimentRequest
from app.services.investigation_service import InvestigationService
from app.services.sentiment_service import SentimentService

STATELESS_LIMITATION = "Requests are stateless; include the relevant feedback again for each question."


class ConversationService:
    """Delegate once by explicit mode; retain service dependencies, never conversations."""

    def __init__(
        self, sentiment_service: SentimentService, investigation_service: InvestigationService
    ) -> None:
        self._sentiment_service = sentiment_service
        self._investigation_service = investigation_service

    async def respond(self, request: ChatRequest) -> ChatResponse:
        """Use current-request data only and preserve existing controlled errors."""
        try:
            request = ChatRequest.model_validate(request.model_dump(mode="json"))
        except (ValidationError, ValueError, TypeError, AttributeError):
            raise ApplicationError(ErrorCode.VALIDATION_ERROR) from None
        if request.mode == ChatMode.ANALYZE_TEXT:
            # The conversational instruction is deliberately not classified as
            # feedback, appended to the prompt, or sent to another model.
            analysis = await self._sentiment_service.analyze(
                SentimentRequest(
                    text=cast(str, request.feedback_text), business_type=request.business_type
                )
            )
            answer = (
                f"The feedback is classified as {analysis.sentiment.value.lower()} sentiment. "
                f"The primary category is {analysis.issue_category.value.lower().replace('_', ' ')}. "
                f"Suggested triage urgency is {analysis.urgency.value.lower()}; "
                "this is not a verified safety assessment."
            )
            return ChatResponse(
                mode=request.mode,
                answer=answer,
                sentiment_analysis=analysis,
                investigation=None,
                limitations=[
                    "Analysis is based only on the feedback supplied in this request.",
                    "Classifications are model inferences, not independently verified business facts.",
                    STATELESS_LIMITATION,
                ],
            )
        investigation = await self._investigation_service.investigate(
            InvestigationRequest(
                question=request.message,
                business_type=request.business_type,
                feedback=cast(list[FeedbackItem], request.feedback),
            )
        )
        return ChatResponse(
            mode=request.mode,
            answer=investigation.answer,
            sentiment_analysis=None,
            investigation=investigation,
            limitations=list(dict.fromkeys([*investigation.limitations, STATELESS_LIMITATION])),
        )
