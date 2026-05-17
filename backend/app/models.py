from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, String, Text, func
from pgvector.sqlalchemy import Vector
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


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
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    file_path: Mapped[str] = mapped_column(String(1024), unique=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=True)
    extracted_text: Mapped[str] = mapped_column(Text, nullable=True)
    extraction_method: Mapped[str] = mapped_column(String(32), default="unknown")
    extraction_success: Mapped[bool] = mapped_column(default=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
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
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    path: Mapped[str] = mapped_column(String(1024), unique=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
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
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    path: Mapped[str] = mapped_column(String(1024), unique=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
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
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    cv_id: Mapped[int] = mapped_column(ForeignKey("cv_documents.id"))
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    embedding: Mapped[list[float]] = mapped_column(Vector(384))
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
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("job_documents.id"))
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    embedding: Mapped[list[float]] = mapped_column(Vector(384))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )