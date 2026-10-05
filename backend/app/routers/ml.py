"""Endpoints ML/IA : /esco/lookup, /search."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select

from ..db import SessionLocal
from ..deps import require_user
from ..models import (
    CvDocument,
    CvEmbedding,
    ExtractedText,
    JobDocument,
    JobEmbedding,
)
from ..schemas import (
    EscoLookupRequest,
    EscoLookupResult,
    EscoMatch,
    SearchHit,
    SearchRequest,
)
from ..services import embed_text, score_texts
from ..settings import get_settings

settings = get_settings()

router = APIRouter(tags=["ml"])


def _vector_score(distance: float) -> float:
    similarity = max(0.0, 1.0 - distance)
    return round(similarity * 100, 2)


def _hybrid_score_with_weights(
    vector_score: float,
    lexical_score: float,
    vector_weight: float,
    lexical_weight: float,
) -> float:
    weight_sum = vector_weight + lexical_weight
    if weight_sum <= 0:
        return vector_score
    combined = (vector_score * vector_weight + lexical_score * lexical_weight) / weight_sum
    return round(combined, 2)


@router.post("/esco/lookup", response_model=EscoLookupResult)
def esco_lookup(payload: EscoLookupRequest, request: Request) -> EscoLookupResult:
    require_user(request)
    from ..services.esco_taxonomy import find_skills_esco, get_esco_index
    if not payload.text.strip():
        raise HTTPException(status_code=400, detail="text required")
    idx = get_esco_index()
    if idx is None:
        return EscoLookupResult(matches=[], available=False)
    hits = find_skills_esco(payload.text, top_k=max(1, min(20, payload.top_k)))
    return EscoLookupResult(
        matches=[
            EscoMatch(uri=s.uri, preferred_label=s.preferred_label, score=round(score, 4))
            for s, score in hits
        ],
        available=True,
    )


@router.post("/search", response_model=list[SearchHit])
def search_semantic(payload: SearchRequest) -> list[SearchHit]:
    if not settings.embedding_enabled:
        raise HTTPException(status_code=400, detail="embeddings disabled")

    query_text = payload.query.strip()
    if not query_text:
        raise HTTPException(status_code=400, detail="query required")

    vector = embed_text(query_text)
    if not vector:
        return []

    top_k = max(1, min(payload.top_k, 100))

    vector_weight = (
        payload.vector_weight
        if payload.vector_weight is not None
        else settings.hybrid_vector_weight
    )
    lexical_weight = (
        payload.lexical_weight
        if payload.lexical_weight is not None
        else settings.hybrid_lexical_weight
    )
    vector_weight = max(0.0, vector_weight)
    lexical_weight = max(0.0, lexical_weight)
    use_hybrid = settings.hybrid_scoring_enabled or payload.vector_weight is not None or payload.lexical_weight is not None

    if payload.kind == "cv":
        distance = CvEmbedding.embedding.cosine_distance(vector).label("distance")
        stmt = (
            select(CvDocument, ExtractedText.extracted_text, distance)
            .join(CvEmbedding, CvEmbedding.cv_id == CvDocument.id)
            .join(ExtractedText, ExtractedText.file_path == CvDocument.path, isouter=True)
            .order_by(distance.asc())
            .limit(top_k)
        )
        if payload.status:
            stmt = stmt.where(CvDocument.status == payload.status)
    else:
        distance = JobEmbedding.embedding.cosine_distance(vector).label("distance")
        stmt = (
            select(JobDocument, ExtractedText.extracted_text, distance)
            .join(JobEmbedding, JobEmbedding.job_id == JobDocument.id)
            .join(ExtractedText, ExtractedText.file_path == JobDocument.path, isouter=True)
            .order_by(distance.asc())
            .limit(top_k)
        )
        if payload.status:
            stmt = stmt.where(JobDocument.status == payload.status)

    results: list[SearchHit] = []
    with SessionLocal() as session:
        rows = session.execute(stmt).all()

    for doc, extracted_text, distance_value in rows:
        vector_score = _vector_score(float(distance_value))
        score = vector_score
        if use_hybrid:
            lexical_score = 0.0
            if extracted_text:
                lexical_score, _ = score_texts(query_text, extracted_text)
            score = _hybrid_score_with_weights(
                vector_score,
                lexical_score,
                vector_weight,
                lexical_weight,
            )
        if payload.min_score is not None and score < payload.min_score:
            continue
        results.append(
            SearchHit(
                id=doc.id,
                path=doc.path,
                status=doc.status,
                score=score,
                updated_at=doc.updated_at,
            )
        )

    return results
