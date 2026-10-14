"""PostgreSQL batch metadata and per-record outcomes; never stores credentials."""

from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class BatchJobRow(Base):
    __tablename__ = 'batch_jobs'
    __table_args__ = (
        UniqueConstraint('public_id', name='uq_batch_jobs_public_id'),
        CheckConstraint('processed = successful + failed AND processed <= total', name='ck_batch_job_progress'),
        CheckConstraint('total > 0 AND valid >= 0 AND invalid >= 0 AND valid + invalid = total AND processed >= 0 AND successful >= 0 AND failed >= 0', name='ck_batch_job_counts'),
        CheckConstraint("status IN ('PENDING','RUNNING','COMPLETED','PARTIAL_SUCCESS','FAILED')", name='ck_batch_job_status'),
        CheckConstraint("status NOT IN ('COMPLETED','PARTIAL_SUCCESS','FAILED') OR processed = total", name='ck_batch_job_terminal'),
        CheckConstraint("(status != 'COMPLETED' OR failed = 0) AND (status != 'FAILED' OR successful = 0) AND (status != 'PARTIAL_SUCCESS' OR (successful > 0 AND failed > 0))", name='ck_batch_job_outcomes'),
        Index('ix_batch_jobs_tenant_public', 'tenant_id', 'public_id'),
        Index('ix_batch_jobs_recovery', 'status', 'created_at'),
        Index('ix_batch_jobs_expiration', 'expires_at'),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    public_id: Mapped[str] = mapped_column(String(32), nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(100), nullable=False)
    options: Mapped[dict] = mapped_column(JSONB, nullable=False)
    business_type: Mapped[str] = mapped_column(String(20), nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    # Untrusted original filenames are intentionally not retained; never used as paths.
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    total: Mapped[int] = mapped_column(Integer, nullable=False)
    valid: Mapped[int] = mapped_column(Integer, nullable=False)
    invalid: Mapped[int] = mapped_column(Integer, nullable=False)
    skipped_blank_rows: Mapped[int] = mapped_column(Integer, nullable=False)
    processed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    successful: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_code: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class BatchRecordRow(Base):
    __tablename__ = 'batch_records'
    __table_args__ = (
        UniqueConstraint('job_id', 'feedback_id', name='uq_batch_records_feedback'),
        UniqueConstraint('job_id', 'position', name='uq_batch_records_position'),
        CheckConstraint("status IN ('PENDING','PROCESSING','SUCCESS','FAILED')", name='ck_batch_record_status'),
        CheckConstraint("(status = 'PROCESSING') = (claim_token IS NOT NULL AND claim_expires_at IS NOT NULL)", name='ck_batch_record_claim'),
        CheckConstraint("status = 'PROCESSING' OR (claim_token IS NULL AND claim_expires_at IS NULL)", name='ck_batch_record_cleared_claim'),
        Index('ix_batch_records_claim', 'job_id', 'status', 'claim_expires_at', 'position'),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey('batch_jobs.id', ondelete='CASCADE'), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    feedback_id: Mapped[str] = mapped_column(String(100), nullable=False)
    source_row: Mapped[int] = mapped_column(Integer, nullable=False)
    raw_text: Mapped[str | None] = mapped_column(Text)
    normalized_date: Mapped[date | None] = mapped_column(Date)
    date_status: Mapped[str] = mapped_column(String(20), nullable=False)
    validation_error: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    attempted: Mapped[bool] = mapped_column(nullable=False, default=False)
    error_code: Mapped[str | None] = mapped_column(String(100))
    sentiment: Mapped[str | None] = mapped_column(String(20))
    issue_category: Mapped[str | None] = mapped_column(String(40))
    urgency: Mapped[str | None] = mapped_column(String(20))
    aspects: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    summary: Mapped[str | None] = mapped_column(Text)
    suggested_next_step: Mapped[str | None] = mapped_column(Text)
    evidence_phrases: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    claim_token: Mapped[str | None] = mapped_column(String(32))
    claim_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
