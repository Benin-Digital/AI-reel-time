"""add snapshot columns to match_feedback

Revision ID: 0014_match_feedback_snapshots
Revises: 0013_learned_weights
Create Date: 2026-08-28

Purely additive: three new nullable columns on an existing table, no data
migration, safe to run without downtime.
"""
import sqlalchemy as sa

from alembic import op

revision = '0014_match_feedback_snapshots'
down_revision = '0013_learned_weights'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('match_feedback', sa.Column('cv_text_snapshot', sa.Text(), nullable=True))
    op.add_column('match_feedback', sa.Column('job_text_snapshot', sa.Text(), nullable=True))
    op.add_column('match_feedback', sa.Column('scores_snapshot', sa.JSON(), nullable=True))


def downgrade():
    op.drop_column('match_feedback', 'scores_snapshot')
    op.drop_column('match_feedback', 'job_text_snapshot')
    op.drop_column('match_feedback', 'cv_text_snapshot')
