"""Durable pseudonymous Gmail message identities, retry state and fenced claims only."""
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.storage.batch_models import Base


class GmailMessageRow(Base):
    __tablename__ = 'gmail_message_tracking'
    __table_args__ = (
        UniqueConstraint('tenant_id', 'mailbox_key', 'message_id', name='uq_gmail_message_identity'),
        CheckConstraint("status IN ('PENDING','RESERVED','PROCESSING','SUCCEEDED','FAILED')", name='ck_gmail_tracking_status'),
        CheckConstraint('attempts >= 0', name='ck_gmail_tracking_attempts'),
        CheckConstraint("(status IN ('RESERVED','PROCESSING') AND claim_token IS NOT NULL AND claim_expires_at IS NOT NULL) OR (status NOT IN ('RESERVED','PROCESSING') AND claim_token IS NULL AND claim_expires_at IS NULL)", name='ck_gmail_tracking_claim'),
        CheckConstraint("status != 'PROCESSING' OR (attempts > 0 AND last_attempt_at IS NOT NULL)", name='ck_gmail_tracking_started'),
        CheckConstraint("status != 'SUCCEEDED' OR (attempts > 0 AND completed_at IS NOT NULL AND last_error IS NULL AND retry_at IS NULL)", name='ck_gmail_tracking_success'),
        Index('ix_gmail_tracking_expiry', 'status', 'claim_expires_at'),
        Index('ix_gmail_tracking_retry', 'tenant_id', 'mailbox_key', 'status', 'retry_at'),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(100), nullable=False)
    mailbox_key: Mapped[str] = mapped_column(String(64), nullable=False)
    message_id: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    claim_token: Mapped[str | None] = mapped_column(String(32))
    claim_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    job_id: Mapped[str | None] = mapped_column(String(32))
    last_error: Mapped[str | None] = mapped_column(String(100))
    retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
