"""
AI matching engine v2.

Combines:
  1. Cross-encoder semantic scoring (antoinelouis/crossencoder-camembert-large-mmarcoFR)
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
import time
import unicodedata
from collections import Counter
from dataclasses import dataclass, field

from .parser import ParsedDocument, parse_document
from .taxonomy import normalize_skill

logger = logging.getLogger(__name__)

# ── Cross-encoder ─────────────────────────────────────────────────────────────

_cross_encoder = None
_cross_encoder_disabled = False  # settings.crossencoder_enabled == False -- permanent, deliberate
_cross_encoder_last_failure: float | None = None  # time.monotonic() of the last load attempt that failed
_CROSS_ENCODER_RETRY_COOLDOWN_S = 300
_ce_lock = threading.Lock()


def _get_cross_encoder():
    """Lazily load the cross-encoder, retrying a failed load after a cooldown
    instead of caching failure forever.

    Observed in production: the model import chain (sentence_transformers ->
    transformers -> torch -> sympy) is heavy enough that a transient hiccup
    at the very first scoring call (cold-start CPU/memory contention, a slow
    disk) can make it raise once -- the same import succeeds fine moments
    later. The previous version cached that single failure as a permanent
    "unavailable" sentinel for the process's entire lifetime, silently
    flattening every match's semantic component (40% of the total weight) to
    a neutral 0.5 until someone noticed and restarted the API. A bounded
    retry means it self-heals instead.
    """
    global _cross_encoder, _cross_encoder_disabled, _cross_encoder_last_failure
    if _cross_encoder is not None:
        return _cross_encoder
    if _cross_encoder_disabled:
        return None
    with _ce_lock:
        if _cross_encoder is not None:
            return _cross_encoder
        if _cross_encoder_disabled:
            return None
        from ..settings import get_settings

        settings = get_settings()
        if not settings.crossencoder_enabled:
            _cross_encoder_disabled = True
            return None
        now = time.monotonic()
        if (
            _cross_encoder_last_failure is not None
            and now - _cross_encoder_last_failure < _CROSS_ENCODER_RETRY_COOLDOWN_S
        ):
            return None
        model_name = settings.crossencoder_model_name
        try:
            from sentence_transformers import CrossEncoder
            logger.info("Loading cross-encoder: %s", model_name)
            _cross_encoder = CrossEncoder(model_name)
            _cross_encoder_last_failure = None
            logger.info("Cross-encoder ready")
        except Exception as exc:
            _cross_encoder_last_failure = now
            logger.warning(
                "Cross-encoder unavailable (%s) — semantic score = 0.5, retrying in %ss",
                exc, _CROSS_ENCODER_RETRY_COOLDOWN_S,
            )
    return _cross_encoder


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


# A CamemBERT-family cross-encoder shares one ~512-token budget across BOTH
# sequences of the pair, so 800 chars/side (~200 tokens each at this
# tokenizer's ~4 chars/token) leaves headroom rather than betting the whole
# budget on a single side.
_CHUNK_CHARS = 800
# Hard cap on chunks per side: bounds worst-case cross-encoder calls for one
# pathological document (a huge OCR dump) instead of scaling unboundedly.
_MAX_CHUNKS = 8


def _chunk_text(text: str, chunk_size: int = _CHUNK_CHARS) -> list[str]:
    """Split text into chunk_size-character windows, breaking at the last
    newline/space before the limit so a chunk doesn't split mid-word."""
    text = text.strip()
    if not text:
        return []
    if len(text) <= chunk_size:
        return [text]

    chunks: list[str] = []
    start = 0
    n = len(text)
    while start < n and len(chunks) < _MAX_CHUNKS:
        end = min(start + chunk_size, n)
        if end < n:
            break_at = text.rfind("\n", start, end)
            if break_at <= start:
                break_at = text.rfind(" ", start, end)
            if break_at > start:
                end = break_at
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        start = end
    return chunks


def _cross_encode_best(query: str, document: str) -> float:
    """Cross-encode a pair that may be too long for a single ~512-token pass
    by scoring every (query_chunk, document_chunk) combination and keeping
    the best (max) score, instead of silently losing whatever falls outside
    a single window.

    Real CVs in this project average ~9-10k characters — a manual check on
    35 real documents found 67% still exceeded a single 2000-char window
    even after _semantic_repr() already prioritizes the most relevant
    sections (skills/summary) over raw text. A long CV's most relevant
    excerpt should be able to drive the score, not just whatever happened
    to fit first.

    Reuses _cross_encode() per chunk pair (rather than batching all pairs
    into one model.predict() call) so existing tests that monkeypatch
    _cross_encode stay meaningful, and because at this project's documented
    scale (≤50 CV/job pairs) the extra per-call overhead is negligible.
    """
    query_chunks = _chunk_text(query) or [""]
    doc_chunks = _chunk_text(document) or [""]
    return max(
        _cross_encode(q, d)
        for q in query_chunks
        for d in doc_chunks
    )


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
    # Lowered from 0.40 (2026-09-11), after measuring on a 16-CV / 1-job
    # validation set (independent human-judgment target per pair) that the
    # cross-encoder's real output barely varies across genuinely different
    # candidates (0.57-0.73 for all 16, most clustered at 0.70-0.73
    # regardless of actual fit): replacing every candidate's real semantic
    # score with a flat 0.70 changed the mean absolute error against the
    # human targets by less than half a point (8.51 -> 8.80). At its old
    # 0.40 weight -- the single highest of any component -- that's 40% of
    # the formula spent on a signal that, on this evidence, isn't
    # discriminating between good and bad matches. Skill and
    # priority-keyword coverage carry the real signal (removing THEM the
    # same way roughly doubles the error), so weight moved there instead.
    # Not dropped to zero: the one candidate whose real score noticeably
    # differed from the 0.70 cluster was pulled slightly CLOSER to their
    # human-judgment target by it, so some weight is kept.
    "semantic": 0.10,
    "skills": 0.40,
    # Only counted when the job has priority keywords (see has_signal on
    # _priority_keyword_score) -- absent for the common case (a recruiter
    # who never filled this in), so it changes nothing there. When present,
    # it's excluded from neither semantic's nor skills' weight: adding a
    # 7th component to the weighted average proportionally dilutes every
    # other component's effective share instead (weight_total grows from
    # 1.00 to 1.20), which is what actually fixes bug 1 -- a CV can no
    # longer make up for missing exactly what the recruiter flagged as
    # priority by scoring well on generic semantic similarity, because
    # that similarity's share of the total shrinks too, not just skills'.
    "priority_keywords": 0.40,
    # Raised from 0.12 (2026-09-11), after a real production comparison
    # (job "Developpeur Full Stack PHP/Laravel/VueJS", 5 ans requis) showed
    # a junior profile (~3 ans reels, 1 mot-cle prioritaire de plus) scoring
    # ABOVE a senior profile (8 ans, exact same stack used in a comparable
    # mission) -- 67.53% vs 66.93%. At 0.12, a whole extra/missing priority
    # keyword (weighted 0.40) always outweighs even a severe experience
    # shortfall, which is backwards for a role that states an explicit
    # years requirement: a human recruiter would treat "half the required
    # experience" as more disqualifying than one missing keyword. Not
    # raised further to keep skills/priority_keywords (the least ambiguous
    # signals when present) as the dominant components.
    "experience": 0.20,
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


# Four explicit zones (2026-09-11), replacing a two-way split that treated
# "exactly meets the requirement" and "comfortably more experienced" the
# same as a hard cliff at 3x for "over-qualified", with no room in between:
#   - INFERIEUR (cv_y < job_y): unchanged, linear shortfall penalty.
#   - EGAL (cv_y == job_y): full credit.
#   - LEGEREMENT SUPERIEUR (job_y < cv_y <= _EXPERIENCE_COMFORTABLE_OVER_RATIO
#     * job_y): still full credit -- a job stating "au moins N ans" (a
#     FLOOR, not a target window) means more experience than the floor is
#     never itself a downside up to a reasonable multiple.
#   - TROP SUPERIEUR (beyond that): real overqualification risk (salary
#     expectations, day-to-day boredom, retention) exists, but it's a
#     gradual concern, not a step function -- tapers from full credit down
#     to a floor instead of jumping straight to one fixed penalty value.
_EXPERIENCE_COMFORTABLE_OVER_RATIO = 2.0
_EXPERIENCE_SEVERE_OVER_RATIO = 4.0
_EXPERIENCE_SEVERE_OVER_FLOOR = 0.85


def _experience_score(cv: ParsedDocument, job: ParsedDocument) -> tuple[float, bool]:
    """Years-of-experience match."""
    cv_y, job_y = cv.experience_years, job.experience_years
    if job_y <= 0 and cv_y <= 0:
        return 0.5, False  # no years extracted on either side
    if job_y <= 0:
        return 0.75, False  # job states no requirement to compare against
    if cv_y <= 0:
        return 0.2, False  # couldn't extract CV experience to compare
    if cv_y == job_y:
        return 1.0, True
    if cv_y > job_y:
        ratio = cv_y / job_y
        if ratio <= _EXPERIENCE_COMFORTABLE_OVER_RATIO:
            return 1.0, True
        if ratio >= _EXPERIENCE_SEVERE_OVER_RATIO:
            return _EXPERIENCE_SEVERE_OVER_FLOOR, True
        span = _EXPERIENCE_SEVERE_OVER_RATIO - _EXPERIENCE_COMFORTABLE_OVER_RATIO
        progress = (ratio - _EXPERIENCE_COMFORTABLE_OVER_RATIO) / span
        return 1.0 - progress * (1.0 - _EXPERIENCE_SEVERE_OVER_FLOOR), True
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
    # Recruiter-curated priority keywords (job.priority_keyword_terms), a
    # component distinct from the general skills score -- see
    # _priority_keyword_score. None (not 0.0) when the job has no priority
    # keywords at all, so a recruiter/UI can tell "no priorities set" apart
    # from "priorities set, none found in this CV".
    score_priority_keywords: float | None = None
    priority_keywords_matched: list[str] = field(default_factory=list)
    priority_keywords_total: int = 0
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
    a cleaned-text tail to fill any gap — de-duplicated. Same order
    regardless of doc.kind, so the CV and job sides stay symmetric (see the
    comment in match_cv_to_job for why symmetry matters).

    Capped at 12000 chars as a safety ceiling (a pathological OCR dump),
    NOT at the cross-encoder's single-pass window: _cross_encode_best()
    chunks and scores the full text instead of betting everything on one
    ~2000-char window, since real CVs in this project average ~9-10k
    characters and a manual check found most exceed a single window even
    after this section-priority selection.

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

    return combined[:12000]


def match_cv_to_job(cv_text: str, job_text: str, priority_keywords: str | None = None) -> MatchScore:
    """
    Full CV↔Job match using cross-encoder + structured scoring.

    Args:
        cv_text: Raw or pre-extracted CV text
        job_text: Raw or pre-extracted job offer text
        priority_keywords: Raw text of the job's recruiter-curated priority
            keywords (JobDocument.priority_keywords, one per line) — see
            _apply_priority_keywords for how these are folded in.

    Returns:
        MatchScore with all component scores and final 0-100 score
    """
    cv = parse_document(cv_text, kind="cv")
    job = parse_document(job_text, kind="job")
    job.priority_keyword_terms = split_priority_keywords(priority_keywords)
    return match_parsed_documents(cv, job)


# A "Mots Clés.docx" pasted into the priority-keywords textarea very
# commonly renders each bullet as a leading glyph the source Word list
# style used ("•", "◦", "‣", "▪", a plain "-"/"*", or a numbered
# "1."/"1)"/"(1)") -- none of which are actual keyword characters. Left
# in place, EVERY line in a bulleted list keeps its marker as part of the
# "keyword" text ("• Chef de projet" instead of "Chef de projet"), which
# then never normalizes to anything in the taxonomy and silently fails to
# match a CV that plainly demonstrates it. Confirmed as a recurring,
# manual chore: recruiters report routinely having to strip this
# themselves before saving, for every bulleted keyword list they paste.
_BULLET_PREFIX_RE = re.compile(r"^(?:[•◦‣▪·\-\*]|\(?\d+[.)])\s+")

# The header line ("Mots Clés :", "Liste des mots-clés", "MOTS CLÉS",
# "Mot cle recherche"...) varies more than a small fixed set of exact
# strings can reliably catch -- checking that the folded line merely
# CONTAINS "mots cle" (singular root, so "clé"/"clés"/"cles" all fold to
# it) after the bullet/punctuation strip below catches real-world
# variations, including a leading lead-in word ("Liste des mots-clés"),
# without needing to enumerate every one of them by hand. No real skill
# or job keyword would itself contain the phrase "mot(s) clé(s)", so a
# substring check carries no meaningful false-positive risk here.
_KEYWORDS_HEADER_MARKERS = ("mots cle", "mot cle", "keyword")


def split_priority_keywords(raw: str | None) -> list[str]:
    """Parse a recruiter-edited priority-keywords text (one per line, as
    saved from the "Mots-clés prioritaires" textarea) into a clean list of
    terms. Blank lines are dropped; a leading list-bullet marker per line
    and a "Mots Clés :"-style header line (both commonly present when a
    "Mots Clés.docx" list is pasted in directly) are stripped too."""
    if not raw:
        return []
    terms = []
    for line in raw.splitlines():
        term = _BULLET_PREFIX_RE.sub("", line.strip())
        term = term.strip().strip(":,;").strip()
        if not term:
            continue
        # "-" -> " " before the containment check: _fold() strips accents
        # and case but leaves hyphens alone, and "mots-clés" (hyphenated)
        # is at least as common a spelling as "mots clés" (space).
        folded_term = _fold(term).replace("-", " ")
        if len(term.split()) <= 6 and any(marker in folded_term for marker in _KEYWORDS_HEADER_MARKERS):
            continue
        terms.append(term)
    return terms


def _normalize_priority_keyword(raw_term: str) -> str | None:
    """normalize_skill(), extended for the recruiter shorthand of combining
    two synonymous abbreviations on one line with a slash ("MOA / AMOA",
    "Assurance/IARD"). normalize_skill() itself does one exact lookup on
    the whole folded string -- "moa / amoa" is never going to be a
    registered alias itself, even though "moa" and "amoa" both are (both
    to the same canonical, "Maîtrise d'ouvrage"). Confirmed in production:
    a candidate whose CV literally read "Chef de Projet MOA" three times
    still showed "MOA / AMOA" as a missing priority keyword, because the
    combined raw string never matched anything -- the coverage fraction
    used the literal text "MOA / AMOA" as its own fake "canonical" instead
    of the real one his CV plainly satisfied.

    Splits on "/" and normalizes each side; returns the shared canonical
    only when every side that does normalize agrees, so an ambiguous
    combo naming two genuinely different things ("Excel/PowerPoint")
    isn't silently collapsed into one.
    """
    canonical = normalize_skill(raw_term)
    if canonical:
        return canonical
    if "/" not in raw_term:
        return None
    parts_canonical = {
        normalize_skill(part) for part in raw_term.split("/") if part.strip()
    }
    parts_canonical.discard(None)
    if len(parts_canonical) == 1:
        return next(iter(parts_canonical))
    return None


def _apply_priority_keywords(cv: ParsedDocument, job: ParsedDocument) -> None:
    """Make a job's recruiter-curated priority keywords detectable on the
    CV side, bypassing find_skills() for terms it doesn't recognize --
    WITHOUT folding them into job.required_skill_terms (that used to be
    the whole mechanism, before priority keywords got their own scoring
    component: see _priority_keyword_score and the priority_keywords
    weight in _DEFAULT_W). Mixing them into the general required-skills
    set meant they only ever pulled the *generic* skills score up or down
    by whatever fraction they made of the total -- a CV missing exactly
    what the recruiter flagged as priority could still score well by
    covering enough *other*, auto-detected skills instead. A dedicated
    component with its own weight can't be compensated for that way.

    Some of these terms (e.g. "LOD2", "DORA", "TRM" -- real examples from
    production) have no taxonomy entry at all, so no amount of them
    appearing in the CV would ever make find_skills() extract them as a
    skill on its own. For each keyword: normalize to a taxonomy canonical
    when one exists (so it lines up with whatever find_skills() already
    extracted from the CV, e.g. "assurance" -> the same canonical the CV's
    own text would produce); otherwise scan the CV's own text for the raw
    term directly -- it can never end up in cv.skill_terms any other way.
    Either way, mutates cv.skill_terms only (never job.required_skill_terms),
    purely so the term shows up in the CV's detected competences for
    transparency; _resolve_priority_keywords() below is what actually
    scores coverage.
    """
    cv_text_folded = _fold(cv.cleaned_text)
    for raw_term in job.priority_keyword_terms:
        canonical = _normalize_priority_keyword(raw_term)
        if canonical:
            continue  # already detectable via find_skills() like any other skill
        term = raw_term
        if term not in cv.skill_terms and re.search(rf"\b{re.escape(_fold(term))}\b", cv_text_folded):
            cv.skill_terms.append(term)


def _resolve_priority_keywords(cv: ParsedDocument, job: ParsedDocument) -> tuple[list[str], list[str]]:
    """(matched, all_terms): the job's priority keywords resolved to their
    taxonomy canonical (or left as the raw term when the taxonomy doesn't
    recognize it), DEDUPLICATED by canonical, and which of those are
    present in cv.skill_terms (already enriched for unknown terms by
    _apply_priority_keywords). Shared by _priority_keyword_score (the
    weighted component) and match_parsed_documents (which exposes the raw
    counts on MatchScore for the UI, e.g. "6/9 mots-clés prioritaires
    trouvés").

    Deduplication matters because recruiters routinely type several
    phrasings of the SAME tool as separate lines ("SAS Enterprise Guide",
    "SAS Base", "SAS Grid" all normalize to the single canonical "SAS
    (logiciel)"; "tableaux de bord" and "reporting" both normalize to
    "Reporting"). Counting each raw line as its own slot silently changes
    what the fraction actually measures: a candidate who mentions SAS once
    got credit for 3 "matched" keywords instead of 1 (inflating anyone with
    even a passing mention of the job's core tool), while a candidate who
    never mentions SAS at all only lost 3 slots out of 12+ -- diluting the
    one gap that should matter most into a fraction of a broad average.
    Deduplicating first means the count reflects distinct required
    concepts, so a candidate missing the job's headline tool can't have
    that loss buried under a dozen effectively-repeated line items.
    """
    seen: dict[str, None] = {}
    matched_seen: dict[str, None] = {}
    cv_skills = set(cv.skill_terms)
    for raw_term in job.priority_keyword_terms:
        canonical = _normalize_priority_keyword(raw_term) or raw_term
        seen.setdefault(canonical, None)
        if canonical in cv_skills:
            matched_seen.setdefault(canonical, None)
    return list(matched_seen), list(seen)


def _priority_keyword_score(cv: ParsedDocument, job: ParsedDocument) -> tuple[float, bool]:
    """Coverage of the job's recruiter-curated priority keywords, as its
    own scoring component distinct from the general skills coverage (see
    _DEFAULT_W's priority_keywords weight) -- so a CV missing exactly what
    the recruiter flagged as priority can't be made up for by scoring well
    on generic vocabulary/skills elsewhere.

    has_signal is False when the job has no priority keywords at all (the
    common case: most recruiters never fill this in), so it's excluded
    from the weighted average entirely for that job rather than diluting
    every score with a neutral placeholder value.
    """
    if not job.priority_keyword_terms:
        return 0.5, False
    matched, all_terms = _resolve_priority_keywords(cv, job)
    return (len(matched) / len(all_terms) if all_terms else 0.5), True


# A recruiter who types several phrasings of the SAME tool as separate
# priority-keyword lines ("SAS Enterprise Guide", "SAS Base", "SAS Grid" --
# all normalizing to the canonical "SAS (logiciel)") is, in effect, telling
# us that tool is the job's headline requirement, not just one item among
# many. The average priority-keywords coverage fraction can't capture this:
# missing exactly that one emphasized tool is diluted into a fraction of a
# dozen-plus other, less central keywords -- observed in production on a
# "Data Analyst Expert SAS" job, where several candidates with zero SAS
# experience but decent generic BI/SQL overlap still scored 55-68%.
#
# Repetition count is a fully generic signal (position in the list, or the
# literal word, are NOT used) -- it only reacts to a pattern the recruiter
# themselves created by typing the same concept multiple times, so it
# applies to any future job without hardcoding any specific tool name. A
# second, independent signal is checked alongside it: whether the keyword
# also appears in the job's own title line (see _core_keyword_coverage) --
# together they catch both a recruiter who repeats the headline tool
# across several keyword lines AND one who only types it once but names it
# in the job title itself (arguably the more common case).
_CORE_KEYWORD_MIN_REPEATS = 3
# Multiplicative, not a hard cap: final *= CORE_PENALTY_FLOOR + (1 -
# CORE_PENALTY_FLOOR) * core_coverage. A hard min() cap was tried first and
# rejected -- it collapsed every candidate missing the core tool to the
# exact same floor value regardless of how they differed otherwise
# (experience, other real skills), erasing differentiation a human
# reviewer clearly still makes among "doesn't have the core tool" CVs.
# Scaling the final score instead preserves that relative ordering while
# still applying a substantial, real penalty for missing the emphasized
# requirement.
_CORE_PENALTY_FLOOR = 0.45

# Floor for the skills/priority-keywords caps below (0.0-1.0 coverage maps
# to _SKILL_CAP_FLOOR-1.0 score). See the comment at the cap's call site in
# match_parsed_documents for the calibration rationale.
_SKILL_CAP_FLOOR = 0.30


def _core_keyword_coverage(cv: ParsedDocument, job: ParsedDocument) -> float:
    """Coverage (0.0-1.0) of the job's "emphasized" priority keywords.

    A canonical is emphasized when either:
    - the recruiter typed it via at least _CORE_KEYWORD_MIN_REPEATS
      distinct raw lines (see the module comment above), or
    - its raw keyword text literally appears in the job's title line
      (ParsedDocument.title_line) -- a job posting's title is
      recruiter-authored and reliably names the role/headline tool
      ("Data Analyst Expert SAS"), unlike a CV's first line (often just
      the candidate's name), so this check is only applied to the job
      side. This also naturally recovers a taxonomy edge case: bare "SAS"
      doesn't normalize to "SAS (logiciel)" (excluded as a common French
      legal-entity suffix, see taxonomy.py), so a candidate who plainly
      wrote "SAS" on their CV wouldn't otherwise match the canonical the
      recruiter's other SAS-variant keywords resolved to -- checking the
      raw keyword against cv.skill_terms too (not just its canonical)
      credits that candidate correctly.

    Returns 1.0 (no penalty) when no keyword qualifies as emphasized, so
    an ordinary, non-repeated priority-keyword list for a job whose title
    doesn't mention any of them is entirely unaffected by this mechanism.
    """
    if not job.priority_keyword_terms:
        return 1.0
    counts = Counter(_normalize_priority_keyword(t) or t for t in job.priority_keyword_terms)
    core = {canonical for canonical, n in counts.items() if n >= _CORE_KEYWORD_MIN_REPEATS}

    title_folded = _fold(job.title_line)
    cv_skills = set(cv.skill_terms)
    matched = {c for c in core if c in cv_skills}
    if title_folded:
        for raw_term in job.priority_keyword_terms:
            canonical = _normalize_priority_keyword(raw_term) or raw_term
            if canonical in core:
                continue
            if _fold(raw_term) not in title_folded:
                continue
            core.add(canonical)
            if canonical in cv_skills or raw_term in cv_skills:
                matched.add(canonical)

    if not core:
        return 1.0
    return len(matched) / len(core)


def match_parsed_documents(cv: ParsedDocument, job: ParsedDocument) -> MatchScore:
    """
    Same as match_cv_to_job, but takes documents already parsed by the caller.

    Use this when scoring one document against many counterparts (e.g. one
    CV against a shortlist of jobs) so the side that doesn't change across
    the loop is parsed once instead of once per pair.
    """
    if job.priority_keyword_terms:
        _apply_priority_keywords(cv, job)

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
    semantic = _cross_encode_best(job_repr, cv_repr)

    skills, skills_ok = _skill_score(cv, job)
    priority_kw_score, priority_kw_ok = _priority_keyword_score(cv, job)
    experience, experience_ok = _experience_score(cv, job)
    education, education_ok = _education_score(cv, job)
    languages, languages_ok = _language_score(cv, job)
    contract, contract_ok = _contract_score(cv, job)

    structured = (
        ("skills", skills, skills_ok),
        ("priority_keywords", priority_kw_score, priority_kw_ok),
        ("experience", experience, experience_ok),
        ("education", education, education_ok),
        ("languages", languages, languages_ok),
        ("contract", contract, contract_ok),
    )
    low_confidence = [name for name, _value, ok in structured if not ok]

    # Renormalize over components with a real signal instead of averaging in
    # the neutral/penalty defaults of missing ones (e.g. skills=0.0 when the
    # CV extraction failed, experience=0.2 when years couldn't be read). Those
    # defaults exist so each component always returns a number, not so a
    # failed extraction can silently drag the final score down at full
    # weight — see the has_signal contract on each _*_score function above.
    # 'semantic' has no has_signal flag: the cross-encoder always produces a
    # comparison (real, or a neutral 0.5 fallback when unavailable), so it
    # always counts.
    weighted_sum = w["semantic"] * semantic
    weight_total = w["semantic"]
    for name, value, ok in structured:
        if ok:
            weighted_sum += w[name] * value
            weight_total += w[name]

    final = weighted_sum / weight_total if weight_total > 0 else 0.5
    final = max(0.0, min(1.0, final))

    # Cap: semantic similarity (0.40, the single highest weight) plus decent
    # experience/education/language/contract scores can otherwise push a CV
    # missing MOST of the job's required skills into "Fort" territory on
    # generic professional vocabulary alone (reporting, communication,
    # gouvernance...) shared with the job text. Observed in production on a
    # "Data Analyst Expert SAS" offer: three CVs missing the job's named
    # core tool -- two of them missing SQL too -- scored 93%+ "Fort" while
    # the system's own explanation admitted those skills were absent. Skill
    # coverage is the most literal, least ambiguous signal we have when the
    # job lists required skills at all, so it sets a ceiling the rest of the
    # score can approach but never exceed.
    #
    # Floor calibrated (2026-09-11) against a 16-CV / 1-job real-world
    # validation set with an independent human-judgment target score for
    # each pair: the previous 0.5 floor let a CV with essentially no
    # relevant skill overlap still land at 50%, far above what any
    # recruiter reviewing the same pair would call it. _SKILL_CAP_FLOOR is
    # the floor at zero coverage; coverage of 1.0 always reaches 100%
    # regardless of the floor (floor + (1-floor)*1.0 == 1.0), so a genuinely
    # perfect match is never held back by this constant.
    if skills_ok:
        final = min(final, _SKILL_CAP_FLOOR + (1 - _SKILL_CAP_FLOOR) * skills)
    # Same reasoning, applied to the recruiter's own priorities specifically:
    # a weight alone still lets the other ~80% of the score compensate for
    # missing exactly what the recruiter flagged as most important. The cap
    # makes that non-negotiable, the same way the skills cap above does for
    # the general required-skills set.
    if priority_kw_ok:
        final = min(final, _SKILL_CAP_FLOOR + (1 - _SKILL_CAP_FLOOR) * priority_kw_score)

    # Multiplicative penalty (not a cap) for missing the job's "emphasized"
    # tool(s) -- see _core_keyword_coverage. Applied after the caps above
    # rather than folded into them, so it scales down whatever differentiated
    # score two candidates already have instead of collapsing them to one
    # shared floor value.
    core_coverage = _core_keyword_coverage(cv, job)
    if core_coverage < 1.0:
        final *= _CORE_PENALTY_FLOOR + (1 - _CORE_PENALTY_FLOOR) * core_coverage

    cv_skills = set(cv.skill_terms)
    job_required = set(job.required_skill_terms or job.skill_terms)
    priority_matched, priority_all = (
        _resolve_priority_keywords(cv, job) if job.priority_keyword_terms else ([], [])
    )

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
        score_priority_keywords=round(priority_kw_score, 4) if priority_kw_ok else None,
        priority_keywords_matched=sorted(priority_matched),
        priority_keywords_total=len(priority_all),
    )


def score_texts(cv_text: str, job_text: str, priority_keywords: str | None = None) -> tuple[float, list[str]]:
    """
    Drop-in replacement for the legacy score_texts() in scoring.py.
    Returns (score_0_to_100, common_keywords).
    """
    result = match_cv_to_job(cv_text, job_text, priority_keywords)
    return result.score, result.common_skills
