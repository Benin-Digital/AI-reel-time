"""add on-demand structuring status/error to cv/job documents

Revision ID: 0015_document_structuring_status
Revises: 0014_match_feedback_snapshots
Create Date: 2026-09-08 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '0015_document_structuring_status'
down_revision = '0014_match_feedback_snapshots'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('cv_documents', sa.Column('structuring_status', sa.String(length=32), nullable=True))
    op.add_column('cv_documents', sa.Column('structuring_error', sa.Text(), nullable=True))
    op.add_column('job_documents', sa.Column('structuring_status', sa.String(length=32), nullable=True))
    op.add_column('job_documents', sa.Column('structuring_error', sa.Text(), nullable=True))


def downgrade():
    op.drop_column('job_documents', 'structuring_error')
    op.drop_column('job_documents', 'structuring_status')
    op.drop_column('cv_documents', 'structuring_error')
    op.drop_column('cv_documents', 'structuring_status')
