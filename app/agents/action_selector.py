"""One-shot, strict, allowlisted language interpretation with no corpus access."""

import asyncio
from typing import Protocol

import groq
import httpx
from langchain_groq import ChatGroq
from langsmith import tracing_context
from pydantic import BaseModel, ValidationError

from app.core.config import Settings
from app.core.exceptions import ApplicationError, ErrorCode
from app.core.processing_limits import ModelAdmission
from app.prompts.investigation import action_messages
from app.schemas.investigation import ActionSelection
from app.schemas.sentiment import BusinessType
from app.services.sentiment_service import STRICT_MODELS, StructuredModel, classify_provider_error


class Selector(Protocol):
    async def select(self, question: str, business_type: BusinessType) -> ActionSelection: ...


class ActionSelector:
    """No fallback or selector retry; provider errors retain the T01 policy codes."""

    def __init__(
        self,
        model: StructuredModel | None,
        *,
        timeout_seconds: float = 30,
        configuration_error: ErrorCode = ErrorCode.GROQ_NOT_CONFIGURED,
        admission: ModelAdmission | None = None,
    ) -> None:
        if not 0 < timeout_seconds <= 120:
            raise ValueError("Invalid action selector timeout.")
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._configuration_error = configuration_error
        self._admission = admission

    def configure_admission(self, admission: ModelAdmission) -> None:
        self._admission = admission

    async def select(self, question: str, business_type: BusinessType) -> ActionSelection:
        if self._admission is None:
            return await self._select(question, business_type)
        async with self._admission.claim():
            return await self._select(question, business_type)

    async def _select(self, question: str, business_type: BusinessType) -> ActionSelection:
        if self._model is None:
            raise ApplicationError(self._configuration_error)
        try:
            async with asyncio.timeout(self._timeout_seconds):
                with tracing_context(enabled=False):
                    value = await self._model.ainvoke(action_messages(question, business_type))
            if isinstance(value, BaseModel):
                value = value.model_dump(mode="json")
            return ActionSelection.model_validate(value)
        except groq.APIError as error:
            code, _ = classify_provider_error(error)
            if code == ErrorCode.INVALID_MODEL_RESPONSE:
                code = ErrorCode.INVALID_ACTION_SELECTION
            raise ApplicationError(code) from None
        except TimeoutError:
            raise ApplicationError(ErrorCode.UPSTREAM_TIMEOUT) from None
        except (ValidationError, ValueError, TypeError):
            raise ApplicationError(ErrorCode.INVALID_ACTION_SELECTION) from None
        except Exception:
            raise ApplicationError(ErrorCode.INTERNAL_ERROR) from None


def create_action_selector(
    settings: Settings,
    *,
    http_client: httpx.Client,
    http_async_client: httpx.AsyncClient,
    admission: ModelAdmission | None = None,
) -> ActionSelector:
    """Use the same verified adapter configuration as T01, without tool calling."""
    if settings.groq_api_key is None:
        return ActionSelector(None, timeout_seconds=settings.groq_timeout_seconds, admission=admission)
    if settings.groq_model not in STRICT_MODELS:
        return ActionSelector(
            None, timeout_seconds=settings.groq_timeout_seconds,
            configuration_error=ErrorCode.GROQ_MODEL_UNSUPPORTED,
            admission=admission,
        )
    try:
        model = ChatGroq(
            model=settings.groq_model,
            api_key=settings.groq_api_key,
            timeout=settings.groq_timeout_seconds,
            max_retries=0,
            max_tokens=2048,
            temperature=0,
            streaming=False,
            cache=False,
            verbose=False,
            http_client=http_client,
            http_async_client=http_async_client,
        ).with_structured_output(ActionSelection, method="json_schema", strict=True)
    except (ValueError, TypeError):
        return ActionSelector(
            None, timeout_seconds=settings.groq_timeout_seconds,
            configuration_error=ErrorCode.GROQ_CONFIGURATION_ERROR,
            admission=admission,
        )
    return ActionSelector(model, timeout_seconds=settings.groq_timeout_seconds, admission=admission)
