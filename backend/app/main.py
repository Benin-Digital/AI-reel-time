from contextlib import asynccontextmanager
import json
from html import escape
import logging
from pathlib import Path
import tempfile
from time import perf_counter, time
from datetime import datetime
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request, Response, UploadFile, File, Form, BackgroundTasks
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import redis
from sqlalchemy import delete, func, or_, select, text, update
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
    LearnedWeights,
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
)
from .services.scoring import analyze_match
from .services.structured import build_document_profile, normalize_job_offer_from_parsed, StructuredDocument
from .services.matcher import match_cv_to_job, set_learned_weights, get_active_weights
from .services.weight_learner import compute_learned_weights
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
            # if content changed, invalidate cached parsed profile
            if existing.content_hash != payload.content_hash:
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
        profile = _get_or_build_profile(session, extraction, "cv")


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
            existing.content_hash = extraction.content_hash
            existing.status = status
            existing.last_error = last_error
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
            existing.content_hash = extraction.content_hash
            existing.status = status
            existing.last_error = last_error
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
    cs = component_scores or {}
    with SessionLocal() as session:
        existing = session.scalar(
            select(MatchResult).where(
                MatchResult.cv_id == cv_id,
                MatchResult.job_id == job_id,
            )
        )
        if existing:
            existing.score = score
            existing.common_keywords = serialize_keywords(common)
            if cs:
                existing.score_semantic = cs.get("semantic")
                existing.score_skills = cs.get("skills")
                existing.score_experience = cs.get("experience")
                existing.score_education = cs.get("education")
                existing.score_languages = cs.get("languages")
                existing.score_contract = cs.get("contract")
                existing.match_domain = cs.get("domain")
            session.commit()
            session.refresh(existing)
            return MatchRead(
                id=existing.id,
                cv_id=existing.cv_id,
                job_id=existing.job_id,
                score=existing.score,
                common_keywords=deserialize_keywords(existing.common_keywords),
                created_at=existing.created_at,
                updated_at=existing.updated_at,
            )

        match = MatchResult(
            cv_id=cv_id,
            job_id=job_id,
            score=score,
            common_keywords=serialize_keywords(common),
            score_semantic=cs.get("semantic"),
            score_skills=cs.get("skills"),
            score_experience=cs.get("experience"),
            score_education=cs.get("education"),
            score_languages=cs.get("languages"),
            score_contract=cs.get("contract"),
            match_domain=cs.get("domain"),
        )
        session.add(match)
        session.commit()
        session.refresh(match)
        return MatchRead(
            id=match.id,
            cv_id=match.cv_id,
            job_id=match.job_id,
            score=match.score,
            common_keywords=deserialize_keywords(match.common_keywords),
            created_at=match.created_at,
            updated_at=match.updated_at,
        )


def _match_count_for_document(doc_id: int, role: str) -> int:
    with SessionLocal() as session:
        if role == "cv":
            count = session.scalar(
                select(func.count()).select_from(MatchResult).where(MatchResult.cv_id == doc_id)
            )
        else:
            count = session.scalar(
                select(func.count()).select_from(MatchResult).where(MatchResult.job_id == doc_id)
            )
    return int(count or 0)


def _upsert_cv_embedding(
    cv_id: int,
    content_hash: str | None,
    embedding: list[float],
    session: Session | None = None,
) -> None:
    if len(embedding) != settings.embedding_dim:
        logger.warning("embedding dim mismatch for cv %s", cv_id)
        return

    def _apply(target_session):
        existing = target_session.scalar(select(CvEmbedding).where(CvEmbedding.cv_id == cv_id))
        if existing and existing.content_hash == content_hash:
            return
        if existing:
            existing.content_hash = content_hash
            existing.embedding = embedding
            target_session.commit()
            return
        row = CvEmbedding(cv_id=cv_id, content_hash=content_hash, embedding=embedding)
        target_session.add(row)
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

    def _apply(target_session):
        existing = target_session.scalar(select(JobEmbedding).where(JobEmbedding.job_id == job_id))
        if existing and existing.content_hash == content_hash:
            return
        if existing:
            existing.content_hash = content_hash
            existing.embedding = embedding
            target_session.commit()
            return
        row = JobEmbedding(job_id=job_id, content_hash=content_hash, embedding=embedding)
        target_session.add(row)
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


def _render_text_pdf_to_temp(title: str, text_value: str) -> Path:
    temp_file = tempfile.NamedTemporaryFile(prefix="parsed-", suffix=".pdf", delete=False)
    temp_file_path = Path(temp_file.name)
    temp_file.close()

    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(str(temp_file_path), pagesize=A4)
    width, height = A4
    margin = 40
    y = height - margin
    c.setFont("Helvetica-Bold", 16)
    c.drawString(margin, y, title)
    y -= 24
    c.setFont("Helvetica", 10)
    for line in text_value.splitlines():
        if y < margin + 20:
            c.showPage()
            y = height - margin
            c.setFont("Helvetica", 10)
        c.drawString(margin, y, line[:200])
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
) -> set[int]:
    text_value = (extraction.extracted_text or "").strip()
    if not text_value:
        return set()

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
        return set()

    if not vector:
        return set()

    _upsert_cv_embedding(cv_doc.id, extraction.content_hash, vector)

    with SessionLocal() as session:
        distance = JobEmbedding.embedding.cosine_distance(vector).label("distance")
        rows = session.execute(
            select(
                JobEmbedding.job_id,
                JobDocument.path,
                ExtractedText.extracted_text,
                distance,
            )
            .join(JobDocument, JobEmbedding.job_id == JobDocument.id)
            .join(ExtractedText, ExtractedText.file_path == JobDocument.path, isouter=True)
            .order_by(distance.asc())
            .limit(settings.embedding_top_k)
        ).all()

    if not rows:
        return set()

    matched_job_ids: set[int] = set()
    for row in rows:
        job_text = (row.extracted_text or "").strip()
        if job_text:
            match_result = match_cv_to_job(text_value, job_text)
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
            }
        else:
            vector_score = _vector_score(float(row.distance))
            score = vector_score
            common = []
            cs = {}
        _insert_score_result(Path(cv_doc.path), Path(row.path), score, common)
        _upsert_match_result(cv_doc.id, row.job_id, score, common, cs)
        matched_job_ids.add(int(row.job_id))

    return matched_job_ids


def _vector_match_job(
    job_doc: JobDocumentRead,
    extraction: ExtractedTextRead,
) -> set[int]:
    text_value = (extraction.extracted_text or "").strip()
    if not text_value:
        return set()

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
        return set()

    if not vector:
        return set()

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
            .order_by(distance.asc())
            .limit(settings.embedding_top_k)
        ).all()

    if not rows:
        return set()

    matched_cv_ids: set[int] = set()
    for row in rows:
        cv_text = (row.extracted_text or "").strip()
        if cv_text:
            # Use structured offer text when available for richer job representation
            job_repr = (
                _render_job_offer_focus_text(structured_offer)
                if structured_offer is not None
                else text_value
            )
            match_result = match_cv_to_job(cv_text, job_repr)
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
            }
        else:
            vector_score = _vector_score(float(row.distance))
            score = vector_score
            common = []
            cs = {}
        _insert_score_result(Path(row.path), Path(job_doc.path), score, common)
        _upsert_match_result(row.cv_id, job_doc.id, score, common, cs)
        matched_cv_ids.add(int(row.cv_id))

    return matched_cv_ids


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


def _extract_and_persist(path: Path) -> ExtractedTextRead:
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
        if existing and existing.content_hash == content_hash and existing.extraction_success:
            settings_local = get_settings()
            docling_active = getattr(settings_local, "conversion_use_docling", False)
            already_docling = (existing.extraction_method or "").startswith("pdf-docling") or \
                              (existing.extraction_method or "").startswith("docling")
            # Re-extract if Docling is now active but the cached extraction didn't use it
            if not docling_active or already_docling:
                return ExtractedTextRead.model_validate(existing)

    try:
        settings_local = get_settings()
        method = path.suffix.lower().lstrip(".") or "unknown"
        if getattr(settings_local, "conversion_use_docling", False):
            from .services.conversion import convert_document
            converted = convert_document(path)
            extracted = converted.full_text
            method = f"pdf-{converted.backend}"
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


def _cleanup_removed_file(path: Path, role: str) -> None:
    with SessionLocal() as session:
        session.execute(
            delete(ExtractedText).where(ExtractedText.file_path == str(path))
        )
        if role == "cv":
            doc = session.scalar(select(CvDocument).where(CvDocument.path == str(path)))
            if doc:
                session.execute(delete(CvEmbedding).where(CvEmbedding.cv_id == doc.id))
                session.execute(delete(MatchResult).where(MatchResult.cv_id == doc.id))
                session.delete(doc)
            session.execute(delete(ScoreResult).where(ScoreResult.cv_path == str(path)))
        else:
            doc = session.scalar(select(JobDocument).where(JobDocument.path == str(path)))
            if doc:
                session.execute(delete(JobEmbedding).where(JobEmbedding.job_id == doc.id))
                session.execute(delete(MatchResult).where(MatchResult.job_id == doc.id))
                session.delete(doc)
            session.execute(delete(ScoreResult).where(ScoreResult.job_path == str(path)))
        session.commit()


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


def _score_against_counterparts(changed_path: Path, role: str) -> None:
    changed_result = _extract_and_persist(changed_path)
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

        existing_match_count = _match_count_for_document(cv_doc.id, "cv")
        if (
            previous_hash
            and changed_result.content_hash == previous_hash
            and previous_status == "ready"
            and existing_match_count > 0
        ):
            return

        matched_job_ids: set[int] = set()
        if settings.embedding_enabled:
            matched_job_ids = _vector_match_cv(cv_doc, changed_result)

        changed_text = changed_result.extracted_text or ""
        for job_path in _list_candidate_files(Path(settings.watch_job_dir)):
            job_result = _extract_and_persist(job_path)
            job_doc = _upsert_job_document(job_path, job_result)
            if job_doc.id in matched_job_ids:
                continue
            if not job_result.extraction_success:
                continue
            score, common = score_texts(changed_text, job_result.extracted_text or "")
            _insert_score_result(changed_path, job_path, score, common)
            _upsert_match_result(cv_doc.id, job_doc.id, score, common)
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
            previous_hash
            and changed_result.content_hash == previous_hash
            and previous_status == "ready"
            and _match_count_for_document(job_doc.id, "job") > 0
        ):
            return

        matched_cv_ids: set[int] = set()
        if settings.embedding_enabled:
            matched_cv_ids = _vector_match_job(job_doc, changed_result)

        changed_text = changed_result.extracted_text or ""
        for cv_path in _list_candidate_files(Path(settings.watch_cv_dir)):
            cv_result = _extract_and_persist(cv_path)
            cv_doc = _upsert_cv_document(cv_path, cv_result)
            if cv_doc.id in matched_cv_ids:
                continue
            if not cv_result.extraction_success:
                continue
            score, common = score_texts(cv_result.extracted_text or "", changed_text)
            _insert_score_result(cv_path, changed_path, score, common)
            _upsert_match_result(cv_doc.id, job_doc.id, score, common)


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
    init_db()
    with SessionLocal() as session:
        ensure_bootstrap_user(session)
        _load_active_weights(session)
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
    )
    worker.start()
    app.state.watcher = watcher
    app.state.worker = worker
    try:
        yield
    finally:
        worker.stop()
        watcher.stop()


_configure_logging()
app = FastAPI(title=settings.app_name, version=settings.app_version, lifespan=lifespan)


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


@app.get("/health")
def healthcheck() -> dict[str, str]:
    return {
        "status": "ok",
        "environment": settings.environment,
        "version": settings.app_version,
    }


@app.get("/ready")
def readiness() -> dict[str, str]:
    try:
        with SessionLocal() as session:
            session.execute(text("SELECT 1"))
    except Exception as exc:  # pragma: no cover
        logger.error("db readiness failed: %s", exc)
        raise HTTPException(status_code=503, detail="database unavailable")

    try:
        client = _get_redis_client()
        client.ping()
    except Exception as exc:  # pragma: no cover
        logger.error("redis readiness failed: %s", exc)
        raise HTTPException(status_code=503, detail="redis unavailable")

    return {"status": "ready"}


@app.get("/metrics")
def metrics() -> dict[str, float | int | bool | str | None]:
    uptime = int(time() - app.state.started_at)
    queue_status = get_queue_status()
    worker = getattr(app.state, "worker", None)
    with SessionLocal() as session:
        events = session.scalar(select(func.count()).select_from(EventLog))
        extractions = session.scalar(select(func.count()).select_from(ExtractedText))
        scores = session.scalar(select(func.count()).select_from(ScoreResult))
    return {
        "uptime_seconds": uptime,
        "event_count": int(events or 0),
        "extraction_count": int(extractions or 0),
        "score_count": int(scores or 0),
        "redis_available": bool(queue_status.get("redis_available", False)),
        "redis_queue_length": int(queue_status.get("redis_queue_length", 0)),
        "memory_queue_length": int(queue_status.get("memory_queue_length", 0)),
        "worker_alive": bool(worker.is_running) if worker is not None else False,
        "worker_last_error": worker.last_error if worker is not None else None,
    }


@app.get("/metrics/prometheus")
def metrics_prometheus() -> Response:
    queue_status = get_queue_status()
    worker = getattr(app.state, "worker", None)
    with SessionLocal() as session:
        events = session.scalar(select(func.count()).select_from(EventLog))
        extractions = session.scalar(select(func.count()).select_from(ExtractedText))
        scores = session.scalar(select(func.count()).select_from(ScoreResult))
        matches = session.scalar(select(func.count()).select_from(MatchResult))
        cv_documents = session.scalar(select(func.count()).select_from(CvDocument))
        job_documents = session.scalar(select(func.count()).select_from(JobDocument))
        cv_embeddings = session.scalar(select(func.count()).select_from(CvEmbedding))
        job_embeddings = session.scalar(select(func.count()).select_from(JobEmbedding))

    update_runtime_metrics(
        queue_status,
        bool(worker.is_running) if worker is not None else False,
        {
            "events": int(events or 0),
            "extractions": int(extractions or 0),
            "scores": int(scores or 0),
            "matches": int(matches or 0),
            "cv_documents": int(cv_documents or 0),
            "job_documents": int(job_documents or 0),
            "cv_embeddings": int(cv_embeddings or 0),
            "job_embeddings": int(job_embeddings or 0),
        },
        settings.embedding_enabled,
    )
    return Response(content=render_metrics(), media_type=CONTENT_TYPE_LATEST)


@app.get("/queue-status")
def queue_status() -> dict[str, int | bool]:
    return get_queue_status()


@app.get("/worker-status")
def worker_status() -> dict[str, bool | str | None]:
    worker = getattr(app.state, "worker", None)
    if worker is None:
        raise HTTPException(status_code=503, detail="worker unavailable")
    return {
        "alive": worker.is_running,
        "last_error": worker.last_error,
    }


@app.post("/auth/login", response_model=AuthLoginResponse)
def login(payload: AuthLoginRequest) -> AuthLoginResponse:
    with SessionLocal() as session:
        user = authenticate_user(session, payload.email, payload.password)
        if user is None:
            raise HTTPException(status_code=401, detail="Invalid credentials")
        token = create_access_token(user)
        return AuthLoginResponse(
            access_token=token,
            user=UserRead.model_validate(user),
        )


@app.get("/auth/me", response_model=UserRead)
def get_me(request: Request) -> UserRead:
    user = getattr(request.state, "user", None)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return UserRead.model_validate(user)


@app.get("/auth/users", response_model=list[UserRead])
def list_users(request: Request) -> list[UserRead]:
    _require_admin(request)
    with SessionLocal() as session:
        rows = session.scalars(select(User).order_by(User.id.asc())).all()
        return [UserRead.model_validate(row) for row in rows]


@app.post("/auth/users", response_model=UserRead)
def create_user(payload: UserCreate, request: Request) -> UserRead:
    current_user = _require_admin(request)
    if current_user.role == "admin" and payload.role != "member":
        raise HTTPException(status_code=403, detail="Admin can only create member accounts")
    with SessionLocal() as session:
        existing = session.scalar(select(User).where(User.email == payload.email))
        if existing is not None:
            raise HTTPException(status_code=409, detail="User already exists")
        user = User(
            email=payload.email,
            password_hash=hash_password(payload.password),
            first_name=payload.first_name,
            last_name=payload.last_name,
            role=payload.role,
            is_active=True,
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        return UserRead.model_validate(user)


@app.patch("/auth/users/{user_id}", response_model=UserRead)
def update_user(user_id: int, payload: UserUpdate, request: Request) -> UserRead:
    current_user = _require_admin(request)
    with SessionLocal() as session:
        user = session.get(User, user_id)
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")
        if user.role == "superadmin":
            raise HTTPException(status_code=403, detail="Superadmin account is protected")

        if current_user.role == "admin":
            if user.role != "member":
                raise HTTPException(status_code=403, detail="Admin can only manage member accounts")
            if payload.role is not None and payload.role != "member":
                raise HTTPException(status_code=403, detail="Admin can only keep member role")

        if payload.role is not None:
            user.role = payload.role
        if payload.is_active is not None:
            user.is_active = payload.is_active

        session.add(user)
        session.commit()
        session.refresh(user)
        return UserRead.model_validate(user)


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


@app.post("/ingest")
def ingest_file(
    folder: str = Form(...),
    upload: UploadFile = File(...),
    filename: str | None = Form(None),
) -> dict[str, str]:
    if folder not in {"cv", "job"}:
        raise HTTPException(status_code=400, detail="Invalid folder")

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

                c = canvas.Canvas(str(pdf_path), pagesize=A4)
                width, height = A4
                margin = 40
                y = height - margin
                c.setFont("Helvetica-Bold", 16)
                c.drawString(margin, y, offer.title or "Offre")
                y -= 24
                c.setFont("Helvetica", 10)
                lines = rendered_text.splitlines()
                for line in lines:
                    if y < margin + 20:
                        c.showPage()
                        y = height - margin
                        c.setFont("Helvetica", 10)
                    c.drawString(margin, y, line[:200])
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


def _calculate_session_counts(session: Session, session_id: int) -> tuple[int, int, int]:
    cv_count = session.scalar(
        select(func.count()).select_from(CvDocument).where(CvDocument.session_id == session_id)
    ) or 0
    job_count = session.scalar(
        select(func.count()).select_from(JobDocument).where(JobDocument.session_id == session_id)
    ) or 0
    match_count = session.scalar(
        select(func.count()).select_from(MatchResult)
        .join(CvDocument, MatchResult.cv_id == CvDocument.id)
        .join(JobDocument, MatchResult.job_id == JobDocument.id)
        .where(CvDocument.session_id == session_id, JobDocument.session_id == session_id)
    ) or 0
    return int(cv_count), int(job_count), int(match_count)


@app.get("/sessions", response_model=list[AnalysisSessionRead])
def list_analysis_sessions(
    page: int = 1,
    page_size: int = 25,
    status: str | None = None,
    search: str | None = None,
) -> list[AnalysisSessionRead]:
    safe_size = max(1, min(page_size, 100))
    safe_offset = max(0, (page - 1) * safe_size)
    stmt = select(AnalysisSession)
    if status:
        stmt = stmt.where(AnalysisSession.status == status)
    if search:
        search_expr = f"%{search}%"
        stmt = stmt.where(
            or_(
                AnalysisSession.name.ilike(search_expr),
                AnalysisSession.description.ilike(search_expr),
            )
        )
    stmt = stmt.order_by(AnalysisSession.id.desc()).offset(safe_offset).limit(safe_size)
    with SessionLocal() as session:
        rows = session.scalars(stmt).all()
        result = []
        for row in rows:
            cv_count, job_count, match_count = _calculate_session_counts(session, row.id)
            result.append(
                AnalysisSessionRead(
                    id=row.id,
                    name=row.name,
                    description=row.description,
                    status=row.status,
                    closed_at=row.closed_at,
                    cv_count=cv_count,
                    job_count=job_count,
                    match_count=match_count,
                    created_at=row.created_at,
                    updated_at=row.updated_at,
                )
            )
        return result


@app.post("/sessions", response_model=AnalysisSessionRead)
def create_analysis_session(payload: AnalysisSessionCreate) -> AnalysisSessionRead:
    with SessionLocal() as session:
        new_session = AnalysisSession(
            name=payload.name.strip(),
            description=payload.description.strip() if payload.description else None,
            status=payload.status,
            closed_at=datetime.utcnow() if payload.status == "closed" else None,
        )
        session.add(new_session)
        session.commit()
        session.refresh(new_session)
        cv_count, job_count, match_count = _calculate_session_counts(session, new_session.id)
        return AnalysisSessionRead(
            id=new_session.id,
            name=new_session.name,
            description=new_session.description,
            status=new_session.status,
            closed_at=new_session.closed_at,
            cv_count=cv_count,
            job_count=job_count,
            match_count=match_count,
            created_at=new_session.created_at,
            updated_at=new_session.updated_at,
        )


@app.get("/sessions/{session_id}", response_model=AnalysisSessionDetailRead)
def get_analysis_session(session_id: int) -> AnalysisSessionDetailRead:
    with SessionLocal() as session:
        session_obj = session.get(AnalysisSession, session_id)
        if not session_obj:
            raise HTTPException(status_code=404, detail="Analyse session not found")

        cv_docs = session.scalars(
            select(CvDocument)
            .where(CvDocument.session_id == session_id)
            .order_by(CvDocument.id.desc())
        ).all()
        job_docs = session.scalars(
            select(JobDocument)
            .where(JobDocument.session_id == session_id)
            .order_by(JobDocument.id.desc())
        ).all()
        cv_count, job_count, match_count = _calculate_session_counts(session, session_id)
        return AnalysisSessionDetailRead(
            id=session_obj.id,
            name=session_obj.name,
            description=session_obj.description,
            status=session_obj.status,
            closed_at=session_obj.closed_at,
            cv_count=cv_count,
            job_count=job_count,
            match_count=match_count,
            created_at=session_obj.created_at,
            updated_at=session_obj.updated_at,
            cv_documents=[CvDocumentRead.model_validate(doc) for doc in cv_docs],
            job_documents=[JobDocumentRead.model_validate(doc) for doc in job_docs],
        )


@app.patch("/sessions/{session_id}", response_model=AnalysisSessionRead)
def update_analysis_session(session_id: int, payload: AnalysisSessionUpdate) -> AnalysisSessionRead:
    with SessionLocal() as session:
        session_obj = session.get(AnalysisSession, session_id)
        if not session_obj:
            raise HTTPException(status_code=404, detail="Analyse session not found")

        if payload.name is not None:
            session_obj.name = payload.name.strip()
        if payload.description is not None:
            session_obj.description = payload.description.strip() if payload.description else None
        if payload.status is not None:
            session_obj.status = payload.status
            if payload.status == "closed" and session_obj.closed_at is None:
                session_obj.closed_at = datetime.utcnow()
            elif payload.status == "open":
                session_obj.closed_at = None
        session.commit()
        session.refresh(session_obj)
        cv_count, job_count, match_count = _calculate_session_counts(session, session_id)
        return AnalysisSessionRead(
            id=session_obj.id,
            name=session_obj.name,
            description=session_obj.description,
            status=session_obj.status,
            closed_at=session_obj.closed_at,
            cv_count=cv_count,
            job_count=job_count,
            match_count=match_count,
            created_at=session_obj.created_at,
            updated_at=session_obj.updated_at,
        )


@app.post("/sessions/{session_id}/assign", response_model=AnalysisSessionDetailRead)
def assign_documents_to_session(session_id: int, payload: SessionAssignRequest) -> AnalysisSessionDetailRead:
    with SessionLocal() as session:
        session_obj = session.get(AnalysisSession, session_id)
        if not session_obj:
            raise HTTPException(status_code=404, detail="Analyse session not found")

        if payload.cv_ids:
            cv_rows = session.scalars(select(CvDocument).where(CvDocument.id.in_(payload.cv_ids))).all()
            if len(cv_rows) != len(payload.cv_ids):
                raise HTTPException(status_code=404, detail="Un ou plusieurs CV n'ont pas été trouvés")
            for doc in cv_rows:
                doc.session_id = session_id

        if payload.job_ids:
            job_rows = session.scalars(select(JobDocument).where(JobDocument.id.in_(payload.job_ids))).all()
            if len(job_rows) != len(payload.job_ids):
                raise HTTPException(status_code=404, detail="Une ou plusieurs offres n'ont pas été trouvées")
            for doc in job_rows:
                doc.session_id = session_id

        session.commit()
        session.refresh(session_obj)
        cv_docs = session.scalars(
            select(CvDocument).where(CvDocument.session_id == session_id).order_by(CvDocument.id.desc())
        ).all()
        job_docs = session.scalars(
            select(JobDocument).where(JobDocument.session_id == session_id).order_by(JobDocument.id.desc())
        ).all()
        cv_count, job_count, match_count = _calculate_session_counts(session, session_id)
        return AnalysisSessionDetailRead(
            id=session_obj.id,
            name=session_obj.name,
            description=session_obj.description,
            status=session_obj.status,
            closed_at=session_obj.closed_at,
            cv_count=cv_count,
            job_count=job_count,
            match_count=match_count,
            created_at=session_obj.created_at,
            updated_at=session_obj.updated_at,
            cv_documents=[CvDocumentRead.model_validate(doc) for doc in cv_docs],
            job_documents=[JobDocumentRead.model_validate(doc) for doc in job_docs],
        )


@app.post("/sessions/{session_id}/unassign", response_model=AnalysisSessionDetailRead)
def unassign_session_documents(session_id: int) -> AnalysisSessionDetailRead:
    with SessionLocal() as session:
        session_obj = session.get(AnalysisSession, session_id)
        if not session_obj:
            raise HTTPException(status_code=404, detail="Session not found")
        session.execute(
            update(CvDocument).where(CvDocument.session_id == session_id).values(session_id=None)
        )
        session.execute(
            update(JobDocument).where(JobDocument.session_id == session_id).values(session_id=None)
        )
        session_obj.status = "open"
        session_obj.closed_at = None
        session.commit()
        session.refresh(session_obj)
        return AnalysisSessionDetailRead(
            id=session_obj.id,
            name=session_obj.name,
            description=session_obj.description,
            status=session_obj.status,
            closed_at=session_obj.closed_at,
            cv_count=0,
            job_count=0,
            match_count=0,
            created_at=session_obj.created_at,
            updated_at=session_obj.updated_at,
            cv_documents=[],
            job_documents=[],
        )


@app.delete("/sessions/{session_id}", status_code=204)
def delete_analysis_session(session_id: int, delete_documents: bool = False) -> None:
    with SessionLocal() as session:
        session_obj = session.get(AnalysisSession, session_id)
        if not session_obj:
            raise HTTPException(status_code=404, detail="Session not found")

        if delete_documents:
            cv_docs  = session.scalars(select(CvDocument).where(CvDocument.session_id == session_id)).all()
            job_docs = session.scalars(select(JobDocument).where(JobDocument.session_id == session_id)).all()
            for doc in cv_docs:
                _cleanup_removed_file(Path(doc.path), "cv")
                try: Path(doc.path).unlink(missing_ok=True)
                except Exception: pass
            for doc in job_docs:
                _cleanup_removed_file(Path(doc.path), "job")
                try: Path(doc.path).unlink(missing_ok=True)
                except Exception: pass

        session.delete(session_obj)
        session.commit()


@app.post("/matches/analyze")
def analyze_texts(payload: AnalyzeRequest) -> JSONResponse:
    analysis = analyze_match(payload.cv_text or "", payload.job_text or "")
    return JSONResponse(content=analysis)


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


@app.get("/extractions/path", response_model=ExtractedTextRead)
def get_extraction_by_path(path: str) -> ExtractedTextRead:
    with SessionLocal() as session:
        extraction = session.scalar(
            select(ExtractedText).where(ExtractedText.file_path == path)
        )
        if not extraction:
            raise HTTPException(status_code=404, detail="Extraction not found")
        return ExtractedTextRead.model_validate(extraction)


@app.get("/cv-documents/{doc_id}/matches", response_model=list[MatchRead])
def list_matches_for_cv(doc_id: int, limit: int = 50) -> list[MatchRead]:
    safe_limit = max(1, min(limit, 200))
    with SessionLocal() as session:
        rows = session.scalars(
            select(MatchResult)
            .where(MatchResult.cv_id == doc_id)
            .order_by(MatchResult.score.desc())
            .limit(safe_limit)
        ).all()
        return [
            MatchRead(
                id=row.id,
                cv_id=row.cv_id,
                job_id=row.job_id,
                score=row.score,
                common_keywords=deserialize_keywords(row.common_keywords),
                created_at=row.created_at,
                updated_at=row.updated_at,
            )
            for row in rows
        ]


@app.get("/job-documents/{doc_id}/matches", response_model=list[MatchRead])
def list_matches_for_job(doc_id: int, limit: int = 50) -> list[MatchRead]:
    safe_limit = max(1, min(limit, 200))
    with SessionLocal() as session:
        rows = session.scalars(
            select(MatchResult)
            .where(MatchResult.job_id == doc_id)
            .order_by(MatchResult.score.desc())
            .limit(safe_limit)
        ).all()
        return [
            MatchRead(
                id=row.id,
                cv_id=row.cv_id,
                job_id=row.job_id,
                score=row.score,
                common_keywords=deserialize_keywords(row.common_keywords),
                created_at=row.created_at,
                updated_at=row.updated_at,
            )
            for row in rows
        ]


@app.get("/matches", response_model=list[MatchRead])
def list_matches(
    page: int = 1,
    page_size: int = 25,
    cv_id: int | None = None,
    job_id: int | None = None,
    session_id: int | None = None,
    unassigned_only: bool = False,
    min_score: float | None = None,
    max_score: float | None = None,
    sort_by: str = "score_desc",
    search: str | None = None,
) -> list[MatchRead]:
    safe_size = max(1, min(page_size, 100))
    safe_offset = max(0, (page - 1) * safe_size)
    stmt = select(MatchResult)
    if session_id is not None or unassigned_only or search:
        stmt = stmt.join(CvDocument, MatchResult.cv_id == CvDocument.id)
        stmt = stmt.join(JobDocument, MatchResult.job_id == JobDocument.id)
    if cv_id is not None:
        stmt = stmt.where(MatchResult.cv_id == cv_id)
    if job_id is not None:
        stmt = stmt.where(MatchResult.job_id == job_id)
    if session_id is not None:
        stmt = stmt.where(
            CvDocument.session_id == session_id,
            JobDocument.session_id == session_id,
        )
    if unassigned_only:
        stmt = stmt.where(
            CvDocument.session_id.is_(None),
            JobDocument.session_id.is_(None),
        )
    if min_score is not None:
        stmt = stmt.where(MatchResult.score >= min_score)
    if max_score is not None:
        stmt = stmt.where(MatchResult.score <= max_score)
    if search:
        search_expr = f"%{search}%"
        stmt = stmt.where(
            or_(
                MatchResult.common_keywords.ilike(search_expr),
                CvDocument.path.ilike(search_expr),
                JobDocument.path.ilike(search_expr),
            )
        )

    if sort_by == "score_asc":
        stmt = stmt.order_by(MatchResult.score.asc())
    elif sort_by == "created_at_asc":
        stmt = stmt.order_by(MatchResult.created_at.asc())
    elif sort_by == "created_at_desc":
        stmt = stmt.order_by(MatchResult.created_at.desc())
    else:
        stmt = stmt.order_by(MatchResult.score.desc())

    with SessionLocal() as session:
        rows = session.scalars(stmt.offset(safe_offset).limit(safe_size)).all()
        return [
            MatchRead(
                id=row.id,
                cv_id=row.cv_id,
                job_id=row.job_id,
                score=row.score,
                common_keywords=deserialize_keywords(row.common_keywords),
                created_at=row.created_at,
                updated_at=row.updated_at,
            )
            for row in rows
        ]


@app.get("/matches/{match_id}", response_model=MatchRead)
def get_match(match_id: int) -> MatchRead:
    with SessionLocal() as session:
        match = session.get(MatchResult, match_id)
        if not match:
            raise HTTPException(status_code=404, detail="Match not found")
        return MatchRead(
            id=match.id,
            cv_id=match.cv_id,
            job_id=match.job_id,
            score=match.score,
            common_keywords=deserialize_keywords(match.common_keywords),
            created_at=match.created_at,
            updated_at=match.updated_at,
        )


@app.get("/matches/{match_id}/explain", response_model=MatchExplainRead)
def explain_match(match_id: int) -> MatchExplainRead:
    with SessionLocal() as session:
        match = session.get(MatchResult, match_id)
        if not match:
            raise HTTPException(status_code=404, detail="Match not found")

        cv_doc = session.get(CvDocument, match.cv_id)
        job_doc = session.get(JobDocument, match.job_id)
        if not cv_doc or not job_doc:
            raise HTTPException(status_code=404, detail="Document not found")

        cv_extract = session.scalar(
            select(ExtractedText).where(ExtractedText.file_path == cv_doc.path)
        )
        job_extract = session.scalar(
            select(ExtractedText).where(ExtractedText.file_path == job_doc.path)
        )

        cv_text = cv_extract.extracted_text if cv_extract else ""
        job_text = job_extract.extracted_text if job_extract else ""
        keywords = deserialize_keywords(match.common_keywords)

        details = build_match_explanation(cv_text, job_text, match.score, keywords)
        return MatchExplainRead(
            match_id=match.id,
            score=match.score,
            summary=str(details["summary"]),
            why_match=list(details["why_match"]),
            vigilance=list(details["vigilance"]),
            evidence=list(details["evidence"]),
            keyword_hits=list(details["keyword_hits"]),
            score_semantic=match.score_semantic,
            score_skills=match.score_skills,
            score_experience=match.score_experience,
            score_education=match.score_education,
            score_languages=match.score_languages,
            score_contract=match.score_contract,
            match_domain=match.match_domain,
        )


@app.get("/matches/{match_id}/feedback", response_model=MatchFeedbackRead | None)
def get_match_feedback(match_id: int, request: Request) -> MatchFeedbackRead | None:
    _require_auth(request)
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


@app.post("/matches/{match_id}/feedback", response_model=MatchFeedbackRead)
def create_match_feedback(match_id: int, payload: MatchFeedbackCreate, request: Request) -> MatchFeedbackRead:
    _require_auth(request)

    rating = payload.rating
    if rating is not None:
        rating = max(1, min(5, rating))

    comment = payload.comment.strip() if payload.comment and payload.comment.strip() else None

    with SessionLocal() as session:
        match = session.get(MatchResult, match_id)
        if not match:
            raise HTTPException(status_code=404, detail="Match not found")

        feedback = MatchFeedback(
            match_id=match.id,
            decision=payload.decision,
            rating=rating,
            comment=comment,
        )
        session.add(feedback)
        session.commit()
        session.refresh(feedback)
        return MatchFeedbackRead.model_validate(feedback)


_COMP_LABELS = {
    "score_skills":     "Compétences",
    "score_semantic":   "Sémantique",
    "score_experience": "Expérience",
    "score_education":  "Formation",
    "score_languages":  "Langues",
    "score_contract":   "Contrat",
}


@app.get("/feedback/stats", response_model=FeedbackStatsRead)
def get_feedback_stats(request: Request) -> FeedbackStatsRead:
    _require_auth(request)
    with SessionLocal() as session:
        # 1. Distribution by decision
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

        # 2. Average component scores by decision
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

        # 3. By domain
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

        # 4. Weight hints: delta = accept_mean − reject_mean per component
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


def _load_active_weights(session) -> None:
    row = session.scalar(
        select(LearnedWeights)
        .where(LearnedWeights.is_active == True)  # noqa: E712
        .order_by(LearnedWeights.created_at.desc())
    )
    if row:
        set_learned_weights({
            "semantic":   row.w_semantic,
            "skills":     row.w_skills,
            "experience": row.w_experience,
            "education":  row.w_education,
            "languages":  row.w_languages,
            "contract":   row.w_contract,
        })


@app.get("/feedback/learned-weights", response_model=LearnedWeightsRead | None)
def get_learned_weights(request: Request) -> LearnedWeightsRead | None:
    _require_auth(request)
    with SessionLocal() as session:
        row = session.scalar(
            select(LearnedWeights)
            .where(LearnedWeights.is_active == True)  # noqa: E712
            .order_by(LearnedWeights.created_at.desc())
        )
        return LearnedWeightsRead.model_validate(row) if row else None


@app.post("/feedback/compute-weights", response_model=WeightComputeResult)
def compute_weights(request: Request) -> WeightComputeResult:
    _require_admin(request)
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


@app.post("/feedback/apply-weights", response_model=LearnedWeightsRead)
def apply_weights(request: Request) -> LearnedWeightsRead:
    _require_admin(request)
    user = _require_admin(request)
    with SessionLocal() as session:
        try:
            result = compute_learned_weights(session)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))

        # Deactivate previous
        session.execute(
            select(LearnedWeights).where(LearnedWeights.is_active == True)  # noqa: E712
        )
        for old in session.scalars(
            select(LearnedWeights).where(LearnedWeights.is_active == True)  # noqa: E712
        ):
            old.is_active = False

        row = LearnedWeights(
            w_semantic=result["semantic"],
            w_skills=result["skills"],
            w_experience=result["experience"],
            w_education=result["education"],
            w_languages=result["languages"],
            w_contract=result["contract"],
            sample_count=result["sample_count"],
            accuracy=result["accuracy"],
            is_active=True,
            created_by=user.id,
        )
        session.add(row)
        session.commit()
        session.refresh(row)

        set_learned_weights({
            "semantic":   row.w_semantic,
            "skills":     row.w_skills,
            "experience": row.w_experience,
            "education":  row.w_education,
            "languages":  row.w_languages,
            "contract":   row.w_contract,
        })
        return LearnedWeightsRead.model_validate(row)


def _scoring_v2_model_path() -> Path | None:
    raw = getattr(settings, "scoring_v2_model_path", "") or ""
    if not raw:
        return None
    p = Path(raw)
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


@app.post("/scoring-v2/train", response_model=ScoringV2TrainResult)
def scoring_v2_train(request: Request) -> ScoringV2TrainResult:
    _require_admin(request)
    from .services.scoring_v2 import train_aggregator
    from .services.embeddings import compute_domain_sim
    model_path = _scoring_v2_model_path()
    with SessionLocal() as session:
        try:
            agg = train_aggregator(session, model_path=model_path, domain_sim_fn=compute_domain_sim)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        except Exception as exc:
            logger.exception("scoring_v2 training failed: %s", exc)
            raise HTTPException(status_code=500, detail=f"training failed: {exc}")
    return ScoringV2TrainResult(
        sample_count=agg.sample_count,
        auc=agg.auc,
        feature_importance={k: round(v, 4) for k, v in agg.feature_importance.items()},
        saved_to=str(model_path) if model_path else None,
    )


@app.post("/scoring-v2/score", response_model=ScoringV2ScoreResult)
def scoring_v2_score(payload: ScoringV2ScoreRequest, request: Request) -> ScoringV2ScoreResult:
    _require_auth(request)
    from .services.scoring_v2 import score_pair, compute_signals, SIGNAL_KEYS
    from .services.embeddings import compute_domain_sim
    with SessionLocal() as session:
        cv_ext = session.scalar(select(ExtractedText).where(ExtractedText.file_path == payload.cv_path))
        job_ext = session.scalar(select(ExtractedText).where(ExtractedText.file_path == payload.job_path))
        if not cv_ext or not job_ext:
            raise HTTPException(status_code=404, detail="cv_path or job_path not found in extractions")
        cv_profile = cv_ext.parsed_profile or {}
        job_profile = job_ext.parsed_profile or {}
        # Pull cached semantic score from MatchResult if available
        match = session.scalar(
            select(MatchResult).where(
                MatchResult.cv_path == payload.cv_path,
                MatchResult.job_path == payload.job_path,
            )
        )
        semantic_sim = float(match.score_semantic) if (match and match.score_semantic is not None) else 0.0

    domain_sim = compute_domain_sim(cv_profile, job_profile)
    result = score_pair(
        cv_profile=cv_profile,
        job_profile=job_profile,
        semantic_sim=semantic_sim,
        domain_sim=domain_sim,
        model_path=_scoring_v2_model_path(),
    )
    return ScoringV2ScoreResult(
        probability=result["probability"],
        signals={k: round(float(result["signals"].get(k, 0.0)), 4) for k in SIGNAL_KEYS},
        model_available=result["model_available"],
    )


@app.get("/scoring-v2/status", response_model=ScoringV2Status)
def scoring_v2_status(request: Request) -> ScoringV2Status:
    _require_auth(request)
    from .services.scoring_v2 import get_aggregator
    model_path = _scoring_v2_model_path()
    agg = get_aggregator(model_path)
    if agg is None:
        return ScoringV2Status(
            model_available=False,
            model_path=str(model_path) if model_path else None,
        )
    return ScoringV2Status(
        model_available=True,
        model_path=str(model_path) if model_path else None,
        sample_count=agg.sample_count,
        auc=agg.auc,
        feature_importance={k: round(v, 4) for k, v in agg.feature_importance.items()},
    )


@app.post("/esco/lookup", response_model=EscoLookupResult)
def esco_lookup(payload: EscoLookupRequest, request: Request) -> EscoLookupResult:
    _require_auth(request)
    from .services.esco_taxonomy import find_skills_esco, get_esco_index
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


@app.post("/search", response_model=list[SearchHit])
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
