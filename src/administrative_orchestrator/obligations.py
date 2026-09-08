from __future__ import annotations

from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import Field
from sqlalchemy import JSON, Boolean, ForeignKey, Integer, String, Uuid, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from .domain import AdministrativeCase, AuthorityClass, UtcModel
from .persistence import Base, SqlStore
from .policy import PolicyEvaluation


class ObligationError(RuntimeError):
    pass


class AdministrativeObligation(UtcModel):
    obligation_id: UUID
    case_id: UUID
    authority_epoch: int
    governance_basis_id: UUID
    kind: str
    subject_ref: str
    target_system: str
    required_operation: str
    expected_postcondition: dict[str, Any] = Field(default_factory=dict)
    authority_class: AuthorityClass
    required: bool = True


class OnboardingObligationSet(UtcModel):
    requirement_id: UUID
    case_id: UUID
    authority_epoch: int
    governance_basis_id: UUID
    obligations: tuple[AdministrativeObligation, ...]


class ObligationSetRow(Base):
    __tablename__ = "administrative_obligation_set"

    requirement_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    case_id: Mapped[UUID] = mapped_column(
        ForeignKey("administrative_case.case_id"), nullable=False
    )
    authority_epoch: Mapped[int] = mapped_column(Integer, nullable=False)
    governance_basis_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)


class ObligationRow(Base):
    __tablename__ = "administrative_obligation"

    obligation_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    requirement_id: Mapped[UUID] = mapped_column(
        ForeignKey("administrative_obligation_set.requirement_id"), nullable=False
    )
    case_id: Mapped[UUID] = mapped_column(
        ForeignKey("administrative_case.case_id"), nullable=False
    )
    authority_epoch: Mapped[int] = mapped_column(Integer, nullable=False)
    governance_basis_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    kind: Mapped[str] = mapped_column(String(128), nullable=False)
    subject_ref: Mapped[str] = mapped_column(String(512), nullable=False)
    target_system: Mapped[str] = mapped_column(String(255), nullable=False)
    required_operation: Mapped[str] = mapped_column(String(255), nullable=False)
    expected_postcondition_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    authority_class: Mapped[str] = mapped_column(String(64), nullable=False)
    required: Mapped[bool] = mapped_column(Boolean, nullable=False)


class ObligationRepository:
    def __init__(self, store: SqlStore) -> None:
        self.store = store

    def put(self, obligation_set: OnboardingObligationSet) -> OnboardingObligationSet:
        with self.store.sessions.begin() as db:
            return self.put_in_session(db, obligation_set)

    def put_in_session(
        self,
        db: Session,
        obligation_set: OnboardingObligationSet,
    ) -> OnboardingObligationSet:
        existing = db.get(ObligationSetRow, obligation_set.requirement_id)
        if existing is not None:
            restored = self._load_in_session(db, obligation_set.requirement_id)
            if restored != obligation_set:
                raise ObligationError("obligation set id already exists with different semantics")
            return restored
        db.add(
            ObligationSetRow(
                requirement_id=obligation_set.requirement_id,
                case_id=obligation_set.case_id,
                authority_epoch=obligation_set.authority_epoch,
                governance_basis_id=obligation_set.governance_basis_id,
            )
        )
        for item in obligation_set.obligations:
            db.add(
                ObligationRow(
                    obligation_id=item.obligation_id,
                    requirement_id=obligation_set.requirement_id,
                    case_id=item.case_id,
                    authority_epoch=item.authority_epoch,
                    governance_basis_id=item.governance_basis_id,
                    kind=item.kind,
                    subject_ref=item.subject_ref,
                    target_system=item.target_system,
                    required_operation=item.required_operation,
                    expected_postcondition_json=dict(item.expected_postcondition),
                    authority_class=item.authority_class.value,
                    required=item.required,
                )
            )
        return obligation_set

    def get_current(self, case_id: UUID, authority_epoch: int) -> OnboardingObligationSet | None:
        with self.store.sessions() as db:
            row = (
                db.execute(
                    select(ObligationSetRow)
                    .where(
                        ObligationSetRow.case_id == case_id,
                        ObligationSetRow.authority_epoch == authority_epoch,
                    )
                    .order_by(ObligationSetRow.requirement_id)
                    .limit(1)
                )
                .scalars()
                .first()
            )
            return None if row is None else self._load_in_session(db, row.requirement_id)

    @staticmethod
    def _load_in_session(db: Session, requirement_id: UUID) -> OnboardingObligationSet:
        row = db.get(ObligationSetRow, requirement_id)
        if row is None:
            raise KeyError(f"obligation set {requirement_id} not found")
        obligation_rows = (
            db.execute(
                select(ObligationRow)
                .where(ObligationRow.requirement_id == requirement_id)
                .order_by(ObligationRow.target_system, ObligationRow.required_operation)
            )
            .scalars()
            .all()
        )
        return OnboardingObligationSet(
            requirement_id=row.requirement_id,
            case_id=row.case_id,
            authority_epoch=row.authority_epoch,
            governance_basis_id=row.governance_basis_id,
            obligations=tuple(
                AdministrativeObligation(
                    obligation_id=item.obligation_id,
                    case_id=item.case_id,
                    authority_epoch=item.authority_epoch,
                    governance_basis_id=item.governance_basis_id,
                    kind=item.kind,
                    subject_ref=item.subject_ref,
                    target_system=item.target_system,
                    required_operation=item.required_operation,
                    expected_postcondition=dict(item.expected_postcondition_json),
                    authority_class=AuthorityClass(item.authority_class),
                    required=item.required,
                )
                for item in obligation_rows
            ),
        )


def derive_onboarding_obligations(
    case: AdministrativeCase,
    evaluation: PolicyEvaluation,
    *,
    governance_basis_id: UUID,
) -> OnboardingObligationSet:
    if case.fact_snapshot is None:
        raise ObligationError("onboarding obligations require current facts")
    if evaluation.policy_ref != case.policy_ref:
        raise ObligationError("onboarding obligations require current policy evaluation")

    facts = case.fact_snapshot.facts
    templates = {
        (item.target_system, item.operation, item.authority_class): item
        for item in evaluation.allowed_effects
    }
    obligations: list[AdministrativeObligation] = []
    for key in sorted(templates, key=lambda value: (value[0], value[1], value[2].value)):
        template = templates[key]
        obligation_id = uuid5(
            NAMESPACE_URL,
            f"administrative:obligation:{case.case_id}:{case.authority_epoch}:"
            f"{template.target_system}:{template.operation}",
        )
        expected_payload = {
            field: facts.get(field)
            for field in (
                "employee_ref",
                "department_ref",
                "manager_principal_id",
                "start_date",
                "employment_type",
            )
            if facts.get(field) is not None
        }
        expected_postcondition: dict[str, Any] = {
            "target_system": template.target_system,
            "operation": template.operation,
            "subject_ref": case.subject_ref,
            "active": True,
            "payload": expected_payload,
        }
        if template.operation == "account.provision":
            expected_postcondition["requested_system"] = template.target_system
        obligations.append(
            AdministrativeObligation(
                obligation_id=obligation_id,
                case_id=case.case_id,
                authority_epoch=case.authority_epoch,
                governance_basis_id=governance_basis_id,
                kind=f"{template.target_system}.{template.operation}",
                subject_ref=case.subject_ref,
                target_system=template.target_system,
                required_operation=template.operation,
                expected_postcondition=expected_postcondition,
                authority_class=template.authority_class,
                required=True,
            )
        )

    if not obligations:
        raise ObligationError("current onboarding policy produces no required obligations")
    requirement_id = uuid5(
        NAMESPACE_URL,
        f"administrative:obligation-set:{case.case_id}:{case.authority_epoch}:{governance_basis_id}",
    )
    return OnboardingObligationSet(
        requirement_id=requirement_id,
        case_id=case.case_id,
        authority_epoch=case.authority_epoch,
        governance_basis_id=governance_basis_id,
        obligations=tuple(obligations),
    )


__all__ = [
    "AdministrativeObligation",
    "ObligationError",
    "ObligationRepository",
    "ObligationRow",
    "ObligationSetRow",
    "OnboardingObligationSet",
    "derive_onboarding_obligations",
]
