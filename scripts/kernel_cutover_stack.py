from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

import httpx
from portable_runtime.core.capabilities import (
    CapabilityRequest,
    CapabilityResult,
    InvocationContext,
    ProviderDescriptor,
    ProviderHealth,
)
from portable_runtime.core.capability_contract import CapabilityContract, CapabilityContractRegistry
from portable_runtime.core.models import StepAttempt
from portable_runtime.core.provider_semantics import ProviderSemanticContract
from portable_runtime.core.reconciliation_repeatability import (
    ReconciliationRepeatabilityConfiguration,
)
from portable_runtime.core.registry import ProviderRegistry
from portable_runtime.core.reliability import ReliabilityControls
from portable_runtime.core.runtime import Runtime
from portable_runtime.public_contracts.domain_effect import (
    BoundedDomainEffectExecutionProfile,
    BoundedDomainEffectExecutionService,
)
from portable_runtime.records.open_validation import ClosedVerificationResult
from portable_runtime.responsibility.domain_effect_authorization import (
    ADMINISTRATIVE_HRIS_EMPLOYEE_CREATE,
)
from portable_runtime.responsibility.domain_effect_verified_outcome import (
    domain_effect_verification_capability,
)
from portable_runtime.stores.bounded_domain_effect_recovery import (
    BoundedDomainEffectRecoveryInMemoryStateStore,
    BoundedDomainEffectRecoverySQLiteStateStore,
)

SANDBOX_BASE_URL = os.getenv("ADMIN_SANDBOX_BASE_URL", "http://127.0.0.1:8010").rstrip("/")
IAM_CAPABILITY = "administrative.iam.identity.create.v1"
RESULT_COMMIT_FAIL_ONCE_ENV = "PORTABLE_RUNTIME_ADMIN_E2E_RESULT_COMMIT_FAIL_ONCE_PATH"


def sandbox_effect_id(capability: str, subject_ref: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"administrative-kernel-e2e:{capability}:{subject_ref}")


class SandboxAdministrativeProvider:
    def __init__(
        self,
        *,
        provider_id: str,
        capability: str,
        target_system: str,
        operation: str,
        base_url: str = SANDBOX_BASE_URL,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.capability = capability
        self.target_system = target_system
        self.operation = operation
        self._descriptor = ProviderDescriptor(
            id=provider_id,
            name=f"Administrative sandbox {target_system} provider",
            version="2026.09",
            capabilities=[capability],
            effect_semantics="reconcilable",
            side_effect_class="reconcilable",
            reversibility="compensatable",
            provider_family="administrative-sandbox",
            operator="cross-repo-ci",
            execution_domain=f"administrative-sandbox:{target_system}",
            credential_domain="cross-repo-ci:none",
            data_source_domain=f"administrative-sandbox:{target_system}-state",
            network_domain="localhost",
            trust_boundary="cross-repo-ci",
        )

    @property
    def descriptor(self) -> ProviderDescriptor:
        return self._descriptor

    async def health(self) -> ProviderHealth:
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                response = await client.get(f"{self.base_url}/healthz")
                response.raise_for_status()
        except httpx.HTTPError as exc:
            return ProviderHealth(
                provider_id=self.descriptor.id,
                available=False,
                detail=str(exc),
            )
        return ProviderHealth(provider_id=self.descriptor.id, available=True)

    async def invoke(
        self,
        request: CapabilityRequest,
        context: InvocationContext,
    ) -> CapabilityResult:
        del context
        subject_ref = request.parameters.get("employee_ref")
        if not isinstance(subject_ref, str) or not subject_ref:
            raise ValueError(f"{self.target_system} execution requires employee_ref")
        effect_id = sandbox_effect_id(request.capability, subject_ref)
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.put(
                    f"{self.base_url}/v1/effects/{effect_id}",
                    json={
                        "target_system": self.target_system,
                        "operation": self.operation,
                        "subject_ref": subject_ref,
                        "payload": dict(request.parameters),
                        "request_ref": request.id,
                    },
                )
                response.raise_for_status()
                payload = response.json()
        except httpx.HTTPError as exc:
            return CapabilityResult(
                request_id=request.id,
                provider_id=self.descriptor.id,
                status="unknown",
                error={"code": type(exc).__name__, "message": str(exc)},
            )
        provider_ref = payload.get("provider_ref") if isinstance(payload, dict) else None
        return CapabilityResult(
            request_id=request.id,
            provider_id=self.descriptor.id,
            status="succeeded",
            external_operation_ref=(provider_ref if isinstance(provider_ref, str) else str(effect_id)),
            metadata={"sandbox_effect_id": str(effect_id)},
        )

    async def cancel(self, request_id: str) -> None:
        del request_id

    async def reconcile(self, request_id: str) -> CapabilityResult | None:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(
                    f"{self.base_url}/v1/reconciliation/effects/{request_id}"
                )
                if response.status_code == 404:
                    return None
                response.raise_for_status()
                payload = response.json()
        except httpx.HTTPError as exc:
            return CapabilityResult(
                request_id=request_id,
                provider_id=self.descriptor.id,
                status="unknown",
                error={"code": type(exc).__name__, "message": str(exc)},
            )
        provider_ref = payload.get("provider_ref") if isinstance(payload, dict) else None
        return CapabilityResult(
            request_id=request_id,
            provider_id=self.descriptor.id,
            status="succeeded",
            reconciled=True,
            external_operation_ref=(provider_ref if isinstance(provider_ref, str) else None),
        )


class SandboxAdministrativeReadbackVerifier:
    def __init__(
        self,
        *,
        provider_id: str,
        effect_capability: str,
        target_system: str,
        base_url: str = SANDBOX_BASE_URL,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.effect_capability = effect_capability
        self.target_system = target_system
        self._descriptor = ProviderDescriptor(
            id=provider_id,
            name=f"Administrative sandbox {target_system} readback verifier",
            version="2026.09",
            capabilities=[domain_effect_verification_capability(effect_capability)],
            effect_semantics="pure",
            side_effect_class="pure",
            reversibility="unknown",
            provider_family="administrative-sandbox-readback",
            operator="cross-repo-ci",
            execution_domain="verification",
            credential_domain="cross-repo-ci:none",
            data_source_domain=f"administrative-sandbox:{target_system}-state",
            evaluation_domain="objective-postcondition",
            network_domain="localhost",
            trust_boundary="cross-repo-ci",
        )

    @property
    def descriptor(self) -> ProviderDescriptor:
        return self._descriptor

    async def health(self) -> ProviderHealth:
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                response = await client.get(f"{self.base_url}/healthz")
                response.raise_for_status()
        except httpx.HTTPError as exc:
            return ProviderHealth(
                provider_id=self.descriptor.id,
                available=False,
                detail=str(exc),
            )
        return ProviderHealth(provider_id=self.descriptor.id, available=True)

    async def invoke(
        self,
        request: CapabilityRequest,
        context: InvocationContext,
    ) -> CapabilityResult:
        del context
        scope = request.parameters.get("verification_scope")
        if not isinstance(scope, dict):
            raise ValueError("verification_scope required")
        capability = scope.get("effect_capability")
        subject_ref = scope.get("subject_ref")
        expected = scope.get("expected_postcondition")
        if capability != self.effect_capability:
            raise ValueError("verification scope capability rebound")
        if not isinstance(subject_ref, str):
            raise ValueError("verification scope lacks subject_ref")
        if not isinstance(expected, dict):
            raise ValueError("verification scope lacks expected postcondition")
        effect_id = sandbox_effect_id(self.effect_capability, subject_ref)
        observed: dict[str, Any]
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self.base_url}/v1/effects/{effect_id}")
                if response.status_code == 404:
                    observed = {}
                else:
                    response.raise_for_status()
                    payload = response.json()
                    state = payload.get("state") if isinstance(payload, dict) else None
                    observed = dict(state) if isinstance(state, dict) else {}
        except httpx.HTTPError as exc:
            return CapabilityResult(
                request_id=request.id,
                provider_id=self.descriptor.id,
                status="unavailable",
                error={"code": type(exc).__name__, "message": str(exc)},
            )
        result = "pass" if observed == expected else "fail"
        return CapabilityResult(
            request_id=request.id,
            provider_id=self.descriptor.id,
            status="succeeded",
            metadata={"observed_postcondition": observed},
            verification_result=ClosedVerificationResult(
                result=result,
                message=f"independent Administrative sandbox {self.target_system} readback",
            ),
        )

    async def cancel(self, request_id: str) -> None:
        del request_id

    async def reconcile(self, request_id: str) -> CapabilityResult | None:
        del request_id
        return None


class ResultCommitFailOnceInMemoryStateStore(BoundedDomainEffectRecoveryInMemoryStateStore):
    """CI-only store seam for the post-provider / pre-result-commit ambiguity window."""

    def save_attempt(self, value: StepAttempt) -> None:
        _fail_result_commit_once(value)
        super().save_attempt(value)


class ResultCommitFailOnceSQLiteStateStore(BoundedDomainEffectRecoverySQLiteStateStore):
    """Durable CI seam equivalent to ResultCommitFailOnceInMemoryStateStore."""

    def save_attempt(self, value: StepAttempt) -> None:
        _fail_result_commit_once(value)
        super().save_attempt(value)


def _fail_result_commit_once(value: StepAttempt) -> None:
    marker_path = os.getenv(RESULT_COMMIT_FAIL_ONCE_ENV)
    if not marker_path or value.status != "succeeded":
        return
    marker = Path(marker_path)
    if marker.exists():
        return
    marker.write_text(
        "provider returned succeeded; StepAttempt succeeded projection intentionally failed\n",
        encoding="utf-8",
    )
    raise RuntimeError("fault injection: post-provider result projection commit failed")


class PreReceiptCrashBoundedDomainEffectExecutionService(BoundedDomainEffectExecutionService):
    """CI-only later crash seam after durable effect success but before bounded receipt."""

    async def _verify_and_complete(self, command, *args, **kwargs):
        marker_path = os.getenv("PORTABLE_RUNTIME_ADMIN_E2E_PRE_RECEIPT_FAIL_ONCE_PATH")
        target_subject = os.getenv("PORTABLE_RUNTIME_ADMIN_E2E_PRE_RECEIPT_FAIL_SUBJECT")
        if marker_path and target_subject and command.subject_ref == target_subject:
            marker = Path(marker_path)
            if not marker.exists():
                marker.write_text(
                    "effect Attempt/Action durable; bounded execution receipt not recorded\n",
                    encoding="utf-8",
                )
                raise RuntimeError(
                    "fault injection: crash after physical effect success before bounded receipt"
                )
        return await super()._verify_and_complete(command, *args, **kwargs)


def _iam_contract() -> CapabilityContract:
    return CapabilityContract(
        capability=IAM_CAPABILITY,
        minimum_impact_class="write-remote",
        effect_semantics="reconcilable",
        reversibility="compensatable",
        authorization_requirement="required",
        minimum_procedure_profile="standard",
        resource_required=True,
        subject_version_required=True,
        default_independence_requirements=[],
        blast_radius=1,
        exposure=1,
    )


def _repeat_safe_reconciliation() -> ReconciliationRepeatabilityConfiguration:
    return ReconciliationRepeatabilityConfiguration(
        reconciliation_protocol_identity="administrative-sandbox-request-readback",
        reconciliation_protocol_version="1",
        repeatability_mode="repeat-safe",
        contract_version="1",
    )


def build() -> tuple[Runtime, BoundedDomainEffectExecutionService]:
    state_path = os.getenv("PORTABLE_RUNTIME_ADMIN_E2E_STATE_PATH")
    store = (
        ResultCommitFailOnceSQLiteStateStore(Path(state_path))
        if state_path
        else ResultCommitFailOnceInMemoryStateStore()
    )
    registry = ProviderRegistry()
    # The generic Runtime default is a personal/local safety profile with a
    # five-second global side-effect cooldown. This deployment represents one
    # server-owned Administrative execution lane, where independently admitted
    # HRIS and IAM obligations must be able to discharge back-to-back. Keep all
    # rate, parallelism, blast-radius, exposure and side-effect budgets active;
    # only the personal interactive cooldown is explicitly disabled.
    reliability = ReliabilityControls(cooldown_seconds=0)
    runtime = Runtime(
        store=store,
        registry=registry,
        contract_registry=CapabilityContractRegistry(contracts=[_iam_contract()]),
        reliability=reliability,
        runtime_id="runtime:administrative-cross-repo-e2e",
    )

    hris_provider = SandboxAdministrativeProvider(
        provider_id="provider:admin-e2e:hris",
        capability=ADMINISTRATIVE_HRIS_EMPLOYEE_CREATE,
        target_system="hris",
        operation="employee.create",
    )
    iam_provider = SandboxAdministrativeProvider(
        provider_id="provider:admin-e2e:iam",
        capability=IAM_CAPABILITY,
        target_system="iam",
        operation="identity.create",
    )
    hris_verifier = SandboxAdministrativeReadbackVerifier(
        provider_id="provider:admin-e2e:hris-readback",
        effect_capability=ADMINISTRATIVE_HRIS_EMPLOYEE_CREATE,
        target_system="hris",
    )
    iam_verifier = SandboxAdministrativeReadbackVerifier(
        provider_id="provider:admin-e2e:iam-readback",
        effect_capability=IAM_CAPABILITY,
        target_system="iam",
    )

    registrations = (
        (hris_provider, "hris", _repeat_safe_reconciliation()),
        (iam_provider, "iam", _repeat_safe_reconciliation()),
        (hris_verifier, "hris-readback", None),
        (iam_verifier, "iam-readback", None),
    )
    for provider, configured_name, repeatability in registrations:
        registry.register(
            provider,
            configured_execution_identity=f"configured:administrative-sandbox:{configured_name}",
            authoritative_configuration_ref=f"config:administrative-sandbox:{configured_name}:v1",
            reconciliation_repeatability=repeatability,
        )

    profiles = (
        BoundedDomainEffectExecutionProfile(
            capability=ADMINISTRATIVE_HRIS_EMPLOYEE_CREATE,
            provider_id=hris_provider.descriptor.id,
            verifier_provider_id=hris_verifier.descriptor.id,
            semantic_contract=ProviderSemanticContract(
                id="semantic:administrative-sandbox:hris-employee-create",
                version="1",
                provider_id=hris_provider.descriptor.id,
            ),
            lease_owner="kernel:administrative-cross-repo-e2e",
        ),
        BoundedDomainEffectExecutionProfile(
            capability=IAM_CAPABILITY,
            provider_id=iam_provider.descriptor.id,
            verifier_provider_id=iam_verifier.descriptor.id,
            semantic_contract=ProviderSemanticContract(
                id="semantic:administrative-sandbox:iam-identity-create",
                version="1",
                provider_id=iam_provider.descriptor.id,
            ),
            lease_owner="kernel:administrative-cross-repo-e2e",
        ),
    )
    return runtime, PreReceiptCrashBoundedDomainEffectExecutionService(runtime, list(profiles))


__all__ = [
    "IAM_CAPABILITY",
    "RESULT_COMMIT_FAIL_ONCE_ENV",
    "SandboxAdministrativeProvider",
    "build",
    "sandbox_effect_id",
]
