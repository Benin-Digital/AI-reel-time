import re
from collections.abc import Iterable

from ..settings import get_settings

settings = get_settings()

_STOPWORDS_EN = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "has",
    "in",
    "is",
    "it",
    "its",
    "of",
    "on",
    "or",
    "that",
    "the",
    "to",
    "was",
    "were",
    "with",
}

_STOPWORDS_FR = {
    "a",
    "au",
    "aux",
    "avec",
    "ce",
    "ces",
    "dans",
    "de",
    "des",
    "du",
    "elle",
    "en",
    "et",
    "eux",
    "il",
    "je",
    "la",
    "le",
    "les",
    "leur",
    "lui",
    "ma",
    "mais",
    "me",
    "meme",
    "mes",
    "moi",
    "mon",
    "ne",
    "nos",
    "notre",
    "nous",
    "on",
    "ou",
    "par",
    "pas",
    "pour",
    "que",
    "qui",
    "sa",
    "se",
    "ses",
    "son",
    "sur",
    "ta",
    "te",
    "tes",
    "toi",
    "ton",
    "tu",
    "un",
    "une",
    "vos",
    "votre",
    "vous",
}


def _parse_csv(value: str) -> list[str]:
    return [item.strip().lower() for item in value.split(",") if item.strip()]


def _parse_synonyms(raw: str) -> dict[str, str]:
    pairs = {}
    for item in _parse_csv(raw):
        if "=" not in item:
            continue
        src, dest = item.split("=", 1)
        src = src.strip()
        dest = dest.strip()
        if src and dest:
            pairs[src] = dest
    return pairs


def _stopwords() -> set[str]:
    languages = {lang.strip().lower() for lang in settings.scoring_stopwords_languages.split(",")}
    words: set[str] = set(_parse_csv(settings.scoring_stopwords))
    if "en" in languages:
        words.update(_STOPWORDS_EN)
    if "fr" in languages:
        words.update(_STOPWORDS_FR)
    return words


def _normalize_token(token: str, synonyms: dict[str, str]) -> str:
    return synonyms.get(token, token)


def _tokenize(text: str, stopwords: set[str], synonyms: dict[str, str]) -> list[str]:
    tokens = re.findall(r"[a-zA-Z0-9]+", text.lower())
    normalized = (_normalize_token(token, synonyms) for token in tokens)
    return [token for token in normalized if len(token) >= 3 and token not in stopwords]


def _token_set(text: str, stopwords: set[str], synonyms: dict[str, str]) -> set[str]:
    return set(_tokenize(text, stopwords, synonyms))


def _weighted_jaccard(common: set[str], union: set[str], weights: dict[str, float]) -> float:
    if not union:
        return 0.0
    numerator = sum(weights.get(token, 1.0) for token in common)
    denominator = sum(weights.get(token, 1.0) for token in union)
    if denominator <= 0:
        return 0.0
    return numerator / denominator


def _extract_years(text: str) -> int:
    matches = re.findall(r"(\d{1,2})\s*(?:\+|\-)?\s*(?:years|year|ans|annee|annees)", text.lower())
    values = [int(value) for value in matches if value.isdigit()]
    return max(values) if values else 0


def _phrase_bonus(text: str, phrases: list[str]) -> int:
    text_lower = text.lower()
    return sum(1 for phrase in phrases if phrase and phrase in text_lower)


def score_texts(cv_text: str, job_text: str) -> tuple[float, list[str]]:
    stopwords = _stopwords()
    synonyms = _parse_synonyms(settings.scoring_synonyms)
    skill_keywords = _parse_csv(settings.scoring_skill_keywords)

    skill_tokens = [token for token in skill_keywords if " " not in token]
    skill_phrases = [phrase for phrase in skill_keywords if " " in phrase]

    cv_tokens = _token_set(cv_text, stopwords, synonyms)
    job_tokens = _token_set(job_text, stopwords, synonyms)

    if not cv_tokens or not job_tokens:
        return 0.0, []

    common = cv_tokens.intersection(job_tokens)
    union = cv_tokens.union(job_tokens)

    weights = {token: settings.scoring_skill_weight for token in skill_tokens}
    overlap = _weighted_jaccard(common, union, weights)

    phrase_hits = min(
        _phrase_bonus(cv_text, skill_phrases),
        _phrase_bonus(job_text, skill_phrases),
    )
    phrase_bonus = min(settings.scoring_max_bonus, phrase_hits * settings.scoring_phrase_bonus)

    required_years = _extract_years(job_text)
    cv_years = _extract_years(cv_text)
    experience_delta = 0.0
    if required_years:
        if cv_years >= required_years:
            experience_delta = settings.scoring_experience_bonus
        else:
            experience_delta = -settings.scoring_experience_penalty

    score = max(0.0, min(1.0, overlap + phrase_bonus + experience_delta))
    return round(score * 100, 2), sorted(common)


def serialize_keywords(keywords: Iterable[str]) -> str:
    return ",".join(keywords)


def deserialize_keywords(value: str | None) -> list[str]:
    if not value:
        return []
    return [item for item in value.split(",") if item]
