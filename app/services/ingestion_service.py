"""Transport-independent normalization and delegation to the existing classifier."""

from app.schemas.ingestion import IngestionRequest, IngestionResponse, WebhookPayload
from app.schemas.sentiment import SentimentRequest, SentimentResponse
from app.services.sentiment_service import SentimentService


def normalize_event(payload: WebhookPayload) -> IngestionRequest:
    return IngestionRequest(
        feedback_id=payload.feedback.id, text=payload.feedback.text, channel="external_api",
        source=payload.source, business_type=payload.business_type,
    )


class IngestionService:
    def __init__(self, sentiment: SentimentService) -> None:
        self.sentiment = sentiment

    async def analyze(self, request: IngestionRequest) -> IngestionResponse:
        request = IngestionRequest.model_validate(request.model_dump())
        result = await self.sentiment.analyze(SentimentRequest(
            text=request.text, source=request.source, business_type=request.business_type,
        ))
        validated = SentimentResponse.model_validate(result.model_dump(), context={"feedback_text": request.text})
        return IngestionResponse(feedback_id=request.feedback_id, channel=request.channel, analysis=validated)
