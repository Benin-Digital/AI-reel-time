"""add missing_skills to match_results

Revision ID: 0022_match_missing_skills
Revises: 0021_document_owner
Create Date: 2026-10-05 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '0022_match_missing_skills'
down_revision = '0021_document_owner'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('match_results', sa.Column('missing_skills', sa.Text(), nullable=True))


def downgrade():
    op.drop_column('match_results', 'missing_skills')
