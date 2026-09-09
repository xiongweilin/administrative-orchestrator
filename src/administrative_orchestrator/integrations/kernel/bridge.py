from __future__ import annotations

from ...config import Settings, get_settings
from ...domain import AdministrativeCase
from ...governance import GovernanceBasis
from ...obligations import AdministrativeObligation
from ...persistence import SqlStore
from .client import HttpKernelResponsibilityClient, KernelResponsibilityClient
from .compatibility import HttpKernelContractProbe, KernelCompatibilityError, KernelContractIdentity
from .mapper import capability_for, derive_effect_intent, derive_execution_grant, project_to_kernel
from .models import KernelProjectionStatus, KernelShadowProjection
from .repository import KernelBridgeRepository

# First physical cutover is deliberately capability-scoped. A second capability
# must prove this runtime seam is generic before this set is expanded.
KERNEL_CUTOVER_CAPABILITIES = frozenset({"administrative.hris.employee.create.v1"})


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
    ) -> None:
        self.store = store
        self.settings = settings or get_settings()
        self.repository = KernelBridgeRepository(store)
        self._compatibility = compatibility
        self._client = client

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

    def owns(self, obligation: AdministrativeObligation) -> bool:
        return self.cutover and capability_for(obligation) in KERNEL_CUTOVER_CAPABILITIES

    def compatibility(self) -> KernelContractIdentity:
        if not self.enabled:
            raise KernelCompatibilityError("kernel bridge is disabled")
        if self._compatibility is None:
            self._compatibility = HttpKernelContractProbe(
                self.settings.kernel_base_url,
                timeout_seconds=self.settings.kernel_contract_timeout_seconds,
                require_work_admission=self.requires_work_admission,
                require_domain_effect_execution=self.cutover,
            ).fetch_identity()
        if (
            self.requires_work_admission
            and self._compatibility.responsibility_work_admission_contract is None
        ):
            raise KernelCompatibilityError(
                "kernel admission/cutover mode requires responsibility-work-admission-v1"
            )
        if self.cutover and self._compatibility.bounded_domain_effect_execution_contract is None:
            raise KernelCompatibilityError(
                "kernel cutover requires bounded-domain-effect-execution-v1"
            )
        return self._compatibility

    def client(self) -> KernelResponsibilityClient:
        if self._client is None:
            self._client = HttpKernelResponsibilityClient(
                self.settings.kernel_base_url,
                timeout_seconds=self.settings.kernel_contract_timeout_seconds,
            )
        return self._client

    def prepare(
        self,
        case: AdministrativeCase,
        obligation: AdministrativeObligation,
        governance: GovernanceBasis,
    ) -> KernelShadowProjection | None:
        if not self.enabled:
            return None

        identity = self.compatibility()
        grant = self.repository.put_grant(
            derive_execution_grant(case, obligation, governance)
        )
        intent = self.repository.put_intent(derive_effect_intent(case, grant))
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
            # because the business obligation remains unresolved.
            return projection

        execution = self.client().execute(projection, grant, intent)
        return self.repository.mark_execution(projection, execution)

    def projection_for_obligation(
        self,
        obligation: AdministrativeObligation,
    ) -> KernelShadowProjection | None:
        return self.repository.get_projection_for_obligation(obligation.obligation_id)


__all__ = ["KERNEL_CUTOVER_CAPABILITIES", "KernelExecutionBridge"]
