"""switch bi-encoder embeddings to a multilingual model (384 -> 768 dim)

all-MiniLM-L6-v2 (384 dim) is trained mostly on English and was inconsistent
with esco_taxonomy.py, which already uses intfloat/multilingual-e5-base
(768 dim) for skill-to-ESCO linking on the same French text. This migration
only reshapes the storage: stored vectors were computed under the old model
and are meaningless in the new one's vector space, so existing rows are
truncated rather than cast. Run `POST /maintenance/backfill-embeddings`
after deploying to repopulate them with the new model.

Revision ID: 0016_multilingual_embeddings
Revises: 0015_document_structuring_status
Create Date: 2026-09-09 00:00:00
"""
from __future__ import annotations

from alembic import op

revision = "0016_multilingual_embeddings"
down_revision = "0015_document_structuring_status"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_cv_embeddings_vector")
    op.execute("DROP INDEX IF EXISTS ix_job_embeddings_vector")

    op.execute("TRUNCATE TABLE cv_embeddings, job_embeddings")

    op.execute("ALTER TABLE cv_embeddings ALTER COLUMN embedding TYPE vector(768)")
    op.execute("ALTER TABLE job_embeddings ALTER COLUMN embedding TYPE vector(768)")

    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_cv_embeddings_vector ON cv_embeddings "
        "USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_job_embeddings_vector ON job_embeddings "
        "USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_cv_embeddings_vector")
    op.execute("DROP INDEX IF EXISTS ix_job_embeddings_vector")

    op.execute("TRUNCATE TABLE cv_embeddings, job_embeddings")

    op.execute("ALTER TABLE cv_embeddings ALTER COLUMN embedding TYPE vector(384)")
    op.execute("ALTER TABLE job_embeddings ALTER COLUMN embedding TYPE vector(384)")

    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_cv_embeddings_vector ON cv_embeddings "
        "USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_job_embeddings_vector ON job_embeddings "
        "USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"
    )
