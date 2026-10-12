"""One independent T01 analysis per record; no batch prompt or new Groq client."""

from pydantic import ValidationError

from app.core.exceptions import ApplicationError, ErrorCode
from app.schemas.batch import BatchResult, ParsedRecord, RecordState
from app.schemas.sentiment import BusinessType, SentimentRequest, SentimentResponse
from app.services.sentiment_service import SentimentService


def failed_result(record: ParsedRecord, error: ErrorCode, *, attempted: bool = False) -> BatchResult:
    return BatchResult(**record.meta.model_dump(), status=RecordState.FAILED, attempted=attempted, error_code=error)


async def analyze_record(
    record: ParsedRecord, business_type: BusinessType, sentiment_service: SentimentService
) -> BatchResult:
    if record.validation_error is not None or record.text is None:
        return failed_result(record, record.validation_error or ErrorCode.BATCH_INVALID_TEXT)
    try:
        # file_upload remains job metadata; T01's existing source contract stays
        # unchanged. Source IDs/dates and other records never enter this prompt.
        analysis = await sentiment_service.analyze(SentimentRequest(text=record.text, business_type=business_type))
        analysis = SentimentResponse.model_validate(
            analysis.model_dump(mode="json"), context={"feedback_text": record.text}
        )
        return BatchResult(
            **record.meta.model_dump(), **analysis.model_dump(), status=RecordState.SUCCESS, attempted=True,
        )
    except ApplicationError as error:
        return failed_result(record, error.code, attempted=True)
    except (ValidationError, ValueError, TypeError, AttributeError):
        return failed_result(record, ErrorCode.INVALID_MODEL_RESPONSE, attempted=True)
    except Exception:
        return failed_result(record, ErrorCode.INTERNAL_ERROR, attempted=True)
