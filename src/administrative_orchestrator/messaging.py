from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import JSON, DateTime, Integer, String, Text, Uuid, or_, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from .persistence import Base, SqlStore, utcnow

OUTBOX_PENDING = "pending"
OUTBOX_PROCESSING = "processing"
OUTBOX_DISPATCHED = "dispatched"
OUTBOX_FAILED = "failed"


class OutboxEventRow(Base):
    __tablename__ = "administrative_outbox_event"

    event_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    aggregate_id: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=OUTBOX_PENDING)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )


@dataclass(frozen=True)
class OutboxEvent:
    event_id: UUID
    event_type: str
    aggregate_id: str
    payload: dict[str, Any]
    attempts: int


@dataclass(frozen=True)
class FailedOutboxEvent:
    event_id: UUID
    event_type: str
    aggregate_id: str
    payload: dict[str, Any]
    attempts: int
    last_error: str | None
    created_at: datetime


def emit_outbox(
    db: Session,
    *,
    event_type: str,
    aggregate_id: str,
    payload: dict[str, Any],
    event_id: UUID | None = None,
) -> UUID:
    event_id = event_id or uuid4()
    db.add(
        OutboxEventRow(
            event_id=event_id,
            event_type=event_type,
            aggregate_id=aggregate_id,
            payload_json=payload,
            status=OUTBOX_PENDING,
            attempts=0,
            created_at=utcnow(),
        )
    )
    return event_id


def recover_expired_leases(store: SqlStore, *, batch: int = 100) -> int:
    now = utcnow()
    with store.sessions.begin() as db:
        rows = list(
            db.execute(
                select(OutboxEventRow)
                .where(
                    OutboxEventRow.status == OUTBOX_PROCESSING,
                    OutboxEventRow.lease_until.is_not(None),
                    OutboxEventRow.lease_until < now,
                )
                .order_by(OutboxEventRow.created_at, OutboxEventRow.event_id)
                .limit(batch)
                .with_for_update(skip_locked=True)
            )
            .scalars()
            .all()
        )
        for row in rows:
            row.status = OUTBOX_PENDING
            row.lease_until = None
            row.last_error = "lease expired; returned to pending"
        return len(rows)


def claim_outbox(
    store: SqlStore,
    *,
    batch: int = 20,
    lease_seconds: int = 30,
) -> list[OutboxEvent]:
    now = utcnow()
    lease_until = now + timedelta(seconds=lease_seconds)
    with store.sessions.begin() as db:
        rows = list(
            db.execute(
                select(OutboxEventRow)
                .where(
                    OutboxEventRow.status == OUTBOX_PENDING,
                    or_(
                        OutboxEventRow.next_attempt_at.is_(None),
                        OutboxEventRow.next_attempt_at <= now,
                    ),
                )
                .order_by(OutboxEventRow.created_at, OutboxEventRow.event_id)
                .limit(batch)
                .with_for_update(skip_locked=True)
            )
            .scalars()
            .all()
        )
        result: list[OutboxEvent] = []
        for row in rows:
            row.status = OUTBOX_PROCESSING
            row.lease_until = lease_until
            result.append(
                OutboxEvent(
                    event_id=row.event_id,
                    event_type=row.event_type,
                    aggregate_id=row.aggregate_id,
                    payload=dict(row.payload_json),
                    attempts=row.attempts,
                )
            )
        return result


def mark_dispatched(store: SqlStore, event_id: UUID) -> None:
    with store.sessions.begin() as db:
        row = db.get(OutboxEventRow, event_id)
        if row is None:
            return
        row.status = OUTBOX_DISPATCHED
        row.lease_until = None
        row.last_error = None


def mark_retry(
    store: SqlStore,
    event_id: UUID,
    error: str,
    *,
    max_attempts: int = 10,
) -> bool:
    with store.sessions.begin() as db:
        row = db.get(OutboxEventRow, event_id)
        if row is None:
            return False
        attempts = row.attempts + 1
        row.attempts = attempts
        row.lease_until = None
        row.last_error = error[:2000]
        if attempts >= max_attempts:
            row.status = OUTBOX_FAILED
            row.next_attempt_at = None
            return True
        row.status = OUTBOX_PENDING
        delay_seconds = min(60, 2 ** max(0, attempts - 1))
        row.next_attempt_at = utcnow() + timedelta(seconds=delay_seconds)
        return False


def list_failed_outbox(store: SqlStore, *, limit: int = 100) -> list[FailedOutboxEvent]:
    limit = max(1, min(limit, 1000))
    with store.sessions() as db:
        rows = (
            db.execute(
                select(OutboxEventRow)
                .where(OutboxEventRow.status == OUTBOX_FAILED)
                .order_by(OutboxEventRow.created_at.desc(), OutboxEventRow.event_id.desc())
                .limit(limit)
            )
            .scalars()
            .all()
        )
        return [
            FailedOutboxEvent(
                event_id=row.event_id,
                event_type=row.event_type,
                aggregate_id=row.aggregate_id,
                payload=dict(row.payload_json),
                attempts=row.attempts,
                last_error=row.last_error,
                created_at=row.created_at,
            )
            for row in rows
        ]


__all__ = [
    "FailedOutboxEvent",
    "OUTBOX_DISPATCHED",
    "OUTBOX_FAILED",
    "OUTBOX_PENDING",
    "OUTBOX_PROCESSING",
    "OutboxEvent",
    "OutboxEventRow",
    "claim_outbox",
    "emit_outbox",
    "list_failed_outbox",
    "mark_dispatched",
    "mark_retry",
    "recover_expired_leases",
]
