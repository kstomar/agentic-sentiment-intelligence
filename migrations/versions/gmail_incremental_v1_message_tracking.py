"""Durable tenant/mailbox/message state; no OAuth tokens, bodies or analysis."""
from alembic import op
import sqlalchemy as sa

revision = 'gmail_incremental_v1'
down_revision = 'feedback_results_v1'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('gmail_message_tracking',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('tenant_id', sa.String(100), nullable=False),
        sa.Column('mailbox_key', sa.String(64), nullable=False),
        sa.Column('message_id', sa.String(128), nullable=False),
        sa.Column('status', sa.String(12), nullable=False),
        sa.Column('attempts', sa.Integer(), nullable=False),
        sa.Column('claim_token', sa.String(32)),
        sa.Column('claim_expires_at', sa.DateTime(timezone=True)),
        sa.Column('job_id', sa.String(32)),
        sa.Column('last_error', sa.String(100)),
        sa.Column('retry_at', sa.DateTime(timezone=True)),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_attempt_at', sa.DateTime(timezone=True)),
        sa.Column('completed_at', sa.DateTime(timezone=True)),
        sa.UniqueConstraint('tenant_id','mailbox_key','message_id', name='uq_gmail_message_identity'),
        sa.CheckConstraint("status IN ('PENDING','RESERVED','PROCESSING','SUCCEEDED','FAILED')", name='ck_gmail_tracking_status'),
        sa.CheckConstraint('attempts >= 0', name='ck_gmail_tracking_attempts'),
        sa.CheckConstraint("(status IN ('RESERVED','PROCESSING') AND claim_token IS NOT NULL AND claim_expires_at IS NOT NULL) OR (status NOT IN ('RESERVED','PROCESSING') AND claim_token IS NULL AND claim_expires_at IS NULL)", name='ck_gmail_tracking_claim'),
        sa.CheckConstraint("status != 'PROCESSING' OR (attempts > 0 AND last_attempt_at IS NOT NULL)", name='ck_gmail_tracking_started'),
        sa.CheckConstraint("status != 'SUCCEEDED' OR (attempts > 0 AND completed_at IS NOT NULL AND last_error IS NULL AND retry_at IS NULL)", name='ck_gmail_tracking_success'),
    )
    op.create_index('ix_gmail_tracking_expiry','gmail_message_tracking',['status','claim_expires_at'])
    op.create_index('ix_gmail_tracking_retry','gmail_message_tracking',['tenant_id','mailbox_key','status','retry_at'])


def downgrade():
    raise RuntimeError('Destructive Gmail ledger downgrades require a separately reviewed migration.')
