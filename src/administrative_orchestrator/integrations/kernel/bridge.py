from __future__ import annotations

from ...config import Settings, get_settings
from ...domain import AdministrativeCase
from ...governance import GovernanceBasis
from ...obligations import AdministrativeObligation
from ...persistence import SqlStore
from .compatibility import HttpKernelContractProbe, KernelCompatibilityError, KernelContractIdentity
from .mapper import derive_effect_intent, derive_execution_grant, project_to_kernel
from .models import KernelShadowProjection
from .repository import KernelBridgeRepository


class KernelExecutionBridge:
    """Project governed administrative work into Agent Kernel contracts.

    Shadow mode is intentionally non-executing: it persists the exact business
    grant/effect intent and the public persistent-responsibility payloads that a
    later Kernel command surface will consume.  It never calls a provider and
    never mints Work, runtime authorization, InvocationPermit, or Outcome.
    """

    def __init__(
        self,
        store: SqlStore,
        *,
        settings: Settings | None = None,
        compatibility: KernelContractIdentity | None = None,
    ) -> None:
        self.store = store
        self.settings = settings or get_settings()
        self.repository = KernelBridgeRepository(store)
        self._compatibility = compatibility

    @property
    def enabled(self) -> bool:
        return self.settings.kernel_bridge_mode != "disabled"

    @property
    def shadow_only(self) -> bool:
        return self.settings.kernel_bridge_mode == "shadow"

    def compatibility(self) -> KernelContractIdentity:
        if not self.enabled:
            raise KernelCompatibilityError("kernel bridge is disabled")
        if self._compatibility is None:
            self._compatibility = HttpKernelContractProbe(
                self.settings.kernel_base_url,
                timeout_seconds=self.settings.kernel_contract_timeout_seconds,
            ).fetch_identity()
        return self._compatibility

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
                "kernel cutover is fail-closed until the responsibility admission/Work command "
                "surface is configured; shadow projection cannot become physical execution"
            )

        identity = self.compatibility()
        grant = self.repository.put_grant(
            derive_execution_grant(case, obligation, governance)
        )
        intent = self.repository.put_intent(derive_effect_intent(case, grant))
        projection = project_to_kernel(grant, intent, identity)
        return self.repository.put_projection(projection)


__all__ = ["KernelExecutionBridge"]
