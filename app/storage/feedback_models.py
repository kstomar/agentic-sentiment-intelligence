"""Durable ingestion inputs and the original validated classifier outcome."""

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Index, Integer, LargeBinary, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.storage.batch_models import Base


class FeedbackEventRow(Base):
    __tablename__ = "feedback_events"
    __table_args__ = (
        UniqueConstraint("tenant_id", "delivery_id", name="uq_feedback_event_owner_delivery"),
        CheckConstraint("kind IN ('webhook','direct')", name="ck_feedback_event_kind"),
        CheckConstraint("status IN ('ACCEPTED','PROCESSING','COMPLETED','FAILED')", name="ck_feedback_event_status"),
        CheckConstraint("(kind = 'webhook' AND integration_id IS NOT NULL AND digest IS NOT NULL AND event_type = 'customer.feedback.created') OR (kind = 'direct' AND integration_id IS NULL AND digest IS NULL AND event_type IS NULL)", name="ck_feedback_event_origin"),
        CheckConstraint("(status = 'COMPLETED' AND analysis IS NOT NULL AND error_code IS NULL AND completed_at IS NOT NULL) OR (status = 'FAILED' AND analysis IS NULL AND error_code IS NOT NULL AND completed_at IS NOT NULL) OR (status IN ('ACCEPTED','PROCESSING') AND analysis IS NULL AND error_code IS NULL AND completed_at IS NULL)", name="ck_feedback_event_outcome"),
        Index("ix_feedback_event_status", "status", "created_at"),
        Index("ix_feedback_event_expiry", "expires_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(100), nullable=False)
    delivery_id: Mapped[str] = mapped_column(String(100), nullable=False)
    integration_id: Mapped[str | None] = mapped_column(String(100))
    kind: Mapped[str] = mapped_column(String(10), nullable=False)
    event_type: Mapped[str | None] = mapped_column(String(40))
    digest: Mapped[bytes | None] = mapped_column(LargeBinary(32))
    operation_id: Mapped[str] = mapped_column(String(32), nullable=False)
    feedback: Mapped[dict] = mapped_column(JSONB, nullable=False)
    # SQL NULL (not JSON null) is important for outcome constraints.
    analysis: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
