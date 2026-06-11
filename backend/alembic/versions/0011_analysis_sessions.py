"""add analysis session and document session references

Revision ID: 0011_analysis_sessions
Revises: 0010_add_parsed_profile
Create Date: 2026-06-04 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '0011_analysis_sessions'
down_revision = '0010_add_parsed_profile'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'analysis_sessions',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=32), nullable=False, server_default='open'),
        sa.Column('closed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    op.create_index('ix_analysis_sessions_status', 'analysis_sessions', ['status'])
    op.add_column('cv_documents', sa.Column('session_id', sa.Integer(), nullable=True))
    op.add_column('job_documents', sa.Column('session_id', sa.Integer(), nullable=True))
    op.create_foreign_key(
        'fk_cv_documents_session', 'cv_documents', 'analysis_sessions', ['session_id'], ['id'], ondelete='SET NULL'
    )
    op.create_foreign_key(
        'fk_job_documents_session', 'job_documents', 'analysis_sessions', ['session_id'], ['id'], ondelete='SET NULL'
    )
    op.create_index('ix_cv_documents_session_id', 'cv_documents', ['session_id'])
    op.create_index('ix_job_documents_session_id', 'job_documents', ['session_id'])


def downgrade():
    op.drop_index('ix_job_documents_session_id', table_name='job_documents')
    op.drop_constraint('fk_job_documents_session', 'job_documents', type_='foreignkey')
    op.drop_column('job_documents', 'session_id')
    op.drop_index('ix_cv_documents_session_id', table_name='cv_documents')
    op.drop_constraint('fk_cv_documents_session', 'cv_documents', type_='foreignkey')
    op.drop_column('cv_documents', 'session_id')
    op.drop_index('ix_analysis_sessions_status', table_name='analysis_sessions')
    op.drop_table('analysis_sessions')
