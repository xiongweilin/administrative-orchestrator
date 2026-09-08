from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import Field
from sqlalchemy import JSON, DateTime, String, select
from sqlalchemy.orm import Mapped, mapped_column

from .domain import PolicyRef, UtcModel, normalize_datetime, utcnow
from .persistence import Base, SqlStore
from .policy import OnboardingPolicy


class PolicyPlaneError(ValueError):
    pass


class PolicyVersionStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    SHADOW = "shadow"
    INACTIVE = "inactive"
    RETIRED = "retired"


class PolicyVersionRecord(UtcModel):
    policy_id: str
    version: str
    owner: str
    status: PolicyVersionStatus = PolicyVersionStatus.DRAFT
    effective_from: datetime
    effective_until: datetime | None = None
    definition: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utcnow)

    @property
    def policy_ref(self) -> PolicyRef:
        return PolicyRef(
            policy_id=self.policy_id,
            version=self.version,
            owner=self.owner,
            effective_from=self.effective_from,
            effective_until=self.effective_until,
        )

    def is_effective_at(self, at: datetime) -> bool:
        at = normalize_datetime(at)
        return self.status == PolicyVersionStatus.ACTIVE and self.policy_ref.is_current_at(at)


class PolicyVersionRow(Base):
    __tablename__ = "administrative_policy_version"

    policy_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    version: Mapped[str] = mapped_column(String(128), primary_key=True)
    owner: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    effective_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    definition_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PolicyRepository:
    def __init__(self, store: SqlStore) -> None:
        self.store = store

    def put_version(self, record: PolicyVersionRecord) -> PolicyVersionRecord:
        with self.store.sessions.begin() as db:
            row = db.get(PolicyVersionRow, (record.policy_id, record.version))
            if row is not None:
                restored = self._from_row(row)
                if restored != record:
                    raise PolicyPlaneError("policy version already exists with different semantics")
                return restored
            db.add(
                PolicyVersionRow(
                    policy_id=record.policy_id,
                    version=record.version,
                    owner=record.owner,
                    status=record.status.value,
                    effective_from=record.effective_from,
                    effective_until=record.effective_until,
                    definition_json=dict(record.definition),
                    created_at=record.created_at,
                )
            )
        return record

    def set_status(
        self,
        policy_id: str,
        version: str,
        status: PolicyVersionStatus,
    ) -> PolicyVersionRecord:
        with self.store.sessions.begin() as db:
            row = db.get(PolicyVersionRow, (policy_id, version))
            if row is None:
                raise KeyError(f"policy version {policy_id}:{version} not found")
            row.status = status.value
            db.flush()
            return self._from_row(row)

    def get_version(self, policy_id: str, version: str) -> PolicyVersionRecord | None:
        with self.store.sessions() as db:
            row = db.get(PolicyVersionRow, (policy_id, version))
            return None if row is None else self._from_row(row)

    def list_versions(self, policy_id: str) -> list[PolicyVersionRecord]:
        with self.store.sessions() as db:
            rows = (
                db.execute(
                    select(PolicyVersionRow)
                    .where(PolicyVersionRow.policy_id == policy_id)
                    .order_by(PolicyVersionRow.effective_from, PolicyVersionRow.version)
                )
                .scalars()
                .all()
            )
            return [self._from_row(row) for row in rows]

    def resolve_current(
        self,
        policy_id: str,
        *,
        at: datetime | None = None,
    ) -> PolicyVersionRecord:
        at = normalize_datetime(at or utcnow())
        candidates = [
            record for record in self.list_versions(policy_id) if record.is_effective_at(at)
        ]
        if not candidates:
            raise PolicyPlaneError(f"no active current policy version for {policy_id}")
        if len(candidates) != 1:
            raise PolicyPlaneError(f"multiple active current policy versions for {policy_id}")
        return candidates[0]

    @staticmethod
    def _from_row(row: PolicyVersionRow) -> PolicyVersionRecord:
        return PolicyVersionRecord(
            policy_id=row.policy_id,
            version=row.version,
            owner=row.owner,
            status=PolicyVersionStatus(row.status),
            effective_from=row.effective_from,
            effective_until=row.effective_until,
            definition=dict(row.definition_json),
            created_at=row.created_at,
        )


def default_onboarding_policy_version() -> PolicyVersionRecord:
    baseline = datetime(2026, 1, 1, tzinfo=UTC)
    return PolicyVersionRecord(
        policy_id="employee-onboarding",
        version="v1",
        owner="administrative-orchestrator",
        status=PolicyVersionStatus.ACTIVE,
        effective_from=baseline,
        definition=OnboardingPolicy.default_definition(),
        created_at=baseline,
    )


def compile_onboarding_policy(record: PolicyVersionRecord) -> OnboardingPolicy:
    if record.policy_id != "employee-onboarding":
        raise PolicyPlaneError("record is not an employee-onboarding policy")
    return OnboardingPolicy(record.policy_ref, definition=record.definition)


__all__ = [
    "PolicyPlaneError",
    "PolicyRepository",
    "PolicyVersionRecord",
    "PolicyVersionRow",
    "PolicyVersionStatus",
    "compile_onboarding_policy",
    "default_onboarding_policy_version",
]
