"""add embeddings tables

Revision ID: 0003_embeddings
Revises: 0002_documents_and_matches
Create Date: 2026-05-17 00:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector


revision = "0003_embeddings"
down_revision = "0002_documents_and_matches"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "cv_embeddings",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("cv_id", sa.Integer(), sa.ForeignKey("cv_documents.id"), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column("embedding", Vector(384), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ux_cv_embeddings_doc", "cv_embeddings", ["cv_id"], unique=True)
    op.create_index("ix_cv_embeddings_updated_at", "cv_embeddings", ["updated_at"], unique=False)

    op.create_table(
        "job_embeddings",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("job_id", sa.Integer(), sa.ForeignKey("job_documents.id"), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column("embedding", Vector(384), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ux_job_embeddings_doc", "job_embeddings", ["job_id"], unique=True)
    op.create_index("ix_job_embeddings_updated_at", "job_embeddings", ["updated_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_job_embeddings_updated_at", table_name="job_embeddings")
    op.drop_index("ux_job_embeddings_doc", table_name="job_embeddings")
    op.drop_table("job_embeddings")

    op.drop_index("ix_cv_embeddings_updated_at", table_name="cv_embeddings")
    op.drop_index("ux_cv_embeddings_doc", table_name="cv_embeddings")
    op.drop_table("cv_embeddings")
