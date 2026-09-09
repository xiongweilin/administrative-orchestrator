from __future__ import annotations

import asyncio
import os
from pathlib import Path

import httpx
from kernel_cutover_stack import IAM_CAPABILITY, SandboxAdministrativeProvider
from portable_runtime.core.models import Event
from portable_runtime.core.reconciliation_repeatability import (
    ReconciliationRepeatabilityConfiguration,
    reconciliation_repeatability_authority_from_dispatch,
)
from portable_runtime.core.registry import ProviderRegistry
from portable_runtime.governance.dispatch import DISPATCH_COMMIT_EVENT
from portable_runtime.governance.provider_execution_binding import (
    provider_execution_binding_from_dispatch,
)
from portable_runtime.responsibility.domain_effect_authorization import (
    ADMINISTRATIVE_HRIS_EMPLOYEE_CREATE,
)
from portable_runtime.stores.invocation_specification import (
    InvocationSpecificationSQLiteStateStore,
)


EFFECT_PROVIDERS = {
    "provider:admin-e2e:hris": (
        ADMINISTRATIVE_HRIS_EMPLOYEE_CREATE,
        "hris",
        "employee.create",
        "hris",
    ),
    "provider:admin-e2e:iam": (
        IAM_CAPABILITY,
        "iam",
        "identity.create",
        "iam",
    ),
}


def _kernel_state_path() -> Path:
    value = os.environ.get("PORTABLE_RUNTIME_ADMIN_E2E_STATE_PATH")
    if not value:
        raise AssertionError("PORTABLE_RUNTIME_ADMIN_E2E_STATE_PATH is required")
    return Path(value).resolve()


def _sandbox_base_url() -> str:
    return os.getenv("ADMIN_SANDBOX_BASE_URL", "http://127.0.0.1:8010").rstrip("/")


def _effect_dispatches(store: InvocationSpecificationSQLiteStateStore) -> list[Event]:
    events: list[Event] = []
    for raw in store.export_state().get("event", []):
        event = Event.model_validate(raw)
        payload = event.payload if isinstance(event.payload, dict) else {}
        if event.type == DISPATCH_COMMIT_EVENT and payload.get("provider_id") in EFFECT_PROVIDERS:
            events.append(event)
    if not events:
        raise AssertionError("Kernel state contains no Administrative effect dispatches")
    return events


def _repeat_safe_reconciliation() -> ReconciliationRepeatabilityConfiguration:
    return ReconciliationRepeatabilityConfiguration(
        reconciliation_protocol_identity="administrative-sandbox-request-readback",
        reconciliation_protocol_version="1",
        repeatability_mode="repeat-safe",
        contract_version="1",
    )


def _fresh_registry(provider_id: str) -> tuple[ProviderRegistry, SandboxAdministrativeProvider]:
    capability, target_system, operation, configured_name = EFFECT_PROVIDERS[provider_id]
    provider = SandboxAdministrativeProvider(
        provider_id=provider_id,
        capability=capability,
        target_system=target_system,
        operation=operation,
    )
    registry = ProviderRegistry()
    registry.register(
        provider,
        configured_execution_identity=f"configured:administrative-sandbox:{configured_name}",
        authoritative_configuration_ref=f"config:administrative-sandbox:{configured_name}:v1",
        reconciliation_repeatability=_repeat_safe_reconciliation(),
    )
    return registry, provider


def _sandbox_observation(request_id: str) -> dict[str, object]:
    response = httpx.get(
        f"{_sandbox_base_url()}/v1/reconciliation/effects/{request_id}",
        timeout=5.0,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise AssertionError("sandbox reconciliation observation must be an object")
    return payload


async def _prove_dispatch(event: Event) -> None:
    payload = event.payload if isinstance(event.payload, dict) else {}
    provider_id = payload.get("provider_id")
    request_id = payload.get("request_id")
    if not isinstance(provider_id, str) or provider_id not in EFFECT_PROVIDERS:
        raise AssertionError("dispatch provider identity is invalid")
    if not isinstance(request_id, str) or not request_id:
        raise AssertionError("dispatch request identity is invalid")

    historical_binding = provider_execution_binding_from_dispatch(event)
    historical_repeatability = reconciliation_repeatability_authority_from_dispatch(event)
    if historical_binding.provider_id != provider_id:
        raise AssertionError("historical ProviderExecutionBinding provider mismatch")
    if historical_repeatability.subject_identity != request_id:
        raise AssertionError("historical reconciliation authority request binding mismatch")

    registry, provider = _fresh_registry(provider_id)
    resolved = registry.resolve_execution_binding(historical_binding)
    if resolved is not provider:
        raise AssertionError("fresh registry could not resolve the exact historical provider target")
    eligibility = registry.reconciliation_repeatability_eligibility(
        historical_repeatability,
        historical_binding,
        required_subject_identity=request_id,
    )
    if not eligibility.eligible or eligibility.status != "eligible":
        raise AssertionError(f"historical reconciliation authority is not eligible: {eligibility.reason}")

    before = _sandbox_observation(request_id)
    result = await provider.reconcile(request_id)
    after = _sandbox_observation(request_id)
    if result is None or result.status != "succeeded" or not result.reconciled:
        raise AssertionError("fresh provider could not reconcile the historical request")
    if result.external_operation_ref != before.get("provider_ref"):
        raise AssertionError("reconciliation returned a different provider operation identity")
    if before.get("request_ref") != request_id or after.get("request_ref") != request_id:
        raise AssertionError("sandbox request binding drifted during reconciliation")
    if before.get("apply_attempts") != after.get("apply_attempts"):
        raise AssertionError("reconciliation crossed the physical apply boundary")


async def main() -> None:
    store = InvocationSpecificationSQLiteStateStore(_kernel_state_path())
    try:
        dispatches = _effect_dispatches(store)
    finally:
        store.close()
    for dispatch in dispatches:
        await _prove_dispatch(dispatch)
    print(
        "durable reconciliation identity verified: "
        f"dispatches={len(dispatches)} exact_B_C=1 fresh_provider_reconcile=1 physical_redispatch=0"
    )


if __name__ == "__main__":
    asyncio.run(main())
