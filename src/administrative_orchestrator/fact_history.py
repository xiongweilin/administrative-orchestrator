from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Uuid, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from .domain import AdministrativeCase, FactSnapshot
from .persistence import Base, SqlStore, utcnow


class FactSnapshotHistoryRow(Base):
    __tablename__ = "administrative_fact_snapshot_history"

    snapshot_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    case_id: Mapped[UUID] = mapped_column(
        ForeignKey("administrative_case.case_id"), nullable=False
    )
    case_version: Mapped[int] = mapped_column(Integer, nullable=False)
    authority_epoch: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[str] = mapped_column(String(255), nullable=False)
    owner: Mapped[str] = mapped_column(String(255), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    digest: Mapped[str | None] = mapped_column(String(128), nullable=True)
    facts_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )


def persist_fact_snapshot(db: Session, case: AdministrativeCase) -> None:
    snapshot = case.fact_snapshot
    if snapshot is None:
        return
    existing = db.get(FactSnapshotHistoryRow, snapshot.snapshot_id)
    if existing is not None:
        restored = _snapshot_from_row(existing)
        if restored != snapshot or existing.case_id != case.case_id:
            raise ValueError("fact snapshot id already exists with different semantics")
        return
    db.add(
        FactSnapshotHistoryRow(
            snapshot_id=snapshot.snapshot_id,
            case_id=case.case_id,
            case_version=case.version,
            authority_epoch=case.authority_epoch,
            source=snapshot.source,
            owner=snapshot.owner,
            observed_at=snapshot.observed_at,
            digest=snapshot.digest,
            facts_json=dict(snapshot.facts),
            recorded_at=utcnow(),
        )
    )


def list_fact_snapshots(store: SqlStore, case_id: UUID) -> list[FactSnapshot]:
    with store.sessions() as db:
        rows = (
            db.execute(
                select(FactSnapshotHistoryRow)
                .where(FactSnapshotHistoryRow.case_id == case_id)
                .order_by(
                    FactSnapshotHistoryRow.case_version,
                    FactSnapshotHistoryRow.recorded_at,
                    FactSnapshotHistoryRow.snapshot_id,
                )
            )
            .scalars()
            .all()
        )
        return [_snapshot_from_row(row) for row in rows]


def _snapshot_from_row(row: FactSnapshotHistoryRow) -> FactSnapshot:
    return FactSnapshot(
        snapshot_id=row.snapshot_id,
        source=row.source,
        owner=row.owner,
        observed_at=row.observed_at,
        facts=dict(row.facts_json),
        digest=row.digest,
    )


__all__ = ["FactSnapshotHistoryRow", "list_fact_snapshots", "persist_fact_snapshot"]
