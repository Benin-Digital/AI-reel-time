"""add created_by_user_id to analysis_sessions

Revision ID: 0020_analysis_session_owner
Revises: 69fd6118fc1d
Create Date: 2026-09-24 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '0020_analysis_session_owner'
down_revision = '69fd6118fc1d'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'analysis_sessions',
        sa.Column('created_by_user_id', sa.Integer(), nullable=True),
    )
    op.create_index(
        'ix_analysis_sessions_created_by_user_id',
        'analysis_sessions',
        ['created_by_user_id'],
    )
    op.create_foreign_key(
        'fk_analysis_sessions_created_by_user_id_users',
        'analysis_sessions',
        'users',
        ['created_by_user_id'],
        ['id'],
        ondelete='SET NULL',
    )


def downgrade():
    op.drop_constraint(
        'fk_analysis_sessions_created_by_user_id_users',
        'analysis_sessions',
        type_='foreignkey',
    )
    op.drop_index('ix_analysis_sessions_created_by_user_id', table_name='analysis_sessions')
    op.drop_column('analysis_sessions', 'created_by_user_id')
