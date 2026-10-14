"""Normalize job source/business fields and strengthen outcome/claim invariants."""
from alembic import op
import sqlalchemy as sa

revision = 't09_batch_v2'
down_revision = 't09_batch_v1'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('batch_jobs',sa.Column('business_type',sa.String(20),nullable=True))
    op.add_column('batch_jobs',sa.Column('source',sa.String(64),nullable=True))
    op.execute("UPDATE batch_jobs SET business_type=COALESCE(options->>'business_type','general'), source=COALESCE(options->>'source','file_upload'), options=options-'business_type'-'source'")
    op.alter_column('batch_jobs','business_type',nullable=False)
    op.alter_column('batch_jobs','source',nullable=False)
    op.create_check_constraint('ck_batch_job_outcomes','batch_jobs',"(status != 'COMPLETED' OR failed = 0) AND (status != 'FAILED' OR successful = 0) AND (status != 'PARTIAL_SUCCESS' OR (successful > 0 AND failed > 0))")
    op.create_check_constraint('ck_batch_record_cleared_claim','batch_records',"status = 'PROCESSING' OR (claim_token IS NULL AND claim_expires_at IS NULL)")


def downgrade():
    raise RuntimeError('Destructive batch downgrades require a separately reviewed migration.')
