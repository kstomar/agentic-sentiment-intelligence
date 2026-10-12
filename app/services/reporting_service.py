"""Deterministic reduction of validated results, without original review text."""

from collections import defaultdict

import pandas as pd

from app.core.exceptions import ApplicationError, ErrorCode
from app.schemas.batch import (
    AspectAggregate, BatchReport, DateState, IssueAggregate, JobState, RecordState, ReportEvidence,
)
from app.schemas.sentiment import Sentiment
from app.storage.job_store import Job
from app.tools.statistics import count_sentiments, group_issue_ids


def percentages(counts: dict[Sentiment, int]) -> dict[Sentiment, float]:
    """Largest-remainder basis points: exactly 100%, or all zeros without success."""
    total = sum(counts.values())
    if not total:
        return {sentiment: 0.0 for sentiment in Sentiment}
    points = {sentiment: counts[sentiment] * 10000 // total for sentiment in Sentiment}
    order = sorted(Sentiment, key=lambda sentiment: -(counts[sentiment] * 10000 % total))
    for sentiment in order[:10000 - sum(points.values())]:
        points[sentiment] += 1
    return {sentiment: points[sentiment] / 100 for sentiment in Sentiment}


class ReportingService:
    def build(self, job: Job, status: JobState) -> BatchReport:
        source = {row.meta.feedback_id: row.meta for row in job.records}
        if len(source) != job.total_records or len(job.results) != job.total_records:
            raise ApplicationError(ErrorCode.BATCH_REPORT_UNAVAILABLE)
        if {item.feedback_id for item in job.results} != set(source):
            raise ApplicationError(ErrorCode.BATCH_REPORT_UNAVAILABLE)
        for item in job.results:
            if (item.source_row, item.normalized_date, item.date_status) != (
                source[item.feedback_id].source_row, source[item.feedback_id].normalized_date,
                source[item.feedback_id].date_status,
            ):
                raise ApplicationError(ErrorCode.BATCH_REPORT_UNAVAILABLE)
        successful = [item for item in job.results if item.status == RecordState.SUCCESS]
        counts = count_sentiments(item.sentiment for item in successful)
        categories = [
            IssueAggregate(category=category, count=len(ids), feedback_ids=ids)
            for category, ids in group_issue_ids((item.issue_category, item.feedback_id) for item in successful)
        ]
        complaints = [item for item in successful if item.sentiment in {Sentiment.NEGATIVE, Sentiment.MIXED}]
        issues = [
            IssueAggregate(category=category, count=len(ids), feedback_ids=ids)
            for category, ids in group_issue_ids((item.issue_category, item.feedback_id) for item in complaints)
        ]
        # Deduplicate each aspect within a source record. Conflicting polarities
        # become MIXED, so each aspect's distribution reconciles to its record count.
        labels: dict[tuple[str, str], set[Sentiment]] = defaultdict(set)
        for item in successful:
            for aspect in item.aspects:
                labels[(aspect.name, item.feedback_id)].add(aspect.sentiment)
        aspect_rows = [
            {"name": name, "feedback_id": identifier, "sentiment": next(iter(values)) if len(values) == 1 else Sentiment.MIXED}
            for (name, identifier), values in labels.items()
        ]
        aspects = []
        if aspect_rows:
            frame = pd.DataFrame(aspect_rows)
            for name, group in frame.groupby("name", sort=True):
                aspects.append(AspectAggregate(
                    name=name, count=len(group), feedback_ids=sorted(group["feedback_id"].tolist()),
                    sentiment_distribution=count_sentiments(group["sentiment"].tolist()),
                ))
        aspects.sort(key=lambda item: (-item.count, item.name))
        ordered_ids = list(dict.fromkeys(
            [identifier for issue in issues for identifier in issue.feedback_ids]
            + sorted(item.feedback_id for item in successful)
        ))
        lookup = {item.feedback_id: item for item in successful}
        evidence = []
        for identifier in ordered_ids:
            item = lookup[identifier]
            if item.evidence_phrases:
                excerpt = item.evidence_phrases[0][:500]
                evidence.append(ReportEvidence(feedback_id=identifier, source_row=item.source_row, text_excerpt=excerpt))
            if len(evidence) == 20:
                break
        if any(item.feedback_id not in lookup or not any(
            item.text_excerpt in phrase for phrase in lookup[item.feedback_id].evidence_phrases
        ) for item in evidence):
            raise ApplicationError(ErrorCode.BATCH_REPORT_UNAVAILABLE)
        attempted = sum(item.attempted for item in job.results)
        report = BatchReport(
            **job.snapshot().model_dump(exclude={"status"}), status=status,
            business_type=job.options.business_type, source=job.options.source,
            valid_records=job.valid_records, invalid_records=job.total_records - job.valid_records,
            attempted_records=attempted, unattempted_valid_records=job.valid_records - attempted,
            skipped_blank_rows=job.skipped_blank_rows,
            invalid_date_records=sum(item.date_status == DateState.INVALID for item in job.results),
            sentiment_distribution=counts, sentiment_percentages=percentages(counts),
            issue_categories=categories, top_issues=issues, top_aspects=aspects[:20], evidence=evidence,
            recommendations=[f"Consider reviewing recurring {issues[0].category.value.lower().replace('_', ' ')} feedback."] if issues else [],
            limitations=[
                "Findings use only the uploaded feedback and validated model classifications, not verified business operations.",
                "Sentiment percentages use successful records only; failures are excluded and rounded by largest remainder to two decimals.",
                "Top issues count NEGATIVE and MIXED records by their primary category; aspect counts are unique records per label.",
                "Invalid or missing optional dates are not invented and do not prevent valid text analysis; no historical trends are inferred.",
                "Evidence is limited to 20 verified excerpts of at most 500 characters; results may contain sensitive summaries and quotes.",
                "Recommendations are tentative review suggestions; no external actions or business investigation were performed.",
            ],
        )
        return report
