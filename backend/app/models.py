from datetime import datetime

from sqlalchemy import DateTime, Float, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class EventLog(Base):
    __tablename__ = "event_logs"

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

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    file_path: Mapped[str] = mapped_column(String(1024), unique=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=True)
    extracted_text: Mapped[str] = mapped_column(Text, nullable=True)
    extraction_method: Mapped[str] = mapped_column(
        String(32), default="unknown"
    )  # "pdf", "docx", "txt", "ocr"
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

