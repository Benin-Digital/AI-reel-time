from contextlib import asynccontextmanager
import json
from html import escape
import logging
from pathlib import Path
import tempfile
import threading
from time import perf_counter, time
from datetime import datetime
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request, Response, UploadFile, File, Form, BackgroundTasks
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import redis
from sqlalchemy import delete, func, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from .db import SessionLocal, init_db
from .auth import (
    authenticate_user,
    authenticate_request,
    create_access_token,
    ensure_bootstrap_user,
    hash_password,
)
from .models import (
    EventLog,
    ExtractedText,
    ScoreResult,
    CvDocument,
    JobDocument,
    MatchResult,
    CvEmbedding,
    JobEmbedding,
    JobOffer,
    MatchFeedback,
    User,
    AnalysisSession,
)
from .schemas import (
    EventCreate,
    EventRead,
    WatcherSimulateRequest,
    IngestDeleteRequest,
    IngestDeleteBatchRequest,
    ExtractedTextCreate,
    ExtractedTextRead,
    ScoreRequest,
    ScoreRead,
    CvDocumentRead,
    CvDocumentDetailRead,
    JobDocumentRead,
    JobDocumentDetailRead,
    JobPriorityKeywordsUpdate,
    JobPriorityKeywordsExtracted,
    AnalysisSessionCreate,
    AnalysisSessionRead,
    AnalysisSessionDetailRead,
    AnalysisSessionUpdate,
    SessionAssignRequest,
    JobOfferCreate,
    JobOfferRead,
    CvProfileCreate,
    CvProfileRead,
    MatchRead,
    MatchFeedbackCreate,
    MatchFeedbackRead,
    FeedbackStatsRead,
    FeedbackDecisionStats,
    FeedbackComponentScores,
    FeedbackDomainRow,
    FeedbackWeightHint,
    LearnedWeightsRead,
    WeightComputeResult,
    ScoringV2TrainResult,
    ScoringV2ScoreRequest,
    ScoringV2ScoreResult,
    ScoringV2Status,
    EscoLookupRequest,
    EscoMatch,
    EscoLookupResult,
    SearchRequest,
    SearchHit,
    AuthLoginRequest,
    AuthLoginResponse,
    MatchExplainRead,
    AnalyzeRequest,
    ScoringWeightsRead,
    UserCreate,
    UserUpdate,
    UserRead,
)
from .services import (
    LocalFolderWatcher,
    WatchEvent,
    EventWorker,
    enqueue_event,
    file_sha256,
    extract_text,
    embed_text,
    embed_texts,
    extract_text,
    score_texts,
    serialize_keywords,
    deserialize_keywords,
    get_queue_status,
    warn_if_unsafe_backend,
    warn_if_esco_missing,
)
from .services.structured import build_document_profile, normalize_job_offer_from_parsed, StructuredDocument
from .services.matcher import match_cv_to_job, match_parsed_documents, split_priority_keywords
from .services.parser import parse_document
from .services.explain import build_match_explanation
from dataclasses import asdict
from .security import enforce_security, validate_security_settings
from .settings import get_settings
from .observability import (
    CONTENT_TYPE_LATEST,
    record_request,
    render_metrics,
    update_runtime_metrics,
)

settings = get_settings()
logger = logging.getLogger(__name__)
SUPPORTED_SUFFIXES = {".pdf", ".docx", ".txt"}


def _resolve_document_pdf_path(doc_path: str, folder: str) -> Path:
    pdf_path = Path(doc_path).resolve()
    root = Path(settings.watch_cv_dir if folder == "cv" else settings.watch_job_dir).resolve()
    try:
        pdf_path.relative_to(root)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="PDF document not found") from exc

    if pdf_path.suffix.lower() != ".pdf":
        raise HTTPException(status_code=415, detail="Document is not a PDF")

    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail="PDF document not found")

    return pdf_path


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "level": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
            "time": self.formatTime(record, datefmt="%Y-%m-%dT%H:%M:%SZ"),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        for key in ("request_id", "path", "method", "status", "duration_ms"):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        return json.dumps(payload)


def _configure_logging() -> None:
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    handler = logging.StreamHandler()
    if settings.log_json:
        handler.setFormatter(_JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
        )
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)


def _get_redis_client() -> redis.Redis:
    return redis.Redis.from_url(settings.redis_url, decode_responses=True)


def _parse_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _sanitize_filename(name: str) -> str:
    # keep letters, numbers, space, dash and underscore
    safe = "".join(c for c in name if c.isalnum() or c in " _-.")
    safe = safe.strip().replace(" ", " ")
    if not safe:
        safe = "document"
    return safe


def _configure_cors(app: FastAPI) -> None:
    origins = _parse_csv(settings.cors_allow_origins)
    if not origins:
        return

    methods = _parse_csv(settings.cors_allow_methods)
    headers = _parse_csv(settings.cors_allow_headers)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_methods=methods or ["*"],
        allow_headers=headers or ["*"],
    )


def _write_upload_to_temp(upload: UploadFile, target_dir: Path, safe_name: str) -> Path:
    max_bytes = max(0, settings.upload_max_mb) * 1024 * 1024
    temp_path: Path | None = None
    with tempfile.NamedTemporaryFile(
        prefix=f".{safe_name}.",
        dir=target_dir,
        delete=False,
    ) as temp_file:
        total = 0
        while True:
            chunk = upload.file.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if max_bytes and total > max_bytes:
                temp_path = Path(temp_file.name)
                temp_file.flush()
                temp_file.close()
                if temp_path.exists():
                    temp_path.unlink()
                raise HTTPException(status_code=413, detail="File too large")
            temp_file.write(chunk)
        temp_path = Path(temp_file.name)
    return temp_path


def _insert_event(payload: EventCreate) -> EventRead:
    with SessionLocal() as session:
        event = EventLog(
            source=payload.source,
            event_type=payload.event_type,
            path=payload.path,
            fingerprint=payload.fingerprint,
            observed_at=payload.observed_at,
        )
        session.add(event)
        session.commit()
        session.refresh(event)
        return EventRead.model_validate(event)


def _upsert_extraction_result(payload: ExtractedTextCreate) -> ExtractedTextRead:
    with SessionLocal() as session:
        existing = session.scalar(
            select(ExtractedText).where(ExtractedText.file_path == payload.file_path)
        )

        if existing:
            # If content changed OR the extraction method changed (e.g. a
            # forced on-demand Docling re-extraction over the same file
            # bytes), the cached structured profile no longer reflects the
            # actual extracted_text — invalidate it either way.
            if (
                existing.content_hash != payload.content_hash
                or existing.extraction_method != payload.extraction_method
            ):
                existing.parsed_profile = None
                existing.parsed_profile_hash = None
                existing.parsed_profile_updated_at = None

            existing.content_hash = payload.content_hash
            existing.extracted_text = payload.extracted_text
            existing.extraction_method = payload.extraction_method
            existing.extraction_success = payload.extraction_success
            existing.error_message = payload.error_message
            session.commit()
            session.refresh(existing)
            return ExtractedTextRead.model_validate(existing)

        extraction = ExtractedText(
            file_path=payload.file_path,
            content_hash=payload.content_hash,
            extracted_text=payload.extracted_text,
            extraction_method=payload.extraction_method,
            extraction_success=payload.extraction_success,
            error_message=payload.error_message,
            parsed_profile=None,
            parsed_profile_hash=None,
            parsed_profile_updated_at=None,
        )
        session.add(extraction)
        session.commit()
        session.refresh(extraction)
        # Eagerly build+cache the structured profile using the correct kind
        # for this path (was hardcoded to "cv", silently mis-classifying the
        # very first extraction of every job document). Also: this branch
        # used to fall through without returning, so the caller got None on
        # every brand-new file — masked in practice by the worker's retry
        # logic finding the now-persisted row on the next attempt, at the
        # cost of a spurious failure/retry (and, for a forced Docling
        # extraction, running Docling twice) on every first-time extraction.
        kind = _resolve_role(Path(payload.file_path)) or "cv"
        if extraction.extraction_success:
            _get_or_build_profile(session, extraction, kind)
        return ExtractedTextRead.model_validate(extraction)


def _insert_score_result(cv_path: Path, job_path: Path, score: float, common: list[str]) -> ScoreRead:
    with SessionLocal() as session:
        result = ScoreResult(
            cv_path=str(cv_path),
            job_path=str(job_path),
            score=score,
            common_keywords=serialize_keywords(common),
        )
        session.add(result)
        session.commit()
        session.refresh(result)
        return ScoreRead(
            id=result.id,
            cv_path=result.cv_path,
            job_path=result.job_path,
            score=result.score,
            common_keywords=deserialize_keywords(result.common_keywords),
            created_at=result.created_at,
        )


def _document_status(result: ExtractedTextRead) -> tuple[str, str | None]:
    if result.extraction_success:
        return "ready", None
    return "failed", result.error_message or "extraction failed"


def _upsert_cv_document(path: Path, extraction: ExtractedTextRead) -> CvDocumentRead:
    status, last_error = _document_status(extraction)
    with SessionLocal() as session:
        existing = session.scalar(
            select(CvDocument).where(CvDocument.path == str(path))
        )
        if existing:
            content_changed = existing.content_hash != extraction.content_hash
            existing.content_hash = extraction.content_hash
            existing.status = status
            existing.last_error = last_error
            if content_changed and existing.session_id is not None:
                # A genuinely new file was dropped at a path that used to hold
                # an archived document — don't let it stay hidden in that old
                # archive; treat it as a fresh active document.
                existing.session_id = None
            session.commit()
            session.refresh(existing)
            return CvDocumentRead.model_validate(existing)

        doc = CvDocument(
            path=str(path),
            content_hash=extraction.content_hash,
            status=status,
            last_error=last_error,
        )
        session.add(doc)
        session.commit()
        session.refresh(doc)
        return CvDocumentRead.model_validate(doc)


def _upsert_job_document(path: Path, extraction: ExtractedTextRead) -> JobDocumentRead:
    status, last_error = _document_status(extraction)
    with SessionLocal() as session:
        existing = session.scalar(
            select(JobDocument).where(JobDocument.path == str(path))
        )
        if existing:
            content_changed = existing.content_hash != extraction.content_hash
            existing.content_hash = extraction.content_hash
            existing.status = status
            existing.last_error = last_error
            if content_changed and existing.session_id is not None:
                # A genuinely new file was dropped at a path that used to hold
                # an archived document — don't let it stay hidden in that old
                # archive; treat it as a fresh active document.
                existing.session_id = None
            session.commit()
            session.refresh(existing)
            return JobDocumentRead.model_validate(existing)

        doc = JobDocument(
            path=str(path),
            content_hash=extraction.content_hash,
            status=status,
            last_error=last_error,
        )
        session.add(doc)
        session.commit()
        session.refresh(doc)
        return JobDocumentRead.model_validate(doc)


def _upsert_match_result(
    cv_id: int,
    job_id: int,
    score: float,
    common: list[str],
    component_scores: dict | None = None,
) -> MatchRead:
    # Atomic INSERT ... ON CONFLICT DO UPDATE instead of SELECT-then-write:
    # with several worker threads, a CV event and a Job event can both land
    # on the exact same (cv_id, job_id) pair at the same time. The old
    # select-then-insert-or-update pattern raced on the unique
    # (cv_id, job_id) constraint under that overlap.
    cs = component_scores or {}
    common_serialized = serialize_keywords(common)
    insert_values = dict(
        cv_id=cv_id,
        job_id=job_id,
        score=score,
        common_keywords=common_serialized,
        score_semantic=cs.get("semantic"),
        score_skills=cs.get("skills"),
        score_experience=cs.get("experience"),
        score_education=cs.get("education"),
        score_languages=cs.get("languages"),
        score_contract=cs.get("contract"),
        match_domain=cs.get("domain"),
        score_priority_keywords=cs.get("priority_keywords"),
        priority_keywords_matched_count=cs.get("priority_keywords_matched_count"),
        priority_keywords_total=cs.get("priority_keywords_total"),
    )
    # A cheap vector-only rescore (no component breakdown) must not blank out
    # a previously-computed detailed breakdown for this pair.
    update_values = {
        "score": score,
        "common_keywords": common_serialized,
        "updated_at": func.now(),
    }
    if cs:
        update_values.update(
            score_semantic=cs.get("semantic"),
            score_skills=cs.get("skills"),
            score_experience=cs.get("experience"),
            score_education=cs.get("education"),
            score_languages=cs.get("languages"),
            score_contract=cs.get("contract"),
            match_domain=cs.get("domain"),
            score_priority_keywords=cs.get("priority_keywords"),
            priority_keywords_matched_count=cs.get("priority_keywords_matched_count"),
            priority_keywords_total=cs.get("priority_keywords_total"),
        )

    with SessionLocal() as session:
        stmt = (
            pg_insert(MatchResult)
            .values(**insert_values)
            .on_conflict_do_update(
                index_elements=[MatchResult.cv_id, MatchResult.job_id],
                set_=update_values,
            )
            .returning(MatchResult)
        )
        match = session.scalars(stmt).one()
        session.commit()
        return MatchRead(
            id=match.id,
            cv_id=match.cv_id,
            job_id=match.job_id,
            score=match.score,
            common_keywords=deserialize_keywords(match.common_keywords),
            created_at=match.created_at,
            updated_at=match.updated_at,
        )


def _matched_all_active_counterparts(doc_id: int, role: str) -> bool:
    """True if `doc_id` (a CV or a job) already has a MatchResult against
    every currently-active (non-archived) counterpart.

    Used to decide whether re-processing an unchanged, already-"ready"
    document can safely skip the matching loop entirely. A naive version of
    this check (counting ANY match regardless of the counterpart's archive
    status) would count matches against counterparts that are now archived
    -- so a CV reactivated from an archive (same content hash, still
    "ready", but with old matches from before it was archived) looked like
    it "already had matches" and got skipped even when a brand new,
    never-matched job was sitting in the active library. Real production
    case: re-importing an archived CV made it turn "ready" quickly
    (extraction cache hit) but it then never appeared in Correspondances
    against a newly added job, while genuinely new CVs matched normally.
    """
    with SessionLocal() as session:
        if role == "cv":
            active_counterpart_count = session.scalar(
                select(func.count()).select_from(JobDocument).where(JobDocument.session_id.is_(None))
            ) or 0
            if active_counterpart_count == 0:
                return True
            matched_active_count = session.scalar(
                select(func.count(func.distinct(MatchResult.job_id)))
                .select_from(MatchResult)
                .join(JobDocument, MatchResult.job_id == JobDocument.id)
                .where(MatchResult.cv_id == doc_id, JobDocument.session_id.is_(None))
            ) or 0
        else:
            active_counterpart_count = session.scalar(
                select(func.count()).select_from(CvDocument).where(CvDocument.session_id.is_(None))
            ) or 0
            if active_counterpart_count == 0:
                return True
            matched_active_count = session.scalar(
                select(func.count(func.distinct(MatchResult.cv_id)))
                .select_from(MatchResult)
                .join(CvDocument, MatchResult.cv_id == CvDocument.id)
                .where(MatchResult.job_id == doc_id, CvDocument.session_id.is_(None))
            ) or 0
    return matched_active_count >= active_counterpart_count


def _upsert_cv_embedding(
    cv_id: int,
    content_hash: str | None,
    embedding: list[float],
    session: Session | None = None,
) -> None:
    if len(embedding) != settings.embedding_dim:
        logger.warning("embedding dim mismatch for cv %s", cv_id)
        return

    # Atomic INSERT ... ON CONFLICT DO UPDATE: with several worker threads,
    # the same CV can get re-embedded by two overlapping events (e.g. a rapid
    # re-upload) — the old select-then-insert-or-update pattern raced on the
    # unique cv_id constraint in that case. The WHERE clause keeps the
    # "skip if content unchanged" shortcut atomic too.
    def _apply(target_session):
        stmt = (
            pg_insert(CvEmbedding)
            .values(cv_id=cv_id, content_hash=content_hash, embedding=embedding)
            .on_conflict_do_update(
                index_elements=[CvEmbedding.cv_id],
                set_={
                    "content_hash": content_hash,
                    "embedding": embedding,
                    "updated_at": func.now(),
                },
                where=(CvEmbedding.content_hash.is_distinct_from(content_hash)),
            )
        )
        target_session.execute(stmt)
        target_session.commit()

    if session is not None:
        _apply(session)
        return

    with SessionLocal() as local_session:
        _apply(local_session)


def _upsert_job_embedding(
    job_id: int,
    content_hash: str | None,
    embedding: list[float],
    session: Session | None = None,
) -> None:
    if len(embedding) != settings.embedding_dim:
        logger.warning("embedding dim mismatch for job %s", job_id)
        return

    # See _upsert_cv_embedding: atomic upsert to avoid racing on the unique
    # job_id constraint when several worker threads run concurrently.
    def _apply(target_session):
        stmt = (
            pg_insert(JobEmbedding)
            .values(job_id=job_id, content_hash=content_hash, embedding=embedding)
            .on_conflict_do_update(
                index_elements=[JobEmbedding.job_id],
                set_={
                    "content_hash": content_hash,
                    "embedding": embedding,
                    "updated_at": func.now(),
                },
                where=(JobEmbedding.content_hash.is_distinct_from(content_hash)),
            )
        )
        target_session.execute(stmt)
        target_session.commit()

    if session is not None:
        _apply(session)
        return

    with SessionLocal() as local_session:
        _apply(local_session)


def _vector_score(distance: float) -> float:
    similarity = max(0.0, 1.0 - distance)
    return round(similarity * 100, 2)


def _require_auth(request: Request) -> User:
    user = getattr(request.state, "user", None)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


def _require_admin(request: Request) -> User:
    user = getattr(request.state, "user", None)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    if user.role not in {"admin", "superadmin"}:
        raise HTTPException(status_code=403, detail="Admin role required")
    return user


def _require_superadmin(request: Request) -> User:
    user = _require_admin(request)
    if user.role != "superadmin":
        raise HTTPException(status_code=403, detail="Superadmin role required")
    return user


def _hybrid_score(vector_score: float, lexical_score: float) -> float:
    if not settings.hybrid_scoring_enabled:
        return vector_score
    weight_sum = settings.hybrid_vector_weight + settings.hybrid_lexical_weight
    if weight_sum <= 0:
        return vector_score
    combined = (
        vector_score * settings.hybrid_vector_weight
        + lexical_score * settings.hybrid_lexical_weight
    ) / weight_sum
    return round(combined, 2)


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


def _normalize_lines(values: list[str] | None) -> list[str]:
    return [value.strip() for value in (values or []) if value and value.strip()]


def _format_optional_number(value: int | None, suffix: str = "") -> str:
    if value is None:
        return "Non renseigné"
    return f"{value}{suffix}"


def _format_optional_datetime(value) -> str:
    if value is None:
        return "Non renseigné"
    return value.isoformat(sep=" ", timespec="minutes")


def _render_job_offer_text(offer: JobOfferCreate) -> str:
    meta_keywords = _normalize_lines(offer.meta_keywords)
    languages = _normalize_lines(offer.languages) or ["Français"]
    skills = _normalize_lines(offer.skills)
    strong_constraints = _normalize_lines(offer.strong_constraints)

    sections = [
        "OFFRE STRUCTURÉE",
        f"Titre: {offer.title}",
        f"Catégorie: {offer.category}",
        f"Type de contrat: {offer.contract_type}",
        f"Type de poste: {offer.job_type or 'Non renseigné'}",
        f"Langue(s): {', '.join(languages) if languages else 'Français'}",
        f"Méta mots-clés: {', '.join(meta_keywords) if meta_keywords else 'Aucun'}",
        "",
        "Compétences requises",
        "\n".join(f"- {item}" for item in skills) if skills else "Aucune",
        "",
        "Prérequis essentiels",
        "\n".join(f"- {item}" for item in strong_constraints) if strong_constraints else "Aucun",
        "",
        "Description du poste",
        offer.description.strip(),
    ]

    return "\n".join(sections).strip() + "\n"


def _render_job_offer_html(offer: JobOfferCreate, rendered_text: str) -> str:
    def _list_html(values: list[str]) -> str:
        if not values:
            return "<p>Aucune</p>"
        return "<ul>" + "".join(f"<li>{escape(value)}</li>" for value in values) + "</ul>"

    description_html = escape(offer.description).replace("\n", "<br />")

    return f"""<!doctype html>
<html lang="fr">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{escape(offer.title)}</title>
  <style>
    body {{ font-family: Arial, Helvetica, sans-serif; margin: 0; padding: 32px; color: #1b1f1d; background: #f5f7f6; }}
    .card {{ max-width: 900px; margin: 0 auto; background: #fff; border: 1px solid #d9e3df; border-radius: 20px; padding: 28px; box-shadow: 0 24px 70px rgba(22, 34, 28, 0.08); }}
    h1 {{ margin-top: 0; font-size: 30px; }}
    h2 {{ margin-top: 24px; font-size: 18px; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px 18px; }}
    .item strong {{ display: block; font-size: 12px; text-transform: uppercase; letter-spacing: 0.08em; color: #6b746f; margin-bottom: 4px; }}
    .item span {{ font-size: 15px; }}
    ul {{ margin: 8px 0 0 18px; }}
    pre {{ white-space: pre-wrap; background: #f0f4f2; border-radius: 14px; padding: 16px; border: 1px solid #d9e3df; }}
  </style>
</head>
<body>
  <div class="card">
    <h1>{escape(offer.title)}</h1>
    <div class="grid">
      <div class="item"><strong>Catégorie</strong><span>{escape(offer.category)}</span></div>
      <div class="item"><strong>Type de contrat</strong><span>{escape(offer.contract_type)}</span></div>
      <div class="item"><strong>Type de poste</strong><span>{escape(offer.job_type or 'Non renseigné')}</span></div>
    </div>
    <h2>Méta mots-clés</h2>
    {_list_html(_normalize_lines(offer.meta_keywords))}
    <h2>Compétences</h2>
    {_list_html(_normalize_lines(offer.skills))}
        <h2>Prérequis essentiels</h2>
    {_list_html(_normalize_lines(offer.strong_constraints))}
        <h2>Description du poste</h2>
        <p>{description_html}</p>
    <h2>Texte canonique de matching</h2>
    <pre>{escape(rendered_text)}</pre>
  </div>
</body>
</html>"""


def _render_job_offer_focus_text(offer: JobOffer) -> str:
    sections = [
        f"Titre du poste: {offer.title}",
        f"Catégorie: {offer.category}",
        f"Type de contrat: {offer.contract_type}",
        f"Type de poste: {offer.job_type or 'Non renseigné'}",
        f"Méta mots-clés: {', '.join(_normalize_lines(offer.meta_keywords)) or 'Aucun'}",
        f"Compétences requises: {', '.join(_normalize_lines(offer.skills)) or 'Aucune'}",
        f"Contraintes fortes: {', '.join(_normalize_lines(offer.strong_constraints)) or 'Aucune'}",
        f"Description du poste: {offer.description}",
    ]
    return "\n".join(sections).strip()


def _render_list_section(title: str, items: list[str]) -> list[str]:
    if not items:
        return []
    lines = [title]
    lines.extend(f"- {item}" for item in items)
    return lines


def _render_parsed_document_text(profile, kind: str) -> str:
    header = ["DOCUMENT PARSE", f"Type: {kind.upper()}"]

    meta_lines: list[str] = []
    if kind == "job" and getattr(profile, "job_title", None):
        meta_lines.append(f"Titre du poste: {profile.job_title}")
    if profile.person_name:
        meta_lines.append(f"Nom: {profile.person_name}")
    if profile.contract_type:
        meta_lines.append(f"Contrat: {profile.contract_type}")
    if profile.experience_years:
        meta_lines.append(f"Experience: {profile.experience_years} ans")
    if profile.language_terms:
        meta_lines.append(f"Langues detectees: {', '.join(profile.language_terms)}")
    if profile.organization_terms:
        meta_lines.append(f"Organisations: {', '.join(profile.organization_terms)}")
    if profile.location_terms:
        meta_lines.append(f"Lieux: {', '.join(profile.location_terms)}")
    if profile.date_terms:
        meta_lines.append(f"Dates: {', '.join(profile.date_terms)}")

    sections: list[str] = []
    if meta_lines:
        sections.extend(meta_lines)
        sections.append("")

    if profile.summary_text:
        sections.extend(["Resume", profile.summary_text, ""])
    if profile.skills_text:
        sections.extend(["Competences", profile.skills_text, ""])
    if profile.experience_text:
        sections.extend(["Experience", profile.experience_text, ""])
    if profile.education_text:
        sections.extend(["Formation", profile.education_text, ""])
    if profile.certifications_text:
        sections.extend(["Certifications", profile.certifications_text, ""])
    if profile.languages_text:
        sections.extend(["Langues (texte)", profile.languages_text, ""])

    if kind == "job":
        if profile.job_required_text:
            sections.extend(["Competences requises", profile.job_required_text, ""])
        if profile.job_nice_text:
            sections.extend(["Competences souhaitees", profile.job_nice_text, ""])

    sections.extend(_render_list_section("Skills detectees", profile.skill_terms))
    sections.extend(_render_list_section("Soft skills", profile.soft_skill_terms))
    if kind == "job":
        sections.extend(_render_list_section("Skills requis", profile.required_skill_terms))
        sections.extend(_render_list_section("Skills bonus", profile.nice_skill_terms))

    parts = [line for line in (header + [""] + sections) if line is not None]
    return "\n".join(str(part) for part in parts).strip() + "\n"


def _cleanup_temp_file(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        return
    except Exception:
        logger.exception("Failed to cleanup temp file: %s", path)


def _wrap_line_to_width(text: str, font_name: str, font_size: float, max_width: float) -> list[str]:
    from reportlab.pdfbase.pdfmetrics import stringWidth

    if not text:
        return [""]

    lines: list[str] = []
    current = ""
    for word in text.split(" "):
        candidate = word if not current else f"{current} {word}"
        if stringWidth(candidate, font_name, font_size) <= max_width:
            current = candidate
            continue
        if current:
            lines.append(current)
            current = ""
        if stringWidth(word, font_name, font_size) <= max_width:
            current = word
            continue
        chunk = ""
        for char in word:
            if stringWidth(chunk + char, font_name, font_size) <= max_width:
                chunk += char
            else:
                lines.append(chunk)
                chunk = char
        current = chunk
    if current:
        lines.append(current)
    return lines or [""]


def _render_text_pdf_to_temp(title: str, text_value: str) -> Path:
    temp_file = tempfile.NamedTemporaryFile(prefix="parsed-", suffix=".pdf", delete=False)
    temp_file_path = Path(temp_file.name)
    temp_file.close()

    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(str(temp_file_path), pagesize=A4)
    width, height = A4
    margin = 40
    max_width = width - 2 * margin
    y = height - margin
    c.setFont("Helvetica-Bold", 16)
    for wrapped in _wrap_line_to_width(title, "Helvetica-Bold", 16, max_width):
        c.drawString(margin, y, wrapped)
        y -= 20
    y -= 4
    c.setFont("Helvetica", 10)
    for line in text_value.splitlines():
        for wrapped in _wrap_line_to_width(line, "Helvetica", 10, max_width):
            if y < margin + 20:
                c.showPage()
                y = height - margin
                c.setFont("Helvetica", 10)
            c.drawString(margin, y, wrapped)
            y -= 14
    c.save()
    return temp_file_path


def _render_cv_profile_text(profile: CvProfileCreate) -> str:
        experience = _normalize_lines(profile.experience)
        education = _normalize_lines(profile.education)
        certifications = _normalize_lines(profile.certifications)
        skills = _normalize_lines(profile.skills)
        languages = _normalize_lines(profile.languages) or ["Français"]

        sections = [
                "CV STRUCTURÉ",
                f"Nom complet: {profile.full_name}",
                f"Titre professionnel: {profile.headline}",
                f"Statut: {profile.status}",
                "Profil",
                profile.summary.strip(),
                "Compétences",
                "\n".join(f"- {item}" for item in skills) if skills else "Aucune",
                "",
                "Expérience",
                "\n".join(f"- {item}" for item in experience) if experience else "Aucune",
                "",
                "Formation",
                "\n".join(f"- {item}" for item in education) if education else "Aucune",
                "",
                "Certifications",
                "\n".join(f"- {item}" for item in certifications) if certifications else "Aucune",
                "",
                f"Langues: {', '.join(languages) if languages else 'Français'}",
                f"Contrat recherché: {profile.contract_type or 'Non renseigné'}",
                f"Localisation: {profile.location or 'Non renseignée'}",
        ]

        return "\n".join(part for part in sections if part is not None).strip() + "\n"


def _render_cv_profile_html(profile: CvProfileCreate, rendered_text: str) -> str:
        def _list_html(values: list[str]) -> str:
                if not values:
                        return "<p>Aucune</p>"
                return "<ul>" + "".join(f"<li>{escape(value)}</li>" for value in values) + "</ul>"

        summary_html = escape(profile.summary).replace("\n", "<br />")

        return f"""<!doctype html>
<html lang="fr">
<head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{escape(profile.full_name)}</title>
    <style>
        body {{ font-family: Arial, Helvetica, sans-serif; margin: 0; padding: 32px; color: #1b1f1d; background: #f4f7fb; }}
        .card {{ max-width: 900px; margin: 0 auto; background: #fff; border: 1px solid #d9e3df; border-radius: 20px; padding: 28px; box-shadow: 0 24px 70px rgba(22, 34, 28, 0.08); }}
        h1 {{ margin-top: 0; font-size: 30px; }}
        h2 {{ margin-top: 24px; font-size: 18px; }}
        .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px 18px; }}
        .item strong {{ display: block; font-size: 12px; text-transform: uppercase; letter-spacing: 0.08em; color: #6b746f; margin-bottom: 4px; }}
        .item span {{ font-size: 15px; }}
        ul {{ margin: 8px 0 0 18px; }}
        pre {{ white-space: pre-wrap; background: #f0f4f2; border-radius: 14px; padding: 16px; border: 1px solid #d9e3df; }}
    </style>
</head>
<body>
    <div class="card">
        <h1>{escape(profile.full_name)}</h1>
        <div class="grid">
            <div class="item"><strong>Titre</strong><span>{escape(profile.headline)}</span></div>
            <div class="item"><strong>Contrat recherché</strong><span>{escape(profile.contract_type or 'Non renseigné')}</span></div>
            <div class="item"><strong>Localisation</strong><span>{escape(profile.location or 'Non renseignée')}</span></div>
        </div>
        <h2>Résumé</h2>
        <p>{summary_html}</p>
        <h2>Compétences</h2>
        {_list_html(_normalize_lines(profile.skills))}
        <h2>Expérience</h2>
        {_list_html(_normalize_lines(profile.experience))}
        <h2>Formation</h2>
        {_list_html(_normalize_lines(profile.education))}
        <h2>Certifications</h2>
        {_list_html(_normalize_lines(profile.certifications))}
        <h2>Langues</h2>
        {_list_html(_normalize_lines(profile.languages) or ["Français"])}
        <h2>Texte canonique de matching</h2>
        <pre>{escape(rendered_text)}</pre>
    </div>
</body>
</html>"""


def _vector_match_cv(
    cv_doc: CvDocumentRead,
    extraction: ExtractedTextRead,
) -> tuple[set[int], dict[int, float]]:
    """Score this CV against job candidates ranked by embedding similarity.

    Only the top `embedding_top_k` closest jobs get the expensive full match
    (cross-encoder + structured scoring, one CV parse shared across all of
    them). The remaining jobs are returned as {job_id: distance} so the
    caller can give them a cheap vector-only score instead of re-running the
    full pipeline on every single job in the library.
    """
    text_value = (extraction.extracted_text or "").strip()
    if not text_value:
        return set(), {}

    # prefer using cached parsed_profile (which may have NER disabled for form-published docs)
    vector = None
    try:
        with SessionLocal() as session:
            row = session.scalar(select(ExtractedText).where(ExtractedText.file_path == str(cv_doc.path)))
            profile = None
            if row and row.parsed_profile and row.parsed_profile_hash and row.parsed_profile_hash == extraction.content_hash:
                try:
                    profile = StructuredDocument(**row.parsed_profile)
                except Exception:
                    profile = None
            if profile is None:
                profile = build_document_profile(text_value, kind="cv")

            chunks = profile.embedding_chunks or ([profile.cleaned_text] if profile.cleaned_text else [])
            if chunks:
                vectors = embed_texts(chunks)
                # average vectors
                if vectors:
                    if len(vectors) == 1:
                        vector = vectors[0]
                    else:
                        length = len(vectors[0])
                        totals = [0.0] * length
                        count = 0
                        for vec in vectors:
                            if len(vec) != length:
                                continue
                            count += 1
                            for i, v in enumerate(vec):
                                totals[i] += v
                        if count:
                            averaged = [v / max(count, 1) for v in totals]
                            # normalize
                            norm = sum(v * v for v in averaged) ** 0.5
                            if norm > 0:
                                averaged = [v / norm for v in averaged]
                            vector = averaged
    except Exception as exc:
        logger.warning("embedding failed for cv %s: %s", cv_doc.id, exc)
        return set(), {}

    if not vector:
        return set(), {}

    _upsert_cv_embedding(cv_doc.id, extraction.content_hash, vector)

    with SessionLocal() as session:
        distance = JobEmbedding.embedding.cosine_distance(vector).label("distance")
        rows = session.execute(
            select(
                JobEmbedding.job_id,
                JobDocument.path,
                JobDocument.priority_keywords,
                ExtractedText.extracted_text,
                distance,
            )
            .join(JobDocument, JobEmbedding.job_id == JobDocument.id)
            .join(ExtractedText, ExtractedText.file_path == JobDocument.path, isouter=True)
            .where(JobDocument.session_id.is_(None))
            .order_by(distance.asc())
        ).all()

    if not rows:
        return set(), {}

    top_rows = rows[: settings.embedding_top_k]
    rest_rows = rows[settings.embedding_top_k :]

    # The CV side is identical across every job in top_rows — parse it once
    # instead of once per pair.
    cv_parsed = parse_document(text_value, kind="cv")

    matched_job_ids: set[int] = set()
    for row in top_rows:
        job_text = (row.extracted_text or "").strip()
        if job_text:
            job_parsed = parse_document(job_text, kind="job")
            job_parsed.priority_keyword_terms = split_priority_keywords(row.priority_keywords)
            match_result = match_parsed_documents(cv_parsed, job_parsed)
            score = match_result.score
            common = match_result.common_skills
            cs = {
                "semantic": match_result.score_semantic,
                "skills": match_result.score_skills,
                "experience": match_result.score_experience,
                "education": match_result.score_education,
                "languages": match_result.score_languages,
                "contract": match_result.score_contract,
                "domain": match_result.domain,
                "priority_keywords": match_result.score_priority_keywords,
                "priority_keywords_matched_count": len(match_result.priority_keywords_matched),
                "priority_keywords_total": match_result.priority_keywords_total,
            }
        else:
            vector_score = _vector_score(float(row.distance))
            score = vector_score
            common = []
            cs = {}
        _insert_score_result(Path(cv_doc.path), Path(row.path), score, common)
        _upsert_match_result(cv_doc.id, row.job_id, score, common, cs)
        matched_job_ids.add(int(row.job_id))

    remaining_distances = {int(row.job_id): float(row.distance) for row in rest_rows}
    return matched_job_ids, remaining_distances


def _vector_match_job(
    job_doc: JobDocumentRead,
    extraction: ExtractedTextRead,
) -> tuple[set[int], dict[int, float]]:
    """Score this job against CV candidates ranked by embedding similarity.

    Mirrors _vector_match_cv: only the top `embedding_top_k` closest CVs get
    the expensive full match; the rest are returned as {cv_id: distance} for
    a cheap vector-only score.
    """
    text_value = (extraction.extracted_text or "").strip()
    if not text_value:
        return set(), {}

    # prefer using cached parsed_profile (which may have NER disabled for form-published docs)
    vector = None
    try:
        with SessionLocal() as session:
            row = session.scalar(select(ExtractedText).where(ExtractedText.file_path == str(job_doc.path)))
            profile = None
            if row and row.parsed_profile and row.parsed_profile_hash and row.parsed_profile_hash == extraction.content_hash:
                try:
                    profile = StructuredDocument(**row.parsed_profile)
                except Exception:
                    profile = None
            if profile is None:
                profile = build_document_profile(text_value, kind="job")

            chunks = profile.embedding_chunks or ([profile.cleaned_text] if profile.cleaned_text else [])
            if chunks:
                vectors = embed_texts(chunks)
                # average vectors
                if vectors:
                    if len(vectors) == 1:
                        vector = vectors[0]
                    else:
                        length = len(vectors[0])
                        totals = [0.0] * length
                        count = 0
                        for vec in vectors:
                            if len(vec) != length:
                                continue
                            count += 1
                            for i, v in enumerate(vec):
                                totals[i] += v
                        if count:
                            averaged = [v / max(count, 1) for v in totals]
                            # normalize
                            norm = sum(v * v for v in averaged) ** 0.5
                            if norm > 0:
                                averaged = [v / norm for v in averaged]
                            vector = averaged
    except Exception as exc:
        logger.warning("embedding failed for job %s: %s", job_doc.id, exc)
        return set(), {}

    if not vector:
        return set(), {}

    _upsert_job_embedding(job_doc.id, extraction.content_hash, vector)

    structured_offer = None
    with SessionLocal() as session:
        structured_offer = session.scalar(
            select(JobOffer).where(JobOffer.published_document_path == job_doc.path)
        )

    with SessionLocal() as session:
        distance = CvEmbedding.embedding.cosine_distance(vector).label("distance")
        rows = session.execute(
            select(
                CvEmbedding.cv_id,
                CvDocument.path,
                ExtractedText.extracted_text,
                distance,
            )
            .join(CvDocument, CvEmbedding.cv_id == CvDocument.id)
            .join(ExtractedText, ExtractedText.file_path == CvDocument.path, isouter=True)
            .where(CvDocument.session_id.is_(None))
            .order_by(distance.asc())
        ).all()

    if not rows:
        return set(), {}

    top_rows = rows[: settings.embedding_top_k]
    rest_rows = rows[settings.embedding_top_k :]

    # Use structured offer text when available for richer job representation.
    # The job side is identical across every CV in top_rows — parse it once
    # instead of once per pair.
    job_repr = (
        _render_job_offer_focus_text(structured_offer)
        if structured_offer is not None
        else text_value
    )
    job_parsed = parse_document(job_repr, kind="job")
    job_parsed.priority_keyword_terms = split_priority_keywords(job_doc.priority_keywords)

    matched_cv_ids: set[int] = set()
    for row in top_rows:
        cv_text = (row.extracted_text or "").strip()
        if cv_text:
            cv_parsed = parse_document(cv_text, kind="cv")
            match_result = match_parsed_documents(cv_parsed, job_parsed)
            score = match_result.score
            common = match_result.common_skills
            cs = {
                "semantic": match_result.score_semantic,
                "skills": match_result.score_skills,
                "experience": match_result.score_experience,
                "education": match_result.score_education,
                "languages": match_result.score_languages,
                "contract": match_result.score_contract,
                "domain": match_result.domain,
                "priority_keywords": match_result.score_priority_keywords,
                "priority_keywords_matched_count": len(match_result.priority_keywords_matched),
                "priority_keywords_total": match_result.priority_keywords_total,
            }
        else:
            vector_score = _vector_score(float(row.distance))
            score = vector_score
            common = []
            cs = {}
        _insert_score_result(Path(row.path), Path(job_doc.path), score, common)
        _upsert_match_result(row.cv_id, job_doc.id, score, common, cs)
        matched_cv_ids.add(int(row.cv_id))

    remaining_distances = {int(row.cv_id): float(row.distance) for row in rest_rows}
    return matched_cv_ids, remaining_distances


def _is_supported_file(path: Path) -> bool:
    return path.suffix.lower() in SUPPORTED_SUFFIXES


def _resolve_role(path: Path) -> str | None:
    try:
        path.resolve().relative_to(Path(settings.watch_cv_dir).resolve())
        return "cv"
    except ValueError:
        pass

    try:
        path.resolve().relative_to(Path(settings.watch_job_dir).resolve())
        return "job"
    except ValueError:
        return None


def _list_candidate_files(folder: Path) -> list[Path]:
    if not folder.exists():
        return []
    return [
        item
        for item in folder.iterdir()
        if item.is_file() and _is_supported_file(item)
    ]


# Process-local cache of Docling section maps, keyed by content_hash.
# Bounded to avoid unbounded growth in long-running processes. Sections are
# regenerated for free on next ingest if the cache is cold (Docling re-runs).
_DOCLING_SECTIONS_CACHE: dict[str, dict[str, str]] = {}
_DOCLING_SECTIONS_CACHE_MAX = 512


def _stash_docling_sections(content_hash: str, sections: dict[str, str]) -> None:
    if not content_hash or not sections:
        return
    if len(_DOCLING_SECTIONS_CACHE) >= _DOCLING_SECTIONS_CACHE_MAX:
        # FIFO eviction: drop oldest entry
        try:
            _DOCLING_SECTIONS_CACHE.pop(next(iter(_DOCLING_SECTIONS_CACHE)))
        except StopIteration:
            pass
    _DOCLING_SECTIONS_CACHE[content_hash] = sections


def _peek_docling_sections(content_hash: str | None) -> dict[str, str] | None:
    if not content_hash:
        return None
    return _DOCLING_SECTIONS_CACHE.get(content_hash)


def _extract_and_persist(path: Path, force_docling: bool = False, force: bool = False) -> ExtractedTextRead:
    """Extract text for `path`.

    By default (force_docling=False) this always uses the fast plain-text
    path (PyMuPDF, with a page-capped/timed-out OCR fallback for scanned
    PDFs) — this is what automatic ingestion uses for every document,
    regardless of AI_REALTIME_CONVERSION_USE_DOCLING, since Docling's
    layout/table models are CPU-heavy per page and were causing multi-minute
    stalls (and nginx 502s) on ordinary uploads.

    force_docling=True is used only by the explicit, user-triggered
    "structure this document" action (see _structure_document) — a
    deliberate, one-off, on-demand request to pay that cost for a richer,
    section-aware extraction.

    force=True bypasses the content-hash cache below entirely, so an
    unchanged file still gets re-extracted with whatever extraction code
    is currently deployed. Used by POST /matches/recompute: an extraction
    fix (e.g. the PDF column-layout ordering) only changes how a file is
    *read*, never its bytes on disk, so the ordinary content-hash cache
    would otherwise keep serving the stale pre-fix text forever.
    """
    if not path.exists():
        logger.warning("File not found for extraction: %s", path)
        return _upsert_extraction_result(
            ExtractedTextCreate(
                file_path=str(path),
                extraction_success=False,
                error_message="File not found",
            )
        )

    content_hash = file_sha256(path) if path.is_file() else None
    existing = None
    with SessionLocal() as session:
        existing = session.scalar(
            select(ExtractedText).where(ExtractedText.file_path == str(path))
        )
        if not force and existing and existing.content_hash == content_hash and existing.extraction_success:
            already_docling = (existing.extraction_method or "").startswith("pdf-docling") or \
                              (existing.extraction_method or "").startswith("docling")
            # Automatic (force_docling=False) calls always trust the cache
            # once content matches, regardless of which method produced it.
            # A forced structuring request only needs a real Docling pass if
            # the cache isn't already a Docling extraction of this content.
            if not force_docling or already_docling:
                return ExtractedTextRead.model_validate(existing)

    try:
        method = path.suffix.lower().lstrip(".") or "unknown"
        if force_docling:
            from .services.conversion import convert_document
            converted = convert_document(path)
            extracted = converted.full_text
            method = "docling"
            if content_hash and converted.sections:
                _stash_docling_sections(content_hash, converted.sections)
        else:
            extracted = extract_text(path)
        success = bool(extracted and extracted.strip())

        return _upsert_extraction_result(
            ExtractedTextCreate(
                file_path=str(path),
                content_hash=content_hash,
                extracted_text=extracted,
                extraction_method=method,
                extraction_success=success,
                error_message=None if success else "No text extracted",
            )
        )
    except Exception as exc:
        logger.exception("Extraction failed for %s: %s", path, exc)
        return _upsert_extraction_result(
            ExtractedTextCreate(
                file_path=str(path),
                content_hash=content_hash,
                extraction_success=False,
                error_message=str(exc),
            )
        )


from .deps import cleanup_removed_file as _cleanup_removed_file  # noqa: E402


def _get_or_build_profile(session: Session, extraction: ExtractedText, kind: str) -> StructuredDocument:
    """Return a StructuredDocument either from cached JSON on `extraction` or by building it and persisting the cache."""
    # if cached and matches content_hash, reuse
    try:
        if extraction.parsed_profile and extraction.parsed_profile_hash and extraction.parsed_profile_hash == extraction.content_hash:
            data = extraction.parsed_profile
            # reconstruct dataclass
            return StructuredDocument(**data)
    except Exception:
        # fallthrough to rebuild
        pass

    # build and persist
    override_sections = _peek_docling_sections(extraction.content_hash)
    profile = build_document_profile(
        extraction.extracted_text or "",
        kind=kind,
        override_sections=override_sections,
    )
    try:
        extraction.parsed_profile = asdict(profile)
        extraction.parsed_profile_hash = extraction.content_hash
        extraction.parsed_profile_updated_at = datetime.utcnow()
        session.add(extraction)
        session.commit()
    except Exception:
        session.rollback()
    return profile


def _score_against_counterparts(changed_path: Path, role: str, force: bool = False) -> None:
    """force=True bypasses the "content unchanged and already matched"
    skip below, and the embedding-based shortlist shortcut, so every pair
    is rescored through the full score_texts() pipeline regardless of
    whether anything on disk changed. It also forces every document
    involved through a fresh (non-cached) extraction — see the force
    parameter on _extract_and_persist — so an extraction-code change
    (e.g. the PDF column-layout ordering) takes effect too, not just a
    scoring-code one. Used by POST /matches/recompute to let a recruiter
    see the effect of a matcher.py/parser.py/extraction.py/taxonomy.py
    deploy on already-computed scores, without touching any document."""
    changed_result = _extract_and_persist(changed_path, force=force)
    if role == "cv":
        previous_hash = None
        with SessionLocal() as session:
            previous = session.scalar(
                select(CvDocument).where(CvDocument.path == str(changed_path))
            )
            previous_hash = previous.content_hash if previous else None
            previous_status = previous.status if previous else None

        cv_doc = _upsert_cv_document(changed_path, changed_result)
        if not changed_result.extraction_success:
            return

        if (
            not force
            and previous_hash
            and changed_result.content_hash == previous_hash
            and previous_status == "ready"
            and _matched_all_active_counterparts(cv_doc.id, "cv")
        ):
            return

        matched_job_ids: set[int] = set()
        job_distances: dict[int, float] = {}
        if settings.embedding_enabled and not force:
            matched_job_ids, job_distances = _vector_match_cv(cv_doc, changed_result)

        changed_text = changed_result.extracted_text or ""
        for job_path in _list_candidate_files(Path(settings.watch_job_dir)):
            job_result = _extract_and_persist(job_path, force=force)
            job_doc = _upsert_job_document(job_path, job_result)
            if job_doc.session_id is not None:
                # Archived (assigned to a closed analysis session): stays on
                # disk, so the file-listing loop would otherwise keep
                # matching every new CV against it forever — archiving only
                # ever affected the /job-documents listing filter, not this
                # loop, which doesn't touch the DB session_id at all.
                continue
            if job_doc.id in matched_job_ids:
                continue
            if not job_result.extraction_success:
                continue
            if job_doc.id in job_distances:
                # Already ranked by embedding similarity outside the expensive
                # top-K — a cheap vector-only score avoids running the full
                # cross-encoder + structured pipeline on every job in the
                # library for every single upload.
                score = _vector_score(job_distances[job_doc.id])
                common: list[str] = []
                cs: dict = {}
            else:
                match_result = match_cv_to_job(
                    changed_text, job_result.extracted_text or "", job_doc.priority_keywords
                )
                score = match_result.score
                common = match_result.common_skills
                cs = {
                    "semantic": match_result.score_semantic,
                    "skills": match_result.score_skills,
                    "experience": match_result.score_experience,
                    "education": match_result.score_education,
                    "languages": match_result.score_languages,
                    "contract": match_result.score_contract,
                    "domain": match_result.domain,
                    "priority_keywords": match_result.score_priority_keywords,
                    "priority_keywords_matched_count": len(match_result.priority_keywords_matched),
                    "priority_keywords_total": match_result.priority_keywords_total,
                }
            _insert_score_result(changed_path, job_path, score, common)
            _upsert_match_result(cv_doc.id, job_doc.id, score, common, cs)
    else:
        previous_hash = None
        with SessionLocal() as session:
            previous = session.scalar(
                select(JobDocument).where(JobDocument.path == str(changed_path))
            )
            previous_hash = previous.content_hash if previous else None
            previous_status = previous.status if previous else None

        job_doc = _upsert_job_document(changed_path, changed_result)
        if not changed_result.extraction_success:
            return

        # optional: create a JobOffer draft from parsed file if none exists
        if settings.auto_create_job_offer:
            try:
                with SessionLocal() as session2:
                    existing_offer = session2.scalar(
                        select(JobOffer).where(JobOffer.published_document_path == str(changed_path))
                    )
                    if not existing_offer:
                        extraction_row = session2.scalar(
                            select(ExtractedText).where(ExtractedText.file_path == str(changed_path))
                        )
                        if extraction_row:
                            parsed = _get_or_build_profile(session2, extraction_row, "job")
                        else:
                            parsed = build_document_profile(changed_result.extracted_text or "", kind="job")
                        offer_payload = normalize_job_offer_from_parsed(parsed, str(changed_path))
                        # render text/html using helpers
                        from .schemas import JobOfferCreate

                        offer_input = JobOfferCreate(**offer_payload)
                        rendered_text = _render_job_offer_text(offer_input)
                        rendered_html = _render_job_offer_html(offer_input, rendered_text)

                        new_offer = JobOffer(
                            title=offer_input.title,
                            meta_keywords=offer_input.meta_keywords,
                            contract_type=offer_input.contract_type,
                            company=offer_input.company,
                            category=offer_input.category,
                            job_type=offer_input.job_type,
                            salary_max=offer_input.salary_max,
                            languages=offer_input.languages,
                            description=offer_input.description,
                            visual_code=offer_input.visual_code,
                            paragraph=offer_input.paragraph,
                            skills=offer_input.skills,
                            strong_constraints=offer_input.strong_constraints,
                            status=offer_input.status,
                            rendered_text=rendered_text,
                            rendered_html=rendered_html,
                            published_document_path=str(changed_path),
                        )
                        session2.add(new_offer)
                        session2.commit()
            except Exception as exc:  # pragma: no cover
                logger.exception("Failed to auto-create JobOffer from file: %s", exc)

        if (
            not force
            and previous_hash
            and changed_result.content_hash == previous_hash
            and previous_status == "ready"
            and _matched_all_active_counterparts(job_doc.id, "job")
        ):
            return

        matched_cv_ids: set[int] = set()
        cv_distances: dict[int, float] = {}
        if settings.embedding_enabled and not force:
            matched_cv_ids, cv_distances = _vector_match_job(job_doc, changed_result)

        changed_text = changed_result.extracted_text or ""
        for cv_path in _list_candidate_files(Path(settings.watch_cv_dir)):
            cv_result = _extract_and_persist(cv_path, force=force)
            cv_doc = _upsert_cv_document(cv_path, cv_result)
            if cv_doc.session_id is not None:
                # Archived: see the matching guard in the cv branch above.
                continue
            if cv_doc.id in matched_cv_ids:
                continue
            if not cv_result.extraction_success:
                continue
            if cv_doc.id in cv_distances:
                # Already ranked by embedding similarity outside the expensive
                # top-K — a cheap vector-only score avoids running the full
                # cross-encoder + structured pipeline on every CV in the
                # library for every single job upload.
                score = _vector_score(cv_distances[cv_doc.id])
                common: list[str] = []
                cs: dict = {}
            else:
                match_result = match_cv_to_job(
                    cv_result.extracted_text or "", changed_text, job_doc.priority_keywords
                )
                score = match_result.score
                common = match_result.common_skills
                cs = {
                    "semantic": match_result.score_semantic,
                    "skills": match_result.score_skills,
                    "experience": match_result.score_experience,
                    "education": match_result.score_education,
                    "languages": match_result.score_languages,
                    "contract": match_result.score_contract,
                    "domain": match_result.domain,
                    "priority_keywords": match_result.score_priority_keywords,
                    "priority_keywords_matched_count": len(match_result.priority_keywords_matched),
                    "priority_keywords_total": match_result.priority_keywords_total,
                }
            _insert_score_result(cv_path, changed_path, score, common)
            _upsert_match_result(cv_doc.id, job_doc.id, score, common, cs)


def _structure_document(path: Path, role: str) -> None:
    """On-demand deep structuring (Docling) for one already-ingested document.

    Triggered explicitly by the user via POST /{cv,job}-documents/{id}/structure
    — never by automatic ingestion. Forces a Docling re-extraction, then (if
    it succeeds) re-runs matching so scores reflect the richer, section-aware
    text.
    """
    model = CvDocument if role == "cv" else JobDocument
    result = _extract_and_persist(path, force_docling=True)

    with SessionLocal() as session:
        doc = session.scalar(select(model).where(model.path == str(path)))
        if doc is None:
            return
        if result.extraction_success:
            doc.structuring_status = "ready"
            doc.structuring_error = None
        else:
            doc.structuring_status = "failed"
            doc.structuring_error = result.error_message or "structuring failed"
        session.commit()

    if result.extraction_success:
        _score_against_counterparts(path, role)


def _process_watch_event(event: WatchEvent) -> None:
    role = _resolve_role(event.path)
    if role is None:
        return

    if not event.path.exists() or not event.path.is_file():
        _cleanup_removed_file(event.path, role)
        return

    if not _is_supported_file(event.path):
        logger.info("Skipping unsupported file type: %s", event.path)
        return

    if event.event_type == "structure":
        _structure_document(event.path, role)
        return

    if event.event_type == "rescore":
        _score_against_counterparts(event.path, role, force=True)
        return

    _score_against_counterparts(event.path, role)


def _on_watch_event(event: WatchEvent) -> None:
    try:
        fingerprint: str | None = None
        if event.path.exists() and event.path.is_file():
            fingerprint = file_sha256(event.path)

        _insert_event(
            EventCreate(
                source="watcher",
                event_type=event.event_type,
                path=str(event.path),
                fingerprint=fingerprint,
                observed_at=event.observed_at,
            )
        )
    except Exception as exc:  # pragma: no cover
        logger.exception("watcher callback failed: %s", exc)
        return

    try:
        if not enqueue_event(event):
            _process_watch_event(event)
    except Exception as exc:  # pragma: no cover
        logger.exception("watcher enqueue failed: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    validate_security_settings()
    warn_if_unsafe_backend()
    warn_if_esco_missing()
    init_db()
    with SessionLocal() as session:
        ensure_bootstrap_user(session)
    app.state.started_at = time()
    watched_folders = [Path(settings.watch_cv_dir), Path(settings.watch_job_dir)]
    watcher = LocalFolderWatcher(folders=watched_folders, callback=_on_watch_event)
    watcher.start()
    worker = EventWorker(
        handler=_process_watch_event,
        max_retries=settings.worker_max_retries,
        retry_base_delay=settings.worker_retry_base_delay,
        retry_max_delay=settings.worker_retry_max_delay,
        ack_on_failure=settings.queue_ack_on_failure,
        num_workers=settings.worker_concurrency,
    )
    worker.start()
    app.state.watcher = watcher
    app.state.worker = worker

    if settings.conversion_use_docling:
        def _warm_up_docling() -> None:
            try:
                from .services.conversion import _get_converter
                _get_converter()
            except Exception as exc:
                logger.warning("Docling warm-up failed (will retry lazily on first document): %s", exc)

        threading.Thread(target=_warm_up_docling, name="docling-warmup", daemon=True).start()

    # Warm up the other lazily-loaded ML models too. Without this, the FIRST
    # real document processed after a container (re)start pays the full cold
    # -load cost of every model it happens to touch -- NER, both embedders,
    # the cross-encoder, and the ESCO FAISS index (itself a multi-minute
    # build, see esco_taxonomy.py) -- serially, in the request path. Observed
    # in production: a single CV took 150+ seconds this way, well past the
    # frontend's request timeouts. Each warm-up runs in its own daemon
    # thread so they overlap instead of stacking, and a failure here only
    # logs a warning -- the same model loads lazily (and correctly) on first
    # real use, this is purely a latency optimization.
    if settings.ner_enabled and getattr(settings, "ner_backend", "spacy") == "camembert":
        def _warm_up_ner() -> None:
            try:
                from .services.ner_camembert import _get_pipeline
                _get_pipeline()
            except Exception as exc:
                logger.warning("NER warm-up failed (will retry lazily on first document): %s", exc)

        threading.Thread(target=_warm_up_ner, name="ner-warmup", daemon=True).start()

    if settings.embedding_enabled:
        def _warm_up_embedder() -> None:
            try:
                from .services.embeddings import get_embedder
                get_embedder()
            except Exception as exc:
                logger.warning("Embedding model warm-up failed (will retry lazily on first document): %s", exc)

        threading.Thread(target=_warm_up_embedder, name="embedder-warmup", daemon=True).start()

    if settings.skill_embedding_enabled:
        def _warm_up_skill_embedder() -> None:
            try:
                from .services.embeddings import _embed_one
                _embed_one("Python")
            except Exception as exc:
                logger.warning("Skill embedding model warm-up failed (will retry lazily on first document): %s", exc)

        threading.Thread(target=_warm_up_skill_embedder, name="skill-embedder-warmup", daemon=True).start()

    if settings.crossencoder_enabled:
        def _warm_up_cross_encoder() -> None:
            try:
                from .services.matcher import _get_cross_encoder
                _get_cross_encoder()
            except Exception as exc:
                logger.warning("Cross-encoder warm-up failed (will retry lazily on first document): %s", exc)

        threading.Thread(target=_warm_up_cross_encoder, name="crossencoder-warmup", daemon=True).start()

    if settings.esco_enrich_skills:
        def _warm_up_esco() -> None:
            try:
                from .services.esco_taxonomy import get_esco_index
                get_esco_index()
            except Exception as exc:
                logger.warning("ESCO index warm-up failed (will retry lazily on first document): %s", exc)

        threading.Thread(target=_warm_up_esco, name="esco-warmup", daemon=True).start()
    try:
        yield
    finally:
        worker.stop()
        watcher.stop()


_configure_logging()
app = FastAPI(title=settings.app_name, version=settings.app_version, lifespan=lifespan)

from .routers.health import router as _health_router  # noqa: E402
from .routers.auth import router as _auth_router  # noqa: E402
from .routers.sessions import router as _sessions_router  # noqa: E402
from .routers.matches import router as _matches_router  # noqa: E402
from .routers.feedback import router as _feedback_router  # noqa: E402
from .routers.ml import router as _ml_router  # noqa: E402

app.include_router(_health_router)
app.include_router(_auth_router)
app.include_router(_sessions_router)
app.include_router(_matches_router)
app.include_router(_feedback_router)
app.include_router(_ml_router)


@app.middleware("http")
async def security_middleware(request: Request, call_next):
    request_id = request.headers.get("x-request-id", str(uuid4()))
    request.state.request_id = request_id
    start = perf_counter()
    try:
        enforce_security(request)
    except HTTPException as exc:
        response = JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
        response.headers["x-request-id"] = request_id
        return response
    
    # JWT authentication: allow preflight OPTIONS requests through without authorization
    if request.method == "OPTIONS":
        request.state.user = None
    elif settings.auth_enabled:
        try:
            with SessionLocal() as session:
                user = authenticate_request(request, session)
                request.state.user = user
        except HTTPException as exc:
            # If authentication is required but fails, return 401
            # Skip paths that don't require auth (like /health, /auth/login, etc.)
            skip_auth_paths = {"/health", "/ready", "/auth/login", "/auth/register"}
            if request.url.path not in skip_auth_paths and not request.url.path.startswith("/docs") and not request.url.path.startswith("/openapi"):
                response = JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
                response.headers["x-request-id"] = request_id
                return response
            request.state.user = None
    else:
        request.state.user = None
    
    response = await call_next(request)
    response.headers["x-request-id"] = request_id
    duration_ms = (perf_counter() - start) * 1000
    route = request.scope.get("route")
    route_path = route.path if route and hasattr(route, "path") else request.url.path
    record_request(
        request.method,
        route_path,
        response.status_code,
        duration_ms / 1000,
    )
    logger.info(
        "request",
        extra={
            "request_id": request_id,
            "path": request.url.path,
            "method": request.method,
            "status": response.status_code,
            "duration_ms": round(duration_ms, 2),
        },
    )
    return response


# CORS doit être ajouté EN DERNIER pour être la couche la plus externe.
# En Starlette, chaque add_middleware s'insère en tête de pile (position 0),
# donc le dernier ajouté est exécuté en premier pour les requêtes entrantes.
# Ainsi CORS s'exécute avant security_middleware et ajoute ses headers même sur les 401.
_configure_cors(app)



@app.post("/events", response_model=EventRead)
def create_event(payload: EventCreate) -> EventRead:
    return _insert_event(payload)





@app.get("/events", response_model=list[EventRead])
def list_events(limit: int = 50) -> list[EventRead]:
    safe_limit = max(1, min(limit, 200))
    with SessionLocal() as session:
        rows = session.scalars(
            select(EventLog).order_by(EventLog.id.desc()).limit(safe_limit)
        ).all()
        return [EventRead.model_validate(row) for row in rows]


@app.post("/watcher/simulate")
def simulate_watcher_event(payload: WatcherSimulateRequest) -> dict[str, str]:
    if payload.path:
        event_path = Path(payload.path)
        event_type = (payload.event_type or "created").strip() or "created"
        _on_watch_event(
            WatchEvent(
                path=event_path,
                event_type=event_type,
                observed_at=time(),
            )
        )
        return {
            "status": "queued",
            "path": str(event_path),
            "event_type": event_type,
            "timestamp": str(time()),
        }

    folder = Path(settings.watch_cv_dir)
    if payload.folder == "job":
        folder = Path(settings.watch_job_dir)

    folder.mkdir(parents=True, exist_ok=True)
    safe_name = Path(payload.filename or "").name
    if not safe_name:
        raise HTTPException(status_code=400, detail="filename is required when path is not provided")
    target = folder / safe_name
    target.write_text(payload.content, encoding="utf-8")

    return {
        "status": "written",
        "path": str(target),
        "timestamp": str(time()),
    }


@app.post("/admin/reextract")
def admin_reextract(request: Request) -> dict[str, object]:
    """Re-trigger extraction for all files in CV and job dirs.

    Use this after enabling Docling to reprocess documents that were previously
    extracted with PyMuPDF. Only accessible to admins.
    """
    _require_admin(request)
    cv_files = _list_candidate_files(Path(settings.watch_cv_dir))
    job_files = _list_candidate_files(Path(settings.watch_job_dir))
    queued: list[str] = []
    for path in cv_files + job_files:
        try:
            _on_watch_event(WatchEvent(path=path, event_type="created", observed_at=time()))
            queued.append(str(path))
        except Exception as exc:
            logger.warning("reextract: failed to queue %s: %s", path, exc)
    return {"queued": len(queued), "files": queued}


@app.post("/matches/recompute")
def recompute_matches(request: Request) -> dict[str, object]:
    """Force a full re-extraction and rescoring of every active CV against
    every active job with whatever matching/extraction code is currently
    deployed, bypassing both the extraction content-hash cache and the
    "content unchanged and already matched" scoring optimization that
    normally skip a document with nothing new to process.

    Re-extraction reruns PyMuPDF (and its OCR fallback) on every active
    file even though its bytes haven't changed -- necessary because an
    extraction-code fix (e.g. the PDF column-layout ordering) changes how
    a file is *read*, not the file itself, so the ordinary hash-based
    cache would otherwise keep serving pre-fix text forever. Rescoring
    then updates each pair's existing MatchResult row in place (same
    cv_id/job_id upsert as automatic ingestion), so any feedback already
    left on a match stays attached to it.

    Use this right after deploying a change to matcher.py, parser.py,
    extraction.py, or taxonomy.py to see its effect on already-computed
    scores without touching or reuploading any document. Only accessible
    to admins: this reruns extraction and the cross-encoder on every
    active document, which is not something to trigger by accident.
    """
    _require_admin(request)
    with SessionLocal() as session:
        active_cv_paths = session.scalars(
            select(CvDocument.path).where(CvDocument.session_id.is_(None))
        ).all()

    queued: list[str] = []
    for raw_path in active_cv_paths:
        path = Path(raw_path)
        try:
            _on_watch_event(WatchEvent(path=path, event_type="rescore", observed_at=time()))
            queued.append(str(path))
        except Exception as exc:
            logger.warning("recompute: failed to queue %s: %s", path, exc)
    return {"queued": len(queued), "files": queued}


def _ensure_pending_document_and_unarchive(
    model: type, path: Path, priority_keywords: str | None = None
) -> None:
    """Create a pending document record for a freshly uploaded file, or, if
    one already exists at this path, unarchive it unconditionally.

    Re-uploading a file through /ingest unarchives it even when its content
    is byte-identical to what's already on disk: an explicit upload IS the
    user's signal of intent to make the document active again. This is
    deliberately more permissive than the passive file-watcher path
    (_upsert_cv_document/_upsert_job_document in _score_against_counterparts),
    which only clears session_id when content_hash actually changed -- right
    for a watcher restart silently rediscovering an unchanged, intentionally
    archived file, but wrong here: without this, re-uploading a CV that
    happens to already sit in an archive (same filename, same bytes) stayed
    archived and invisible, with no error shown to the user.

    priority_keywords (job offers only) is applied here, before the ingest
    watch event below queues extraction + first scoring pass, so that very
    first pass already sees them -- _score_against_counterparts reads
    JobDocument.priority_keywords fresh from the row at scoring time.
    Without this, the recruiter would need a separate PATCH afterward,
    forcing a second full rescore for a value they already had in hand.
    """
    with SessionLocal() as session:
        existing = session.scalar(select(model).where(model.path == str(path)))
        if existing is None:
            new_doc = model(path=str(path), status="pending")
            if priority_keywords is not None:
                new_doc.priority_keywords = priority_keywords
            session.add(new_doc)
            session.commit()
        else:
            changed = False
            if existing.session_id is not None:
                existing.session_id = None
                changed = True
            if priority_keywords is not None:
                existing.priority_keywords = priority_keywords
                changed = True
            if changed:
                session.commit()


@app.post("/ingest")
def ingest_file(
    folder: str = Form(...),
    upload: UploadFile = File(...),
    filename: str | None = Form(None),
    priority_keywords: str | None = Form(None),
) -> dict[str, str]:
    if folder not in {"cv", "job"}:
        raise HTTPException(status_code=400, detail="Invalid folder")
    if priority_keywords is not None and folder != "job":
        raise HTTPException(status_code=400, detail="priority_keywords is only valid for job offers")

    target_dir = Path(settings.watch_cv_dir if folder == "cv" else settings.watch_job_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    raw_name = filename or upload.filename or ""
    safe_name = Path(raw_name).name
    if not safe_name:
        raise HTTPException(status_code=400, detail="Missing filename")

    suffix = Path(safe_name).suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise HTTPException(status_code=400, detail="Unsupported file type")

    target_path = target_dir / safe_name
    temp_path: Path | None = None
    try:
        temp_path = _write_upload_to_temp(upload, target_dir, safe_name)
    finally:
        try:
            upload.file.close()
        except Exception:
            pass

    if temp_path is None:
        raise HTTPException(status_code=500, detail="Upload failed")

    try:
        temp_path.replace(target_path)
    except Exception:
        if temp_path.exists():
            temp_path.unlink()
        raise

    _ensure_pending_document_and_unarchive(
        CvDocument if folder == "cv" else JobDocument,
        target_path,
        priority_keywords=(priority_keywords or "").strip() or None,
    )

    _on_watch_event(
        WatchEvent(
            path=target_path,
            event_type="ingest",
            observed_at=time(),
        )
    )
    return {
        "status": "stored",
        "path": str(target_path),
    }


@app.post("/job-offers", response_model=JobOfferRead)
def create_job_offer(payload: JobOfferCreate, request: Request) -> JobOfferRead:
    _require_admin(request)

    normalized_status = payload.status if payload.status in {"draft", "published"} else "published"
    normalized_languages = ["Français"]
    normalized_meta_keywords = _normalize_lines(payload.meta_keywords)
    normalized_skills = _normalize_lines(payload.skills)
    normalized_constraints = _normalize_lines(payload.strong_constraints)

    offer_input = JobOfferCreate(
        title=payload.title.strip(),
        meta_keywords=normalized_meta_keywords,
        contract_type=payload.contract_type.strip(),
        company=payload.company.strip() if payload.company else "Non renseigné",
        category=payload.category.strip(),
        job_type=payload.job_type.strip() if payload.job_type else None,
        salary_max=payload.salary_max,
        languages=normalized_languages,
        description=payload.description.strip(),
        visual_code=payload.visual_code.strip() if payload.visual_code else None,
        paragraph=payload.paragraph.strip() if payload.paragraph else None,
        skills=normalized_skills,
        strong_constraints=normalized_constraints,
        status=normalized_status,
    )

    rendered_text = _render_job_offer_text(offer_input)
    rendered_html = _render_job_offer_html(offer_input, rendered_text)

    with SessionLocal() as session:
        offer = JobOffer(
            title=offer_input.title,
            meta_keywords=offer_input.meta_keywords,
            contract_type=offer_input.contract_type,
            company=offer_input.company,
            category=offer_input.category,
            job_type=offer_input.job_type,
            salary_max=offer_input.salary_max,
            languages=offer_input.languages,
            description=offer_input.description,
            visual_code=offer_input.visual_code,
            paragraph=offer_input.paragraph,
            skills=offer_input.skills,
            strong_constraints=offer_input.strong_constraints,
            status=offer_input.status,
            rendered_text=rendered_text,
            rendered_html=rendered_html,
            published_document_path=None,
        )
        session.add(offer)
        session.commit()
        session.refresh(offer)

        snapshot_path = None
        if offer.status == "published":
            job_root = Path(settings.watch_job_dir)
            job_root.mkdir(parents=True, exist_ok=True)
            snapshot_path = job_root / f"offre-structuree-{offer.id}.txt"

            # try to render a simple PDF representation of the offer
            title_safe = _sanitize_filename(offer.title or f"offre-{offer.id}")
            pdf_path = job_root / f"{title_safe}.pdf"
            # avoid overwriting existing file for same title
            if pdf_path.exists():
                pdf_path = job_root / f"{title_safe}-{offer.id}.pdf"

            try:
                # import lazily to avoid hard dependency unless available
                from reportlab.lib.pagesizes import A4
                from reportlab.pdfgen import canvas

                from reportlab.lib.utils import simpleSplit

                c = canvas.Canvas(str(pdf_path), pagesize=A4)
                width, height = A4
                margin = 40
                max_width = width - 2 * margin
                y = height - margin
                c.setFont("Helvetica-Bold", 16)
                c.drawString(margin, y, offer.title or "Offre")
                y -= 24
                c.setFont("Helvetica", 10)
                for raw_line in rendered_text.splitlines():
                    wrapped = simpleSplit(raw_line or " ", "Helvetica", 10, max_width)
                    for segment in wrapped:
                        if y < margin + 20:
                            c.showPage()
                            y = height - margin
                            c.setFont("Helvetica", 10)
                        c.drawString(margin, y, segment)
                        y -= 14
                c.save()
                offer.published_document_path = str(pdf_path)
            except Exception as exc:  # pragma: no cover - optional PDF dependency
                logger.info("PDF generation skipped or failed: %s", exc)
                # fallback: write the plain text snapshot and publish it
                try:
                    snapshot_path.write_text(rendered_text, encoding="utf-8")
                except Exception:
                    logger.exception("Failed to write snapshot text for job offer %s", offer.id)
                offer.published_document_path = str(snapshot_path)

            # ensure a JobDocument row exists for the published file so it appears in the job library
            try:
                doc_path = Path(offer.published_document_path)
                if doc_path.exists():
                    # precompute and store extracted_text + parsed_profile with NER disabled
                    try:
                        extracted_value = extract_text(doc_path)
                        content_hash_val = None
                        try:
                            content_hash_val = file_sha256(doc_path)
                        except Exception:
                            content_hash_val = None
                        profile = build_document_profile(extracted_value or "", kind="job", enable_ner=False)
                        with SessionLocal() as session2:
                            existing_extraction = session2.scalar(
                                select(ExtractedText).where(ExtractedText.file_path == str(doc_path))
                            )
                            if existing_extraction:
                                existing_extraction.content_hash = content_hash_val
                                existing_extraction.extracted_text = extracted_value
                                existing_extraction.extraction_method = doc_path.suffix.lower().lstrip(".") or "unknown"
                                existing_extraction.extraction_success = bool(extracted_value and extracted_value.strip())
                                existing_extraction.error_message = None if existing_extraction.extraction_success else "No text extracted"
                                existing_extraction.parsed_profile = asdict(profile)
                                existing_extraction.parsed_profile_hash = content_hash_val
                                existing_extraction.parsed_profile_updated_at = datetime.utcnow()
                                session2.commit()
                            else:
                                extraction = ExtractedText(
                                    file_path=str(doc_path),
                                    content_hash=content_hash_val,
                                    extracted_text=extracted_value,
                                    extraction_method=doc_path.suffix.lower().lstrip(".") or "unknown",
                                    extraction_success=bool(extracted_value and extracted_value.strip()),
                                    error_message=None if (extracted_value and extracted_value.strip()) else "No text extracted",
                                    parsed_profile=asdict(profile),
                                    parsed_profile_hash=content_hash_val,
                                    parsed_profile_updated_at=datetime.utcnow(),
                                )
                                session2.add(extraction)
                                session2.commit()
                    except Exception as exc:  # pragma: no cover
                        logger.exception("Failed to precompute parsed profile for published offer: %s", exc)

                    with SessionLocal() as session2:
                        existing = session2.scalar(select(JobDocument).where(JobDocument.path == str(doc_path)))
                        if not existing:
                            content_hash = None
                            try:
                                content_hash = file_sha256(doc_path)
                            except Exception:
                                content_hash = None
                            job_doc = JobDocument(
                                path=str(doc_path),
                                content_hash=content_hash,
                                status="ready",
                            )
                            session2.add(job_doc)
                            session2.commit()
                            session2.refresh(job_doc)

                    # trigger watcher processing for scoring and matches
                    try:
                        _on_watch_event(WatchEvent(path=doc_path, event_type="created", observed_at=time()))
                    except Exception as exc:
                        logger.warning("Failed to enqueue created watch event for published offer: %s", exc)
            except Exception as exc:  # pragma: no cover
                logger.exception("Failed to register JobDocument for published offer: %s", exc)
            session.add(offer)
            session.commit()
            session.refresh(offer)

    return JobOfferRead.model_validate(offer)


@app.post("/cv-profiles", response_model=CvProfileRead)
def create_cv_profile(payload: CvProfileCreate, request: Request) -> CvProfileRead:
    _require_admin(request)

    normalized_status = payload.status if payload.status in {"draft", "published"} else "published"
    normalized_experience = _normalize_lines(payload.experience)
    normalized_education = _normalize_lines(payload.education)
    normalized_certifications = _normalize_lines(payload.certifications)
    normalized_skills = _normalize_lines(payload.skills)
    normalized_languages = _normalize_lines(payload.languages) or ["Français"]

    cv_input = CvProfileCreate(
        full_name=payload.full_name.strip(),
        headline=payload.headline.strip(),
        summary=payload.summary.strip(),
        experience=normalized_experience,
        education=normalized_education,
        certifications=normalized_certifications,
        skills=normalized_skills,
        languages=normalized_languages,
        contract_type=payload.contract_type.strip() if payload.contract_type else None,
        location=payload.location.strip() if payload.location else None,
        status=normalized_status,
    )

    rendered_text = _render_cv_profile_text(cv_input)
    rendered_html = _render_cv_profile_html(cv_input, rendered_text)

    published_document_path = None
    if cv_input.status == "published":
        cv_root = Path(settings.watch_cv_dir)
        cv_root.mkdir(parents=True, exist_ok=True)
        title_safe = _sanitize_filename(cv_input.full_name or cv_input.headline or "cv")
        snapshot_path = cv_root / f"cv-structure-{title_safe}.txt"

        pdf_path = cv_root / f"cv-{title_safe}.pdf"
        if pdf_path.exists():
            pdf_path = cv_root / f"cv-{title_safe}-{int(time())}.pdf"

        try:
            from reportlab.lib.pagesizes import A4
            from reportlab.pdfgen import canvas

            c = canvas.Canvas(str(pdf_path), pagesize=A4)
            width, height = A4
            margin = 40
            y = height - margin
            c.setFont("Helvetica-Bold", 16)
            c.drawString(margin, y, cv_input.full_name or "CV")
            y -= 24
            c.setFont("Helvetica", 10)
            for line in rendered_text.splitlines():
                if y < margin + 20:
                    c.showPage()
                    y = height - margin
                    c.setFont("Helvetica", 10)
                c.drawString(margin, y, line[:200])
                y -= 14
            c.save()
            published_document_path = str(pdf_path)
        except Exception as exc:  # pragma: no cover - optional PDF dependency
            logger.info("CV PDF generation skipped or failed: %s", exc)
            # fallback: write the plain text snapshot and publish it
            try:
                snapshot_path.write_text(rendered_text, encoding="utf-8")
            except Exception:
                logger.exception("Failed to write snapshot text for CV %s", cv_input.full_name)
            published_document_path = str(snapshot_path)

        try:
            doc_path = Path(published_document_path)
            if doc_path.exists():
                # precompute and store extracted_text + parsed_profile with NER disabled
                try:
                    extracted_value = extract_text(doc_path)
                    content_hash_val = None
                    try:
                        content_hash_val = file_sha256(doc_path)
                    except Exception:
                        content_hash_val = None
                    profile = build_document_profile(extracted_value or "", kind="cv", enable_ner=False)
                    with SessionLocal() as session:
                        existing_extraction = session.scalar(
                            select(ExtractedText).where(ExtractedText.file_path == str(doc_path))
                        )
                        if existing_extraction:
                            existing_extraction.content_hash = content_hash_val
                            existing_extraction.extracted_text = extracted_value
                            existing_extraction.extraction_method = doc_path.suffix.lower().lstrip(".") or "unknown"
                            existing_extraction.extraction_success = bool(extracted_value and extracted_value.strip())
                            existing_extraction.error_message = None if existing_extraction.extraction_success else "No text extracted"
                            existing_extraction.parsed_profile = asdict(profile)
                            existing_extraction.parsed_profile_hash = content_hash_val
                            existing_extraction.parsed_profile_updated_at = datetime.utcnow()
                            session.commit()
                        else:
                            extraction = ExtractedText(
                                file_path=str(doc_path),
                                content_hash=content_hash_val,
                                extracted_text=extracted_value,
                                extraction_method=doc_path.suffix.lower().lstrip(".") or "unknown",
                                extraction_success=bool(extracted_value and extracted_value.strip()),
                                error_message=None if (extracted_value and extracted_value.strip()) else "No text extracted",
                                parsed_profile=asdict(profile),
                                parsed_profile_hash=content_hash_val,
                                parsed_profile_updated_at=datetime.utcnow(),
                            )
                            session.add(extraction)
                            session.commit()
                except Exception as exc:  # pragma: no cover
                    logger.exception("Failed to precompute parsed profile for published CV: %s", exc)

                with SessionLocal() as session:
                    existing = session.scalar(select(CvDocument).where(CvDocument.path == str(doc_path)))
                    if not existing:
                        content_hash = None
                        try:
                            content_hash = file_sha256(doc_path)
                        except Exception:
                            content_hash = None
                        cv_doc = CvDocument(
                            path=str(doc_path),
                            content_hash=content_hash,
                            status="ready",
                        )
                        session.add(cv_doc)
                        session.commit()
                        session.refresh(cv_doc)

                try:
                    _on_watch_event(WatchEvent(path=doc_path, event_type="created", observed_at=time()))
                except Exception as exc:
                    logger.warning("Failed to enqueue created watch event for published CV: %s", exc)
        except Exception as exc:  # pragma: no cover
            logger.exception("Failed to register CvDocument for published CV: %s", exc)

    return CvProfileRead(
        full_name=cv_input.full_name,
        headline=cv_input.headline,
        summary=cv_input.summary,
        experience=cv_input.experience,
        education=cv_input.education,
        certifications=cv_input.certifications,
        skills=cv_input.skills,
        languages=cv_input.languages,
        contract_type=cv_input.contract_type,
        location=cv_input.location,
        status=cv_input.status,
        rendered_text=rendered_text,
        rendered_html=rendered_html,
        published_document_path=published_document_path,
    )


@app.post("/ingest/delete")
def ingest_delete(payload: IngestDeleteRequest) -> dict[str, str]:
    folder = payload.folder
    target_dir = Path(settings.watch_cv_dir if folder == "cv" else settings.watch_job_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    safe_name = Path(payload.filename).name
    if not safe_name:
        raise HTTPException(status_code=400, detail="Missing filename")

    suffix = Path(safe_name).suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise HTTPException(status_code=400, detail="Unsupported file type")

    target_path = target_dir / safe_name
    status = "missing"
    if target_path.exists():
        target_path.unlink()
        status = "deleted"

    # Clean up DB synchronously so the frontend sees the change immediately,
    # without waiting for the async Redis worker to process the event.
    _cleanup_removed_file(target_path, folder)

    delete_event = WatchEvent(
        path=target_path,
        event_type="deleted",
        observed_at=time(),
    )
    try:
        _on_watch_event(delete_event)
    except Exception as exc:  # pragma: no cover
        logger.warning("ingest delete enqueue failed: %s", exc)

    return {
        "status": status,
        "path": str(target_path),
    }


@app.post("/ingest/delete-batch")
def ingest_delete_batch(payload: IngestDeleteBatchRequest) -> dict[str, list[dict[str, str]]]:
    folder = payload.folder
    target_dir = Path(settings.watch_cv_dir if folder == "cv" else settings.watch_job_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    results: list[dict[str, str]] = []
    for raw_name in payload.filenames:
        safe_name = Path(raw_name).name
        if not safe_name:
            results.append({"filename": raw_name, "status": "invalid"})
            continue

        suffix = Path(safe_name).suffix.lower()
        if suffix not in SUPPORTED_SUFFIXES:
            results.append({"filename": safe_name, "status": "unsupported"})
            continue

        target_path = target_dir / safe_name
        status = "missing"
        if target_path.exists():
            target_path.unlink()
            status = "deleted"

        _cleanup_removed_file(target_path, folder)

        delete_event = WatchEvent(
            path=target_path,
            event_type="deleted",
            observed_at=time(),
        )
        try:
            _on_watch_event(delete_event)
        except Exception as exc:  # pragma: no cover
            logger.warning("ingest delete enqueue failed: %s", exc)

        results.append({"filename": safe_name, "status": status})

    return {"status": "ok", "results": results}




@app.get("/extractions", response_model=list[ExtractedTextRead])
def list_extractions(limit: int = 50) -> list[ExtractedTextRead]:
    safe_limit = max(1, min(limit, 200))
    with SessionLocal() as session:
        rows = session.scalars(
            select(ExtractedText).order_by(ExtractedText.id.desc()).limit(safe_limit)
        ).all()
        return [ExtractedTextRead.model_validate(row) for row in rows]



@app.post("/score", response_model=ScoreRead)
def score_match(payload: ScoreRequest) -> ScoreRead:
    cv_path = Path(payload.cv_path)
    job_path = Path(payload.job_path)

    if not cv_path.exists():
        raise HTTPException(status_code=404, detail="CV file not found")
    if not job_path.exists():
        raise HTTPException(status_code=404, detail="JOB file not found")

    cv_text = extract_text(cv_path)
    job_text = extract_text(job_path)
    score, common = score_texts(cv_text, job_text)
    return _insert_score_result(cv_path, job_path, score, common)


@app.get("/scores", response_model=list[ScoreRead])
def list_scores(limit: int = 50) -> list[ScoreRead]:
    safe_limit = max(1, min(limit, 200))
    with SessionLocal() as session:
        rows = session.scalars(
            select(ScoreResult).order_by(ScoreResult.id.desc()).limit(safe_limit)
        ).all()
        return [
            ScoreRead(
                id=row.id,
                cv_path=row.cv_path,
                job_path=row.job_path,
                score=row.score,
                common_keywords=deserialize_keywords(row.common_keywords),
                created_at=row.created_at,
            )
            for row in rows
        ]


@app.get("/cv-documents", response_model=list[CvDocumentRead])
def list_cv_documents(
    page: int = 1,
    page_size: int = 25,
    status: str | None = None,
    query: str | None = None,
    session_id: int | None = None,
) -> list[CvDocumentRead]:
    safe_size = max(1, min(page_size, 100))
    safe_offset = max(0, (page - 1) * safe_size)
    stmt = select(CvDocument)
    if session_id is None:
        stmt = stmt.where(CvDocument.session_id.is_(None))
    else:
        stmt = stmt.where(CvDocument.session_id == session_id)
    if status:
        stmt = stmt.where(CvDocument.status == status)
    if query:
        search_expr = f"%{query}%"
        stmt = stmt.join(
            ExtractedText,
            ExtractedText.file_path == CvDocument.path,
            isouter=True,
        ).where(
            or_(
                CvDocument.path.ilike(search_expr),
                ExtractedText.extracted_text.ilike(search_expr),
            )
        )
    stmt = stmt.order_by(CvDocument.id.desc()).offset(safe_offset).limit(safe_size)
    with SessionLocal() as session:
        rows = session.scalars(stmt).all()
        return [CvDocumentRead.model_validate(row) for row in rows]


@app.get("/cv-documents/{doc_id}", response_model=CvDocumentRead)
def get_cv_document(doc_id: int) -> CvDocumentRead:
    with SessionLocal() as session:
        doc = session.get(CvDocument, doc_id)
        if not doc:
            raise HTTPException(status_code=404, detail="CV document not found")
        return CvDocumentRead.model_validate(doc)


@app.get("/cv-documents/{doc_id}/details", response_model=CvDocumentDetailRead)
def get_cv_document_details(doc_id: int, limit: int = 6) -> CvDocumentDetailRead:
    safe_limit = max(1, min(limit, 50))
    with SessionLocal() as session:
        doc = session.get(CvDocument, doc_id)
        if not doc:
            raise HTTPException(status_code=404, detail="CV document not found")

        extraction = session.scalar(
            select(ExtractedText).where(ExtractedText.file_path == doc.path)
        )
        match_rows = session.scalars(
            select(MatchResult)
            .where(MatchResult.cv_id == doc_id)
            .order_by(MatchResult.score.desc())
            .limit(safe_limit)
        ).all()

        match_count = session.scalar(
            select(func.count()).select_from(MatchResult).where(MatchResult.cv_id == doc_id)
        ) or 0
        average_score = session.scalar(
            select(func.avg(MatchResult.score)).where(MatchResult.cv_id == doc_id)
        )

        keyword_counts: dict[str, int] = {}
        for row in match_rows:
            for keyword in deserialize_keywords(row.common_keywords):
                keyword_counts[keyword] = keyword_counts.get(keyword, 0) + 1

        top_keywords = [
            keyword
            for keyword, _ in sorted(
                keyword_counts.items(),
                key=lambda item: (-item[1], item[0]),
            )[:12]
        ]

        return CvDocumentDetailRead(
            id=doc.id,
            path=doc.path,
            content_hash=doc.content_hash,
            status=doc.status,
            last_error=doc.last_error,
            structuring_status=doc.structuring_status,
            structuring_error=doc.structuring_error,
            created_at=doc.created_at,
            updated_at=doc.updated_at,
            match_count=match_count,
            average_score=round(float(average_score), 2) if average_score is not None else None,
            top_keywords=top_keywords,
            extraction=ExtractedTextRead.model_validate(extraction) if extraction else None,
            top_matches=[
                MatchRead(
                    id=row.id,
                    cv_id=row.cv_id,
                    job_id=row.job_id,
                    score=row.score,
                    common_keywords=deserialize_keywords(row.common_keywords),
                    created_at=row.created_at,
                    updated_at=row.updated_at,
                )
                for row in match_rows
            ],
            
        )


@app.get("/cv-documents/{doc_id}/pdf")
def get_cv_document_pdf(doc_id: int) -> FileResponse:
    with SessionLocal() as session:
        doc = session.get(CvDocument, doc_id)
        if not doc:
            raise HTTPException(status_code=404, detail="CV document not found")

    pdf_path = _resolve_document_pdf_path(doc.path, "cv")
    return FileResponse(pdf_path, media_type="application/pdf", filename=pdf_path.name)


@app.get("/cv-documents/{doc_id}/parsed-text")
def get_cv_document_parsed_text(doc_id: int) -> Response:
    with SessionLocal() as session:
        doc = session.get(CvDocument, doc_id)
        if not doc:
            raise HTTPException(status_code=404, detail="CV document not found")
        extraction = session.scalar(
            select(ExtractedText).where(ExtractedText.file_path == doc.path)
        )

    if not extraction or not extraction.extracted_text:
        raise HTTPException(status_code=404, detail="Extraction not found")

    profile = _get_or_build_profile(session, extraction, "cv")
    rendered = _render_parsed_document_text(profile, "cv")
    return Response(content=rendered, media_type="text/plain")


@app.get("/cv-documents/{doc_id}/parsed-pdf")
def get_cv_document_parsed_pdf(doc_id: int, background_tasks: BackgroundTasks) -> FileResponse:
    with SessionLocal() as session:
        doc = session.get(CvDocument, doc_id)
        if not doc:
            raise HTTPException(status_code=404, detail="CV document not found")
        extraction = session.scalar(
            select(ExtractedText).where(ExtractedText.file_path == doc.path)
        )

    if not extraction or not extraction.extracted_text:
        raise HTTPException(status_code=404, detail="Extraction not found")

    profile = _get_or_build_profile(session, extraction, "cv")
    rendered = _render_parsed_document_text(profile, "cv")
    pdf_path = _render_text_pdf_to_temp(f"CV parse #{doc_id}", rendered)
    background_tasks.add_task(_cleanup_temp_file, pdf_path)
    return FileResponse(pdf_path, media_type="application/pdf", filename=f"cv-parsed-{doc_id}.pdf")


@app.get("/cv-documents/{doc_id}/parsed-json")
def get_cv_document_parsed_json(doc_id: int) -> JSONResponse:
    with SessionLocal() as session:
        doc = session.get(CvDocument, doc_id)
        if not doc:
            raise HTTPException(status_code=404, detail="CV document not found")
        extraction = session.scalar(
            select(ExtractedText).where(ExtractedText.file_path == doc.path)
        )

    if not extraction or not extraction.extracted_text:
        raise HTTPException(status_code=404, detail="Extraction not found")

    profile = _get_or_build_profile(session, extraction, "cv")
    return JSONResponse(content=asdict(profile))


@app.post("/cv-documents/{doc_id}/structure")
def structure_cv_document(doc_id: int) -> dict:
    if not settings.conversion_use_docling:
        raise HTTPException(status_code=400, detail="Structuring is disabled on this deployment")

    with SessionLocal() as session:
        doc = session.get(CvDocument, doc_id)
        if not doc:
            raise HTTPException(status_code=404, detail="CV document not found")
        doc.structuring_status = "pending"
        doc.structuring_error = None
        session.commit()
        doc_path = Path(doc.path)

    _on_watch_event(WatchEvent(path=doc_path, event_type="structure", observed_at=time()))
    return {"status": "queued"}


@app.get("/job-documents", response_model=list[JobDocumentRead])
def list_job_documents(
    page: int = 1,
    page_size: int = 25,
    status: str | None = None,
    query: str | None = None,
    session_id: int | None = None,
) -> list[JobDocumentRead]:
    safe_size = max(1, min(page_size, 100))
    safe_offset = max(0, (page - 1) * safe_size)
    stmt = select(JobDocument)
    if session_id is None:
        stmt = stmt.where(JobDocument.session_id.is_(None))
    else:
        stmt = stmt.where(JobDocument.session_id == session_id)
    if status:
        stmt = stmt.where(JobDocument.status == status)
    if query:
        search_expr = f"%{query}%"
        stmt = stmt.join(
            ExtractedText,
            ExtractedText.file_path == JobDocument.path,
            isouter=True,
        ).where(
            or_(
                JobDocument.path.ilike(search_expr),
                ExtractedText.extracted_text.ilike(search_expr),
            )
        )
    stmt = stmt.order_by(JobDocument.id.desc()).offset(safe_offset).limit(safe_size)
    with SessionLocal() as session:
        rows = session.scalars(stmt).all()
        return [JobDocumentRead.model_validate(row) for row in rows]


@app.get("/job-documents/{doc_id}", response_model=JobDocumentRead)
def get_job_document(doc_id: int) -> JobDocumentRead:
    with SessionLocal() as session:
        doc = session.get(JobDocument, doc_id)
        if not doc:
            raise HTTPException(status_code=404, detail="JOB document not found")
        return JobDocumentRead.model_validate(doc)


@app.get("/job-documents/{doc_id}/details", response_model=JobDocumentDetailRead)
def get_job_document_details(doc_id: int, limit: int = 6) -> JobDocumentDetailRead:
    safe_limit = max(1, min(limit, 50))
    with SessionLocal() as session:
        doc = session.get(JobDocument, doc_id)
        if not doc:
            raise HTTPException(status_code=404, detail="JOB document not found")

        extraction = session.scalar(
            select(ExtractedText).where(ExtractedText.file_path == doc.path)
        )
        match_rows = session.scalars(
            select(MatchResult)
            .where(MatchResult.job_id == doc_id)
            .order_by(MatchResult.score.desc())
            .limit(safe_limit)
        ).all()

        match_count = session.scalar(
            select(func.count()).select_from(MatchResult).where(MatchResult.job_id == doc_id)
        ) or 0
        average_score = session.scalar(
            select(func.avg(MatchResult.score)).where(MatchResult.job_id == doc_id)
        )

        keyword_counts: dict[str, int] = {}
        for row in match_rows:
            for keyword in deserialize_keywords(row.common_keywords):
                keyword_counts[keyword] = keyword_counts.get(keyword, 0) + 1

        top_keywords = [
            keyword
            for keyword, _ in sorted(
                keyword_counts.items(),
                key=lambda item: (-item[1], item[0]),
            )[:12]
        ]

        return JobDocumentDetailRead(
            id=doc.id,
            path=doc.path,
            content_hash=doc.content_hash,
            status=doc.status,
            last_error=doc.last_error,
            structuring_status=doc.structuring_status,
            structuring_error=doc.structuring_error,
            priority_keywords=doc.priority_keywords,
            created_at=doc.created_at,
            updated_at=doc.updated_at,
            match_count=match_count,
            average_score=round(float(average_score), 2) if average_score is not None else None,
            top_keywords=top_keywords,
            extraction=ExtractedTextRead.model_validate(extraction) if extraction else None,
            top_matches=[
                MatchRead(
                    id=row.id,
                    cv_id=row.cv_id,
                    job_id=row.job_id,
                    score=row.score,
                    common_keywords=deserialize_keywords(row.common_keywords),
                    created_at=row.created_at,
                    updated_at=row.updated_at,
                )
                for row in match_rows
            ],
            
        )




@app.get("/scoring/weights", response_model=ScoringWeightsRead)
def scoring_weights() -> ScoringWeightsRead:
    # expose the main scoring/structured weights for inspection
    return ScoringWeightsRead(
        structured_lexical_weight=settings.structured_lexical_weight,
        structured_skill_weight=settings.structured_skill_weight,
        structured_must_have_weight=settings.structured_must_have_weight,
        structured_experience_weight=settings.structured_experience_weight,
        structured_language_weight=settings.structured_language_weight,
        structured_contract_weight=settings.structured_contract_weight,
        structured_summary_weight=settings.structured_summary_weight,
        structured_education_weight=settings.structured_education_weight,
        structured_missing_required_penalty=settings.structured_missing_required_penalty,
        structured_missing_experience_penalty=settings.structured_missing_experience_penalty,
        scoring_skill_weight=settings.scoring_skill_weight,
        scoring_phrase_bonus=settings.scoring_phrase_bonus,
        scoring_max_bonus=settings.scoring_max_bonus,
    )


@app.get("/job-documents/{doc_id}/pdf")
def get_job_document_pdf(doc_id: int) -> FileResponse:
    with SessionLocal() as session:
        doc = session.get(JobDocument, doc_id)
        if not doc:
            raise HTTPException(status_code=404, detail="JOB document not found")

    pdf_path = _resolve_document_pdf_path(doc.path, "job")
    return FileResponse(pdf_path, media_type="application/pdf", filename=pdf_path.name)


@app.get("/job-documents/{doc_id}/parsed-text")
def get_job_document_parsed_text(doc_id: int) -> Response:
    with SessionLocal() as session:
        doc = session.get(JobDocument, doc_id)
        if not doc:
            raise HTTPException(status_code=404, detail="JOB document not found")
        extraction = session.scalar(
            select(ExtractedText).where(ExtractedText.file_path == doc.path)
        )

    if not extraction or not extraction.extracted_text:
        raise HTTPException(status_code=404, detail="Extraction not found")

    profile = _get_or_build_profile(session, extraction, "job")
    rendered = _render_parsed_document_text(profile, "job")
    return Response(content=rendered, media_type="text/plain")


@app.get("/job-documents/{doc_id}/parsed-pdf")
def get_job_document_parsed_pdf(doc_id: int, background_tasks: BackgroundTasks) -> FileResponse:
    with SessionLocal() as session:
        doc = session.get(JobDocument, doc_id)
        if not doc:
            raise HTTPException(status_code=404, detail="JOB document not found")
        extraction = session.scalar(
            select(ExtractedText).where(ExtractedText.file_path == doc.path)
        )

    if not extraction or not extraction.extracted_text:
        raise HTTPException(status_code=404, detail="Extraction not found")

    profile = _get_or_build_profile(session, extraction, "job")
    rendered = _render_parsed_document_text(profile, "job")
    pdf_path = _render_text_pdf_to_temp(f"Offre parsee #{doc_id}", rendered)
    background_tasks.add_task(_cleanup_temp_file, pdf_path)
    return FileResponse(pdf_path, media_type="application/pdf", filename=f"job-parsed-{doc_id}.pdf")


@app.get("/job-documents/{doc_id}/parsed-json")
def get_job_document_parsed_json(doc_id: int) -> JSONResponse:
    with SessionLocal() as session:
        doc = session.get(JobDocument, doc_id)
        if not doc:
            raise HTTPException(status_code=404, detail="JOB document not found")
        extraction = session.scalar(
            select(ExtractedText).where(ExtractedText.file_path == doc.path)
        )

    if not extraction or not extraction.extracted_text:
        raise HTTPException(status_code=404, detail="Extraction not found")

    profile = _get_or_build_profile(session, extraction, "job")
    return JSONResponse(content=asdict(profile))


@app.post("/job-documents/{doc_id}/structure")
def structure_job_document(doc_id: int) -> dict:
    if not settings.conversion_use_docling:
        raise HTTPException(status_code=400, detail="Structuring is disabled on this deployment")

    with SessionLocal() as session:
        doc = session.get(JobDocument, doc_id)
        if not doc:
            raise HTTPException(status_code=404, detail="JOB document not found")
        doc.structuring_status = "pending"
        doc.structuring_error = None
        session.commit()
        doc_path = Path(doc.path)

    _on_watch_event(WatchEvent(path=doc_path, event_type="structure", observed_at=time()))
    return {"status": "queued"}


@app.patch("/job-documents/{doc_id}/priority-keywords", response_model=JobDocumentDetailRead)
def update_job_priority_keywords(doc_id: int, payload: JobPriorityKeywordsUpdate) -> JobDocumentDetailRead:
    """Save the recruiter's edited priority-keywords text (typed directly,
    or pre-filled from an uploaded file via the /extract endpoint below --
    either way, this is the only path that persists anything).

    Immediately re-queues this offer for rescoring (not re-extraction: the
    file on disk hasn't changed) so the recruiter sees the new keywords'
    effect on scores without a separate "Relancer l'IA" click. See the
    "rescore" watch-event type in _process_watch_event.
    """
    with SessionLocal() as session:
        doc = session.get(JobDocument, doc_id)
        if not doc:
            raise HTTPException(status_code=404, detail="JOB document not found")
        doc.priority_keywords = payload.keywords.strip() or None
        session.commit()
        doc_path = Path(doc.path)

    _on_watch_event(WatchEvent(path=doc_path, event_type="rescore", observed_at=time()))
    return get_job_document_details(doc_id)


def _extract_priority_keywords_text(upload: UploadFile) -> str:
    """Shared by both priority-keywords extract endpoints below: this never
    writes to the database or the watched storage dirs, it's purely a
    convenience to pre-fill a textarea for the recruiter to review and edit
    before saving."""
    raw_name = upload.filename or ""
    safe_name = Path(raw_name).name or "upload"
    suffix = Path(safe_name).suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise HTTPException(status_code=400, detail="Unsupported file type")

    temp_dir = Path(tempfile.gettempdir())
    temp_path: Path | None = None
    try:
        raw_temp = _write_upload_to_temp(upload, temp_dir, safe_name)
        # extract_text() dispatches on suffix -- _write_upload_to_temp's
        # NamedTemporaryFile name doesn't end in .pdf/.docx/.txt, so append
        # it rather than relying on the random temp name.
        temp_path = raw_temp.with_name(raw_temp.name + suffix)
        raw_temp.rename(temp_path)
        text = extract_text(temp_path)
    finally:
        try:
            upload.file.close()
        except Exception:
            pass
        if temp_path and temp_path.exists():
            temp_path.unlink()

    if not text or not text.strip():
        raise HTTPException(status_code=422, detail="Aucun texte n'a pu être extrait de ce fichier")

    return text.strip()


@app.post("/job-documents/{doc_id}/priority-keywords/extract", response_model=JobPriorityKeywordsExtracted)
def extract_job_priority_keywords(doc_id: int, upload: UploadFile = File(...)) -> JobPriorityKeywordsExtracted:
    """Extract text from an uploaded PDF/DOCX/TXT for the recruiter to
    review and edit before saving -- this endpoint never writes to the
    database or the watched storage dirs, it's purely a convenience to
    pre-fill the priority-keywords textarea. PATCH above is the only save
    path."""
    with SessionLocal() as session:
        if session.get(JobDocument, doc_id) is None:
            raise HTTPException(status_code=404, detail="JOB document not found")

    return JobPriorityKeywordsExtracted(keywords=_extract_priority_keywords_text(upload))


@app.post("/priority-keywords/extract-preview", response_model=JobPriorityKeywordsExtracted)
def extract_priority_keywords_preview(upload: UploadFile = File(...)) -> JobPriorityKeywordsExtracted:
    """Same extraction as above, but usable before the offer's JobDocument
    even exists -- backs the pre-upload dialog where the recruiter can set
    priority keywords before importing the offer file itself, so the first
    scoring pass already uses them (see /ingest's priority_keywords field)."""
    return JobPriorityKeywordsExtracted(keywords=_extract_priority_keywords_text(upload))


@app.get("/extractions/path", response_model=ExtractedTextRead)
def get_extraction_by_path(path: str) -> ExtractedTextRead:
    with SessionLocal() as session:
        extraction = session.scalar(
            select(ExtractedText).where(ExtractedText.file_path == path)
        )
        if not extraction:
            raise HTTPException(status_code=404, detail="Extraction not found")
        return ExtractedTextRead.model_validate(extraction)







@app.post("/maintenance/cleanup")
def cleanup_retention() -> dict[str, int]:
    deleted_events = 0
    deleted_extractions = 0
    deleted_scores = 0

    with SessionLocal() as session:
        if settings.retention_event_days > 0:
            cutoff = text(
                f"now() - interval '{int(settings.retention_event_days)} days'"
            )
            deleted_events = session.execute(
                delete(EventLog).where(EventLog.created_at < cutoff)
            ).rowcount or 0

        if settings.retention_extraction_days > 0:
            cutoff = text(
                f"now() - interval '{int(settings.retention_extraction_days)} days'"
            )
            deleted_extractions = session.execute(
                delete(ExtractedText).where(ExtractedText.created_at < cutoff)
            ).rowcount or 0

        if settings.retention_score_days > 0:
            cutoff = text(
                f"now() - interval '{int(settings.retention_score_days)} days'"
            )
            deleted_scores = session.execute(
                delete(ScoreResult).where(ScoreResult.created_at < cutoff)
            ).rowcount or 0

        session.commit()

    return {
        "deleted_events": deleted_events,
        "deleted_extractions": deleted_extractions,
        "deleted_scores": deleted_scores,
    }


@app.post("/maintenance/purge-orphans")
def purge_orphan_files() -> dict[str, int]:
    removed_files = 0
    removed_documents = 0

    cv_root = Path(settings.watch_cv_dir)
    job_root = Path(settings.watch_job_dir)

    with SessionLocal() as session:
        cv_paths = {
            Path(row)
            for row in session.scalars(select(CvDocument.path)).all()
            if row
        }
        job_paths = {
            Path(row)
            for row in session.scalars(select(JobDocument.path)).all()
            if row
        }

        for path in cv_paths:
            if not path.exists():
                _cleanup_removed_file(path, "cv")
                removed_documents += 1

        for path in job_paths:
            if not path.exists():
                _cleanup_removed_file(path, "job")
                removed_documents += 1

    for folder in (cv_root, job_root):
        if not folder.exists():
            continue
        for file_path in folder.iterdir():
            if not file_path.is_file():
                continue
            if not _is_supported_file(file_path):
                continue
            if file_path in cv_paths or file_path in job_paths:
                continue
            try:
                file_path.unlink()
                removed_files += 1
            except Exception as exc:  # pragma: no cover
                logger.warning("failed to remove orphan file %s: %s", file_path, exc)

    return {
        "removed_files": removed_files,
        "removed_documents": removed_documents,
    }


@app.post("/maintenance/backfill-embeddings")
def backfill_embeddings(
    scope: str = "all",
    limit: int | None = None,
    offset: int = 0,
    batch_size: int | None = None,
    dry_run: bool = False,
) -> dict[str, int]:
    if not settings.embedding_enabled:
        raise HTTPException(status_code=400, detail="embeddings disabled")

    normalized = scope.lower()
    if normalized not in {"all", "cv", "job"}:
        raise HTTPException(status_code=400, detail="invalid scope")

    processed = 0
    skipped = 0
    failed = 0
    total = 0

    def _apply_batch(batch: list[tuple[int, str | None, str]], kind: str) -> None:
        nonlocal processed, failed
        if not batch:
            return
        if dry_run:
            processed += len(batch)
            return
        try:
            vectors = embed_texts([item[2] for item in batch])
        except Exception as exc:
            logger.warning("embedding batch failed: %s", exc)
            failed += len(batch)
            return

        for idx, (doc_id, content_hash, _) in enumerate(batch):
            vector = vectors[idx] if idx < len(vectors) else []
            if not vector:
                failed += 1
                continue
            if kind == "cv":
                _upsert_cv_embedding(doc_id, content_hash, vector, session=session)
            else:
                _upsert_job_embedding(doc_id, content_hash, vector, session=session)
            processed += 1

    with SessionLocal() as session:
        if normalized in {"all", "cv"}:
            remaining = None if limit is None else max(limit - processed, 0)
            if remaining == 0:
                return {
                    "processed": processed,
                    "skipped": skipped,
                    "failed": failed,
                    "total": total,
                    "has_more": False,
                    "next_offset": offset,
                }

            total += session.scalar(select(func.count()).select_from(CvDocument)) or 0

            query = (
                select(
                    CvDocument.id,
                    ExtractedText.content_hash,
                    ExtractedText.extracted_text,
                )
                .join(ExtractedText, ExtractedText.file_path == CvDocument.path, isouter=True)
                .order_by(CvDocument.id)
            )
            if offset:
                query = query.offset(offset)
            if batch_size is not None:
                query = query.limit(batch_size)
            elif remaining is not None:
                query = query.limit(remaining)

            rows = session.execute(query)
            batch: list[tuple[int, str | None, str]] = []
            for cv_id, content_hash, extracted_text in rows:
                if limit is not None and processed >= limit:
                    break
                text_value = (extracted_text or "").strip()
                if not text_value:
                    skipped += 1
                    continue
                batch.append((cv_id, content_hash, text_value))
                if len(batch) >= settings.embedding_batch_size:
                    _apply_batch(batch, "cv")
                    batch = []

            _apply_batch(batch, "cv")
        if normalized in {"all", "job"}:
            remaining = None if limit is None else max(limit - processed, 0)
            if remaining == 0:
                return {
                    "processed": processed,
                    "skipped": skipped,
                    "failed": failed,
                    "total": total,
                    "has_more": False,
                    "next_offset": offset,
                }

            total += session.scalar(select(func.count()).select_from(JobDocument)) or 0

            query = (
                select(
                    JobDocument.id,
                    ExtractedText.content_hash,
                    ExtractedText.extracted_text,
                )
                .join(ExtractedText, ExtractedText.file_path == JobDocument.path, isouter=True)
                .order_by(JobDocument.id)
            )
            if offset:
                query = query.offset(offset)
            if batch_size is not None:
                query = query.limit(batch_size)
            elif remaining is not None:
                query = query.limit(remaining)

            rows = session.execute(query)
            batch: list[tuple[int, str | None, str]] = []
            for job_id, content_hash, extracted_text in rows:
                if limit is not None and processed >= limit:
                    break
                text_value = (extracted_text or "").strip()
                if not text_value:
                    skipped += 1
                    continue
                batch.append((job_id, content_hash, text_value))
                if len(batch) >= settings.embedding_batch_size:
                    _apply_batch(batch, "job")
                    batch = []

            _apply_batch(batch, "job")

    next_offset = offset
    if batch_size is not None:
        next_offset = offset + batch_size

    has_more = True
    if batch_size is None:
        has_more = False
    elif total and next_offset >= total:
        has_more = False

    return {
        "processed": processed,
        "skipped": skipped,
        "failed": failed,
        "total": total,
        "has_more": has_more,
        "next_offset": next_offset,
    }

@app.post("/extract", response_model=ExtractedTextRead)
def ingest_and_extract(file_path: str) -> ExtractedTextRead:
    return _extract_and_persist(Path(file_path))
