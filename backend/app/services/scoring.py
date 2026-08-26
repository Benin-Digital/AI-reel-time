from __future__ import annotations

import re
from collections.abc import Iterable

from ..settings import get_settings
from .structured import build_document_profile, canonical_token_set, canonical_tokens

settings = get_settings()

_NOISE_KEYWORDS = {
    "year",
    "years",
    "annee",
    "annees",
    "experience",
    "experiences",
    "exp",
    "month",
    "months",
    "ans",
}


def _parse_csv(value: str) -> list[str]:
    return [item.strip().lower() for item in value.split(",") if item.strip()]


def _stopwords() -> set[str]:
    languages = {lang.strip().lower() for lang in settings.scoring_stopwords_languages.split(",")}
    words: set[str] = set(_parse_csv(settings.scoring_stopwords))
    if "en" in languages:
        words.update(
            {
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
        )
    if "fr" in languages:
        words.update(
            {
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
        )
    return words


def _tokenize(text: str, stopwords: set[str]) -> list[str]:
    return [
        token
        for token in canonical_tokens(text)
        if len(token) >= 3 and token not in stopwords and token not in _NOISE_KEYWORDS and not token.isdigit()
    ]


def _token_set(text: str, stopwords: set[str]) -> set[str]:
    return set(_tokenize(text, stopwords))


def _weighted_jaccard(common: set[str], union: set[str], weights: dict[str, float]) -> float:
    if not union:
        return 0.0
    numerator = sum(weights.get(token, 1.0) for token in common)
    denominator = sum(weights.get(token, 1.0) for token in union)
    if denominator <= 0:
        return 0.0
    return numerator / denominator


def _extract_years(text: str) -> int:
    matches = re.findall(r"(\d{1,2})\s*(?:\+|\-|plus)?\s*(?:years|year|ans|ann[eé]e?s?)", text.lower())
    values = [int(value) for value in matches if value.isdigit()]
    return max(values) if values else 0


def _phrase_bonus(text: str, phrases: list[str]) -> int:
    text_lower = text.lower()
    return sum(1 for phrase in phrases if phrase and phrase in text_lower)


def _coverage(source_terms: set[str], target_terms: set[str]) -> float:
    if not target_terms:
        return 1.0
    if not source_terms:
        return 0.0
    return len(source_terms.intersection(target_terms)) / len(target_terms)


def _jaccard(source_terms: set[str], target_terms: set[str]) -> float:
    if not source_terms or not target_terms:
        return 0.0
    union = source_terms.union(target_terms)
    if not union:
        return 0.0
    return len(source_terms.intersection(target_terms)) / len(union)


def _experience_score(cv_years: int, required_years: int) -> tuple[float, float]:
    if required_years <= 0 and cv_years <= 0:
        return 0.5, 0.0
    if required_years <= 0:
        return (0.75 if cv_years > 0 else 0.4), 0.0
    if cv_years <= 0:
        return 0.0, settings.structured_missing_experience_penalty
    if cv_years >= required_years:
        gap_ratio = min((cv_years - required_years) / max(required_years, 1), 1.0)
        return 1.0, 0.0 if gap_ratio <= 0.5 else settings.scoring_experience_penalty * 0.5
    shortfall = (required_years - cv_years) / max(required_years, 1)
    score = max(0.0, 1.0 - shortfall)
    return score, settings.structured_missing_experience_penalty * shortfall


def _contract_score(cv_contract: str | None, job_contract: str | None) -> float:
    if not job_contract:
        return 0.5
    if not cv_contract:
        return 0.35
    return 1.0 if cv_contract == job_contract else 0.0


def _language_score(cv_languages: set[str], job_languages: set[str]) -> float:
    if not job_languages:
        return 0.5 if cv_languages else 0.4
    if not cv_languages:
        return 0.0
    return _coverage(cv_languages, job_languages)


def _summary_text(profile_kind: str, summary: str, fallback: str) -> str:
    if summary.strip():
        return summary
    return fallback if profile_kind == "job" else fallback


def _relevant_text(profile) -> str:
    parts = [
        profile.summary_text,
        profile.skills_text,
        profile.job_required_text,
        profile.job_nice_text,
        profile.experience_text,
        profile.education_text,
        profile.certifications_text,
        profile.languages_text,
        profile.contract_text,
    ]
    return "\n".join(part for part in parts if part).strip()


def analyze_match(cv_text: str, job_text: str) -> dict[str, object]:
    stopwords = _stopwords()
    skill_keywords = canonical_token_set(settings.scoring_skill_keywords)

    cv_profile = build_document_profile(cv_text or "", kind="cv")
    job_profile = build_document_profile(job_text or "", kind="job")

    cv_focus_text = _relevant_text(cv_profile) or cv_profile.cleaned_text
    job_focus_text = _relevant_text(job_profile) or job_profile.cleaned_text

    cv_general = _token_set(cv_focus_text, stopwords)
    job_general = _token_set(job_focus_text, stopwords)
    lexical_common = cv_general.intersection(job_general)
    lexical_union = cv_general.union(job_general)
    lexical_weights = {token: settings.scoring_skill_weight for token in skill_keywords}
    lexical_overlap = _weighted_jaccard(lexical_common, lexical_union, lexical_weights)

    cv_skill_terms = set(cv_profile.skill_terms)
    job_skill_terms = set(job_profile.skill_terms)
    required_terms = set(job_profile.required_skill_terms or job_profile.skill_terms)
    nice_terms = set(job_profile.nice_skill_terms)

    skill_overlap = _jaccard(cv_skill_terms, job_skill_terms)
    required_coverage = _coverage(cv_skill_terms, required_terms)
    nice_coverage = _coverage(cv_skill_terms, nice_terms)
    missing_required = sorted(required_terms.difference(cv_skill_terms))
    missing_required_ratio = (len(missing_required) / len(required_terms)) if required_terms else 0.0

    cv_summary_tokens = set(_tokenize(_summary_text("cv", cv_profile.summary_text, cv_focus_text), stopwords))
    job_summary_tokens = set(_tokenize(_summary_text("job", job_profile.summary_text, job_focus_text), stopwords))
    summary_overlap = _jaccard(cv_summary_tokens, job_summary_tokens)

    cv_languages = set(cv_profile.language_terms)
    job_languages = set(job_profile.language_terms)
    language_score = _language_score(cv_languages, job_languages)

    contract_score = _contract_score(cv_profile.contract_type, job_profile.contract_type)

    cv_years = cv_profile.experience_years
    job_years = job_profile.experience_years
    experience_score, experience_penalty = _experience_score(cv_years, job_years)

    education_score = _jaccard(
        set(_tokenize(cv_profile.education_text, stopwords)),
        set(_tokenize(job_profile.education_text, stopwords)),
    )
    certification_score = _jaccard(
        set(_tokenize(cv_profile.certifications_text, stopwords)),
        set(_tokenize(job_profile.certifications_text, stopwords)),
    )

    phrase_keywords = _parse_csv(settings.scoring_skill_keywords)
    skill_phrases = [phrase for phrase in phrase_keywords if " " in phrase]
    phrase_hits = min(
        _phrase_bonus(cv_focus_text, skill_phrases),
        _phrase_bonus(job_focus_text, skill_phrases),
    )
    phrase_bonus = min(settings.scoring_max_bonus, phrase_hits * settings.scoring_phrase_bonus)

    score = (
        lexical_overlap * settings.structured_lexical_weight
        + skill_overlap * settings.structured_skill_weight
        + required_coverage * settings.structured_must_have_weight
        + experience_score * settings.structured_experience_weight
        + language_score * settings.structured_language_weight
        + contract_score * settings.structured_contract_weight
        + summary_overlap * settings.structured_summary_weight
        + education_score * settings.structured_education_weight
        + certification_score * (settings.structured_education_weight * 0.5)
        + nice_coverage * (settings.structured_must_have_weight * 0.35)
        + phrase_bonus
        - missing_required_ratio * settings.structured_missing_required_penalty
        - experience_penalty
    )

    score = max(0.0, min(1.0, score))

    lexical_keywords = {
        token
        for token in lexical_common
        if token in skill_keywords or token in cv_skill_terms or token in job_skill_terms
    }
    common_keywords = sorted(
        lexical_keywords
        | cv_skill_terms.intersection(job_skill_terms)
        | cv_skill_terms.intersection(required_terms)
        | cv_skill_terms.intersection(nice_terms)
        | cv_languages.intersection(job_languages)
    )

    return {
        "score": round(score * 100, 2),
        "common_keywords": common_keywords,
        "metrics": {
            "lexical_overlap": round(lexical_overlap, 4),
            "skill_overlap": round(skill_overlap, 4),
            "required_coverage": round(required_coverage, 4),
            "nice_coverage": round(nice_coverage, 4),
            "summary_overlap": round(summary_overlap, 4),
            "language_score": round(language_score, 4),
            "contract_score": round(contract_score, 4),
            "experience_score": round(experience_score, 4),
            "experience_penalty": round(experience_penalty, 4),
            "missing_required_ratio": round(missing_required_ratio, 4),
            "cv_years": cv_years,
            "job_years": job_years,
            "missing_required": missing_required,
        },
        "profiles": {
            "cv": cv_profile,
            "job": job_profile,
        },
    }


def score_texts(cv_text: str, job_text: str) -> tuple[float, list[str]]:
    if not (cv_text or "").strip() or not (job_text or "").strip():
        return 0.0, []
    analysis = analyze_match(cv_text, job_text)
    return float(analysis["score"]), list(analysis["common_keywords"])


def serialize_keywords(keywords: Iterable[str]) -> str:
    return ",".join(keywords)


def deserialize_keywords(value: str | None) -> list[str]:
    if not value:
        return []
    return [item for item in value.split(",") if item]
