"""add priority-keywords score columns to match_results

Revision ID: 0018_match_priority_keywords
Revises: 0017_job_priority_keywords
Create Date: 2026-09-10 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '0018_match_priority_keywords'
down_revision = '0017_job_priority_keywords'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('match_results', sa.Column('score_priority_keywords', sa.Float(), nullable=True))
    op.add_column('match_results', sa.Column('priority_keywords_matched_count', sa.Integer(), nullable=True))
    op.add_column('match_results', sa.Column('priority_keywords_total', sa.Integer(), nullable=True))


def downgrade():
    op.drop_column('match_results', 'priority_keywords_total')
    op.drop_column('match_results', 'priority_keywords_matched_count')
    op.drop_column('match_results', 'score_priority_keywords')
