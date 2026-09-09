from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import Field
from sqlalchemy import JSON, DateTime, String, Uuid, select
from sqlalchemy.orm import Mapped, mapped_column

from .authority import AuthorityError, IdentityBinding, IdentityBindingRow, PrincipalRow
from .domain import UtcModel, normalize_datetime, utcnow
from .persistence import Base, SqlStore


class AuthorityLifecycleEvent(UtcModel):
    event_id: UUID = Field(default_factory=uuid4)
    event_type: str
    actor_principal_id: str
    target_ref: str
    reason: str
    payload: dict[str, Any] = Field(default_factory=dict)
    occurred_at: datetime = Field(default_factory=utcnow)


class AuthorityLifecycleEventRow(Base):
    __tablename__ = "administrative_authority_lifecycle_event"

    event_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    actor_principal_id: Mapped[str] = mapped_column(String(255), nullable=False)
    target_ref: Mapped[str] = mapped_column(String(1000), nullable=False)
    reason: Mapped[str] = mapped_column(String(2000), nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AuthorityLifecycleRepository:
    def __init__(self, store: SqlStore) -> None:
        self.store = store

    def deactivate_principal(
        self,
        principal_id: str,
        *,
        actor_principal_id: str,
        reason: str,
    ) -> AuthorityLifecycleEvent:
        if not reason.strip():
            raise AuthorityError("principal deactivation requires a reason")
        with self.store.sessions.begin() as db:
            row = db.get(PrincipalRow, principal_id)
            if row is None:
                raise AuthorityError("principal does not exist")
            if row.active:
                row.active = False
            event = AuthorityLifecycleEvent(
                event_type="principal.deactivated",
                actor_principal_id=actor_principal_id,
                target_ref=f"principal:{principal_id}",
                reason=reason,
                payload={"principal_id": principal_id},
            )
            self._record(db, event)
            return event

    def expire_identity_binding(
        self,
        binding_id: UUID,
        *,
        actor_principal_id: str,
        reason: str,
        at: datetime | None = None,
    ) -> AuthorityLifecycleEvent:
        if not reason.strip():
            raise AuthorityError("identity revocation requires a reason")
        at = normalize_datetime(at or utcnow())
        with self.store.sessions.begin() as db:
            row = db.get(IdentityBindingRow, binding_id)
            if row is None:
                raise AuthorityError("identity binding does not exist")
            if row.valid_until is None or at < normalize_datetime(row.valid_until):
                row.valid_until = at
            event = AuthorityLifecycleEvent(
                event_type="identity_binding.revoked",
                actor_principal_id=actor_principal_id,
                target_ref=f"identity-binding:{binding_id}",
                reason=reason,
                payload={
                    "binding_id": str(binding_id),
                    "provider": row.provider,
                    "external_subject": row.external_subject,
                    "principal_id": row.principal_id,
                    "valid_until": at.isoformat(),
                },
                occurred_at=at,
            )
            self._record(db, event)
            return event

    def bind_identity(
        self,
        binding: IdentityBinding,
        *,
        actor_principal_id: str,
        reason: str,
    ) -> AuthorityLifecycleEvent:
        if not reason.strip():
            raise AuthorityError("identity binding requires a reason")
        with self.store.sessions.begin() as db:
            principal = db.get(PrincipalRow, binding.principal_id)
            if principal is None or not principal.active:
                raise AuthorityError("identity may bind only to an active principal")
            rows = (
                db.execute(
                    select(IdentityBindingRow).where(
                        IdentityBindingRow.provider == binding.provider,
                        IdentityBindingRow.external_subject == binding.external_subject,
                    )
                )
                .scalars()
                .all()
            )
            for row in rows:
                existing = IdentityBinding(
                    binding_id=row.binding_id,
                    provider=row.provider,
                    external_subject=row.external_subject,
                    principal_id=row.principal_id,
                    valid_from=row.valid_from,
                    valid_until=row.valid_until,
                )
                if _windows_overlap(existing, binding):
                    raise AuthorityError("identity binding validity overlaps existing binding")
            db.add(
                IdentityBindingRow(
                    binding_id=binding.binding_id,
                    provider=binding.provider,
                    external_subject=binding.external_subject,
                    principal_id=binding.principal_id,
                    valid_from=binding.valid_from,
                    valid_until=binding.valid_until,
                )
            )
            event = AuthorityLifecycleEvent(
                event_type="identity_binding.created",
                actor_principal_id=actor_principal_id,
                target_ref=f"identity-binding:{binding.binding_id}",
                reason=reason,
                payload=binding.model_dump(mode="json"),
                occurred_at=binding.valid_from,
            )
            self._record(db, event)
            return event

    def list_events(self, *, limit: int = 200) -> list[AuthorityLifecycleEvent]:
        with self.store.sessions() as db:
            rows = (
                db.execute(
                    select(AuthorityLifecycleEventRow)
                    .order_by(AuthorityLifecycleEventRow.occurred_at.desc())
                    .limit(limit)
                )
                .scalars()
                .all()
            )
            return [
                AuthorityLifecycleEvent(
                    event_id=row.event_id,
                    event_type=row.event_type,
                    actor_principal_id=row.actor_principal_id,
                    target_ref=row.target_ref,
                    reason=row.reason,
                    payload=dict(row.payload_json),
                    occurred_at=row.occurred_at,
                )
                for row in rows
            ]

    @staticmethod
    def _record(db, event: AuthorityLifecycleEvent) -> None:
        db.add(
            AuthorityLifecycleEventRow(
                event_id=event.event_id,
                event_type=event.event_type,
                actor_principal_id=event.actor_principal_id,
                target_ref=event.target_ref,
                reason=event.reason,
                payload_json=dict(event.payload),
                occurred_at=event.occurred_at,
            )
        )


def _windows_overlap(left: IdentityBinding, right: IdentityBinding) -> bool:
    left_end = left.valid_until
    right_end = right.valid_until
    if left_end is not None and normalize_datetime(left_end) <= normalize_datetime(right.valid_from):
        return False
    if right_end is not None and normalize_datetime(right_end) <= normalize_datetime(left.valid_from):
        return False
    return True


__all__ = [
    "AuthorityLifecycleEvent",
    "AuthorityLifecycleEventRow",
    "AuthorityLifecycleRepository",
]
