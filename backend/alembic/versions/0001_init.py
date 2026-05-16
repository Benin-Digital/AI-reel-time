"""init tables

Revision ID: 0001_init
Revises:
Create Date: 2026-05-16 00:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0001_init"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "event_logs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("source", sa.String(length=32), nullable=False, server_default="watcher"),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("path", sa.String(length=1024), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=True),
        sa.Column("observed_at", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_event_logs_created_at", "event_logs", ["created_at"], unique=False)
    op.create_index("ix_event_logs_path", "event_logs", ["path"], unique=False)

    op.create_table(
        "extracted_text",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("file_path", sa.String(length=1024), nullable=False, unique=True),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column("extracted_text", sa.Text(), nullable=True),
        sa.Column("extraction_method", sa.String(length=32), nullable=False, server_default="unknown"),
        sa.Column("extraction_success", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_extracted_text_updated_at", "extracted_text", ["updated_at"], unique=False)
    op.create_index("ix_extracted_text_content_hash", "extracted_text", ["content_hash"], unique=False)

    op.create_table(
        "score_results",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("cv_path", sa.String(length=1024), nullable=False),
        sa.Column("job_path", sa.String(length=1024), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("common_keywords", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_score_results_created_at", "score_results", ["created_at"], unique=False)
    op.create_index("ix_score_results_cv_path", "score_results", ["cv_path"], unique=False)
    op.create_index("ix_score_results_job_path", "score_results", ["job_path"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_score_results_job_path", table_name="score_results")
    op.drop_index("ix_score_results_cv_path", table_name="score_results")
    op.drop_index("ix_score_results_created_at", table_name="score_results")
    op.drop_table("score_results")

    op.drop_index("ix_extracted_text_content_hash", table_name="extracted_text")
    op.drop_index("ix_extracted_text_updated_at", table_name="extracted_text")
    op.drop_table("extracted_text")

    op.drop_index("ix_event_logs_path", table_name="event_logs")
    op.drop_index("ix_event_logs_created_at", table_name="event_logs")
    op.drop_table("event_logs")
