import re
from collections.abc import Iterable


def _tokenize(text: str) -> set[str]:
    tokens = re.findall(r"[a-zA-Z0-9]+", text.lower())
    return {token for token in tokens if len(token) >= 3}


def score_texts(cv_text: str, job_text: str) -> tuple[float, list[str]]:
    cv_tokens = _tokenize(cv_text)
    job_tokens = _tokenize(job_text)

    if not cv_tokens or not job_tokens:
        return 0.0, []

    common = sorted(cv_tokens.intersection(job_tokens))
    score = (2 * len(common)) / (len(cv_tokens) + len(job_tokens))
    return round(score * 100, 2), common


def serialize_keywords(keywords: Iterable[str]) -> str:
    return ",".join(keywords)


def deserialize_keywords(value: str | None) -> list[str]:
    if not value:
        return []
    return [item for item in value.split(",") if item]
