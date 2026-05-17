"""add document tables

Revision ID: 0002_documents_and_matches
Revises: 0001_init
Create Date: 2026-05-17 00:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0002_documents_and_matches"
down_revision = "0001_init"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cv_documents",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("path", sa.String(length=1024), nullable=False, unique=True),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_cv_documents_path", "cv_documents", ["path"], unique=False)
    op.create_index("ix_cv_documents_status", "cv_documents", ["status"], unique=False)
    op.create_index("ix_cv_documents_updated_at", "cv_documents", ["updated_at"], unique=False)

    op.create_table(
        "job_documents",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("path", sa.String(length=1024), nullable=False, unique=True),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_job_documents_path", "job_documents", ["path"], unique=False)
    op.create_index("ix_job_documents_status", "job_documents", ["status"], unique=False)
    op.create_index("ix_job_documents_updated_at", "job_documents", ["updated_at"], unique=False)

    op.create_table(
        "match_results",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("cv_id", sa.Integer(), sa.ForeignKey("cv_documents.id"), nullable=False),
        sa.Column("job_id", sa.Integer(), sa.ForeignKey("job_documents.id"), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("common_keywords", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index(
        "ux_match_results_cv_job",
        "match_results",
        ["cv_id", "job_id"],
        unique=True,
    )
    op.create_index("ix_match_results_score", "match_results", ["score"], unique=False)
    op.create_index("ix_match_results_created_at", "match_results", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_match_results_created_at", table_name="match_results")
    op.drop_index("ix_match_results_score", table_name="match_results")
    op.drop_index("ux_match_results_cv_job", table_name="match_results")
    op.drop_table("match_results")

    op.drop_index("ix_job_documents_updated_at", table_name="job_documents")
    op.drop_index("ix_job_documents_status", table_name="job_documents")
    op.drop_index("ix_job_documents_path", table_name="job_documents")
    op.drop_table("job_documents")

    op.drop_index("ix_cv_documents_updated_at", table_name="cv_documents")
    op.drop_index("ix_cv_documents_status", table_name="cv_documents")
    op.drop_index("ix_cv_documents_path", table_name="cv_documents")
    op.drop_table("cv_documents")
