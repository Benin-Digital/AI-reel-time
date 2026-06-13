"""add learned_weights table

Revision ID: 0013_learned_weights
Revises: 0012_match_component_scores
Create Date: 2026-06-13
"""
from alembic import op
import sqlalchemy as sa

revision = '0013_learned_weights'
down_revision = '0012_match_component_scores'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'learned_weights',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('w_semantic',   sa.Float(), nullable=False),
        sa.Column('w_skills',     sa.Float(), nullable=False),
        sa.Column('w_experience', sa.Float(), nullable=False),
        sa.Column('w_education',  sa.Float(), nullable=False),
        sa.Column('w_languages',  sa.Float(), nullable=False),
        sa.Column('w_contract',   sa.Float(), nullable=False),
        sa.Column('sample_count', sa.Integer(), nullable=False),
        sa.Column('accuracy',     sa.Float(), nullable=True),
        sa.Column('is_active',    sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_by',   sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('created_at',   sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_learned_weights_is_active', 'learned_weights', ['is_active'])
    op.create_index('ix_learned_weights_created_at', 'learned_weights', ['created_at'])


def downgrade() -> None:
    op.drop_index('ix_learned_weights_created_at', table_name='learned_weights')
    op.drop_index('ix_learned_weights_is_active', table_name='learned_weights')
    op.drop_table('learned_weights')
