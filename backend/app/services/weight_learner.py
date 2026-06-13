"""
Adaptive weight learning from match feedback.

Uses logistic regression (sklearn) on accept/reject labeled matches to
derive component weights that best predict recruiter decisions.
Requires at least MIN_SAMPLES feedbacks with non-null component scores.
"""
from __future__ import annotations

import logging

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

MIN_SAMPLES     = 10
MIN_PER_CLASS   = 3

COMPONENTS = [
    "score_skills",
    "score_semantic",
    "score_experience",
    "score_education",
    "score_languages",
    "score_contract",
]

WEIGHT_KEYS = [
    "skills",
    "semantic",
    "experience",
    "education",
    "languages",
    "contract",
]


def compute_learned_weights(session: Session) -> dict:
    """
    Fetch accept/reject feedbacks joined with component scores, train a
    logistic regression, and return normalised weight dict + metadata.

    Returns:
        {
            "skills": float, "semantic": float, ...,
            "sample_count": int,
            "accuracy": float,
        }

    Raises:
        ValueError: if not enough labeled data.
    """
    from ..models import MatchFeedback, MatchResult  # local import avoids circular
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler

    rows = session.execute(
        select(
            MatchFeedback.decision,
            MatchResult.score_skills,
            MatchResult.score_semantic,
            MatchResult.score_experience,
            MatchResult.score_education,
            MatchResult.score_languages,
            MatchResult.score_contract,
        )
        .join(MatchResult, MatchFeedback.match_id == MatchResult.id)
        .where(MatchFeedback.decision.in_(["accept", "reject"]))
        .where(MatchResult.score_skills.isnot(None))
    ).all()

    if len(rows) < MIN_SAMPLES:
        raise ValueError(
            f"Données insuffisantes : {len(rows)} feedbacks avec scores "
            f"(minimum {MIN_SAMPLES} requis)."
        )

    X = np.array([
        [
            r.score_skills     or 0.0,
            r.score_semantic   or 0.0,
            r.score_experience or 0.0,
            r.score_education  or 0.0,
            r.score_languages  or 0.0,
            r.score_contract   or 0.0,
        ]
        for r in rows
    ], dtype=float)

    y = np.array([1 if r.decision == "accept" else 0 for r in rows])

    n_accept = int(y.sum())
    n_reject = int(len(y) - n_accept)
    if n_accept < MIN_PER_CLASS or n_reject < MIN_PER_CLASS:
        raise ValueError(
            f"Il faut au moins {MIN_PER_CLASS} exemples acceptés ET rejetés "
            f"(actuellement : {n_accept} acceptés, {n_reject} rejetés)."
        )

    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    lr = LogisticRegression(C=1.0, max_iter=1000, random_state=42)
    lr.fit(X_scaled, y)

    coefs = lr.coef_[0]  # shape (6,)

    # Keep only positive coefficients (predictors of acceptance)
    positive = np.maximum(coefs, 0.0)
    total = positive.sum()
    if total < 1e-9:
        # All negative: use absolute values (shouldn't happen in practice)
        positive = np.abs(coefs)
        total = positive.sum()

    weights = (positive / total).tolist()
    accuracy = float(lr.score(X_scaled, y))

    result = dict(zip(WEIGHT_KEYS, weights))
    result["sample_count"] = len(rows)
    result["accuracy"] = round(accuracy, 3)

    logger.info(
        "Learned weights computed from %d samples (accuracy=%.1f%%): %s",
        len(rows), accuracy * 100,
        {k: round(v, 3) for k, v in result.items() if k not in ("sample_count", "accuracy")},
    )
    return result
