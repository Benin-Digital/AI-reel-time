"""Keyword (de)serialization helpers used to store match keywords in the DB.

The scoring engine that used to live in this module (analyze_match,
score_texts, and the weighted-jaccard/structured heuristics behind them)
has been removed: matcher.py is the only matching engine used in
production, and this legacy engine had diverged from it (see git history
for details — it produced different skill/semantic scores than matcher.py
from the same input text, which caused visible inconsistencies between
persisted scores and their on-demand explanations).

Only these two serialization helpers remain, since they are still used to
store/read the common-keywords column on match records.
"""
from __future__ import annotations

from collections.abc import Iterable


def serialize_keywords(keywords: Iterable[str]) -> str:
    return ",".join(keywords)


def deserialize_keywords(value: str | None) -> list[str]:
    if not value:
        return []
    return [item for item in value.split(",") if item]
