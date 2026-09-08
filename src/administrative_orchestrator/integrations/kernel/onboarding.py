from __future__ import annotations

from uuid import UUID

from ...authority import AuthorityRepository
from ...domain import CaseStatus
from ...governance import GovernanceRepository
from ...obligations import ObligationRepository, derive_onboarding_obligations
from ...persistence import SqlStore
from ...service import TransitionError
from .bridge import KernelExecutionBridge
from .models import KernelShadowProjection


_KERNEL_PROJECTABLE_STATUSES = frozenset(
    {
        CaseStatus.AUTHORIZED,
        CaseStatus.EXECUTING,
        CaseStatus.VERIFYING,
        CaseStatus.RECONCILING,
    }
)


def prepare_onboarding_kernel_shadow(
    store: SqlStore,
    case_id: UUID,
    *,
    bridge: KernelExecutionBridge | None = None,
) -> list[KernelShadowProjection]:
    """Create replay-stable Kernel shadow objects for one governed case.

    This function performs no physical effect.  It is safe to call before the
    legacy execution engine because obligation derivation and bridge identities
    are deterministic and append-only.
    """

    bridge = bridge or KernelExecutionBridge(store)
    if not bridge.enabled:
        return []

    case = store.get_case(case_id)
    if case is None:
        raise KeyError(f"case {case_id} not found")
    if case.status not in _KERNEL_PROJECTABLE_STATUSES:
        return []

    evaluation = store.get_latest_policy_evaluation(case.case_id)
    if evaluation is None or evaluation.policy_ref != case.policy_ref:
        raise TransitionError("kernel bridge requires the current policy evaluation")

    authority = AuthorityRepository(store)
    satisfaction = authority.get_approval_satisfaction(case.case_id, case.authority_epoch)
    if satisfaction is None:
        raise TransitionError("kernel bridge requires current approval satisfaction")
    if satisfaction.policy_ref != case.policy_ref:
        raise TransitionError("kernel bridge approval satisfaction policy is stale")
    if not set(evaluation.required_decision_roles).issubset(set(satisfaction.satisfied_roles)):
        raise TransitionError("kernel bridge approval satisfaction does not cover required roles")

    governance_repo = GovernanceRepository(store)
    governance = governance_repo.get_for_approval(satisfaction.satisfaction_id)
    if governance is None:
        raise TransitionError("kernel bridge requires a dependency-scoped governance basis")
    validation = governance_repo.revalidate(governance, case)
    if not validation.valid:
        raise TransitionError(
            "kernel bridge governance basis is stale: " + "; ".join(validation.reasons)
        )

    obligations = ObligationRepository(store)
    obligation_set = obligations.get_current(case.case_id, case.authority_epoch)
    if obligation_set is None:
        obligation_set = derive_onboarding_obligations(
            case,
            evaluation,
            governance_basis_id=governance.basis_id,
        )
        obligations.put(obligation_set)
    elif obligation_set.governance_basis_id != governance.basis_id:
        raise TransitionError("kernel bridge obligation set binds a different governance basis")

    projections: list[KernelShadowProjection] = []
    for obligation in obligation_set.obligations:
        projection = bridge.prepare(case, obligation, governance)
        if projection is not None:
            projections.append(projection)
    return projections


__all__ = ["prepare_onboarding_kernel_shadow"]
