"""add component score columns to match_results

Revision ID: 0012_match_component_scores
Revises: 0011_analysis_sessions
Create Date: 2026-06-11 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = '0012_match_component_scores'
down_revision = '0011_analysis_sessions'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('match_results', sa.Column('score_semantic', sa.Float(), nullable=True))
    op.add_column('match_results', sa.Column('score_skills', sa.Float(), nullable=True))
    op.add_column('match_results', sa.Column('score_experience', sa.Float(), nullable=True))
    op.add_column('match_results', sa.Column('score_education', sa.Float(), nullable=True))
    op.add_column('match_results', sa.Column('score_languages', sa.Float(), nullable=True))
    op.add_column('match_results', sa.Column('score_contract', sa.Float(), nullable=True))
    op.add_column('match_results', sa.Column('match_domain', sa.String(length=32), nullable=True))


def downgrade():
    op.drop_column('match_results', 'match_domain')
    op.drop_column('match_results', 'score_contract')
    op.drop_column('match_results', 'score_languages')
    op.drop_column('match_results', 'score_education')
    op.drop_column('match_results', 'score_experience')
    op.drop_column('match_results', 'score_skills')
    op.drop_column('match_results', 'score_semantic')
