from __future__ import annotations

import os
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
from portable_runtime.core.provider_semantics import ProviderSemanticContract
from portable_runtime.core.registry import ProviderRegistry
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
    DOMAIN_EFFECT_VERIFICATION_CAPABILITY,
)
from portable_runtime.stores.invocation_specification import (
    InvocationSpecificationInMemoryStateStore,
)

SANDBOX_BASE_URL = os.getenv("ADMIN_SANDBOX_BASE_URL", "http://127.0.0.1:8010").rstrip("/")
EFFECT_PROVIDER_ID = "provider:admin-e2e:hris"
VERIFIER_PROVIDER_ID = "provider:admin-e2e:hris-readback"


def sandbox_effect_id(capability: str, subject_ref: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"administrative-kernel-e2e:{capability}:{subject_ref}")


class SandboxHrisProvider:
    def __init__(self, base_url: str = SANDBOX_BASE_URL) -> None:
        self.base_url = base_url.rstrip("/")
        self._request_effect_ids: dict[str, UUID] = {}
        self._descriptor = ProviderDescriptor(
            id=EFFECT_PROVIDER_ID,
            name="Administrative sandbox HRIS provider",
            version="2026.09",
            capabilities=[ADMINISTRATIVE_HRIS_EMPLOYEE_CREATE],
            effect_semantics="reconcilable",
            side_effect_class="reconcilable",
            reversibility="compensatable",
            provider_family="administrative-sandbox",
            operator="cross-repo-ci",
            execution_domain="administrative-sandbox:hris",
            credential_domain="cross-repo-ci:none",
            data_source_domain="administrative-sandbox:hris-state",
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
            raise ValueError("HRIS execution requires employee_ref")
        effect_id = sandbox_effect_id(request.capability, subject_ref)
        self._request_effect_ids[request.id] = effect_id
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.put(
                    f"{self.base_url}/v1/effects/{effect_id}",
                    json={
                        "target_system": "hris",
                        "operation": "employee.create",
                        "subject_ref": subject_ref,
                        "payload": dict(request.parameters),
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
        effect_id = self._request_effect_ids.get(request_id)
        if effect_id is None:
            return None
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self.base_url}/v1/effects/{effect_id}")
                if response.status_code == 404:
                    return None
                response.raise_for_status()
        except httpx.HTTPError as exc:
            return CapabilityResult(
                request_id=request_id,
                provider_id=self.descriptor.id,
                status="unknown",
                error={"code": type(exc).__name__, "message": str(exc)},
            )
        return CapabilityResult(
            request_id=request_id,
            provider_id=self.descriptor.id,
            status="succeeded",
            reconciled=True,
            external_operation_ref=f"sandbox:{effect_id}",
        )


class SandboxHrisReadbackVerifier:
    def __init__(self, base_url: str = SANDBOX_BASE_URL) -> None:
        self.base_url = base_url.rstrip("/")
        self._descriptor = ProviderDescriptor(
            id=VERIFIER_PROVIDER_ID,
            name="Administrative sandbox HRIS readback verifier",
            version="2026.09",
            capabilities=[DOMAIN_EFFECT_VERIFICATION_CAPABILITY],
            effect_semantics="pure",
            side_effect_class="pure",
            reversibility="unknown",
            provider_family="administrative-sandbox-readback",
            operator="cross-repo-ci",
            execution_domain="verification",
            credential_domain="cross-repo-ci:none",
            data_source_domain="administrative-sandbox:hris-state",
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
        if not isinstance(capability, str) or not isinstance(subject_ref, str):
            raise ValueError("verification scope lacks effect identity")
        if not isinstance(expected, dict):
            raise ValueError("verification scope lacks expected postcondition")
        effect_id = sandbox_effect_id(capability, subject_ref)
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
                message="independent Administrative sandbox HRIS readback",
            ),
        )

    async def cancel(self, request_id: str) -> None:
        del request_id

    async def reconcile(self, request_id: str) -> CapabilityResult | None:
        del request_id
        return None


def build() -> tuple[Runtime, BoundedDomainEffectExecutionService]:
    store = InvocationSpecificationInMemoryStateStore()
    registry = ProviderRegistry()
    runtime = Runtime(
        store=store,
        registry=registry,
        runtime_id="runtime:administrative-cross-repo-e2e",
    )
    effect_provider = SandboxHrisProvider()
    verifier = SandboxHrisReadbackVerifier()
    registry.register(
        effect_provider,
        configured_execution_identity="configured:administrative-sandbox:hris",
        authoritative_configuration_ref="config:administrative-sandbox:hris:v1",
    )
    registry.register(
        verifier,
        configured_execution_identity="configured:administrative-sandbox:hris-readback",
        authoritative_configuration_ref="config:administrative-sandbox:hris-readback:v1",
    )
    service = BoundedDomainEffectExecutionService(
        runtime,
        [
            BoundedDomainEffectExecutionProfile(
                capability=ADMINISTRATIVE_HRIS_EMPLOYEE_CREATE,
                provider_id=effect_provider.descriptor.id,
                verifier_provider_id=verifier.descriptor.id,
                semantic_contract=ProviderSemanticContract(
                    id="semantic:administrative-sandbox:hris-employee-create",
                    version="1",
                    provider_id=effect_provider.descriptor.id,
                ),
                lease_owner="kernel:administrative-cross-repo-e2e",
            )
        ],
    )
    return runtime, service


__all__ = ["build", "sandbox_effect_id"]