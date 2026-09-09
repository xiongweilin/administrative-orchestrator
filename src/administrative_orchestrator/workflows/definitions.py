from __future__ import annotations

from typing import Any
from uuid import UUID

from dbos import DBOS

from ..config import get_settings
from ..domain import CaseStatus
from ..effect_provider import EffectProvider, HttpEffectProvider
from ..fact_acquisition import build_hris_source
from ..integrations.kernel.bridge import KernelExecutionBridge
from ..integrations.kernel.effect_provider import KernelCutoverEffectProvider
from ..integrations.kernel.onboarding import prepare_onboarding_kernel_shadow
from ..onboarding_execution import OnboardingExecutionEngine
from ..persistence import SqlStore
from ..production_trust_execution import ProductionTrustOnboardingExecutionEngine
from .protocol import (
    CASE_CHANGED_TOPIC,
    NORMAL_WAKE_TIMEOUT_SECONDS,
    RECONCILIATION_POLL_SECONDS,
)

TERMINAL_STATUSES = frozenset(
    {
        CaseStatus.COMPLETED.value,
        CaseStatus.CANCELLED.value,
        CaseStatus.FAILED.value,
    }
)


@DBOS.step(name="administrative_drive_onboarding_case")
def drive_onboarding_case_step(case_id: str) -> dict[str, Any]:
    """Drive one durable business transition with capability-scoped reality ownership."""
    settings = get_settings()
    store = SqlStore(settings.worker_database_url or settings.database_url)
    case = store.get_case(UUID(case_id))
    if case is None:
        raise ValueError(f"administrative case {case_id} not found")

    if case.status in {
        CaseStatus.AUTHORIZED,
        CaseStatus.EXECUTING,
        CaseStatus.VERIFYING,
        CaseStatus.RECONCILING,
    }:
        bridge: KernelExecutionBridge | None = None
        if settings.kernel_bridge_mode != "disabled":
            bridge = KernelExecutionBridge(store, settings=settings)
            prepare_onboarding_kernel_shadow(store, UUID(case_id), bridge=bridge)

        if not settings.external_effects_enabled:
            return {
                "case_id": case_id,
                "status": CaseStatus.WAITING.value,
                "case_version": case.version,
                "authority_epoch": case.authority_epoch,
                "reason": "external_effects_disabled",
            }
        provider: EffectProvider = HttpEffectProvider(
            settings.sandbox_base_url,
            timeout_seconds=settings.provider_timeout_seconds,
        )
        if bridge is not None and bridge.cutover:
            provider = KernelCutoverEffectProvider(provider, bridge)

        hris_source = build_hris_source(settings)
        if hris_source is None:
            engine = OnboardingExecutionEngine(store, provider)
        else:
            engine = ProductionTrustOnboardingExecutionEngine(
                store,
                provider,
                hris_source=hris_source,
                max_fact_age_seconds=settings.authoritative_fact_max_age_seconds,
            )
        case = engine.run(UUID(case_id))

    return {
        "case_id": case_id,
        "status": case.status.value,
        "case_version": case.version,
        "authority_epoch": case.authority_epoch,
    }


@DBOS.workflow(name="administrative_onboarding_case_v1")
def onboarding_case_workflow(*, case_id: str) -> dict[str, Any]:
    """Durably wait and re-drive one AdministrativeCase until terminal.

    DBOS owns waiting/replay only. AdministrativeCase remains the sole business
    state machine and all authority/effect semantics stay outside this module.
    """
    while True:
        state = drive_onboarding_case_step(case_id)
        status = str(state["status"])
        if status in TERMINAL_STATUSES:
            return state

        timeout = (
            RECONCILIATION_POLL_SECONDS
            if status == CaseStatus.RECONCILING.value
            else NORMAL_WAKE_TIMEOUT_SECONDS
        )
        DBOS.recv(topic=CASE_CHANGED_TOPIC, timeout_seconds=timeout)


__all__ = ["drive_onboarding_case_step", "onboarding_case_workflow"]
