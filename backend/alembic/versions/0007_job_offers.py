"""add structured job offers

Revision ID: 0007_job_offers
Revises: 0006_add_user_names
Create Date: 2026-05-24 00:00:00
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0007_job_offers"
down_revision = "0006_add_user_names"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "job_offers",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("meta_keywords", sa.JSON(), nullable=False),
        sa.Column("department", sa.String(length=255), nullable=True),
        sa.Column("contract_type", sa.String(length=64), nullable=False),
        sa.Column("company", sa.String(length=255), nullable=False),
        sa.Column("category", sa.String(length=255), nullable=False),
        sa.Column("job_type", sa.String(length=64), nullable=True),
        sa.Column("salary_min", sa.Integer(), nullable=True),
        sa.Column("salary_max", sa.Integer(), nullable=True),
        sa.Column("languages", sa.JSON(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("visual_code", sa.Text(), nullable=True),
        sa.Column("paragraph", sa.Text(), nullable=True),
        sa.Column("skills", sa.JSON(), nullable=False),
        sa.Column("strong_constraints", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("rendered_text", sa.Text(), nullable=False),
        sa.Column("rendered_html", sa.Text(), nullable=True),
        sa.Column("published_document_path", sa.String(length=1024), nullable=True),
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
    op.create_index("ix_job_offers_status", "job_offers", ["status"])
    op.create_index("ix_job_offers_company", "job_offers", ["company"])
    op.create_index("ix_job_offers_created_at", "job_offers", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_job_offers_created_at", table_name="job_offers")
    op.drop_index("ix_job_offers_company", table_name="job_offers")
    op.drop_index("ix_job_offers_status", table_name="job_offers")
    op.drop_table("job_offers")
