"""add scoring_profile to job_documents

Revision ID: 0019_job_scoring_profile
Revises: 0018_match_priority_keywords
Create Date: 2026-09-14 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '0019_job_scoring_profile'
down_revision = '0018_match_priority_keywords'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('job_documents', sa.Column('scoring_profile', sa.String(length=32), nullable=True))


def downgrade():
    op.drop_column('job_documents', 'scoring_profile')
