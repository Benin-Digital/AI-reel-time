"""create parser_feedback table

Revision ID: 0009_parser_feedback
Revises: 0008_match_feedback
Create Date: 2026-05-25 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '0009_parser_feedback'
down_revision = '0008_match_feedback'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'parser_feedback',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('kind', sa.String(length=16), nullable=False),
        sa.Column('doc_id', sa.Integer(), nullable=False),
        sa.Column('corrections', sa.JSON(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    op.create_index('ix_parser_feedback_kind_doc', 'parser_feedback', ['kind', 'doc_id'])
    op.create_index('ix_parser_feedback_created_at', 'parser_feedback', ['created_at'])


def downgrade():
    op.drop_index('ix_parser_feedback_created_at', table_name='parser_feedback')
    op.drop_index('ix_parser_feedback_kind_doc', table_name='parser_feedback')
    op.drop_table('parser_feedback')
*** End Patch