from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text, func
from pgvector.sqlalchemy import Vector
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        Index("ux_users_email", "email", unique=True),
        Index("ix_users_role", "role"),
        Index("ix_users_active", "is_active"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255))
    password_hash: Mapped[str] = mapped_column(String(255))
    first_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    role: Mapped[str] = mapped_column(String(32), default="member")
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class EventLog(Base):
    __tablename__ = "event_logs"
    __table_args__ = (
        Index("ix_event_logs_created_at", "created_at"),
        Index("ix_event_logs_path", "path"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(32), default="watcher")
    event_type: Mapped[str] = mapped_column(String(32))
    path: Mapped[str] = mapped_column(String(1024))
    fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    observed_at: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )


class ExtractedText(Base):
    __tablename__ = "extracted_text"
    __table_args__ = (
        Index("ix_extracted_text_updated_at", "updated_at"),
        Index("ix_extracted_text_content_hash", "content_hash"),
        # Created directly in migration 0010_add_parsed_profile, never
        # declared here (2026-09-14 schema-drift audit) -- alembic
        # autogenerate saw "DB has an index the model doesn't know about"
        # and proposed dropping it. Declaring it here (no DB change) makes
        # the model match reality instead.
        Index("ix_extracted_text_parsed_profile_hash", "parsed_profile_hash"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    file_path: Mapped[str] = mapped_column(String(1024), unique=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=True)
    extracted_text: Mapped[str] = mapped_column(Text, nullable=True)
    extraction_method: Mapped[str] = mapped_column(String(32), default="unknown")
    extraction_success: Mapped[bool] = mapped_column(default=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    # cached parsed profile (structure produced by build_document_profile)
    parsed_profile: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    parsed_profile_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    parsed_profile_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class ScoreResult(Base):
    __tablename__ = "score_results"
    __table_args__ = (
        Index("ix_score_results_created_at", "created_at"),
        Index("ix_score_results_cv_path", "cv_path"),
        Index("ix_score_results_job_path", "job_path"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    cv_path: Mapped[str] = mapped_column(String(1024))
    job_path: Mapped[str] = mapped_column(String(1024))
    score: Mapped[float] = mapped_column(Float)
    common_keywords: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )


class CvDocument(Base):
    __tablename__ = "cv_documents"
    __table_args__ = (
        Index("ix_cv_documents_path", "path"),
        Index("ix_cv_documents_status", "status"),
        Index("ix_cv_documents_updated_at", "updated_at"),
        Index("ix_cv_documents_session_id", "session_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    path: Mapped[str] = mapped_column(String(1024), unique=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # ondelete="SET NULL" + explicit name: matches the real production
    # constraint from migration 0011_analysis_sessions exactly -- this was
    # missing from the model (2026-09-14 schema-drift audit), which made
    # `alembic check`/autogenerate propose DROPPING and recreating this FK
    # WITHOUT "ON DELETE SET NULL", silently losing that cascade behavior
    # (deleting a session would then fail with a FK violation instead of
    # gracefully un-assigning affected CVs). Fixing the model to match
    # reality, not the other way around.
    session_id: Mapped[int | None] = mapped_column(
        ForeignKey("analysis_sessions.id", ondelete="SET NULL", name="fk_cv_documents_session"),
        nullable=True,
    )
    # On-demand deep structuring (Docling), separate from `status` (which
    # tracks the fast default extraction). None = never requested.
    structuring_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    structuring_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class JobDocument(Base):
    __tablename__ = "job_documents"
    __table_args__ = (
        Index("ix_job_documents_path", "path"),
        Index("ix_job_documents_status", "status"),
        Index("ix_job_documents_updated_at", "updated_at"),
        Index("ix_job_documents_session_id", "session_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    path: Mapped[str] = mapped_column(String(1024), unique=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # See the matching comment on CvDocument.session_id above.
    session_id: Mapped[int | None] = mapped_column(
        ForeignKey("analysis_sessions.id", ondelete="SET NULL", name="fk_job_documents_session"),
        nullable=True,
    )
    # On-demand deep structuring (Docling), separate from `status` (which
    # tracks the fast default extraction). None = never requested.
    structuring_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    structuring_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Recruiter-curated priority keywords for this offer, one per line.
    # Distinct from the auto-detected taxonomy skills: some of these terms
    # (acronyms like "LOD2", "DORA", "TRM") aren't in the skill dictionary
    # at all, so they're injected directly into required_skill_terms at
    # match time instead of going through find_skills() -- see
    # matcher.py::_priority_keyword_terms.
    priority_keywords: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Which pre-calibrated weight profile to score this job with (see
    # matcher._SCORING_PROFILES) -- None means the platform default
    # ("equilibre"). Deliberately a closed set of admin-validated presets,
    # not free-form weight values: letting a recruiter pick raw weights
    # directly recreates the exact risk that led to removing the old
    # /feedback/apply-weights endpoint (see feedback.py::compute_weights).
    scoring_profile: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class JobOffer(Base):
    __tablename__ = "job_offers"
    __table_args__ = (
        Index("ix_job_offers_status", "status"),
        Index("ix_job_offers_company", "company"),
        Index("ix_job_offers_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(255))
    meta_keywords: Mapped[list[str]] = mapped_column(JSON, default=list)
    contract_type: Mapped[str] = mapped_column(String(64))
    company: Mapped[str] = mapped_column(String(255))
    category: Mapped[str] = mapped_column(String(255))
    job_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    salary_max: Mapped[int | None] = mapped_column(nullable=True)
    languages: Mapped[list[str]] = mapped_column(JSON, default=list)
    description: Mapped[str] = mapped_column(Text)
    visual_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    paragraph: Mapped[str | None] = mapped_column(Text, nullable=True)
    skills: Mapped[list[str]] = mapped_column(JSON, default=list)
    strong_constraints: Mapped[list[str]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(32), default="draft")
    rendered_text: Mapped[str] = mapped_column(Text)
    rendered_html: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_document_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class AnalysisSession(Base):
    __tablename__ = "analysis_sessions"
    __table_args__ = (
        Index("ix_analysis_sessions_status", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="open")
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class MatchResult(Base):
    __tablename__ = "match_results"
    __table_args__ = (
        Index("ux_match_results_cv_job", "cv_id", "job_id", unique=True),
        Index("ix_match_results_score", "score"),
        Index("ix_match_results_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    cv_id: Mapped[int] = mapped_column(ForeignKey("cv_documents.id"))
    job_id: Mapped[int] = mapped_column(ForeignKey("job_documents.id"))
    score: Mapped[float] = mapped_column(Float)
    common_keywords: Mapped[str] = mapped_column(Text, nullable=True)
    # Component scores from the AI engine (v2)
    score_semantic: Mapped[float | None] = mapped_column(Float, nullable=True)
    score_skills: Mapped[float | None] = mapped_column(Float, nullable=True)
    score_experience: Mapped[float | None] = mapped_column(Float, nullable=True)
    score_education: Mapped[float | None] = mapped_column(Float, nullable=True)
    score_languages: Mapped[float | None] = mapped_column(Float, nullable=True)
    score_contract: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Recruiter-curated priority keywords (see JobDocument.priority_keywords),
    # a component distinct from score_skills -- see matcher.py's
    # _priority_keyword_score. NULL when the job has none set.
    score_priority_keywords: Mapped[float | None] = mapped_column(Float, nullable=True)
    priority_keywords_matched_count: Mapped[int | None] = mapped_column(nullable=True)
    priority_keywords_total: Mapped[int | None] = mapped_column(nullable=True)
    # The MISSING terms' actual names (comma-joined, like common_keywords) --
    # added so the match card can show which specific priority keywords a
    # candidate lacks without the cost of GET /matches/{id}/explain (a full
    # re-parse of both documents). The matched-count columns above predate
    # this and stayed cheap on purpose; this one is small by construction
    # (a job's priority keyword list is recruiter-curated and short, unlike
    # the full auto-detected skill set), so persisting the names here adds
    # negligible row size for a real UI win.
    priority_keywords_missing: Mapped[str | None] = mapped_column(Text, nullable=True)
    match_domain: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class MatchFeedback(Base):
    __tablename__ = "match_feedback"
    __table_args__ = (
        Index("ix_match_feedback_match_id", "match_id"),
        Index("ix_match_feedback_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("match_results.id"))
    decision: Mapped[str] = mapped_column(String(32))
    rating: Mapped[int | None] = mapped_column(nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Snapshot of what was actually compared/scored at feedback time. Needed
    # because deleting a CV or job file cascades to delete its MatchResult
    # rows (see deps.cleanup_removed_file), which would otherwise orphan
    # this feedback with no way to recover what CV/job/score it was about.
    cv_text_snapshot: Mapped[str | None] = mapped_column(Text, nullable=True)
    job_text_snapshot: Mapped[str | None] = mapped_column(Text, nullable=True)
    scores_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class ParserFeedback(Base):
    __tablename__ = "parser_feedback"
    __table_args__ = (
        Index("ix_parser_feedback_kind_doc", "kind", "doc_id"),
        Index("ix_parser_feedback_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(16))
    doc_id: Mapped[int] = mapped_column(nullable=False)
    corrections: Mapped[list[dict]] = mapped_column(JSON, default=list)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class CvEmbedding(Base):
    __tablename__ = "cv_embeddings"
    __table_args__ = (
        Index("ux_cv_embeddings_doc", "cv_id", unique=True),
        Index("ix_cv_embeddings_updated_at", "updated_at"),
        # Created directly (raw SQL, ivfflat isn't expressible via a plain
        # Index(...)) in migration 0004_embeddings_index, never declared
        # here (2026-09-14 schema-drift audit) -- alembic autogenerate saw
        # "DB has an index the model doesn't know about" and proposed
        # DROPPING this vector-similarity index, which would have quietly
        # killed the performance of every embedding_top_k nearest-neighbor
        # query in production. Declaring it here (no DB change, matches
        # the real index exactly) makes the model match reality instead.
        Index(
            "ix_cv_embeddings_vector", "embedding",
            postgresql_using="ivfflat",
            postgresql_ops={"embedding": "vector_cosine_ops"},
            postgresql_with={"lists": 100},
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    cv_id: Mapped[int] = mapped_column(ForeignKey("cv_documents.id"))
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    embedding: Mapped[list[float]] = mapped_column(Vector(768))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class JobEmbedding(Base):
    __tablename__ = "job_embeddings"
    __table_args__ = (
        Index("ux_job_embeddings_doc", "job_id", unique=True),
        Index("ix_job_embeddings_updated_at", "updated_at"),
        # See the matching comment on CvEmbedding above.
        Index(
            "ix_job_embeddings_vector", "embedding",
            postgresql_using="ivfflat",
            postgresql_ops={"embedding": "vector_cosine_ops"},
            postgresql_with={"lists": 100},
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("job_documents.id"))
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    embedding: Mapped[list[float]] = mapped_column(Vector(768))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

class LearnedWeights(Base):
    __tablename__ = "learned_weights"
    __table_args__ = (
        Index("ix_learned_weights_is_active", "is_active"),
        Index("ix_learned_weights_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    w_semantic: Mapped[float] = mapped_column(Float)
    w_skills: Mapped[float] = mapped_column(Float)
    w_experience: Mapped[float] = mapped_column(Float)
    w_education: Mapped[float] = mapped_column(Float)
    w_languages: Mapped[float] = mapped_column(Float)
    w_contract: Mapped[float] = mapped_column(Float)
    sample_count: Mapped[int] = mapped_column(Integer)
    accuracy: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
