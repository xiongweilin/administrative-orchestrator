from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from dbos import DBOS

from ..config import get_settings
from ..domain import CaseStatus, utcnow
from ..effect_provider import EffectProvider, HttpEffectProvider
from ..fact_acquisition import build_hris_source
from ..integrations.kernel.bridge import KernelExecutionBridge
from ..integrations.kernel.effect_provider import KernelCutoverEffectProvider
from ..integrations.kernel.onboarding import prepare_onboarding_kernel_shadow
from ..offboarding_execution import (
    OffboardingExecutionEngine,
    ProductionTrustOffboardingExecutionEngine,
)
from ..onboarding_execution import OnboardingExecutionEngine
from ..persistence import SqlStore
from ..production_trust_execution import ProductionTrustOnboardingExecutionEngine
from ..service import authoritative_effective_time
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


@DBOS.step(name="administrative_drive_offboarding_case")
def drive_offboarding_case_step(case_id: str) -> dict[str, Any]:
    settings = get_settings()
    store = SqlStore(settings.worker_database_url or settings.database_url)
    case = store.get_case(UUID(case_id))
    if case is None:
        raise ValueError(f"administrative case {case_id} not found")

    bridge: KernelExecutionBridge | None = None
    provider: EffectProvider = HttpEffectProvider(
        settings.sandbox_base_url,
        timeout_seconds=settings.provider_timeout_seconds,
    )
    if settings.kernel_bridge_mode != "disabled":
        bridge = KernelExecutionBridge(store, settings=settings)
        if bridge.cutover:
            provider = KernelCutoverEffectProvider(provider, bridge)

    hris_source = build_hris_source(settings)
    if hris_source is None:
        engine = OffboardingExecutionEngine(store, provider)
    else:
        engine = ProductionTrustOffboardingExecutionEngine(
            store,
            provider,
            hris_source=hris_source,
            max_fact_age_seconds=settings.authoritative_fact_max_age_seconds,
        )

    effective_at = authoritative_effective_time(case)
    before_effective = effective_at is not None and effective_at > utcnow()
    if settings.external_effects_enabled or before_effective:
        case = engine.run(UUID(case_id))
    elif case.status in {
        CaseStatus.AUTHORIZED,
        CaseStatus.WAITING,
        CaseStatus.EXECUTING,
        CaseStatus.VERIFYING,
        CaseStatus.RECONCILING,
    }:
        return {
            "case_id": case_id,
            "status": case.status.value,
            "case_version": case.version,
            "authority_epoch": case.authority_epoch,
            "reason": "external_effects_disabled",
            "next_qualified_action_at": effective_at.isoformat() if effective_at else None,
        }

    return {
        "case_id": case_id,
        "status": case.status.value,
        "case_version": case.version,
        "authority_epoch": case.authority_epoch,
        "next_qualified_action_at": effective_at.isoformat() if effective_at else None,
    }


@DBOS.workflow(name="administrative_offboarding_case_v1")
def offboarding_case_workflow(*, case_id: str) -> dict[str, Any]:
    while True:
        state = drive_offboarding_case_step(case_id)
        status = str(state["status"])
        if status in TERMINAL_STATUSES:
            return state
        timeout = _offboarding_wake_timeout(state)
        DBOS.recv(topic=CASE_CHANGED_TOPIC, timeout_seconds=timeout)


def _offboarding_wake_timeout(state: dict[str, Any]) -> float:
    status = str(state["status"])
    if status == CaseStatus.RECONCILING.value:
        return RECONCILIATION_POLL_SECONDS
    if status != CaseStatus.WAITING.value:
        return NORMAL_WAKE_TIMEOUT_SECONDS
    raw = state.get("next_qualified_action_at")
    if not isinstance(raw, str) or not raw:
        return NORMAL_WAKE_TIMEOUT_SECONDS
    try:
        target = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return NORMAL_WAKE_TIMEOUT_SECONDS
    seconds = (target - utcnow()).total_seconds()
    return max(0.1, seconds)


__all__ = [
    "drive_offboarding_case_step",
    "drive_onboarding_case_step",
    "offboarding_case_workflow",
    "onboarding_case_workflow",
    "_offboarding_wake_timeout",
]
