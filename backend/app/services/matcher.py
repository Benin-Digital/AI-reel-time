"""
AI matching engine v2.

Combines:
  1. Cross-encoder semantic scoring (antoinelouis/crossencoder-camembert-base-mmarcoFR)
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
from dataclasses import dataclass, field

from .parser import ParsedDocument, parse_document

logger = logging.getLogger(__name__)

# ── Cross-encoder ─────────────────────────────────────────────────────────────

_cross_encoder = None
_ce_lock = threading.Lock()


def _get_cross_encoder():
    global _cross_encoder
    if _cross_encoder is None:
        with _ce_lock:
            if _cross_encoder is None:
                from ..settings import get_settings

                settings = get_settings()
                if not settings.crossencoder_enabled:
                    _cross_encoder = "unavailable"
                    return None
                model_name = settings.crossencoder_model_name
                try:
                    from sentence_transformers import CrossEncoder
                    logger.info("Loading cross-encoder: %s", model_name)
                    _cross_encoder = CrossEncoder(model_name)
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
#
# _DOMAIN_W below is NOT applied to scoring (see _weights()). It's kept as
# reference data from an earlier design where the final score used a
# different weight profile per detected domain (health/legal weighting
# education higher, tech weighting skills higher, etc.).
#
# That design was retired: detect_domain() (parser.py) is a keyword-count
# heuristic over the first 3000 chars, and a single out-of-context keyword
# (e.g. "patient" mentioned once in an e-health tech CV) could flip the
# entire weight profile with no signal visible to the recruiter — in
# production, tech CVs were observed landing in the health domain and
# having their score silently distorted by it. The weight deltas between
# profiles were also hand-tuned, never validated against real outcomes.
#
# Domain is still detected and shown to the recruiter as a label
# (MatchScore.domain) — it just no longer feeds the score itself. If
# domain-aware weighting is revisited, do it with a confidence gate or a
# proportional blend instead of this hard per-domain lookup, and validate
# the effect on the accuracy dataset (test_validation_dataset.py) first.

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


def _weights() -> dict[str, float]:
    """Weights for the final score. Domain-independent — see the comment
    above _DOMAIN_W for why per-domain weighting was retired."""
    with _learned_weights_lock:
        if _learned_weights is not None:
            return _learned_weights.copy()
    return dict(_DEFAULT_W)


# ── Component scoring ─────────────────────────────────────────────────────────
#
# Each component returns (score, has_signal). `has_signal` is False when the
# neutral/penalty score is due to MISSING information rather than a real
# comparison — e.g. the job specifies no language requirement, or an education
# section couldn't be extracted from either side. The scores themselves are
# unchanged; has_signal is surfaced separately (see MatchScore.low_confidence_
# components) so a recruiter can tell a legitimately-neutral 0.5 apart from a
# 0.5 that just means "we couldn't read this".

def _skill_score(cv: ParsedDocument, job: ParsedDocument) -> tuple[float, bool]:
    """Coverage of required job skills by CV skills.

    Hybrid (F6): exact lexical matches always count as full credit. For each
    required skill NOT matched literally, we optionally add *partial* credit
    based on the max embedding cosine similarity to the CV's skills (so
    "Vue.js" required vs "React" in the CV scores some credit instead of 0),
    capped so a semantic match never beats an exact one. This can only ever
    RAISE the score vs pure lexical, never lower it, and falls back to exact
    lexical behaviour when embeddings are disabled or unavailable.
    """
    required = set(job.required_skill_terms or job.skill_terms)
    if not required:
        return 0.5, False  # job lists no extractable required skills
    cv_skills = set(cv.skill_terms)
    if not cv_skills:
        return 0.0, False  # nothing extracted from the CV to compare

    matched = cv_skills & required
    unmatched = required - matched

    # Base credit: one point per exactly-matched required skill.
    credit = float(len(matched))

    # Semantic top-up for the unmatched required skills (best-effort).
    credit += _semantic_skill_credit(unmatched, cv_skills)

    coverage = credit / len(required)

    # Nice-to-have bonus (15 % weight) — kept lexical, unchanged.
    nice = set(job.nice_skill_terms)
    if nice:
        nice_coverage = len(cv_skills & nice) / len(nice)
        coverage = coverage * 0.85 + nice_coverage * 0.15
    return min(1.0, coverage), True


def _semantic_skill_credit(unmatched: set[str], cv_skills: set[str]) -> float:
    """Sum of partial credits (each in [0, max_credit]) for required skills not
    matched literally, using embedding similarity to the CV's skills.

    Returns 0.0 — i.e. no change vs pure lexical — whenever the feature is
    disabled, the model is unavailable, or nothing clears the threshold.
    """
    if not unmatched or not cv_skills:
        return 0.0
    try:
        from ..settings import get_settings

        settings = get_settings()
        if not getattr(settings, "skill_embedding_enabled", False):
            return 0.0
        threshold = settings.skill_embedding_threshold
        max_credit = settings.skill_embedding_max_credit

        from .embeddings import best_skill_similarities

        sims = best_skill_similarities(tuple(sorted(unmatched)), tuple(sorted(cv_skills)))
    except Exception as exc:  # pragma: no cover - defensive: any failure -> lexical
        logger.warning("Semantic skill credit unavailable (%s) — lexical only", exc)
        return 0.0

    if not sims:
        return 0.0

    total = 0.0
    for sim in sims.values():
        if sim >= threshold:
            # Scale similarity above threshold into [0, max_credit] so that a
            # borderline match earns little and a near-exact match earns close
            # to (but never more than) max_credit.
            span = 1.0 - threshold
            frac = (sim - threshold) / span if span > 0 else 1.0
            total += max_credit * min(1.0, frac)
    return total


def _experience_score(cv: ParsedDocument, job: ParsedDocument) -> tuple[float, bool]:
    """Years-of-experience match."""
    cv_y, job_y = cv.experience_years, job.experience_years
    if job_y <= 0 and cv_y <= 0:
        return 0.5, False  # no years extracted on either side
    if job_y <= 0:
        return 0.75, False  # job states no requirement to compare against
    if cv_y <= 0:
        return 0.2, False  # couldn't extract CV experience to compare
    if cv_y >= job_y:
        # Over-qualified: slight penalty if 3× over-qualified
        return (0.85 if cv_y / job_y > 3 else 1.0), True
    shortfall = (job_y - cv_y) / job_y
    return max(0.0, 1.0 - shortfall), True


def _fold(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text)
    return nfkd.encode("ascii", "ignore").decode("ascii").lower()


def _education_score(cv: ParsedDocument, job: ParsedDocument) -> tuple[float, bool]:
    """Token-level Jaccard on education sections."""
    if not cv.education_text or not job.education_text:
        return 0.5, False  # education section missing on at least one side
    stopwords = {"les", "des", "une", "the", "and", "for", "with", "dans", "de", "du"}

    def tokens(text: str) -> set[str]:
        words = set(re.findall(r"[a-z0-9]{3,}", _fold(text)))
        return words - stopwords

    cv_t = tokens(cv.education_text)
    job_t = tokens(job.education_text)
    if not cv_t or not job_t:
        return 0.5, False
    union = cv_t | job_t
    return len(cv_t & job_t) / len(union), True


def _language_score(cv: ParsedDocument, job: ParsedDocument) -> tuple[float, bool]:
    """Coverage of required languages."""
    job_langs = set(job.language_terms)
    if not job_langs:
        return 0.5, False  # job requires no specific language
    cv_langs = set(cv.language_terms)
    if not cv_langs:
        return 0.3, False  # couldn't extract CV languages to compare
    return len(cv_langs & job_langs) / len(job_langs), True


def _contract_score(cv: ParsedDocument, job: ParsedDocument) -> tuple[float, bool]:
    if not job.contract_type:
        return 0.5, False  # job specifies no contract type
    if not cv.contract_type:
        return 0.4, False  # couldn't extract CV contract preference
    return (1.0 if cv.contract_type == job.contract_type else 0.0), True


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
    # Components whose score is a neutral/default value driven by MISSING
    # information rather than a real comparison (e.g. no language requirement
    # in the job, or an education section that couldn't be extracted). Lets a
    # recruiter tell "legitimately neutral" apart from "we couldn't read this"
    # instead of both looking like an identical 0.5. Never includes 'semantic'
    # (the cross-encoder always produces a real comparison when available).
    low_confidence_components: list[str] = field(default_factory=list)


# ── Public API ────────────────────────────────────────────────────────────────

def _semantic_repr(doc: ParsedDocument) -> str:
    """Text excerpt fed to the cross-encoder for semantic comparison.

    F4: rather than betting on a single section (which fails when section
    classification misfires), combine the informative sections in a fixed
    order — required/skills first (most discriminating), then summary, then
    a cleaned-text tail to fill any gap — de-duplicated and truncated to the
    cross-encoder's window (~512 tokens ≈ 2000 chars). Same order regardless
    of doc.kind, so the CV and job sides stay symmetric (see the comment in
    match_cv_to_job for why symmetry matters).

    Falls back to cleaned_text when the structured sections are empty, so a
    document whose sections were all mis-parsed still gets a representation.
    """
    parts: list[str] = []
    seen: set[str] = set()
    for section in (
        doc.job_required_text,
        doc.skills_text,
        doc.summary_text,
    ):
        s = (section or "").strip()
        if s and s not in seen:
            seen.add(s)
            parts.append(s)

    combined = "\n".join(parts).strip()
    if not combined:
        combined = (doc.cleaned_text or "").strip()
    elif len(combined) < 400:
        # Sections were thin — top up with cleaned text so a mis-parse doesn't
        # starve the comparison, without duplicating what we already have.
        tail = (doc.cleaned_text or "").strip()
        if tail and tail not in seen:
            combined = (combined + "\n" + tail).strip()

    return combined[:2000]


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
    return match_parsed_documents(cv, job)


def match_parsed_documents(cv: ParsedDocument, job: ParsedDocument) -> MatchScore:
    """
    Same as match_cv_to_job, but takes documents already parsed by the caller.

    Use this when scoring one document against many counterparts (e.g. one
    CV against a shortlist of jobs) so the side that doesn't change across
    the loop is parsed once instead of once per pair.
    """
    # Domain is still detected and returned as a display label (MatchScore.domain)
    # but no longer selects a weight profile — see the comment above _DOMAIN_W.
    domain = job.domain if job.domain != "general" else cv.domain
    w = _weights()

    # Semantic: feed the most relevant section of each document. Section
    # classification (_match_section) is content-driven, not kind-driven
    # (see parser.py) — a document can have its substantive content land in
    # job_required_text regardless of whether it was parsed as kind='cv' or
    # kind='job'. Using a different field priority per side here meant a
    # self-match (or any pair sharing similar structure) could feed the
    # cross-encoder two genuinely different excerpts of the same document
    # (e.g. job_repr = the rich "Competences requises" section while
    # cv_repr fell back to a mostly-empty generic "skills" section),
    # scoring them as semantically dissimilar even though nothing else
    # differs. Both sides now use the same fallback order.
    cv_repr = _semantic_repr(cv)
    job_repr = _semantic_repr(job)
    semantic = _cross_encode(job_repr, cv_repr)

    skills, skills_ok = _skill_score(cv, job)
    experience, experience_ok = _experience_score(cv, job)
    education, education_ok = _education_score(cv, job)
    languages, languages_ok = _language_score(cv, job)
    contract, contract_ok = _contract_score(cv, job)

    low_confidence = [
        name
        for name, ok in (
            ("skills", skills_ok),
            ("experience", experience_ok),
            ("education", education_ok),
            ("languages", languages_ok),
            ("contract", contract_ok),
        )
        if not ok
    ]

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
        low_confidence_components=low_confidence,
    )


def score_texts(cv_text: str, job_text: str) -> tuple[float, list[str]]:
    """
    Drop-in replacement for the legacy score_texts() in scoring.py.
    Returns (score_0_to_100, common_keywords).
    """
    result = match_cv_to_job(cv_text, job_text)
    return result.score, result.common_skills
