"""Safe, consistent API error and health response contracts."""

from typing import Literal

from pydantic import BaseModel

from app.core.exceptions import ErrorCode


class ValidationIssue(BaseModel):
    field: str
    code: str
    message: str


class ErrorDetail(BaseModel):
    code: ErrorCode
    message: str
    details: list[ValidationIssue] | None = None


class ErrorResponse(BaseModel):
    error: ErrorDetail
    request_id: str


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
