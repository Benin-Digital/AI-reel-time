"""add first and last names to users

Revision ID: 0006_add_user_names
Revises: 0005_users
Create Date: 2026-05-22 00:00:00
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0006_add_user_names"
down_revision = "0005_users"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("first_name", sa.String(length=255), nullable=True))
    op.add_column("users", sa.Column("last_name", sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "last_name")
    op.drop_column("users", "first_name")
