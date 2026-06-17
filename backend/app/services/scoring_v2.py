"""
POC layer 4: Gradient-boosted match aggregator with explicit signals.

Why not just reuse weight_learner.py:
- weight_learner.py learns *linear* weights over the 6 existing component
  scores — fine when component scores are well-calibrated, but it can't model
  interactions like "high skill_overlap is worthless if domain_match is low".
- scoring_v2 adds two new signals (domain_match, lang_proficiency_match) and
  replaces the linear aggregator with a calibrated Gradient Boosting model
  that *does* learn those interactions.

This module is additive: it doesn't touch matcher.py / scoring.py. You opt in
by calling `score_pair(cv_profile, job_profile)` and feeding the result into
the response payload alongside the existing score. Once we have evidence it
beats the linear aggregator on real feedbacks, the matcher can be switched
over.

Training data: MatchFeedback rows joined with MatchResult component scores
(same source as weight_learner) — plus the two new signals computed on the
fly from cached parsed_profile JSONs.
"""
from __future__ import annotations

import logging
import pickle
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

SIGNAL_KEYS = (
    "skill_overlap",       # Jaccard of normalized skill terms
    "semantic_sim",        # cosine of cv/job embeddings
    "experience_fit",      # 1 - |cv_years - job_years_required| / max(job_years, 1)
    "lang_match",          # share of required langs covered by the CV
    "domain_match",        # cosine between cv summary and job summary embeddings
    "must_have_coverage",  # share of required_skill_terms found in cv
)

MIN_SAMPLES = 20
MIN_PER_CLASS = 5
MODEL_FILENAME = "scoring_v2_gbm.pkl"


@dataclass
class SignalVector:
    skill_overlap: float = 0.0
    semantic_sim: float = 0.0
    experience_fit: float = 0.0
    lang_match: float = 0.0
    domain_match: float = 0.0
    must_have_coverage: float = 0.0

    def as_array(self) -> np.ndarray:
        return np.array(
            [
                self.skill_overlap,
                self.semantic_sim,
                self.experience_fit,
                self.lang_match,
                self.domain_match,
                self.must_have_coverage,
            ],
            dtype=float,
        )


@dataclass
class Aggregator:
    """Wraps the trained GBM + calibrator for inference."""
    model: object  # CalibratedClassifierCV
    feature_means: np.ndarray
    feature_stds: np.ndarray
    sample_count: int
    auc: float
    feature_importance: dict[str, float] = field(default_factory=dict)

    def predict_proba(self, sv: SignalVector) -> float:
        x = sv.as_array().reshape(1, -1)
        x = (x - self.feature_means) / (self.feature_stds + 1e-9)
        return float(self.model.predict_proba(x)[0, 1])

    def save(self, path: Path) -> None:
        with path.open("wb") as f:
            pickle.dump(
                {
                    "model": self.model,
                    "feature_means": self.feature_means,
                    "feature_stds": self.feature_stds,
                    "sample_count": self.sample_count,
                    "auc": self.auc,
                    "feature_importance": self.feature_importance,
                },
                f,
            )

    @classmethod
    def load(cls, path: Path) -> "Aggregator":
        with path.open("rb") as f:
            blob = pickle.load(f)
        return cls(**blob)


# ----------------------------------------------------------------------------
# Signal computation
# ----------------------------------------------------------------------------


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def _coverage(required: set[str], present: set[str]) -> float:
    if not required:
        return 1.0
    return len(required & present) / len(required)


def compute_signals(
    cv_profile: dict,
    job_profile: dict,
    semantic_sim: float = 0.0,
    domain_sim: float = 0.0,
) -> SignalVector:
    """Compute the 6 independent signals from two parsed_profile dicts.

    `cv_profile` / `job_profile` are the JSON-serialised StructuredDocument
    payloads stored in `ExtractedText.parsed_profile`. The two embedding-based
    signals (`semantic_sim`, `domain_sim`) are passed in by the caller because
    they require the embedding model loaded — keep this module embedding-free.
    """
    # Prefer ESCO URIs when both sides have them — they're a stable identity
    # that survives phrasing differences ("dev fullstack" vs "ingénieur fullstack").
    # If either side is missing ESCO URIs, fall back to lowercased skill_terms.
    cv_uris = list(cv_profile.get("esco_skill_uris") or [])
    job_uris = list(job_profile.get("esco_skill_uris") or [])
    if cv_uris and job_uris:
        cv_skills = set(cv_uris)
        job_skills = set(job_uris)
        # required falls back to terms even when URIs exist (we don't yet
        # populate required_esco_uris — keep the door open for a future field)
        required = {s.lower() for s in (job_profile.get("required_skill_terms") or [])}
    else:
        cv_skills = {s.lower() for s in (cv_profile.get("skill_terms") or [])}
        job_skills = {s.lower() for s in (job_profile.get("skill_terms") or [])}
        required = {s.lower() for s in (job_profile.get("required_skill_terms") or [])}

    cv_langs = {l.lower() for l in (cv_profile.get("language_terms") or [])}
    job_langs = {l.lower() for l in (job_profile.get("language_terms") or [])}

    cv_years = float(cv_profile.get("experience_years") or 0.0)
    job_years = float(job_profile.get("experience_years") or 0.0)
    if job_years <= 0:
        experience_fit = 1.0 if cv_years >= 0 else 0.0
    else:
        # 1 when match, decays linearly; >= required gives 1.0
        if cv_years >= job_years:
            experience_fit = 1.0
        else:
            experience_fit = max(0.0, cv_years / job_years)

    return SignalVector(
        skill_overlap=_jaccard(cv_skills, job_skills),
        semantic_sim=float(max(0.0, min(1.0, semantic_sim))),
        experience_fit=experience_fit,
        lang_match=_coverage(job_langs, cv_langs),
        domain_match=float(max(0.0, min(1.0, domain_sim))),
        must_have_coverage=_coverage(required, cv_skills),
    )


# ----------------------------------------------------------------------------
# Training
# ----------------------------------------------------------------------------


def train_aggregator(session, model_path: Optional[Path] = None, domain_sim_fn=None) -> Aggregator:
    """Fit a calibrated Gradient Boosting model on MatchFeedback data.

    Layout matches weight_learner.compute_learned_weights but uses the new
    SIGNAL_KEYS as features. Caller may store the trained Aggregator to disk
    for cold-start inference.
    """
    from sqlalchemy import select
    from sklearn.calibration import CalibratedClassifierCV
    from sklearn.ensemble import GradientBoostingClassifier
    from sklearn.metrics import roc_auc_score
    from ..models import ExtractedText, MatchFeedback, MatchResult

    rows = session.execute(
        select(
            MatchFeedback.decision,
            MatchResult.score_skills,
            MatchResult.score_semantic,
            MatchResult.score_experience,
            MatchResult.score_languages,
            MatchResult.cv_path,
            MatchResult.job_path,
        )
        .join(MatchResult, MatchFeedback.match_id == MatchResult.id)
        .where(MatchFeedback.decision.in_(["accept", "reject"]))
        .where(MatchResult.score_skills.isnot(None))
    ).all()

    if len(rows) < MIN_SAMPLES:
        raise ValueError(
            f"Not enough labeled samples: {len(rows)} (need {MIN_SAMPLES})"
        )

    extractions = {
        e.file_path: e.parsed_profile or {}
        for e in session.execute(select(ExtractedText)).scalars().all()
        if e.parsed_profile
    }

    X_list: list[np.ndarray] = []
    y_list: list[int] = []
    for r in rows:
        cv_profile = extractions.get(r.cv_path) or {}
        job_profile = extractions.get(r.job_path) or {}
        domain_sim_val = domain_sim_fn(cv_profile, job_profile) if domain_sim_fn else 0.0
        sv = compute_signals(
            cv_profile,
            job_profile,
            semantic_sim=float(r.score_semantic or 0.0),
            domain_sim=domain_sim_val,
        )
        X_list.append(sv.as_array())
        y_list.append(1 if r.decision == "accept" else 0)

    X = np.vstack(X_list)
    y = np.array(y_list)
    if int(y.sum()) < MIN_PER_CLASS or int(len(y) - y.sum()) < MIN_PER_CLASS:
        raise ValueError(
            f"Need at least {MIN_PER_CLASS} of each class "
            f"(accept={int(y.sum())}, reject={int(len(y) - y.sum())})"
        )

    means = X.mean(axis=0)
    stds = X.std(axis=0)
    X_scaled = (X - means) / (stds + 1e-9)

    base = GradientBoostingClassifier(
        n_estimators=120,
        max_depth=3,
        learning_rate=0.05,
        random_state=42,
    )
    # Sigmoid calibration on the same training set; we don't have enough data
    # for a separate holdout, accept the slight optimism.
    model = CalibratedClassifierCV(base, method="sigmoid", cv=3)
    model.fit(X_scaled, y)

    try:
        proba = model.predict_proba(X_scaled)[:, 1]
        auc = float(roc_auc_score(y, proba))
    except Exception:
        auc = float("nan")

    # Pull feature importance from the underlying GBM ensemble for explainability
    importance: dict[str, float] = {}
    try:
        # CalibratedClassifierCV wraps an ensemble of fitted base estimators
        importances = np.mean(
            [c.estimator.feature_importances_ for c in model.calibrated_classifiers_], axis=0
        )
        importance = {k: float(v) for k, v in zip(SIGNAL_KEYS, importances)}
    except Exception:
        pass

    agg = Aggregator(
        model=model,
        feature_means=means,
        feature_stds=stds,
        sample_count=len(rows),
        auc=auc,
        feature_importance=importance,
    )

    if model_path is not None:
        try:
            agg.save(model_path)
            logger.info("scoring_v2 model saved to %s", model_path)
        except Exception as exc:
            logger.warning("Could not persist scoring_v2 model: %s", exc)

    logger.info(
        "scoring_v2 trained on %d samples, AUC=%.3f, importance=%s",
        len(rows),
        auc,
        {k: round(v, 3) for k, v in importance.items()},
    )
    return agg


# ----------------------------------------------------------------------------
# Inference helper
# ----------------------------------------------------------------------------


_aggregator_singleton: Optional[Aggregator] = None


def get_aggregator(model_path: Optional[Path] = None) -> Optional[Aggregator]:
    """Lazy-load a previously trained aggregator from disk. None if unavailable."""
    global _aggregator_singleton
    if _aggregator_singleton is not None:
        return _aggregator_singleton
    if model_path is None or not model_path.exists():
        return None
    try:
        _aggregator_singleton = Aggregator.load(model_path)
        return _aggregator_singleton
    except Exception as exc:
        logger.warning("scoring_v2 model could not be loaded from %s: %s", model_path, exc)
        return None


def score_pair(
    cv_profile: dict,
    job_profile: dict,
    semantic_sim: float = 0.0,
    domain_sim: float = 0.0,
    model_path: Optional[Path] = None,
) -> dict:
    """High-level inference: returns probability + raw signals for transparency."""
    sv = compute_signals(cv_profile, job_profile, semantic_sim=semantic_sim, domain_sim=domain_sim)
    agg = get_aggregator(model_path)
    proba = agg.predict_proba(sv) if agg is not None else None
    return {
        "probability": proba,
        "signals": {k: float(getattr(sv, k)) for k in SIGNAL_KEYS},
        "model_available": agg is not None,
    }
