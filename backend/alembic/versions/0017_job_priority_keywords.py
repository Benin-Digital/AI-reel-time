"""add priority_keywords to job_documents

Revision ID: 0017_job_priority_keywords
Revises: 0016_multilingual_embeddings
Create Date: 2026-09-10 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '0017_job_priority_keywords'
down_revision = '0016_multilingual_embeddings'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('job_documents', sa.Column('priority_keywords', sa.Text(), nullable=True))


def downgrade():
    op.drop_column('job_documents', 'priority_keywords')
