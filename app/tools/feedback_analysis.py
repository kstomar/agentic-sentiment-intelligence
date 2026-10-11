"""Request-local sequential analysis using only the existing T01 service."""

from app.schemas.investigation import AnalyzedFeedback, InvestigationRequest
from app.schemas.sentiment import SentimentRequest
from app.services.sentiment_service import SentimentService


async def analyze_feedback_items(
    request: InvestigationRequest, sentiment_service: SentimentService
) -> list[AnalyzedFeedback]:
    """Fail fast on any record error; never expose an incomplete dataset as complete."""
    results: list[AnalyzedFeedback] = []
    for item in request.feedback:
        analysis = await sentiment_service.analyze(
            SentimentRequest(text=item.text, business_type=request.business_type)
        )
        results.append(AnalyzedFeedback(feedback_id=item.id, analysis=analysis))
    return results
