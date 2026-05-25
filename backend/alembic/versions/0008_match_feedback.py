"""add match feedback

Revision ID: 0008_match_feedback
Revises: 0007_job_offers
Create Date: 2026-05-25 00:00:00
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0008_match_feedback"
down_revision = "0007_job_offers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "match_feedback",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("match_id", sa.Integer(), sa.ForeignKey("match_results.id"), nullable=False),
        sa.Column("decision", sa.String(length=32), nullable=False),
        sa.Column("rating", sa.Integer(), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_match_feedback_match_id", "match_feedback", ["match_id"])
    op.create_index("ix_match_feedback_created_at", "match_feedback", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_match_feedback_created_at", table_name="match_feedback")
    op.drop_index("ix_match_feedback_match_id", table_name="match_feedback")
    op.drop_table("match_feedback")
