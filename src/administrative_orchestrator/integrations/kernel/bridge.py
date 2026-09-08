from __future__ import annotations

from ...config import Settings, get_settings
from ...domain import AdministrativeCase
from ...governance import GovernanceBasis
from ...obligations import AdministrativeObligation
from ...persistence import SqlStore
from .client import HttpKernelResponsibilityClient, KernelResponsibilityClient
from .compatibility import HttpKernelContractProbe, KernelCompatibilityError, KernelContractIdentity
from .mapper import derive_effect_intent, derive_execution_grant, project_to_kernel
from .models import KernelProjectionStatus, KernelShadowProjection
from .repository import KernelBridgeRepository


class KernelExecutionBridge:
    """Hand governed administrative work into Agent Kernel responsibility semantics.

    `shadow` records/submits only the canonical proposal prefix. `admission`
    additionally asks Kernel to evaluate that proposal through its own priority,
    portfolio, reservation, commitment, and Work chain. Neither mode creates
    runtime authorization, InvocationPermit, provider execution, or Outcome.
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

    def compatibility(self) -> KernelContractIdentity:
        if not self.enabled:
            raise KernelCompatibilityError("kernel bridge is disabled")
        if self._compatibility is None:
            self._compatibility = HttpKernelContractProbe(
                self.settings.kernel_base_url,
                timeout_seconds=self.settings.kernel_contract_timeout_seconds,
                require_work_admission=self.admission_shadow,
            ).fetch_identity()
        if (
            self.admission_shadow
            and self._compatibility.responsibility_work_admission_contract is None
        ):
            raise KernelCompatibilityError(
                "kernel admission mode requires responsibility-work-admission-v1"
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
        if self.settings.kernel_bridge_mode == "cutover":
            raise KernelCompatibilityError(
                "kernel cutover is fail-closed until runtime authorization and the unique "
                "Kernel RealityBoundary path are configured"
            )

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

        if self.admission_shadow:
            if projection.status in {
                KernelProjectionStatus.ADMITTED,
                KernelProjectionStatus.REJECTED,
            }:
                return projection
            if projection.status is not KernelProjectionStatus.SUBMITTED:
                raise KernelCompatibilityError(
                    f"kernel Work admission cannot continue from {projection.status.value}"
                )
            receipt = self.client().admit(
                projection,
                expected_policy_ref=(
                    self.settings.kernel_responsibility_admission_policy_ref
                ),
            )
            return self.repository.mark_work_admission(projection, receipt)

        return projection


__all__ = ["KernelExecutionBridge"]
