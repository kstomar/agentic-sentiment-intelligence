import pytest

from app.schemas.batch import JobState, UploadOptions
from app.schemas.sentiment import Sentiment
from app.services.file_parser import FileParser
from app.services.reporting_service import ReportingService, percentages
from app.storage.job_store import JobStore
from app.tools.batch_analysis import analyze_record
from tests.helpers import Model, analysis, harness


@pytest.mark.parametrize("counts,expected", [
    ([0,0,0,0], [0,0,0,0]), ([1,1,1,0], [33.34,33.33,33.33,0]), ([1,3,0,0], [25,75,0,0]),
])
def test_deterministic_percentage_denominator_and_rounding(counts, expected):
    result = percentages(dict(zip(Sentiment, counts)))
    assert list(result.values()) == expected
    assert round(sum(result.values()), 2) == (100 if sum(counts) else 0)


async def test_reporting_unique_aspects_and_supporting_ids():
    options = UploadOptions(text_column="review", id_column="id")
    parsed = FileParser(max_bytes=1024, max_records=100, max_text=5000, max_extracted=1024).parse(
        b"id,review\nB,b\nA,a", "safe.csv", "text/csv", options)
    model = Model(outputs={"a": analysis("a", aspects=[
        {"name": "delivery", "sentiment": "POSITIVE"}, {"name": "delivery", "sentiment": "NEGATIVE"}])})
    job = JobStore(30).add(options, parsed.records, 0)
    job.status = JobState.RUNNING
    job.results = [await analyze_record(row, "general", harness(model=model).sentiment) for row in parsed.records]
    report = ReportingService().build(job, JobState.COMPLETED)
    assert report.sentiment_distribution[Sentiment.NEGATIVE] == 2
    assert report.top_issues[0].feedback_ids == ["A", "B"]
    assert report.top_aspects[0].count == 2
    assert report.top_aspects[0].sentiment_distribution[Sentiment.MIXED] == 1
    assert report.top_aspects[0].sentiment_distribution[Sentiment.NEGATIVE] == 1
    assert {e.feedback_id for e in report.evidence} == {"A", "B"}
    assert ReportingService().build(job, JobState.COMPLETED) == report


async def test_reporting_rejects_foreign_source_metadata():
    options = UploadOptions(text_column="review")
    parsed = FileParser(max_bytes=1024, max_records=100, max_text=5000, max_extracted=1024).parse(
        b"review\na", "safe.csv", "text/csv", options)
    job = JobStore(30).add(options, parsed.records, 0)
    row = await analyze_record(parsed.records[0], "general", harness().sentiment)
    job.results = [row.model_copy(update={"feedback_id": "invented"})]
    from app.core.exceptions import ApplicationError
    with pytest.raises(ApplicationError):
        ReportingService().build(job, JobState.COMPLETED)
