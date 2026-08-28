"""
AI matching engine v2.

Combines:
  1. Cross-encoder semantic scoring (cross-encoder/ms-marco-MiniLM-L-6-v2)
  2. Structured field scoring (skills, experience, education, languages, contract)
  3. Domain-aware weight adjustment

Designed for small datasets (≤ 50 CV/job pairs) where cross-encoder can run
on every pair without a bi-encoder pre-filter.
"""
from __future__ import annotations

import logging
import math
import re
import threading
import unicodedata
from dataclasses import dataclass

from .parser import ParsedDocument, parse_document

logger = logging.getLogger(__name__)

# ── Cross-encoder ─────────────────────────────────────────────────────────────

_cross_encoder = None
_ce_lock = threading.Lock()
_CE_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"


def _get_cross_encoder():
    global _cross_encoder
    if _cross_encoder is None:
        with _ce_lock:
            if _cross_encoder is None:
                try:
                    from sentence_transformers import CrossEncoder
                    logger.info("Loading cross-encoder: %s", _CE_MODEL)
                    _cross_encoder = CrossEncoder(_CE_MODEL)
                    logger.info("Cross-encoder ready")
                except Exception as exc:
                    logger.warning("Cross-encoder unavailable (%s) — semantic score = 0.5", exc)
                    _cross_encoder = "unavailable"
    return None if _cross_encoder == "unavailable" else _cross_encoder


def _cross_encode(query: str, document: str) -> float:
    """
    Score a (query, document) pair with the cross-encoder.
    ms-marco outputs logits in roughly [-10, 10]; sigmoid maps them to (0, 1).
    Returns 0.5 if model is unavailable.
    """
    model = _get_cross_encoder()
    if model is None:
        return 0.5
    try:
        raw = float(model.predict([(query, document)])[0])
        return 1.0 / (1.0 + math.exp(-raw))
    except Exception as exc:
        logger.warning("Cross-encoder predict failed: %s", exc)
        return 0.5


# ── Domain-aware weights ──────────────────────────────────────────────────────

_DEFAULT_W = {
    "semantic": 0.40,
    "skills": 0.30,
    "experience": 0.12,
    "education": 0.08,
    "languages": 0.05,
    "contract": 0.05,
}

_DOMAIN_W: dict[str, dict[str, float]] = {
    "tech": {
        "semantic": 0.35,
        "skills": 0.40,
        "experience": 0.12,
        "education": 0.05,
        "languages": 0.05,
        "contract": 0.03,
    },
    "health": {
        "semantic": 0.30,
        "skills": 0.25,
        "experience": 0.15,
        "education": 0.20,  # diplomas critical in healthcare
        "languages": 0.05,
        "contract": 0.05,
    },
    "legal": {
        "semantic": 0.35,
        "skills": 0.20,
        "experience": 0.15,
        "education": 0.20,  # legal degrees are prerequisites
        "languages": 0.05,
        "contract": 0.05,
    },
    "finance": {
        "semantic": 0.35,
        "skills": 0.30,
        "experience": 0.15,
        "education": 0.12,
        "languages": 0.05,
        "contract": 0.03,
    },
    "commercial": {
        "semantic": 0.40,
        "skills": 0.25,
        "experience": 0.20,  # track record matters in sales
        "education": 0.05,
        "languages": 0.07,
        "contract": 0.03,
    },
    "hr": {
        "semantic": 0.40,
        "skills": 0.28,
        "experience": 0.15,
        "education": 0.08,
        "languages": 0.06,
        "contract": 0.03,
    },
    "construction": {
        "semantic": 0.30,
        "skills": 0.35,
        "experience": 0.18,
        "education": 0.10,
        "languages": 0.04,
        "contract": 0.03,
    },
    "logistics": {
        "semantic": 0.35,
        "skills": 0.32,
        "experience": 0.18,
        "education": 0.07,
        "languages": 0.05,
        "contract": 0.03,
    },
    "education": {
        "semantic": 0.35,
        "skills": 0.25,
        "experience": 0.15,
        "education": 0.15,
        "languages": 0.07,
        "contract": 0.03,
    },
    "management": {
        "semantic": 0.40,
        "skills": 0.20,
        "experience": 0.25,  # seniority/track record weigh heavily for leadership roles
        "education": 0.08,
        "languages": 0.04,
        "contract": 0.03,
    },
    "marketing": {
        "semantic": 0.40,
        "skills": 0.30,
        "experience": 0.15,
        "education": 0.06,
        "languages": 0.06,
        "contract": 0.03,
    },
}


# Learned weights set by the API after loading from DB
_learned_weights: dict[str, float] | None = None
_learned_weights_lock = threading.Lock()


def set_learned_weights(weights: dict[str, float] | None) -> None:
    global _learned_weights
    with _learned_weights_lock:
        _learned_weights = weights


def get_active_weights() -> dict[str, float] | None:
    with _learned_weights_lock:
        return _learned_weights.copy() if _learned_weights else None


def _weights(domain: str) -> dict[str, float]:
    with _learned_weights_lock:
        if _learned_weights is not None:
            return _learned_weights.copy()
    if domain not in _DOMAIN_W and domain != "general":
        # A document was classified into a domain that parser.py knows how to
        # detect but that has no calibrated weight profile here. Falling back
        # to _DEFAULT_W silently would repeat the 'management'/'marketing' gap
        # (score computed with generic weights while the UI still shows a
        # specific domain badge) — surface it instead of hiding it.
        logger.warning(
            "No calibrated weight profile for domain '%s' — falling back to "
            "_DEFAULT_W. Add an entry to _DOMAIN_W to calibrate this domain.",
            domain,
        )
    raw = _DOMAIN_W.get(domain, _DEFAULT_W).copy()
    total = sum(raw.values())
    return {k: v / total for k, v in raw.items()} if total else raw


# ── Component scoring ─────────────────────────────────────────────────────────

def _skill_score(cv: ParsedDocument, job: ParsedDocument) -> float:
    """Coverage of required job skills by CV skills."""
    required = set(job.required_skill_terms or job.skill_terms)
    if not required:
        return 0.5
    cv_skills = set(cv.skill_terms)
    if not cv_skills:
        return 0.0
    coverage = len(cv_skills & required) / len(required)
    # Nice-to-have bonus (15 % weight)
    nice = set(job.nice_skill_terms)
    if nice:
        nice_coverage = len(cv_skills & nice) / len(nice)
        coverage = coverage * 0.85 + nice_coverage * 0.15
    return min(1.0, coverage)


def _experience_score(cv: ParsedDocument, job: ParsedDocument) -> float:
    """Years-of-experience match."""
    cv_y, job_y = cv.experience_years, job.experience_years
    if job_y <= 0 and cv_y <= 0:
        return 0.5
    if job_y <= 0:
        return 0.75
    if cv_y <= 0:
        return 0.2
    if cv_y >= job_y:
        # Over-qualified: slight penalty if 3× over-qualified
        return 0.85 if cv_y / job_y > 3 else 1.0
    shortfall = (job_y - cv_y) / job_y
    return max(0.0, 1.0 - shortfall)


def _fold(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text)
    return nfkd.encode("ascii", "ignore").decode("ascii").lower()


def _education_score(cv: ParsedDocument, job: ParsedDocument) -> float:
    """Token-level Jaccard on education sections."""
    if not cv.education_text or not job.education_text:
        return 0.5
    stopwords = {"les", "des", "une", "the", "and", "for", "with", "dans", "de", "du"}

    def tokens(text: str) -> set[str]:
        words = set(re.findall(r"[a-z0-9]{3,}", _fold(text)))
        return words - stopwords

    cv_t = tokens(cv.education_text)
    job_t = tokens(job.education_text)
    if not cv_t or not job_t:
        return 0.5
    union = cv_t | job_t
    return len(cv_t & job_t) / len(union)


def _language_score(cv: ParsedDocument, job: ParsedDocument) -> float:
    """Coverage of required languages."""
    job_langs = set(job.language_terms)
    if not job_langs:
        return 0.5
    cv_langs = set(cv.language_terms)
    if not cv_langs:
        return 0.3
    return len(cv_langs & job_langs) / len(job_langs)


def _contract_score(cv: ParsedDocument, job: ParsedDocument) -> float:
    if not job.contract_type:
        return 0.5
    if not cv.contract_type:
        return 0.4
    return 1.0 if cv.contract_type == job.contract_type else 0.0


# ── Result dataclass ──────────────────────────────────────────────────────────

@dataclass
class MatchScore:
    score: float               # Final 0-100 score
    score_semantic: float      # Cross-encoder (0-1)
    score_skills: float        # Skill coverage (0-1)
    score_experience: float    # Years match (0-1)
    score_education: float     # Education match (0-1)
    score_languages: float     # Language match (0-1)
    score_contract: float      # Contract match (0-1)
    domain: str                # Detected domain
    common_skills: list[str]   # Skills in both CV and job
    missing_skills: list[str]  # Required skills absent from CV
    weights: dict[str, float]  # Weights used for this match


# ── Public API ────────────────────────────────────────────────────────────────

def match_cv_to_job(cv_text: str, job_text: str) -> MatchScore:
    """
    Full CV↔Job match using cross-encoder + structured scoring.

    Args:
        cv_text: Raw or pre-extracted CV text
        job_text: Raw or pre-extracted job offer text

    Returns:
        MatchScore with all component scores and final 0-100 score
    """
    cv = parse_document(cv_text, kind="cv")
    job = parse_document(job_text, kind="job")

    # Use job's domain when available (more precise about requirements)
    domain = job.domain if job.domain != "general" else cv.domain
    w = _weights(domain)

    # Semantic: feed the most relevant section of each document
    cv_repr = (cv.skills_text or cv.summary_text or cv.cleaned_text)[:2000]
    job_repr = (job.job_required_text or job.summary_text or job.cleaned_text)[:2000]
    semantic = _cross_encode(job_repr, cv_repr)

    skills = _skill_score(cv, job)
    experience = _experience_score(cv, job)
    education = _education_score(cv, job)
    languages = _language_score(cv, job)
    contract = _contract_score(cv, job)

    final = (
        w["semantic"] * semantic
        + w["skills"] * skills
        + w["experience"] * experience
        + w["education"] * education
        + w["languages"] * languages
        + w["contract"] * contract
    )
    final = max(0.0, min(1.0, final))

    cv_skills = set(cv.skill_terms)
    job_required = set(job.required_skill_terms or job.skill_terms)

    return MatchScore(
        score=round(final * 100, 2),
        score_semantic=round(semantic, 4),
        score_skills=round(skills, 4),
        score_experience=round(experience, 4),
        score_education=round(education, 4),
        score_languages=round(languages, 4),
        score_contract=round(contract, 4),
        domain=domain,
        common_skills=sorted(cv_skills & job_required),
        missing_skills=sorted(job_required - cv_skills),
        weights=w,
    )


def score_texts(cv_text: str, job_text: str) -> tuple[float, list[str]]:
    """
    Drop-in replacement for the legacy score_texts() in scoring.py.
    Returns (score_0_to_100, common_keywords).
    """
    result = match_cv_to_job(cv_text, job_text)
    return result.score, result.common_skills
