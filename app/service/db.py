"""PostgreSQL tables and the duplicate-claim query."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from functools import lru_cache

from sqlalchemy import JSON, DateTime, Integer, String, Text, create_engine, insert, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from app.service.config import get_settings

# Lifecycle: queued -> processing -> approved | review | rejected | failed.
# A person can then move review -> approved | rejected.
STATUSES = ("queued", "processing", "approved", "review", "rejected", "failed")


def _now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    sha256: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    filename: Mapped[str] = mapped_column(String(255))
    storage_key: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(16), index=True, default="queued")
    machine_decision: Mapped[str | None] = mapped_column(String(16))
    reasons: Mapped[list] = mapped_column(JSON, default=list)
    extracted: Mapped[dict | None] = mapped_column(JSON)
    source: Mapped[str | None] = mapped_column(String(8))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    processing_ms: Mapped[int | None] = mapped_column(Integer)
    correlation_id: Mapped[str | None] = mapped_column(String(64))
    review_action: Mapped[str | None] = mapped_column(String(16))
    review_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class InvoiceKey(Base):
    """One row per (vendor, invoice number): the first document that claimed it."""

    __tablename__ = "invoice_keys"

    vendor: Mapped[str] = mapped_column(String(255), primary_key=True)
    invoice_number: Mapped[str] = mapped_column(String(64), primary_key=True)
    document_id: Mapped[str] = mapped_column(String(36))


@lru_cache
def get_engine() -> Engine:
    return create_engine(get_settings().database_url, pool_pre_ping=True)


@lru_cache
def get_sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(get_engine(), expire_on_commit=False)


def init_db(engine: Engine | None = None) -> None:
    Base.metadata.create_all(engine or get_engine())


def claim_invoice_key(session: Session, key: tuple[str, str], document_id: str) -> bool:
    """True if this document owns the key (first time, or a retry of the same document).

    INSERT ... ON CONFLICT DO NOTHING is atomic in PostgreSQL, so two workers processing two
    copies of the same invoice at the same moment cannot both win.
    """
    vendor, number = key
    values = {"vendor": vendor, "invoice_number": number, "document_id": document_id}
    if session.bind is not None and session.bind.dialect.name == "postgresql":
        session.execute(pg_insert(InvoiceKey).values(**values).on_conflict_do_nothing())
    elif session.get(InvoiceKey, (vendor, number)) is None:
        session.execute(insert(InvoiceKey).values(**values))
    owner = session.scalar(
        select(InvoiceKey.document_id).where(
            InvoiceKey.vendor == vendor, InvoiceKey.invoice_number == number
        )
    )
    return owner == document_id
