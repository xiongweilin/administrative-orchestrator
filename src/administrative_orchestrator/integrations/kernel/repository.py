from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Uuid, select
from sqlalchemy.orm import Mapped, mapped_column

from ...domain import AuthorityClass, PolicyRef, utcnow
from ...persistence import Base, SqlStore
from .client import KernelProposalReceipt
from .models import (
    AdministrativeEffectIntent,
    AdministrativeExecutionGrant,
    KernelProjectionStatus,
    KernelShadowProjection,
)


class KernelBridgePersistenceError(RuntimeError):
    pass


class AdministrativeExecutionGrantRow(Base):
    __tablename__ = "administrative_execution_grant"

    grant_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    case_id: Mapped[UUID] = mapped_column(
        ForeignKey("administrative_case.case_id"), nullable=False
    )
    authority_epoch: Mapped[int] = mapped_column(Integer, nullable=False)
    obligation_id: Mapped[UUID] = mapped_column(
        ForeignKey("administrative_obligation.obligation_id"), nullable=False, unique=True
    )
    governance_basis_id: Mapped[UUID] = mapped_column(
        ForeignKey("administrative_governance_basis.basis_id"), nullable=False
    )
    approval_satisfaction_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    policy_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    subject_ref: Mapped[str] = mapped_column(String(512), nullable=False)
    target_system: Mapped[str] = mapped_column(String(255), nullable=False)
    operation: Mapped[str] = mapped_column(String(255), nullable=False)
    authority_class: Mapped[str] = mapped_column(String(64), nullable=False)
    expected_postcondition_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    issued_by: Mapped[str] = mapped_column(String(255), nullable=False)
    issued_at: Mapped[Any] = mapped_column(DateTime(timezone=True), nullable=False)


class AdministrativeEffectIntentRow(Base):
    __tablename__ = "administrative_effect_intent"

    intent_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    grant_id: Mapped[UUID] = mapped_column(
        ForeignKey("administrative_execution_grant.grant_id"), nullable=False, unique=True
    )
    case_id: Mapped[UUID] = mapped_column(
        ForeignKey("administrative_case.case_id"), nullable=False
    )
    authority_epoch: Mapped[int] = mapped_column(Integer, nullable=False)
    obligation_id: Mapped[UUID] = mapped_column(
        ForeignKey("administrative_obligation.obligation_id"), nullable=False, unique=True
    )
    capability: Mapped[str] = mapped_column(String(512), nullable=False)
    subject_ref: Mapped[str] = mapped_column(String(512), nullable=False)
    parameters_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    expected_postcondition_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[Any] = mapped_column(DateTime(timezone=True), nullable=False)


class KernelBridgeProjectionRow(Base):
    __tablename__ = "administrative_kernel_bridge_projection"

    projection_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    case_id: Mapped[UUID] = mapped_column(
        ForeignKey("administrative_case.case_id"), nullable=False
    )
    authority_epoch: Mapped[int] = mapped_column(Integer, nullable=False)
    grant_id: Mapped[UUID] = mapped_column(
        ForeignKey("administrative_execution_grant.grant_id"), nullable=False, unique=True
    )
    intent_id: Mapped[UUID] = mapped_column(
        ForeignKey("administrative_effect_intent.intent_id"), nullable=False, unique=True
    )
    obligation_id: Mapped[UUID] = mapped_column(
        ForeignKey("administrative_obligation.obligation_id"), nullable=False, unique=True
    )
    contract_catalog: Mapped[str] = mapped_column(String(255), nullable=False)
    runtime_protocol: Mapped[str] = mapped_column(String(64), nullable=False)
    persistent_responsibility_contract: Mapped[str] = mapped_column(String(255), nullable=False)
    responsibility_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    admission_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    assessment_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    work_proposal_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    kernel_responsibility_ref: Mapped[str | None] = mapped_column(String(512))
    kernel_admission_ref: Mapped[str | None] = mapped_column(String(512))
    kernel_assessment_ref: Mapped[str | None] = mapped_column(String(512))
    kernel_proposal_ref: Mapped[str | None] = mapped_column(String(512))
    kernel_work_ref: Mapped[str | None] = mapped_column(String(512))
    kernel_run_ref: Mapped[str | None] = mapped_column(String(512))
    created_at: Mapped[Any] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[Any] = mapped_column(DateTime(timezone=True), nullable=False)


class KernelBridgeRepository:
    def __init__(self, store: SqlStore) -> None:
        self.store = store

    def put_grant(self, grant: AdministrativeExecutionGrant) -> AdministrativeExecutionGrant:
        with self.store.sessions.begin() as db:
            row = db.get(AdministrativeExecutionGrantRow, grant.grant_id)
            if row is not None:
                restored = self._grant_from_row(row)
                if restored != grant:
                    raise KernelBridgePersistenceError(
                        "administrative execution grant identity rebound"
                    )
                return restored
            db.add(
                AdministrativeExecutionGrantRow(
                    grant_id=grant.grant_id,
                    case_id=grant.case_id,
                    authority_epoch=grant.authority_epoch,
                    obligation_id=grant.obligation_id,
                    governance_basis_id=grant.governance_basis_id,
                    approval_satisfaction_id=grant.approval_satisfaction_id,
                    policy_json=grant.policy_ref.model_dump(mode="json"),
                    subject_ref=grant.subject_ref,
                    target_system=grant.target_system,
                    operation=grant.operation,
                    authority_class=grant.authority_class.value,
                    expected_postcondition_json=dict(grant.expected_postcondition),
                    issued_by=grant.issued_by,
                    issued_at=grant.issued_at,
                )
            )
        return grant

    def put_intent(self, intent: AdministrativeEffectIntent) -> AdministrativeEffectIntent:
        with self.store.sessions.begin() as db:
            row = db.get(AdministrativeEffectIntentRow, intent.intent_id)
            if row is not None:
                restored = self._intent_from_row(row)
                if restored != intent:
                    raise KernelBridgePersistenceError(
                        "administrative effect intent identity rebound"
                    )
                return restored
            db.add(
                AdministrativeEffectIntentRow(
                    intent_id=intent.intent_id,
                    grant_id=intent.grant_id,
                    case_id=intent.case_id,
                    authority_epoch=intent.authority_epoch,
                    obligation_id=intent.obligation_id,
                    capability=intent.capability,
                    subject_ref=intent.subject_ref,
                    parameters_json=dict(intent.parameters),
                    expected_postcondition_json=dict(intent.expected_postcondition),
                    created_at=intent.created_at,
                )
            )
        return intent

    def put_projection(self, projection: KernelShadowProjection) -> KernelShadowProjection:
        with self.store.sessions.begin() as db:
            row = db.get(KernelBridgeProjectionRow, projection.projection_id)
            if row is not None:
                restored = self._projection_from_row(row)
                if not self._same_projection_semantics(restored, projection):
                    raise KernelBridgePersistenceError("kernel projection identity rebound")
                return restored
            db.add(
                KernelBridgeProjectionRow(
                    projection_id=projection.projection_id,
                    case_id=projection.case_id,
                    authority_epoch=projection.authority_epoch,
                    grant_id=projection.grant_id,
                    intent_id=projection.intent_id,
                    obligation_id=projection.obligation_id,
                    contract_catalog=projection.contract_catalog,
                    runtime_protocol=projection.runtime_protocol,
                    persistent_responsibility_contract=(
                        projection.persistent_responsibility_contract
                    ),
                    responsibility_json=dict(projection.responsibility_payload),
                    admission_json=dict(projection.admission_payload),
                    assessment_json=dict(projection.assessment_payload),
                    work_proposal_json=dict(projection.work_proposal_payload),
                    status=projection.status.value,
                    kernel_responsibility_ref=projection.kernel_responsibility_ref,
                    kernel_admission_ref=projection.kernel_admission_ref,
                    kernel_assessment_ref=projection.kernel_assessment_ref,
                    kernel_proposal_ref=projection.kernel_proposal_ref,
                    kernel_work_ref=projection.kernel_work_ref,
                    kernel_run_ref=projection.kernel_run_ref,
                    created_at=projection.created_at,
                    updated_at=projection.updated_at,
                )
            )
        return projection

    def mark_submitted(
        self,
        projection: KernelShadowProjection,
        receipt: KernelProposalReceipt,
    ) -> KernelShadowProjection:
        with self.store.sessions.begin() as db:
            row = db.get(KernelBridgeProjectionRow, projection.projection_id)
            if row is None:
                raise KernelBridgePersistenceError("kernel projection is not persisted")
            current = self._projection_from_row(row)
            if not self._same_projection_semantics(current, projection):
                raise KernelBridgePersistenceError("kernel projection semantics changed before submit")
            if current.status is KernelProjectionStatus.SUBMITTED:
                expected_refs = (
                    receipt.responsibility_ref,
                    receipt.admission_ref,
                    receipt.assessment_ref,
                    receipt.proposal_ref,
                )
                current_refs = (
                    current.kernel_responsibility_ref,
                    current.kernel_admission_ref,
                    current.kernel_assessment_ref,
                    current.kernel_proposal_ref,
                )
                if current_refs != expected_refs:
                    raise KernelBridgePersistenceError("submitted kernel receipt identity rebound")
                return current
            if current.status is not KernelProjectionStatus.SHADOW:
                raise KernelBridgePersistenceError(
                    f"kernel projection cannot submit from {current.status.value}"
                )
            now = utcnow()
            row.status = KernelProjectionStatus.SUBMITTED.value
            row.kernel_responsibility_ref = receipt.responsibility_ref
            row.kernel_admission_ref = receipt.admission_ref
            row.kernel_assessment_ref = receipt.assessment_ref
            row.kernel_proposal_ref = receipt.proposal_ref
            row.updated_at = now
            db.flush()
            return self._projection_from_row(row)

    def get_projection_for_obligation(self, obligation_id: UUID) -> KernelShadowProjection | None:
        with self.store.sessions() as db:
            row = (
                db.execute(
                    select(KernelBridgeProjectionRow).where(
                        KernelBridgeProjectionRow.obligation_id == obligation_id
                    )
                )
                .scalars()
                .first()
            )
            return None if row is None else self._projection_from_row(row)

    def list_projections(self, case_id: UUID, authority_epoch: int) -> list[KernelShadowProjection]:
        with self.store.sessions() as db:
            rows = (
                db.execute(
                    select(KernelBridgeProjectionRow)
                    .where(
                        KernelBridgeProjectionRow.case_id == case_id,
                        KernelBridgeProjectionRow.authority_epoch == authority_epoch,
                    )
                    .order_by(KernelBridgeProjectionRow.projection_id)
                )
                .scalars()
                .all()
            )
            return [self._projection_from_row(row) for row in rows]

    @staticmethod
    def _same_projection_semantics(
        left: KernelShadowProjection,
        right: KernelShadowProjection,
    ) -> bool:
        excluded = {
            "status",
            "kernel_responsibility_ref",
            "kernel_admission_ref",
            "kernel_assessment_ref",
            "kernel_proposal_ref",
            "kernel_work_ref",
            "kernel_run_ref",
            "updated_at",
        }
        return left.model_dump(mode="json", exclude=excluded) == right.model_dump(
            mode="json", exclude=excluded
        )

    @staticmethod
    def _grant_from_row(row: AdministrativeExecutionGrantRow) -> AdministrativeExecutionGrant:
        return AdministrativeExecutionGrant(
            grant_id=row.grant_id,
            case_id=row.case_id,
            authority_epoch=row.authority_epoch,
            obligation_id=row.obligation_id,
            governance_basis_id=row.governance_basis_id,
            approval_satisfaction_id=row.approval_satisfaction_id,
            policy_ref=PolicyRef.model_validate(row.policy_json),
            subject_ref=row.subject_ref,
            target_system=row.target_system,
            operation=row.operation,
            authority_class=AuthorityClass(row.authority_class),
            expected_postcondition=dict(row.expected_postcondition_json),
            issued_by=row.issued_by,
            issued_at=row.issued_at,
        )

    @staticmethod
    def _intent_from_row(row: AdministrativeEffectIntentRow) -> AdministrativeEffectIntent:
        return AdministrativeEffectIntent(
            intent_id=row.intent_id,
            grant_id=row.grant_id,
            case_id=row.case_id,
            authority_epoch=row.authority_epoch,
            obligation_id=row.obligation_id,
            capability=row.capability,
            subject_ref=row.subject_ref,
            parameters=dict(row.parameters_json),
            expected_postcondition=dict(row.expected_postcondition_json),
            created_at=row.created_at,
        )

    @staticmethod
    def _projection_from_row(row: KernelBridgeProjectionRow) -> KernelShadowProjection:
        return KernelShadowProjection(
            projection_id=row.projection_id,
            case_id=row.case_id,
            authority_epoch=row.authority_epoch,
            grant_id=row.grant_id,
            intent_id=row.intent_id,
            obligation_id=row.obligation_id,
            contract_catalog=row.contract_catalog,
            runtime_protocol=row.runtime_protocol,
            persistent_responsibility_contract=row.persistent_responsibility_contract,
            responsibility_payload=dict(row.responsibility_json),
            admission_payload=dict(row.admission_json),
            assessment_payload=dict(row.assessment_json),
            work_proposal_payload=dict(row.work_proposal_json),
            status=KernelProjectionStatus(row.status),
            kernel_responsibility_ref=row.kernel_responsibility_ref,
            kernel_admission_ref=row.kernel_admission_ref,
            kernel_assessment_ref=row.kernel_assessment_ref,
            kernel_proposal_ref=row.kernel_proposal_ref,
            kernel_work_ref=row.kernel_work_ref,
            kernel_run_ref=row.kernel_run_ref,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )


__all__ = [
    "AdministrativeEffectIntentRow",
    "AdministrativeExecutionGrantRow",
    "KernelBridgePersistenceError",
    "KernelBridgeProjectionRow",
    "KernelBridgeRepository",
]
