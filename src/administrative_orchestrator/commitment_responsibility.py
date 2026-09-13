from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import uuid5

from .commitment_common import M9_NAMESPACE, CommitmentIntakeError, ResponsibilityRefs
from .commitment_models import CommitmentRecord
from .config import Settings
from .domain import AdministrativeCase
from .integrations.kernel.bridge import KernelExecutionBridge
from .integrations.kernel.client import KernelSubmissionError


class KernelCommitmentResponsibilityProvisioner:
    """Submit the generic responsibility prefix without admitting Work."""

    def __init__(
        self,
        store,
        *,
        settings: Settings,
        bridge_factory: Callable[..., KernelExecutionBridge] = KernelExecutionBridge,
    ) -> None:
        self.store = store
        self.settings = settings
        self.bridge_factory = bridge_factory

    def provision(
        self,
        *,
        case: AdministrativeCase,
        commitment: CommitmentRecord,
        governance_basis: Any,
    ) -> ResponsibilityRefs:
        if case.policy_ref is None:
            raise CommitmentIntakeError("Kernel responsibility requires a current policy")
        bridge = self.bridge_factory(
            self.store,
            settings=self.settings,
            require_responsibility_discharge=True,
        )
        identity = bridge.compatibility()
        root = uuid5(M9_NAMESPACE, f"kernel-responsibility:{commitment.commitment_id}")
        responsibility_ref = f"m9resp_{root.hex}"
        admission_ref = f"m9admission_{uuid5(M9_NAMESPACE, f'admission:{root}').hex}"
        assessment_ref = f"m9assessment_{uuid5(M9_NAMESPACE, f'assessment:{root}').hex}"
        proposal_ref = f"m9proposal_{uuid5(M9_NAMESPACE, f'proposal:{root}').hex}"
        created_at = commitment.created_at.isoformat()
        policy_ref = f"{case.policy_ref.policy_id}:{case.policy_ref.version}"
        responsibility = {
            "id": responsibility_ref,
            "object_type": "StandingResponsibility",
            "created_at": created_at,
            "responsibility_kind": "administrative-commitment",
            "statement": "Maintain one admitted administrative responsibility until explicit discharge.",
            "scope": {
                "administrative_case_id": str(case.case_id),
                "authority_epoch": str(case.authority_epoch),
                "commitment_ref": str(commitment.commitment_id),
                "governance_basis_id": str(governance_basis.basis_id),
                "policy_ref": policy_ref,
            },
            "schema_version": identity.persistent_responsibility_contract,
        }
        admission = {
            "id": admission_ref,
            "object_type": "ResponsibilityAdmission",
            "created_at": created_at,
            "responsibility_ref": responsibility_ref,
            "responsibility_version": 1,
            "principal_ref": commitment.committer_principal_id,
            "basis_refs": [
                f"commitment:{commitment.commitment_id}",
                f"governance-basis:{governance_basis.basis_id}",
                f"approval-satisfaction:{governance_basis.approval_satisfaction_id}",
            ],
            "admitted_at": created_at,
        }
        assessment = {
            "id": assessment_ref,
            "object_type": "ResponsibilityAssessment",
            "created_at": created_at,
            "responsibility_ref": responsibility_ref,
            "responsibility_version": 1,
            "subject_ref": commitment.committer_principal_id,
            "assessment_kind": "administrative-commitment-ready",
            "basis_refs": [
                f"commitment:{commitment.commitment_id}",
                f"governance-basis:{governance_basis.basis_id}",
            ],
            "assessed_at": created_at,
            "rationale": "Administrative policy, identity, approval and due time are qualified.",
        }
        proposal = {
            "id": proposal_ref,
            "object_type": "WorkProposal",
            "created_at": created_at,
            "responsibility_ref": responsibility_ref,
            "responsibility_version": 1,
            "assessment_ref": assessment_ref,
            "subject_ref": commitment.committer_principal_id,
            "work_kind": "administrative-commitment",
            "title": "Maintain admitted administrative responsibility",
            "description": "Proposal prefix only; M9 does not admit Kernel Work for a meeting commitment.",
            "requested_resources": {
                "compute_units": 0,
                "api_calls": 0,
                "money_minor": 0,
                "human_attention_units": 0,
                "concurrency_slots": 0,
                "domain_quota": {},
            },
            "requested_capabilities": [],
            "expected_result": "explicit responsibility discharge after fulfillment assessment",
            "stop_conditions": [f"administrative-authority-epoch-changed:{case.case_id}"],
            "escalation_conditions": ["responsibility-discharge-basis-insufficient"],
            "effect_class": "read-only",
        }
        try:
            receipt = bridge.client().submit_payload(
                responsibility_payload=responsibility,
                admission_payload=admission,
                assessment_payload=assessment,
                proposal_payload=proposal,
            )
        except KernelSubmissionError as exc:
            raise CommitmentIntakeError(
                "Kernel responsibility proposal was not recorded"
            ) from exc
        return ResponsibilityRefs(
            responsibility_ref=receipt.responsibility_ref,
            responsibility_version=1,
            admission_ref=receipt.admission_ref,
            assessment_ref=receipt.assessment_ref,
            proposal_ref=receipt.proposal_ref,
        )


__all__ = ["KernelCommitmentResponsibilityProvisioner"]
