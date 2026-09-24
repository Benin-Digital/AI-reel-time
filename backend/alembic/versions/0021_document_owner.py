"""add created_by_user_id to cv_documents and job_documents

Revision ID: 0021_document_owner
Revises: 0020_analysis_session_owner
Create Date: 2026-09-24 01:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '0021_document_owner'
down_revision = '0020_analysis_session_owner'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('cv_documents', sa.Column('created_by_user_id', sa.Integer(), nullable=True))
    op.create_index(
        'ix_cv_documents_created_by_user_id', 'cv_documents', ['created_by_user_id'],
    )
    op.create_foreign_key(
        'fk_cv_documents_created_by_user_id_users',
        'cv_documents', 'users', ['created_by_user_id'], ['id'], ondelete='SET NULL',
    )

    op.add_column('job_documents', sa.Column('created_by_user_id', sa.Integer(), nullable=True))
    op.create_index(
        'ix_job_documents_created_by_user_id', 'job_documents', ['created_by_user_id'],
    )
    op.create_foreign_key(
        'fk_job_documents_created_by_user_id_users',
        'job_documents', 'users', ['created_by_user_id'], ['id'], ondelete='SET NULL',
    )


def downgrade():
    op.drop_constraint('fk_job_documents_created_by_user_id_users', 'job_documents', type_='foreignkey')
    op.drop_index('ix_job_documents_created_by_user_id', table_name='job_documents')
    op.drop_column('job_documents', 'created_by_user_id')

    op.drop_constraint('fk_cv_documents_created_by_user_id_users', 'cv_documents', type_='foreignkey')
    op.drop_index('ix_cv_documents_created_by_user_id', table_name='cv_documents')
    op.drop_column('cv_documents', 'created_by_user_id')
