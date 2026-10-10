"""Reusable asynchronous sentiment service with no FastAPI dependency."""

import asyncio
import logging
import time
from typing import Literal, Protocol

import groq
import httpx
from langchain_groq import ChatGroq
from langchain_core.exceptions import OutputParserException
from langsmith import tracing_context
from pydantic import BaseModel, ValidationError

from app.core.config import Settings
from app.core.exceptions import ApplicationError, ErrorCode
from app.core.processing_limits import ModelAdmission
from app.prompts.sentiment import build_messages
from app.schemas.sentiment import SentimentRequest, SentimentResponse

# langchain-groq 1.1.3 forwards strict=True only for these models. Reject other
# configurations instead of letting the adapter silently omit strict enforcement.
STRICT_MODELS = frozenset({"openai/gpt-oss-20b", "openai/gpt-oss-120b"})
logger = logging.getLogger("app.sentiment")

DiagnosticCategory = Literal[
    "groq_sdk_response_validation", "structured_output_parsing", "unexpected_output_type",
    "pydantic_schema_validation", "exact_evidence_grounding", "output_processing_error",
]
DiagnosticStage = Literal["adapter", "normalization", "service"]


def _log_invalid_output(
    category: DiagnosticCategory, stage: DiagnosticStage, validation: ValidationError | None = None,
) -> None:
    """Emit fixed categories and allowlisted schema paths, never error text/input.

    Extra-field locations can contain arbitrary model/customer text. Match only
    complete known paths and collapse everything else to a fixed response marker.
    Do not stringify exceptions, their causes, parser llm_output or error contexts.
    """
    fields: set[str] = set()
    if validation is not None:
        for error in validation.errors(include_url=False, include_context=False, include_input=False):
            loc = error["loc"]
            if error["type"] == "evidence_not_grounded":
                fields.add("evidence_phrases")
            elif len(loc) == 1 and loc[0] in SentimentResponse.model_fields:
                fields.add(loc[0])
            elif len(loc) == 2 and loc[0] == "evidence_phrases" and type(loc[1]) is int:
                fields.add("evidence_phrases")
            elif (len(loc) == 3 and loc[0] == "aspects" and type(loc[1]) is int
                  and loc[2] in {"name", "sentiment"}):
                fields.add("aspects." + loc[2])
            else:
                fields.add("response")
    logger.warning("sentiment_output_rejected category=%s stage=%s fields=%s",
                   category, stage, ",".join(sorted(fields)) or "response")


def _log_validation_error(error: ValidationError, stage: DiagnosticStage) -> None:
    grounding = any(item["type"] == "evidence_not_grounded" for item in error.errors(
        include_url=False, include_context=False, include_input=False,
    ))
    _log_invalid_output("exact_evidence_grounding" if grounding else "pydantic_schema_validation", stage, error)


def _only_evidence_grounding_failed(error: ValidationError) -> bool:
    errors = error.errors(include_url=False, include_context=False, include_input=False)
    return bool(errors) and all(
        item["type"] == "evidence_not_grounded" and item["loc"] == () for item in errors
    )


class StructuredModel(Protocol):
    """Minimal injectable model interface; callers need no HTTP framework."""

    async def ainvoke(self, input: list[tuple[str, str]]) -> object: ...


def classify_provider_error(error: groq.APIError) -> tuple[ErrorCode, bool]:
    """Classify exceptions by type/status only, never expose their body or text."""
    if isinstance(error, groq.APITimeoutError):
        return ErrorCode.UPSTREAM_TIMEOUT, True
    if isinstance(error, groq.APIConnectionError):
        return ErrorCode.UPSTREAM_UNAVAILABLE, True
    if isinstance(error, groq.APIResponseValidationError):
        return ErrorCode.INVALID_MODEL_RESPONSE, False
    if isinstance(error, groq.APIStatusError):
        if error.status_code in {401, 403}:
            return ErrorCode.UPSTREAM_AUTHENTICATION_FAILED, False
        if error.status_code == 429:
            return ErrorCode.UPSTREAM_RATE_LIMITED, True
        if error.status_code == 408:
            return ErrorCode.UPSTREAM_TIMEOUT, True
        if error.status_code == 409 or error.status_code >= 500:
            return ErrorCode.UPSTREAM_UNAVAILABLE, True
        return ErrorCode.UPSTREAM_REQUEST_REJECTED, False
    return ErrorCode.UPSTREAM_UNAVAILABLE, False


class SentimentService:
    """Analyze validated input with one shared implementation and bounded retries."""

    def __init__(
        self,
        model: StructuredModel | None,
        *,
        timeout_seconds: float = 30,
        max_retries: int = 2,
        configuration_error: ErrorCode = ErrorCode.GROQ_NOT_CONFIGURED,
        admission: ModelAdmission | None = None,
    ) -> None:
        if not 0 < timeout_seconds <= 120 or not 0 <= max_retries <= 3:
            raise ValueError("Invalid sentiment service timeout or retry limit.")
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._max_retries = max_retries
        self._configuration_error = configuration_error
        self._admission = admission

    @property
    def configuration_error(self) -> ErrorCode | None:
        """Inspect local readiness without a provider request or credential exposure."""
        return self._configuration_error if self._model is None else None

    def configure_admission(self, admission: ModelAdmission) -> None:
        """Bind the owning application's shared budget before requests start."""
        self._admission = admission

    async def analyze(self, request: SentimentRequest) -> SentimentResponse:
        """Return only validated output with input-grounded evidence phrases."""
        if self._admission is None:
            return await self._analyze(request)
        async with self._admission.claim():
            return await self._analyze(request)

    async def _analyze(self, request: SentimentRequest) -> SentimentResponse:
        if self._model is None:
            raise ApplicationError(self._configuration_error)
        # Keep the original feedback/context stable across awaits and recovery,
        # including when a direct Python caller retains the mutable input model.
        request = request.model_copy()
        deadline = time.monotonic() + self._timeout_seconds
        recovering_evidence = False
        stage: DiagnosticStage = "adapter"
        try:
            # One wall-clock budget covers all calls and backoff. Tracing is
            # disabled context-locally so feedback is not sent to LangSmith.
            async with asyncio.timeout(self._timeout_seconds):
                with tracing_context(enabled=False):
                    # Existing transport attempts plus ONE correction invocation.
                    # The correction has no separate transport-retry loop/budget.
                    for attempt in range(self._max_retries + 2):
                        if time.monotonic() >= deadline:
                            raise ApplicationError(ErrorCode.UPSTREAM_TIMEOUT)
                        stage = "adapter"
                        try:
                            result = await self._model.ainvoke(build_messages(request, evidence_recovery=recovering_evidence))
                        except groq.APIError as error:
                            if isinstance(error, groq.APIResponseValidationError):
                                _log_invalid_output("groq_sdk_response_validation", "adapter")
                            code, retryable = classify_provider_error(error)
                            if recovering_evidence or not retryable or attempt == self._max_retries:
                                raise ApplicationError(code) from None
                            delay = 0.5 * 2**attempt
                            if isinstance(error, groq.APIStatusError):
                                retry_after = error.response.headers.get("retry-after")
                                if retry_after is not None:
                                    try:
                                        delay = max(delay, float(retry_after))
                                    except ValueError:
                                        pass
                            if delay >= deadline - time.monotonic():
                                raise ApplicationError(code) from None
                            await asyncio.sleep(delay)
                            continue
                        stage = "normalization"
                        if isinstance(result, BaseModel):
                            result = result.model_dump(mode="json")
                        if not isinstance(result, dict):
                            _log_invalid_output("unexpected_output_type", stage)
                            raise ApplicationError(ErrorCode.INVALID_MODEL_RESPONSE)
                        stage = "service"
                        try:
                            validated = SentimentResponse.model_validate(
                                result, context={"feedback_text": request.text}
                            )
                        except ValidationError as error:
                            _log_validation_error(error, stage)
                            if _only_evidence_grounding_failed(error):
                                if not recovering_evidence:
                                    recovering_evidence = True
                                    result = None  # Never replay rejected output/error text to the model.
                                    continue
                                # Only the corrected, otherwise valid response
                                # qualifies. Drop nonexact phrases; do not repair
                                # text, change other fields or bypass validation.
                                if time.monotonic() >= deadline:
                                    raise ApplicationError(ErrorCode.UPSTREAM_TIMEOUT)
                                evidence = result["evidence_phrases"]
                                retained = [phrase for phrase in evidence if phrase in request.text]
                                validated = SentimentResponse.model_validate(
                                    {**result, "evidence_phrases": retained},
                                    context={"feedback_text": request.text},
                                )
                                if time.monotonic() >= deadline:
                                    raise ApplicationError(ErrorCode.UPSTREAM_TIMEOUT)
                                logger.info("sentiment_output_sanitized category=exact_evidence_grounding retained=%d discarded=%d",
                                            len(retained), len(evidence) - len(retained))
                                return validated
                            raise ApplicationError(ErrorCode.INVALID_MODEL_RESPONSE) from None
                        if recovering_evidence:
                            logger.info("sentiment_output_recovered category=exact_evidence_grounding")
                        return validated
        except TimeoutError:
            raise ApplicationError(ErrorCode.UPSTREAM_TIMEOUT) from None
        except ApplicationError:
            raise
        except OutputParserException as error:
            # The installed PydanticOutputParser wraps schema errors with their
            # ValidationError as the direct cause; JSON failures have other causes.
            if isinstance(error.__cause__, ValidationError):
                _log_validation_error(error.__cause__, "adapter")
            else:
                _log_invalid_output("structured_output_parsing", "adapter")
            raise ApplicationError(ErrorCode.INVALID_MODEL_RESPONSE) from None
        except ValidationError as error:
            _log_validation_error(error, stage)
            raise ApplicationError(ErrorCode.INVALID_MODEL_RESPONSE) from None
        except (ValueError, TypeError):
            # Preserve the old controlled mapping for other adapter/output errors.
            _log_invalid_output("output_processing_error", stage)
            raise ApplicationError(ErrorCode.INVALID_MODEL_RESPONSE) from None
        except Exception:
            raise ApplicationError(ErrorCode.INTERNAL_ERROR) from None
        raise ApplicationError(ErrorCode.INTERNAL_ERROR)


def create_sentiment_service(
    settings: Settings,
    *,
    http_client: httpx.Client,
    http_async_client: httpx.AsyncClient,
    admission: ModelAdmission | None = None,
) -> SentimentService:
    """Build a strict adapter without making network requests at startup."""
    if settings.groq_api_key is None:
        return SentimentService(
            None,
            timeout_seconds=settings.groq_timeout_seconds,
            max_retries=settings.groq_max_retries,
            admission=admission,
        )
    if settings.groq_model not in STRICT_MODELS:
        return SentimentService(
            None,
            timeout_seconds=settings.groq_timeout_seconds,
            max_retries=settings.groq_max_retries,
            configuration_error=ErrorCode.GROQ_MODEL_UNSUPPORTED,
            admission=admission,
        )
    try:
        model = ChatGroq(
            model=settings.groq_model,
            api_key=settings.groq_api_key,
            timeout=settings.groq_timeout_seconds,
            max_retries=0,  # Only the service retries, with explicit status rules.
            max_tokens=2048,
            temperature=0,
            streaming=False,
            cache=False,
            verbose=False,
            http_client=http_client,
            http_async_client=http_async_client,
        ).with_structured_output(SentimentResponse, method="json_schema", strict=True)
    except (ValueError, TypeError):
        return SentimentService(
            None,
            timeout_seconds=settings.groq_timeout_seconds,
            max_retries=settings.groq_max_retries,
            configuration_error=ErrorCode.GROQ_CONFIGURATION_ERROR,
            admission=admission,
        )
    return SentimentService(
        model,
        timeout_seconds=settings.groq_timeout_seconds,
        max_retries=settings.groq_max_retries,
        admission=admission,
    )
