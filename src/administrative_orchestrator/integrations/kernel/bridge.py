from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ...authority import AuthorityRepository
from ...config import Settings, get_settings
from ...domain import AdministrativeCase, EffectRecord
from ...governance import GovernanceBasis, GovernanceRepository
from ...obligations import AdministrativeObligation, ObligationRepository
from ...persistence import SqlStore
from .capabilities import (
    ADMINISTRATIVE_HRIS_EMPLOYEE_CREATE,
    ADMINISTRATIVE_IAM_IDENTITY_CREATE,
    FINANCIAL_CUTOVER_CAPABILITIES,
    OFFBOARDING_CUTOVER_CAPABILITIES,
)
from .client import HttpKernelResponsibilityClient, KernelResponsibilityClient
from .compatibility import (
    EXPECTED_RESPONSIBILITY_ASSESSMENT_RECORD,
    EXPECTED_RESPONSIBILITY_DISCHARGE_DECISION_RECORD,
    EXPECTED_RESPONSIBILITY_LIFECYCLE_TRANSITION_APPLY,
    EXPECTED_RESPONSIBILITY_STATUS_VIEW,
    HttpKernelContractProbe,
    KernelCompatibilityError,
    KernelContractIdentity,
)
from .evidence import HttpKernelEvidenceClient, KernelEvidenceClient
from .mapper import capability_for, derive_effect_intent, derive_execution_grant, project_to_kernel
from .models import KernelProjectionStatus, KernelShadowProjection
from .recovery import HttpKernelRecoveryClient, KernelRecoveryClient
from .repository import KernelBridgeRepository

# Physical execution ownership is capability-scoped. HRIS proved the first
# cutover; IAM is the second capability proving the same Kernel runtime seam is
# generic rather than HRIS-specific.
KERNEL_CUTOVER_CAPABILITIES = frozenset(
    {
        ADMINISTRATIVE_HRIS_EMPLOYEE_CREATE,
        ADMINISTRATIVE_IAM_IDENTITY_CREATE,
        *OFFBOARDING_CUTOVER_CAPABILITIES,
        *FINANCIAL_CUTOVER_CAPABILITIES,
    }
)


class KernelExecutionBridge:
    """Hand governed administrative work into Agent Kernel action semantics.

    `shadow` records/submits only the canonical proposal prefix. `admission`
    additionally asks Kernel to materialize Work. `cutover` does the same for
    every projected obligation, but transfers physical execution ownership only
    for explicitly cut-over capabilities. Non-owned capabilities remain on the
    legacy Administrative provider path.
    """

    def __init__(
        self,
        store: SqlStore,
        *,
        settings: Settings | None = None,
        compatibility: KernelContractIdentity | None = None,
        client: KernelResponsibilityClient | None = None,
        evidence_client: KernelEvidenceClient | None = None,
        recovery_client: KernelRecoveryClient | None = None,
        require_responsibility_discharge: bool = False,
    ) -> None:
        self.store = store
        self.settings = settings or get_settings()
        self.repository = KernelBridgeRepository(store)
        self._compatibility = compatibility
        self._client = client
        self._evidence_client = evidence_client
        self._recovery_client = recovery_client
        self._require_responsibility_discharge = require_responsibility_discharge
        self._external_operation_refs: dict[str, str] = {}

    @property
    def enabled(self) -> bool:
        return self.settings.kernel_bridge_mode != "disabled"

    @property
    def shadow_only(self) -> bool:
        return self.settings.kernel_bridge_mode == "shadow"

    @property
    def admission_shadow(self) -> bool:
        return self.settings.kernel_bridge_mode == "admission"

    @property
    def cutover(self) -> bool:
        return self.settings.kernel_bridge_mode == "cutover"

    @property
    def requires_work_admission(self) -> bool:
        return self.settings.kernel_bridge_mode in {"admission", "cutover"}

    @property
    def requires_responsibility_discharge(self) -> bool:
        return self._require_responsibility_discharge

    def owns(self, obligation: AdministrativeObligation) -> bool:
        return self.cutover and capability_for(obligation) in KERNEL_CUTOVER_CAPABILITIES

    def compatibility(self) -> KernelContractIdentity:
        if not self.enabled:
            raise KernelCompatibilityError("kernel bridge is disabled")
        if self._compatibility is None:
            self._compatibility = HttpKernelContractProbe(
                self.settings.kernel_base_url,
                timeout_seconds=self.settings.kernel_contract_timeout_seconds,
                expected_build_revision=(
                    self.settings.kernel_supported_revision.strip() or None
                ),
                require_build_revision=self.settings.runtime_profile
                in {"staging", "production"},
                require_work_admission=self.requires_work_admission,
                require_responsibility_discharge=self.requires_responsibility_discharge,
                require_domain_effect_execution=self.cutover,
                require_domain_effect_recovery=self.cutover,
                require_domain_effect_evidence=self.cutover,
            ).fetch_identity()
        if (
            self.requires_work_admission
            and self._compatibility.responsibility_work_admission_contract is None
        ):
            raise KernelCompatibilityError(
                "kernel admission/cutover mode requires responsibility-work-admission-v1"
            )
        if self.requires_responsibility_discharge:
            expected_discharge = (
                (
                    self._compatibility.responsibility_assessment_record_contract,
                    EXPECTED_RESPONSIBILITY_ASSESSMENT_RECORD,
                ),
                (
                    self._compatibility.responsibility_discharge_decision_record_contract,
                    EXPECTED_RESPONSIBILITY_DISCHARGE_DECISION_RECORD,
                ),
                (
                    self._compatibility.responsibility_lifecycle_transition_apply_contract,
                    EXPECTED_RESPONSIBILITY_LIFECYCLE_TRANSITION_APPLY,
                ),
                (
                    self._compatibility.responsibility_status_view_contract,
                    EXPECTED_RESPONSIBILITY_STATUS_VIEW,
                ),
            )
            if any(actual != expected for actual, expected in expected_discharge):
                raise KernelCompatibilityError(
                    "kernel offboarding discharge requires all responsibility discharge contracts"
                )
        if self.cutover and self._compatibility.bounded_domain_effect_execution_contract is None:
            raise KernelCompatibilityError(
                "kernel cutover is fail-closed without bounded-domain-effect-execution-v1"
            )
        if self.cutover and (
            self._compatibility.bounded_domain_effect_recovery_contract is None
            or self._compatibility.bounded_domain_effect_resolution_view is None
        ):
            raise KernelCompatibilityError(
                "kernel cutover is fail-closed without bounded-domain-effect recovery/resolution v1"
            )
        if self.cutover and self._compatibility.domain_effect_verification_evidence_view is None:
            raise KernelCompatibilityError(
                "kernel cutover is fail-closed without domain-effect-verification-evidence-view-v1"
            )
        return self._compatibility

    def client(self) -> KernelResponsibilityClient:
        if self._client is None:
            self._client = HttpKernelResponsibilityClient(
                self.settings.kernel_base_url,
                timeout_seconds=self.settings.kernel_contract_timeout_seconds,
            )
        return self._client

    def evidence_client(self) -> KernelEvidenceClient:
        if self._evidence_client is None:
            self._evidence_client = HttpKernelEvidenceClient(
                self.settings.kernel_base_url,
                timeout_seconds=self.settings.kernel_contract_timeout_seconds,
            )
        return self._evidence_client

    def recovery_client(self) -> KernelRecoveryClient:
        if self._recovery_client is None:
            self._recovery_client = HttpKernelRecoveryClient(
                self.settings.kernel_base_url,
                timeout_seconds=self.settings.kernel_contract_timeout_seconds,
            )
        return self._recovery_client

    def prepare(
        self,
        case: AdministrativeCase,
        obligation: AdministrativeObligation,
        governance: GovernanceBasis,
        *,
        parameter_overrides: Mapping[str, Any] | None = None,
    ) -> KernelShadowProjection | None:
        if not self.enabled:
            return None

        identity = self.compatibility()
        grant = self.repository.put_grant(
            derive_execution_grant(case, obligation, governance)
        )
        intent = self.repository.put_intent(
            derive_effect_intent(
                case,
                grant,
                parameter_overrides=parameter_overrides,
            )
        )
        planned = project_to_kernel(grant, intent, identity)
        projection = self.repository.put_projection(planned)

        if projection.status is KernelProjectionStatus.SHADOW:
            receipt = self.client().submit(projection)
            projection = self.repository.mark_submitted(projection, receipt)

        if self.shadow_only:
            return projection

        if self.requires_work_admission and projection.status is KernelProjectionStatus.SUBMITTED:
            receipt = self.client().admit(
                projection,
                expected_policy_ref=self.settings.kernel_responsibility_admission_policy_ref,
            )
            projection = self.repository.mark_work_admission(projection, receipt)

        if self.admission_shadow or projection.status is KernelProjectionStatus.REJECTED:
            return projection

        if not self.cutover or not self.owns(obligation):
            return projection

        if projection.status is KernelProjectionStatus.CUTOVER:
            return projection
        if projection.status is not KernelProjectionStatus.ADMITTED:
            raise KernelCompatibilityError(
                f"kernel physical execution cannot continue from {projection.status.value}"
            )
        if projection.kernel_execution_status is not None:
            # A non-completed receipt is still a durable execution fact. Never
            # redispatch through either Kernel or the legacy provider merely
            # because the business obligation remains unresolved. Recovery, if
            # eligible, is a separate Kernel-owned authority path.
            return projection
        if not self.settings.external_effects_enabled:
            # Projection and Work admission may proceed while global physical
            # effects are disabled, but neither Kernel nor the legacy provider
            # may cross reality under that deployment state.
            return projection

        execution = self.client().execute(projection, grant, intent)
        if execution.external_operation_ref:
            self._external_operation_refs[str(projection.projection_id)] = (
                execution.external_operation_ref
            )
        return self.repository.mark_execution(projection, execution)

    def external_operation_ref_for(
        self,
        projection: KernelShadowProjection | None,
    ) -> str | None:
        if projection is None:
            return None
        return self._external_operation_refs.get(str(projection.projection_id))

    def prepare_effect(
        self,
        effect: EffectRecord,
        payload: Mapping[str, Any],
    ) -> KernelShadowProjection | None:
        """Prepare and execute one effect with its final dispatch payload.

        Financial effects are dependency ordered by the Administrative engine.
        Their Kernel projections therefore cannot all be materialized from the
        case fact snapshot before dispatch: a purchase-order confirmation needs
        the durable provider reference returned by the preceding draft effect.
        This entry point creates the projection just-in-time, so that frozen
        Kernel intent parameters include that dependency without rebinding an
        existing intent.
        """

        if effect.obligation_id is None:
            raise KernelCompatibilityError("Kernel-owned effect lacks an obligation identity")
        case = self.store.get_case(effect.case_id)
        if case is None:
            raise KernelCompatibilityError(f"case {effect.case_id} not found for Kernel effect")
        if case.authority_epoch != effect.authority_epoch:
            raise KernelCompatibilityError("Kernel effect authority epoch is stale")

        evaluation = self.store.get_latest_policy_evaluation(case.case_id)
        if evaluation is None or evaluation.policy_ref != case.policy_ref:
            raise KernelCompatibilityError("Kernel effect requires the current policy evaluation")
        satisfaction = AuthorityRepository(self.store).get_approval_satisfaction(
            case.case_id,
            case.authority_epoch,
        )
        if satisfaction is None or satisfaction.policy_ref != case.policy_ref:
            raise KernelCompatibilityError("Kernel effect requires current approval satisfaction")
        if not set(evaluation.required_decision_roles).issubset(
            set(satisfaction.satisfied_roles)
        ):
            raise KernelCompatibilityError(
                "Kernel effect approval satisfaction does not cover required roles"
            )
        governance = GovernanceRepository(self.store).get_for_approval(
            satisfaction.satisfaction_id
        )
        if governance is None:
            raise KernelCompatibilityError("Kernel effect requires a governance basis")
        validation = GovernanceRepository(self.store).revalidate(governance, case)
        if not validation.valid:
            raise KernelCompatibilityError(
                "Kernel effect governance basis is stale: "
                + "; ".join(validation.reasons)
            )

        obligation_set = ObligationRepository(self.store).get_current(
            case.case_id,
            case.authority_epoch,
        )
        if obligation_set is None:
            raise KernelCompatibilityError("Kernel effect requires a current obligation set")
        obligation = next(
            (
                item
                for item in obligation_set.obligations
                if item.obligation_id == effect.obligation_id
            ),
            None,
        )
        if obligation is None:
            raise KernelCompatibilityError("Kernel effect obligation is not in the current set")
        if (
            obligation.target_system != effect.target_system
            or obligation.required_operation != effect.operation
            or obligation.subject_ref != effect.subject_ref
            or obligation.authority_class != effect.authority_class
        ):
            raise KernelCompatibilityError("Kernel effect does not implement its obligation")

        return self.prepare(
            case,
            obligation,
            governance,
            parameter_overrides=payload,
        )

    def projection_for_obligation(
        self,
        obligation: AdministrativeObligation,
    ) -> KernelShadowProjection | None:
        return self.repository.get_projection_for_obligation(obligation.obligation_id)


__all__ = ["KERNEL_CUTOVER_CAPABILITIES", "KernelExecutionBridge"]
