"""add user_id to cv_documents, job_documents, job_offers, analysis_sessions

Revision ID: 0015_user_data_isolation
Revises: 0014_match_feedback_snapshots
Create Date: 2026-09-02

Purely additive: four nullable FK columns, one per table. Existing rows keep
user_id = NULL; admins see all rows regardless of user_id.
"""
import sqlalchemy as sa
from alembic import op

revision = "0015_user_data_isolation"
down_revision = "0014_match_feedback_snapshots"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("cv_documents", sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True))
    op.create_index("ix_cv_documents_user_id", "cv_documents", ["user_id"])

    op.add_column("job_documents", sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True))
    op.create_index("ix_job_documents_user_id", "job_documents", ["user_id"])

    op.add_column("job_offers", sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True))
    op.create_index("ix_job_offers_user_id", "job_offers", ["user_id"])

    op.add_column("analysis_sessions", sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True))
    op.create_index("ix_analysis_sessions_user_id", "analysis_sessions", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_analysis_sessions_user_id", "analysis_sessions")
    op.drop_column("analysis_sessions", "user_id")

    op.drop_index("ix_job_offers_user_id", "job_offers")
    op.drop_column("job_offers", "user_id")

    op.drop_index("ix_job_documents_user_id", "job_documents")
    op.drop_column("job_documents", "user_id")

    op.drop_index("ix_cv_documents_user_id", "cv_documents")
    op.drop_column("cv_documents", "user_id")
