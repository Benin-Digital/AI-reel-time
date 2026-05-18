"""add vector indexes

Revision ID: 0004_embeddings_index
Revises: 0003_embeddings
Create Date: 2026-05-18 00:00:00
"""
from __future__ import annotations

from alembic import op


revision = "0004_embeddings_index"
down_revision = "0003_embeddings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_cv_embeddings_vector ON cv_embeddings "
        "USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_job_embeddings_vector ON job_embeddings "
        "USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_job_embeddings_vector")
    op.execute("DROP INDEX IF EXISTS ix_cv_embeddings_vector")
