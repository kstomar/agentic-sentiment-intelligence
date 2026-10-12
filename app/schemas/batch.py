"""Validated bulk-job contracts; raw text is never part of a public result."""

from datetime import date
from enum import StrEnum
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.exceptions import ErrorCode
from app.schemas.sentiment import Aspect, BusinessType, IssueCategory, Sentiment, SentimentResponse, Urgency

Count = Annotated[int, Field(strict=True, ge=0)]
ColumnName = Annotated[str, Field(min_length=1, max_length=128)]
JobID = Annotated[str, Field(pattern=r"^[0-9a-f]{32}$")]


class BatchModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True, allow_inf_nan=False)


class JobState(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    PARTIAL_SUCCESS = "PARTIAL_SUCCESS"
    FAILED = "FAILED"


TERMINAL_STATES = frozenset({JobState.COMPLETED, JobState.PARTIAL_SUCCESS, JobState.FAILED})


class DateState(StrEnum):
    NOT_PROVIDED = "NOT_PROVIDED"
    MISSING = "MISSING"
    VALID = "VALID"
    INVALID = "INVALID"


class RecordState(StrEnum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


class UploadOptions(BatchModel):
    text_column: ColumnName
    id_column: ColumnName | None = None
    date_column: ColumnName | None = None
    business_type: BusinessType = "general"
    source: str = Field(default="file_upload", min_length=1, max_length=64)

    @field_validator("text_column", "id_column", "date_column", "source")
    @classmethod
    def nonblank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not value.strip():
            raise ValueError("Column names and source must be nonblank.")
        return value.strip()

    @model_validator(mode="after")
    def distinct_mapping(self) -> Self:
        columns = [x for x in [self.text_column, self.id_column, self.date_column] if x is not None]
        if len(columns) != len(set(columns)):
            raise ValueError("Mapped columns must be distinct.")
        return self


class RecordMetadata(BatchModel):
    feedback_id: str = Field(min_length=1, max_length=100)
    source_row: int = Field(strict=True, ge=2)
    normalized_date: date | None = None
    date_status: DateState = DateState.NOT_PROVIDED

    @model_validator(mode="after")
    def date_consistent(self) -> Self:
        if (self.date_status == DateState.VALID) != (self.normalized_date is not None):
            raise ValueError("Only valid source dates may have a normalized date.")
        return self


class ParsedRecord(BaseModel):
    """Internal temporary input; text is excluded from repr and serialization."""

    meta: RecordMetadata
    text: str | None = Field(default=None, exclude=True, repr=False)
    validation_error: ErrorCode | None = None


class BatchResult(RecordMetadata):
    status: RecordState
    attempted: bool
    error_code: ErrorCode | None = None
    sentiment: Sentiment | None = None
    issue_category: IssueCategory | None = None
    urgency: Urgency | None = None
    aspects: list[Aspect] = Field(default_factory=list)
    summary: str | None = None
    suggested_next_step: str | None = None
    evidence_phrases: list[str] = Field(default_factory=list)

    def analysis_data(self) -> dict[str, object]:
        return {name: getattr(self, name) for name in SentimentResponse.model_fields}

    @model_validator(mode="after")
    def result_consistent(self) -> Self:
        if self.status == RecordState.SUCCESS:
            if self.error_code is not None or not self.attempted:
                raise ValueError("Successful results require an analysis attempt and no error.")
            SentimentResponse.model_validate(self.analysis_data())
        elif (
            self.error_code is None or self.aspects or self.evidence_phrases
            or any(getattr(self, name) is not None for name in [
                "sentiment", "issue_category", "urgency", "summary", "suggested_next_step",
            ])
        ):
            raise ValueError("Failed records require an error without invented analysis.")
        return self


class JobAccepted(BatchModel):
    job_id: JobID
    status: JobState = JobState.PENDING
    total_records: int = Field(ge=1)
    message: str = "Bulk analysis job accepted."


class JobStatus(BatchModel):
    job_id: JobID
    status: JobState
    total_records: int = Field(ge=1)
    processed_records: Count
    successful_records: Count
    failed_records: Count
    progress_percentage: float = Field(ge=0, le=100)
    error_code: ErrorCode | None = None

    @model_validator(mode="after")
    def reconcile(self) -> Self:
        if self.successful_records + self.failed_records != self.processed_records:
            raise ValueError("Processed counts must reconcile.")
        if self.processed_records > self.total_records:
            raise ValueError("Progress cannot exceed the dataset.")
        if self.progress_percentage != round(self.processed_records * 100 / self.total_records, 2):
            raise ValueError("Progress must reflect settled records.")
        if self.status in TERMINAL_STATES and self.processed_records != self.total_records:
            raise ValueError("Terminal jobs cannot have unsettled records.")
        if self.status == JobState.COMPLETED and self.failed_records:
            raise ValueError("Completed jobs cannot contain failures.")
        if self.status == JobState.PARTIAL_SUCCESS and not (self.successful_records and self.failed_records):
            raise ValueError("Partial jobs require both successes and failures.")
        if self.status == JobState.FAILED and self.successful_records:
            raise ValueError("Failed jobs cannot expose successful findings.")
        return self


class IssueAggregate(BatchModel):
    category: IssueCategory
    count: int = Field(ge=1)
    feedback_ids: list[str]

    @model_validator(mode="after")
    def unique_count(self) -> Self:
        if self.count != len(self.feedback_ids) or len(set(self.feedback_ids)) != self.count:
            raise ValueError("Category counts require unique supporting records.")
        return self


class AspectAggregate(BatchModel):
    name: str
    count: int = Field(ge=1)
    sentiment_distribution: dict[Sentiment, Count]
    feedback_ids: list[str]

    @model_validator(mode="after")
    def unique_mentions(self) -> Self:
        if set(self.sentiment_distribution) != set(Sentiment):
            raise ValueError("Every aspect sentiment count must be present.")
        if sum(self.sentiment_distribution.values()) != self.count or len(set(self.feedback_ids)) != self.count:
            raise ValueError("Aspect counts must reconcile to unique records.")
        return self


class ReportEvidence(BatchModel):
    feedback_id: str
    source_row: int
    text_excerpt: str = Field(min_length=1, max_length=500)


class BatchReport(JobStatus):
    business_type: BusinessType
    source: str
    valid_records: Count
    invalid_records: Count
    attempted_records: Count
    unattempted_valid_records: Count
    skipped_blank_rows: Count
    invalid_date_records: Count
    sentiment_distribution: dict[Sentiment, Count]
    sentiment_percentages: dict[Sentiment, float]
    percentage_denominator: str = "successful_records"
    issue_categories: list[IssueAggregate]
    top_issues: list[IssueAggregate]
    top_aspects: list[AspectAggregate] = Field(max_length=20)
    evidence: list[ReportEvidence] = Field(max_length=20)
    recommendations: list[str]
    limitations: list[str]

    @model_validator(mode="after")
    def totals(self) -> Self:
        if self.status not in TERMINAL_STATES:
            raise ValueError("Reports require terminal jobs.")
        if self.valid_records + self.invalid_records != self.total_records:
            raise ValueError("Input validation counts must reconcile.")
        if self.attempted_records + self.unattempted_valid_records != self.valid_records:
            raise ValueError("Attempt counts must reconcile.")
        if set(self.sentiment_distribution) != set(Sentiment) or set(self.sentiment_percentages) != set(Sentiment):
            raise ValueError("Every sentiment must be reported.")
        if sum(self.sentiment_distribution.values()) != self.successful_records:
            raise ValueError("Distribution must count successful results only.")
        if round(sum(self.sentiment_percentages.values()), 2) != (100 if self.successful_records else 0):
            raise ValueError("Percentages must reconcile.")
        if sum(x.count for x in self.issue_categories) != self.successful_records:
            raise ValueError("Issue categories must count each successful record once.")
        return self


class ResultsPage(BatchModel):
    job_id: JobID
    status: JobState
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)
    total_results: Count
    results: list[BatchResult]


class BatchDownload(BatchModel):
    report: BatchReport
    results: list[BatchResult]
