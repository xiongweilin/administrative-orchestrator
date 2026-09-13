from __future__ import annotations

from typing import Any

from sqlalchemy.exc import OperationalError

from ..completion import CompletionAssessment, assess_administrative_completion
from ..domain import AdministrativeCase, utcnow
from ..inspection import list_authorizations, list_decisions, list_realizations
from ..integrations.kernel.bridge import KernelExecutionBridge
from ..integrations.kernel.client import KernelResponsibilityDischargeError
from ..integrations.kernel.repository import KernelBridgeRepository
from ..responsibility_discharge import (
    AdministrativeResponsibilityDischargeService,
    ResponsibilityDischargeBlocked,
)
from ..transfer import TransferRequirementRepository
from .runtime import OperationsRuntime


def case_completion_assessment(
    obligation_set,
    effects,
    outcomes,
    *,
    realizations,
    links,
    fulfillments,
) -> CompletionAssessment:
    if obligation_set is None:
        return CompletionAssessment(
            requirement_id="missing-current-obligation-set",
            satisfied=False,
            blocking_reasons=("missing current obligation set",),
        )
    return assess_administrative_completion(
        obligation_set,
        effects,
        outcomes,
        realizations=realizations,
        links=links,
        fulfillments=fulfillments,
    )


def termination_snapshot(case: AdministrativeCase) -> dict[str, Any]:
    facts = case.fact_snapshot.facts if case.fact_snapshot is not None else {}
    return {
        "termination_status": facts.get("termination_status"),
        "termination_effective_at": facts.get("termination_effective_at"),
        "employment_episode_ref": facts.get("employment_episode_ref"),
        "authoritative_fact_snapshot": (
            case.fact_snapshot.model_dump(mode="json") if case.fact_snapshot else None
        ),
    }


def authority_snapshot(
    runtime: OperationsRuntime,
    case: AdministrativeCase,
) -> dict[str, list[dict[str, Any]]]:
    facts = case.fact_snapshot.facts if case.fact_snapshot is not None else {}
    principal_ids = {
        str(value)
        for key, value in facts.items()
        if key.endswith("principal_id") and isinstance(value, str) and value.strip()
    }
    principal_ids.add(case.requester_principal_id)
    bindings: list[dict[str, Any]] = []
    roles: list[dict[str, Any]] = []
    delegations: list[dict[str, Any]] = []
    observed_at = utcnow()
    for principal_id in sorted(principal_ids):
        bindings.extend(
            item.model_dump(mode="json")
            for item in runtime.authority.list_current_identity_bindings(
                principal_id, at=observed_at
            )
        )
        roles.extend(
            item.model_dump(mode="json")
            for item in runtime.authority.list_current_role_assignments(
                principal_id, at=observed_at
            )
        )
        delegations.extend(
            item.model_dump(mode="json")
            for item in runtime.authority.list_current_delegations_involving(
                principal_id, at=observed_at
            )
        )
    return {
        "bindings": dedupe_json_records(bindings),
        "role_assignments": dedupe_json_records(roles),
        "delegations": dedupe_json_records(delegations),
    }


def kernel_projection_snapshot(projection) -> dict[str, Any]:
    return {
        "projection_id": str(projection.projection_id),
        "obligation_id": str(projection.obligation_id),
        "authority_epoch": projection.authority_epoch,
        "status": projection.status.value,
        "responsibility_ref": projection.kernel_responsibility_ref,
        "responsibility_version": projection.admission_payload.get("responsibility_version"),
        "admission_ref": projection.kernel_admission_ref,
        "assessment_ref": projection.kernel_assessment_ref,
        "proposal_ref": projection.kernel_proposal_ref,
        "work_ref": projection.kernel_work_ref,
        "execution": {
            "status": (
                projection.kernel_execution_status.value
                if projection.kernel_execution_status is not None
                else None
            ),
            "execution_ref": projection.kernel_execution_ref,
            "run_ref": projection.kernel_run_ref,
            "request_ref": projection.kernel_request_ref,
            "authorization_ref": projection.kernel_authorization_ref,
            "provider_id": projection.kernel_provider_id,
            "action_ref": projection.kernel_action_ref,
            "outcome_ref": projection.kernel_outcome_ref,
            "evidence_ref": projection.kernel_evidence_ref,
            "responsibility_ref": projection.kernel_execution_responsibility_ref,
            "processed_at": (
                projection.kernel_execution_processed_at.isoformat()
                if projection.kernel_execution_processed_at is not None
                else None
            ),
        },
    }


def responsibility_snapshot(
    runtime: OperationsRuntime,
    case: AdministrativeCase,
    obligation_set,
    completion: CompletionAssessment,
    projections,
    *,
    bridge_factory=KernelExecutionBridge,
    discharge_service_factory=AdministrativeResponsibilityDischargeService,
) -> dict[str, Any]:
    if obligation_set is None:
        return {
            "status": "pending",
            "blocker": "missing_current_obligation_set",
            "responsibilities": [],
            "completion_satisfied": completion.satisfied,
        }
    if not completion.satisfied:
        return {
            "status": "pending",
            "blocker": "completion_assessment_not_satisfied",
            "responsibilities": [],
            "completion_satisfied": False,
        }

    bridge = None
    if runtime.settings.kernel_bridge_mode != "disabled":
        bridge = bridge_factory(
            runtime.store,
            settings=runtime.settings,
            require_responsibility_discharge=True,
        )
    if bridge is None or not bridge.cutover:
        return {
            "status": "pending",
            "blocker": "kernel_cutover_required",
            "responsibilities": [],
            "completion_satisfied": completion.satisfied,
        }

    service = discharge_service_factory(runtime.store, bridge)
    try:
        handles = service.project_responsibility_set(case, obligation_set)
    except ResponsibilityDischargeBlocked as exc:
        return {
            "status": "pending",
            "blocker": str(exc),
            "responsibilities": [],
            "completion_satisfied": completion.satisfied,
        }

    client = bridge.client()
    observations: list[dict[str, Any]] = []
    for handle in handles:
        assessment_ref, decision_ref, transition_ref = service.discharge_chain_refs(
            case, handle
        )
        current_status = "unknown"
        blocker = None
        try:
            current_status = client.get_responsibility_status(
                handle.responsibility_ref,
                expected_version=handle.responsibility_version,
            ).current_status
        except KernelResponsibilityDischargeError:
            blocker = "kernel_responsibility_status_unavailable"
        observations.append(
            {
                "responsibility_ref": handle.responsibility_ref,
                "responsibility_version": handle.responsibility_version,
                "obligation_ids": [str(item) for item in handle.obligation_ids],
                "current_status": current_status,
                "assessment_ref": assessment_ref,
                "decision_ref": decision_ref,
                "transition_ref": transition_ref,
                "blocker": blocker,
            }
        )

    statuses = {item["current_status"] for item in observations}
    if not observations or statuses == {"discharged"}:
        overall = "discharged"
        blocker = None
    else:
        overall = "pending"
        blocker = next(
            (item["blocker"] for item in observations if item["blocker"]),
            "responsibility_set_not_discharged",
        )
    return {
        "status": overall,
        "blocker": blocker,
        "completion_satisfied": completion.satisfied,
        "responsibilities": observations,
    }


def assemble_case_detail(
    runtime: OperationsRuntime,
    case: AdministrativeCase,
    *,
    include_audit: bool,
) -> dict[str, Any]:
    obligation_set = runtime.obligations.get_current(case.case_id, case.authority_epoch)
    effects = runtime.execution.list_effects(case.case_id, case.authority_epoch)
    outcomes = runtime.execution.list_outcomes(case.case_id, case.authority_epoch)
    realizations = runtime.execution.list_realizations(case.case_id, case.authority_epoch)
    links = runtime.obligations.list_links(case.case_id, case.authority_epoch)
    fulfillments = runtime.obligations.list_domain_state_fulfillments(
        case.case_id, case.authority_epoch
    )
    completion = case_completion_assessment(
        obligation_set,
        effects,
        outcomes,
        realizations=realizations,
        links=links,
        fulfillments=fulfillments,
    )
    projections = KernelBridgeRepository(runtime.store).list_projections_for_case(case.case_id)
    transfers = TransferRequirementRepository(runtime.store).list_for_case(
        case.case_id, case.authority_epoch
    )
    authority = authority_snapshot(runtime, case)
    audit = runtime.store.list_audit_events(case.case_id) if include_audit else None
    commitment = None
    communications = []
    try:
        commitment = runtime.commitments.get_commitment(case.case_id)
        communications = runtime.commitments.list_communications(case.case_id)
    except OperationalError:
        commitment = None
        communications = []
    investigations = []
    reopen_history = []
    try:
        investigations = runtime.investigation_service.repository.list_requests(case.case_id)
        reopen_history = runtime.investigation_service.repository.list_reopen_records(case.case_id)
    except OperationalError:
        investigations = []
        reopen_history = []
    return {
        "case": case.model_dump(mode="json"),
        "commitment": commitment.model_dump(mode="json") if commitment is not None else None,
        "communications": [item.model_dump(mode="json") for item in communications],
        "policy": (
            evaluation.model_dump(mode="json")
            if (evaluation := runtime.store.get_latest_policy_evaluation(case.case_id)) is not None
            else None
        ),
        "governance": (
            basis.model_dump(mode="json")
            if (
                basis := runtime.governance.get_current_for_case(
                    case.case_id, case.authority_epoch
                )
            )
            is not None
            else None
        ),
        "obligations": obligation_set.model_dump(mode="json") if obligation_set else None,
        "effects": [item.model_dump(mode="json") for item in effects],
        "realizations": [
            item.model_dump(mode="json")
            for item in list_realizations(runtime.store, case.case_id)
        ],
        "outcomes": [item.model_dump(mode="json") for item in outcomes],
        "decisions": [
            item.model_dump(mode="json") for item in list_decisions(runtime.store, case.case_id)
        ],
        "authorizations": [
            item.model_dump(mode="json")
            for item in list_authorizations(runtime.store, case.case_id)
        ],
        "termination": termination_snapshot(case),
        "authority": authority,
        "transfers": [item.model_dump(mode="json") for item in transfers],
        "domain_fulfillments": [item.model_dump(mode="json") for item in fulfillments],
        "evidence_links": [
            item.model_dump(mode="json")
            for item in runtime.transactions.list_evidence_links(
                case.case_id, case.authority_epoch
            )
        ],
        "qualification_assessments": [
            item.model_dump(mode="json")
            for item in runtime.transactions.list_assessments(
                case.case_id, case.authority_epoch
            )
        ],
        "completion_assessment": completion.model_dump(mode="json"),
        "kernel_projections": [kernel_projection_snapshot(item) for item in projections],
        "responsibility_discharge": responsibility_snapshot(
            runtime,
            case,
            obligation_set,
            completion,
            projections,
        ),
        "investigations": [item.model_dump(mode="json") for item in investigations],
        "reopen_history": [item.model_dump(mode="json") for item in reopen_history],
        "audit": audit,
    }


def dedupe_json_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: dict[str, dict[str, Any]] = {}
    for record in records:
        key = repr(sorted(record.items()))
        unique[key] = record
    return [unique[key] for key in sorted(unique)]


__all__ = [
    "assemble_case_detail",
    "authority_snapshot",
    "case_completion_assessment",
    "dedupe_json_records",
    "kernel_projection_snapshot",
    "responsibility_snapshot",
    "termination_snapshot",
]
