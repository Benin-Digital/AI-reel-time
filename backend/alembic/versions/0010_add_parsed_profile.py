"""add parsed_profile columns to extracted_text

Revision ID: 0010_add_parsed_profile
Revises: 0009_parser_feedback
Create Date: 2026-05-29 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '0010_add_parsed_profile'
down_revision = '0009_parser_feedback'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('extracted_text', sa.Column('parsed_profile', sa.JSON(), nullable=True))
    op.add_column('extracted_text', sa.Column('parsed_profile_hash', sa.String(length=64), nullable=True))
    op.add_column('extracted_text', sa.Column('parsed_profile_updated_at', sa.DateTime(timezone=True), nullable=True))
    op.create_index('ix_extracted_text_parsed_profile_hash', 'extracted_text', ['parsed_profile_hash'])


def downgrade():
    op.drop_index('ix_extracted_text_parsed_profile_hash', table_name='extracted_text')
    op.drop_column('extracted_text', 'parsed_profile_updated_at')
    op.drop_column('extracted_text', 'parsed_profile_hash')
    op.drop_column('extracted_text', 'parsed_profile')
