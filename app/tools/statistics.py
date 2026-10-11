"""Unbounded-in-count deterministic kernels shared by investigation and batch DTOs."""

from collections import Counter, defaultdict
from collections.abc import Iterable

from app.schemas.sentiment import IssueCategory, Sentiment


def count_sentiments(values: Iterable[Sentiment]) -> dict[Sentiment, int]:
    counts = Counter(values)
    return {sentiment: counts[sentiment] for sentiment in Sentiment}


def group_issue_ids(values: Iterable[tuple[IssueCategory, str]]) -> list[tuple[IssueCategory, list[str]]]:
    groups: dict[IssueCategory, set[str]] = defaultdict(set)
    for category, identifier in values:
        groups[category].add(identifier)
    return [
        (category, sorted(ids))
        for category, ids in sorted(groups.items(), key=lambda pair: (-len(pair[1]), pair[0].value))
    ]
