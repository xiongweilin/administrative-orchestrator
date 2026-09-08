from __future__ import annotations

import json
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from ...domain import AdministrativeCase
from ...governance import GovernanceBasis
from ...obligations import AdministrativeObligation
from .compatibility import KernelContractIdentity
from .models import (
    AdministrativeEffectIntent,
    AdministrativeExecutionGrant,
    KernelShadowProjection,
)


def _uuid(kind: str, *parts: object) -> UUID:
    payload = ":".join(str(part) for part in parts)
    return uuid5(NAMESPACE_URL, f"administrative-kernel:{kind}:{payload}")


def _kernel_ref(prefix: str, value: UUID) -> str:
    return f"{prefix}_{value.hex}"


def capability_for(obligation: AdministrativeObligation) -> str:
    target = obligation.target_system.strip().lower().replace("_", "-")
    operation = obligation.required_operation.strip().lower().replace("_", "-")
    if not target or not operation:
        raise ValueError("administrative obligation cannot map to an empty kernel capability")
    return f"administrative.{target}.{operation}.v1"


def derive_execution_grant(
    case: AdministrativeCase,
    obligation: AdministrativeObligation,
    governance: GovernanceBasis,
) -> AdministrativeExecutionGrant:
    if case.case_id != obligation.case_id or case.case_id != governance.case_id:
        raise ValueError("grant inputs belong to different administrative cases")
    if case.authority_epoch != obligation.authority_epoch:
        raise ValueError("obligation is bound to a stale administrative authority epoch")
    if case.authority_epoch != governance.authority_epoch:
        raise ValueError("governance basis is bound to a stale administrative authority epoch")
    if obligation.governance_basis_id != governance.basis_id:
        raise ValueError("obligation does not bind the supplied governance basis")
    if case.policy_ref is None or case.policy_ref != governance.policy_ref:
        raise ValueError("execution grant requires the current governed policy")

    return AdministrativeExecutionGrant(
        grant_id=_uuid("grant", case.case_id, case.authority_epoch, obligation.obligation_id),
        case_id=case.case_id,
        authority_epoch=case.authority_epoch,
        obligation_id=obligation.obligation_id,
        governance_basis_id=governance.basis_id,
        approval_satisfaction_id=governance.approval_satisfaction_id,
        policy_ref=governance.policy_ref,
        subject_ref=obligation.subject_ref,
        target_system=obligation.target_system,
        operation=obligation.required_operation,
        authority_class=obligation.authority_class,
        expected_postcondition=dict(obligation.expected_postcondition),
        issued_at=governance.created_at,
    )


def derive_effect_intent(
    case: AdministrativeCase,
    grant: AdministrativeExecutionGrant,
) -> AdministrativeEffectIntent:
    if case.case_id != grant.case_id or case.authority_epoch != grant.authority_epoch:
        raise ValueError("effect intent requires a current administrative execution grant")
    if case.fact_snapshot is None:
        raise ValueError("effect intent requires a current fact snapshot")
    return AdministrativeEffectIntent(
        intent_id=_uuid("intent", grant.grant_id),
        grant_id=grant.grant_id,
        case_id=grant.case_id,
        authority_epoch=grant.authority_epoch,
        obligation_id=grant.obligation_id,
        capability=(
            f"administrative.{grant.target_system.strip().lower().replace('_', '-')}."
            f"{grant.operation.strip().lower().replace('_', '-')}.v1"
        ),
        subject_ref=grant.subject_ref,
        parameters=dict(case.fact_snapshot.facts),
        expected_postcondition=dict(grant.expected_postcondition),
        created_at=grant.issued_at,
    )


def project_to_kernel(
    grant: AdministrativeExecutionGrant,
    intent: AdministrativeEffectIntent,
    compatibility: KernelContractIdentity,
) -> KernelShadowProjection:
    if intent.grant_id != grant.grant_id or intent.obligation_id != grant.obligation_id:
        raise ValueError("kernel projection requires an effect intent derived from the same grant")

    responsibility_uuid = _uuid("responsibility", grant.grant_id)
    admission_uuid = _uuid("admission", grant.grant_id)
    assessment_uuid = _uuid("assessment", grant.grant_id)
    proposal_uuid = _uuid("proposal", intent.intent_id)
    projection_id = _uuid("projection", grant.grant_id, intent.intent_id)

    responsibility_ref = _kernel_ref("resp_admin", responsibility_uuid)
    admission_ref = _kernel_ref("resp_admission_admin", admission_uuid)
    assessment_ref = _kernel_ref("assessment_admin", assessment_uuid)
    proposal_ref = _kernel_ref("proposal_admin", proposal_uuid)
    created_at = grant.issued_at.isoformat()
    policy_ref = f"{grant.policy_ref.policy_id}:{grant.policy_ref.version}"

    responsibility_payload: dict[str, Any] = {
        "id": responsibility_ref,
        "object_type": "StandingResponsibility",
        "created_at": created_at,
        "responsibility_kind": "administrative-obligation",
        "statement": (
            f"Discharge administrative obligation {grant.obligation_id} for "
            f"{grant.subject_ref} under grant {grant.grant_id}."
        ),
        "scope": {
            "administrative_case_id": str(grant.case_id),
            "authority_epoch": str(grant.authority_epoch),
            "obligation_id": str(grant.obligation_id),
            "governance_basis_id": str(grant.governance_basis_id),
            "execution_grant_id": str(grant.grant_id),
            "target_system": grant.target_system,
            "operation": grant.operation,
            "policy_ref": policy_ref,
        },
        "schema_version": compatibility.persistent_responsibility_contract,
    }
    admission_payload = {
        "id": admission_ref,
        "object_type": "ResponsibilityAdmission",
        "created_at": created_at,
        "responsibility_ref": responsibility_ref,
        "responsibility_version": 1,
        "principal_ref": grant.issued_by,
        "basis_refs": [
            f"administrative-grant:{grant.grant_id}",
            f"governance-basis:{grant.governance_basis_id}",
            f"approval-satisfaction:{grant.approval_satisfaction_id}",
        ],
        "admitted_at": created_at,
    }
    assessment_payload = {
        "id": assessment_ref,
        "object_type": "ResponsibilityAssessment",
        "created_at": created_at,
        "responsibility_ref": responsibility_ref,
        "responsibility_version": 1,
        "subject_ref": grant.subject_ref,
        "assessment_kind": "administrative-obligation-ready",
        "basis_refs": [
            f"administrative-intent:{intent.intent_id}",
            f"administrative-grant:{grant.grant_id}",
            f"governance-basis:{grant.governance_basis_id}",
        ],
        "assessed_at": created_at,
        "rationale": "administrative policy, approval, governance and business obligation are closed",
    }
    work_proposal_payload = {
        "id": proposal_ref,
        "object_type": "WorkProposal",
        "created_at": created_at,
        "responsibility_ref": responsibility_ref,
        "responsibility_version": 1,
        "assessment_ref": assessment_ref,
        "subject_ref": grant.subject_ref,
        "work_kind": "administrative-effect",
        "title": f"{grant.target_system}: {grant.operation} {grant.subject_ref}",
        "description": (
            "Execute one governed administrative effect intent. Administrative business grant "
            "is provenance only; Kernel runtime authority remains required separately."
        ),
        "requested_resources": {
            "compute_units": 0,
            "api_calls": 1,
            "money_minor": 0,
            "human_attention_units": 0,
            "concurrency_slots": 1,
            "domain_quota": {f"administrative:{grant.target_system}": 1},
        },
        "requested_capabilities": [intent.capability],
        "expected_result": json.dumps(
            intent.expected_postcondition,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ),
        "stop_conditions": [
            f"administrative-authority-epoch-changed:{grant.case_id}:{grant.authority_epoch}",
            f"governance-basis-invalidated:{grant.governance_basis_id}",
        ],
        "escalation_conditions": [
            "runtime-authorization-denied",
            "reality-unavailable-or-unknown",
            "semantic-postcondition-mismatch",
        ],
        "effect_class": "external-effect",
    }

    return KernelShadowProjection(
        projection_id=projection_id,
        case_id=grant.case_id,
        authority_epoch=grant.authority_epoch,
        grant_id=grant.grant_id,
        intent_id=intent.intent_id,
        obligation_id=grant.obligation_id,
        contract_catalog=compatibility.catalog_version,
        runtime_protocol=compatibility.runtime_protocol,
        persistent_responsibility_contract=compatibility.persistent_responsibility_contract,
        responsibility_payload=responsibility_payload,
        admission_payload=admission_payload,
        assessment_payload=assessment_payload,
        work_proposal_payload=work_proposal_payload,
        created_at=grant.issued_at,
        updated_at=grant.issued_at,
    )


__all__ = [
    "capability_for",
    "derive_effect_intent",
    "derive_execution_grant",
    "project_to_kernel",
]
