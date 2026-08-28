"""Endpoints /feedback/* et /matches/{id}/feedback."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import func, select

from ..db import SessionLocal
from ..deps import require_admin, require_user
from ..models import (
    CvDocument,
    ExtractedText,
    JobDocument,
    LearnedWeights,
    MatchFeedback,
    MatchResult,
)
from ..schemas import (
    FeedbackComponentScores,
    FeedbackDecisionStats,
    FeedbackDomainRow,
    FeedbackStatsRead,
    FeedbackWeightHint,
    LearnedWeightsRead,
    MatchFeedbackCreate,
    MatchFeedbackExportRead,
    MatchFeedbackRead,
    WeightComputeResult,
)
from ..services.matcher import get_active_weights
from ..services.weight_learner import compute_learned_weights

router = APIRouter(tags=["feedback"])


_COMP_LABELS = {
    "score_skills":     "Compétences",
    "score_semantic":   "Sémantique",
    "score_experience": "Expérience",
    "score_education":  "Formation",
    "score_languages":  "Langues",
    "score_contract":   "Contrat",
}


@router.get("/matches/{match_id}/feedback", response_model=MatchFeedbackRead | None)
def get_match_feedback(match_id: int, request: Request) -> MatchFeedbackRead | None:
    require_user(request)
    with SessionLocal() as session:
        match = session.get(MatchResult, match_id)
        if not match:
            raise HTTPException(status_code=404, detail="Match not found")
        feedback = session.scalar(
            select(MatchFeedback)
            .where(MatchFeedback.match_id == match_id)
            .order_by(MatchFeedback.created_at.desc())
        )
        return MatchFeedbackRead.model_validate(feedback) if feedback else None


@router.post("/matches/{match_id}/feedback", response_model=MatchFeedbackRead)
def create_match_feedback(match_id: int, payload: MatchFeedbackCreate, request: Request) -> MatchFeedbackRead:
    require_user(request)

    rating = payload.rating
    if rating is not None:
        rating = max(1, min(5, rating))

    comment = payload.comment.strip() if payload.comment and payload.comment.strip() else None

    with SessionLocal() as session:
        match = session.get(MatchResult, match_id)
        if not match:
            raise HTTPException(status_code=404, detail="Match not found")

        # Snapshot what was actually compared/scored right now, since the
        # underlying CV/job/MatchResult rows can later be deleted (e.g. the
        # source file is replaced) — see deps.cleanup_removed_file, which
        # cascades to delete MatchResult rows on file deletion. Without this
        # snapshot, that would silently orphan this feedback with no way to
        # recover what it was actually about.
        cv_doc = session.get(CvDocument, match.cv_id)
        job_doc = session.get(JobDocument, match.job_id)
        cv_text_snapshot = None
        job_text_snapshot = None
        if cv_doc:
            extract = session.scalar(select(ExtractedText).where(ExtractedText.file_path == cv_doc.path))
            cv_text_snapshot = extract.extracted_text if extract else None
        if job_doc:
            extract = session.scalar(select(ExtractedText).where(ExtractedText.file_path == job_doc.path))
            job_text_snapshot = extract.extracted_text if extract else None

        scores_snapshot = {
            "score": match.score,
            "score_semantic": match.score_semantic,
            "score_skills": match.score_skills,
            "score_experience": match.score_experience,
            "score_education": match.score_education,
            "score_languages": match.score_languages,
            "score_contract": match.score_contract,
            "domain": match.match_domain,
        }

        feedback = MatchFeedback(
            match_id=match.id,
            decision=payload.decision,
            rating=rating,
            comment=comment,
            cv_text_snapshot=cv_text_snapshot,
            job_text_snapshot=job_text_snapshot,
            scores_snapshot=scores_snapshot,
        )
        session.add(feedback)
        session.commit()
        session.refresh(feedback)
        return MatchFeedbackRead.model_validate(feedback)


@router.get("/feedback/export", response_model=list[MatchFeedbackExportRead])
def export_feedback(request: Request, limit: int = 200, offset: int = 0) -> list[MatchFeedbackExportRead]:
    """Full feedback history (decision, comment, CV/job text and score
    breakdown as they were at feedback time) for periodic manual review —
    intended to be pulled down from time to time to guide corrections to
    the matching engine, not consumed automatically by anything."""
    require_admin(request)
    safe_limit = max(1, min(limit, 500))
    with SessionLocal() as session:
        rows = session.scalars(
            select(MatchFeedback)
            .order_by(MatchFeedback.created_at.desc())
            .offset(max(0, offset))
            .limit(safe_limit)
        ).all()
        return [MatchFeedbackExportRead.model_validate(row) for row in rows]


@router.get("/feedback/stats", response_model=FeedbackStatsRead)
def get_feedback_stats(request: Request) -> FeedbackStatsRead:
    require_user(request)
    with SessionLocal() as session:
        decision_rows = session.execute(
            select(
                MatchFeedback.decision,
                func.count().label("cnt"),
                func.avg(MatchFeedback.rating).label("avg_rating"),
            ).group_by(MatchFeedback.decision)
        ).all()

        total = sum(r.cnt for r in decision_rows)
        by_decision: dict[str, FeedbackDecisionStats] = {
            r.decision: FeedbackDecisionStats(
                count=r.cnt,
                pct=round(r.cnt / total * 100, 1) if total > 0 else 0.0,
                avg_rating=round(float(r.avg_rating), 2) if r.avg_rating is not None else None,
            )
            for r in decision_rows
        }

        comp_rows = session.execute(
            select(
                MatchFeedback.decision,
                func.avg(MatchResult.score_skills).label("score_skills"),
                func.avg(MatchResult.score_semantic).label("score_semantic"),
                func.avg(MatchResult.score_experience).label("score_experience"),
                func.avg(MatchResult.score_education).label("score_education"),
                func.avg(MatchResult.score_languages).label("score_languages"),
                func.avg(MatchResult.score_contract).label("score_contract"),
                func.avg(MatchResult.score).label("score_global"),
            )
            .join(MatchResult, MatchFeedback.match_id == MatchResult.id)
            .group_by(MatchFeedback.decision)
        ).all()

        def _f(v: float | None) -> float | None:
            return round(float(v), 3) if v is not None else None

        avg_scores_by_decision: dict[str, FeedbackComponentScores] = {
            r.decision: FeedbackComponentScores(
                score_skills=_f(r.score_skills),
                score_semantic=_f(r.score_semantic),
                score_experience=_f(r.score_experience),
                score_education=_f(r.score_education),
                score_languages=_f(r.score_languages),
                score_contract=_f(r.score_contract),
                score_global=round(float(r.score_global), 1) if r.score_global is not None else None,
            )
            for r in comp_rows
        }

        domain_rows = session.execute(
            select(
                MatchResult.match_domain,
                MatchFeedback.decision,
                func.count().label("cnt"),
                func.avg(MatchResult.score).label("avg_score"),
            )
            .join(MatchResult, MatchFeedback.match_id == MatchResult.id)
            .where(MatchResult.match_domain.isnot(None))
            .group_by(MatchResult.match_domain, MatchFeedback.decision)
        ).all()

        domain_map: dict[str, FeedbackDomainRow] = {}
        for r in domain_rows:
            if r.match_domain not in domain_map:
                domain_map[r.match_domain] = FeedbackDomainRow(domain=r.match_domain, total=0)
            row = domain_map[r.match_domain]
            row.total += r.cnt
            if r.decision == "accept":
                row.accept = r.cnt
                row.avg_score = round(float(r.avg_score), 1) if r.avg_score is not None else None
            elif r.decision == "reject":
                row.reject = r.cnt
            elif r.decision == "review":
                row.review = r.cnt

        by_domain = sorted(domain_map.values(), key=lambda d: d.total, reverse=True)

        accept_s = avg_scores_by_decision.get("accept")
        reject_s = avg_scores_by_decision.get("reject")
        weight_hints: list[FeedbackWeightHint] = []
        if accept_s and reject_s:
            for comp, label in _COMP_LABELS.items():
                a = getattr(accept_s, comp)
                r = getattr(reject_s, comp)
                if a is not None and r is not None:
                    weight_hints.append(FeedbackWeightHint(
                        component=comp,
                        label=label,
                        delta=round(a - r, 3),
                    ))
            weight_hints.sort(key=lambda h: h.delta, reverse=True)

        return FeedbackStatsRead(
            total=total,
            by_decision=by_decision,
            avg_scores_by_decision=avg_scores_by_decision,
            by_domain=by_domain,
            weight_hints=weight_hints,
        )


@router.get("/feedback/learned-weights", response_model=LearnedWeightsRead | None)
def get_learned_weights(request: Request) -> LearnedWeightsRead | None:
    require_user(request)
    with SessionLocal() as session:
        row = session.scalar(
            select(LearnedWeights)
            .where(LearnedWeights.is_active == True)
            .order_by(LearnedWeights.created_at.desc())
        )
        return LearnedWeightsRead.model_validate(row) if row else None


@router.post("/feedback/compute-weights", response_model=WeightComputeResult)
def compute_weights(request: Request) -> WeightComputeResult:
    """Preview-only: computes suggested weights from feedback via logistic
    regression, for a human (the developer) to review before deciding
    whether/how to adjust matcher._DOMAIN_W accordingly.

    Deliberately does not activate anything: the feedback pool isn't
    segmented by domain, so blindly applying a single learned weight set
    to every domain would undo the domain-specific calibration in
    matcher._DOMAIN_W (e.g. education mattering more in health/legal than
    in tech). See git history for the /feedback/apply-weights endpoint
    that used to auto-activate this and was removed for that reason.
    """
    require_admin(request)
    with SessionLocal() as session:
        try:
            result = compute_learned_weights(session)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))

    current = get_active_weights() or {
        "semantic": 0.40, "skills": 0.30, "experience": 0.12,
        "education": 0.08, "languages": 0.05, "contract": 0.05,
    }
    return WeightComputeResult(
        weights={k: round(v, 4) for k, v in result.items()
                 if k not in ("sample_count", "accuracy")},
        sample_count=result["sample_count"],
        accuracy=result["accuracy"],
        current_weights={k: round(v, 4) for k, v in current.items()},
    )
