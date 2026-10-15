"""Persist original feedback, validated analysis and tenant-scoped delivery identity."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "feedback_results_v1"
down_revision = "t09_batch_v2"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("feedback_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.String(100), nullable=False),
        sa.Column("delivery_id", sa.String(100), nullable=False),
        sa.Column("integration_id", sa.String(100)),
        sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("event_type", sa.String(40)),
        sa.Column("digest", sa.LargeBinary(32)),
        sa.Column("operation_id", sa.String(32), nullable=False),
        sa.Column("feedback", postgresql.JSONB(), nullable=False),
        sa.Column("analysis", postgresql.JSONB(none_as_null=True)),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("error_code", sa.String(100)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("tenant_id", "delivery_id", name="uq_feedback_event_owner_delivery"),
        sa.CheckConstraint("kind IN ('webhook','direct')", name="ck_feedback_event_kind"),
        sa.CheckConstraint("status IN ('ACCEPTED','PROCESSING','COMPLETED','FAILED')", name="ck_feedback_event_status"),
        sa.CheckConstraint("(kind = 'webhook' AND integration_id IS NOT NULL AND digest IS NOT NULL AND event_type = 'customer.feedback.created') OR (kind = 'direct' AND integration_id IS NULL AND digest IS NULL AND event_type IS NULL)", name="ck_feedback_event_origin"),
        sa.CheckConstraint("(status = 'COMPLETED' AND analysis IS NOT NULL AND error_code IS NULL AND completed_at IS NOT NULL) OR (status = 'FAILED' AND analysis IS NULL AND error_code IS NOT NULL AND completed_at IS NOT NULL) OR (status IN ('ACCEPTED','PROCESSING') AND analysis IS NULL AND error_code IS NULL AND completed_at IS NULL)", name="ck_feedback_event_outcome"),
    )
    op.create_index("ix_feedback_event_status", "feedback_events", ["status", "created_at"])
    op.create_index("ix_feedback_event_expiry", "feedback_events", ["expires_at"])


def downgrade():
    raise RuntimeError("Destructive ingestion downgrades require a separately reviewed migration.")
