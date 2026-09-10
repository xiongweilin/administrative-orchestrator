from __future__ import annotations

import os
from pathlib import Path

import httpx
from portable_runtime.core.capabilities import (
    CapabilityRequest,
    CapabilityResult,
    InvocationContext,
    ProviderDescriptor,
    ProviderHealth,
)
from portable_runtime.core.capability_contract import CapabilityContract, CapabilityContractRegistry
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
from portable_runtime.responsibility.domain_effect_verified_outcome import (
    domain_effect_verification_capability,
)
from portable_runtime.stores.bounded_domain_effect_recovery import (
    BoundedDomainEffectRecoverySQLiteStateStore,
)

from administrative_orchestrator.config import get_settings
from administrative_orchestrator.integrations.credentials import CredentialRef
from administrative_orchestrator.integrations.kernel.capabilities import (
    ADMINISTRATIVE_HRIS_EMPLOYEE_CREATE,
    ADMINISTRATIVE_HRIS_EMPLOYEE_DEACTIVATE,
    ADMINISTRATIVE_IAM_IDENTITY_CREATE,
    ADMINISTRATIVE_IAM_IDENTITY_DISABLE,
    ADMINISTRATIVE_IAM_SESSIONS_REVOKE,
)
from administrative_orchestrator.integrations.production_effects import (
    ConnectorResult,
    ConnectorStatus,
    KeycloakEffectConnection,
    KeycloakIdentityDisableConnector,
    KeycloakIdentityDisableVerifier,
    KeycloakIdentityEffectConnector,
    KeycloakIdentityVerifier,
    KeycloakSessionRevokeConnector,
    KeycloakSessionVerifier,
    OdooEffectConnection,
    OdooEmployeeDeactivateConnector,
    OdooEmployeeDeactivateVerifier,
    OdooEmployeeEffectConnector,
    OdooEmployeeVerifier,
)

IAM_CAPABILITY = ADMINISTRATIVE_IAM_IDENTITY_CREATE


class ProductionEffectProvider:
    def __init__(
        self,
        *,
        provider_id: str,
        name: str,
        capability: str,
        family: str,
        execution_domain: str,
        credential_configuration_ref: str,
        network_domain: str,
        connector,
        reversibility: str = "compensatable",
    ) -> None:
        self.connector = connector
        self._descriptor = ProviderDescriptor(
            id=provider_id,
            name=name,
            version="2026.09-m5",
            capabilities=[capability],
            effect_semantics="reconcilable",
            side_effect_class="reconcilable",
            reversibility=reversibility,
            provider_family=family,
            operator="administrative-production",
            execution_domain=execution_domain,
            credential_domain=credential_configuration_ref,
            data_source_domain=execution_domain,
            network_domain=network_domain,
            trust_boundary="enterprise-production",
        )

    @property
    def descriptor(self) -> ProviderDescriptor:
        return self._descriptor

    async def health(self) -> ProviderHealth:
        return ProviderHealth(provider_id=self.descriptor.id, available=True)

    async def invoke(
        self,
        request: CapabilityRequest,
        context: InvocationContext,
    ) -> CapabilityResult:
        del context
        subject_ref = request.parameters.get("employee_ref")
        if not isinstance(subject_ref, str) or not subject_ref:
            subject_ref = request.parameters.get("subject_ref")
        if not isinstance(subject_ref, str) or not subject_ref:
            raise ValueError("production administrative effect requires subject identity")
        result: ConnectorResult = await self.connector.invoke(
            request_ref=request.id,
            subject_ref=subject_ref,
            parameters=dict(request.parameters),
        )
        return _capability_result(request.id, self.descriptor.id, result)

    async def cancel(self, request_id: str) -> None:
        del request_id

    async def reconcile(self, request_id: str) -> CapabilityResult | None:
        result: ConnectorResult | None = await self.connector.reconcile(request_id)
        if result is None:
            return None
        return _capability_result(request_id, self.descriptor.id, result)


class ProductionReadbackVerifier:
    def __init__(
        self,
        *,
        provider_id: str,
        name: str,
        effect_capability: str,
        family: str,
        credential_configuration_ref: str,
        network_domain: str,
        verifier,
    ) -> None:
        self.effect_capability = effect_capability
        self.verifier = verifier
        self._descriptor = ProviderDescriptor(
            id=provider_id,
            name=name,
            version="2026.09-m5",
            capabilities=[domain_effect_verification_capability(effect_capability)],
            effect_semantics="pure",
            side_effect_class="pure",
            reversibility="unknown",
            provider_family=family,
            operator="administrative-production",
            execution_domain="verification",
            credential_domain=credential_configuration_ref,
            data_source_domain=family,
            evaluation_domain="objective-postcondition",
            network_domain=network_domain,
            trust_boundary="enterprise-production",
        )

    @property
    def descriptor(self) -> ProviderDescriptor:
        return self._descriptor

    async def health(self) -> ProviderHealth:
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
            raise ValueError("verification effect capability rebound")
        if not isinstance(subject_ref, str) or not isinstance(expected, dict):
            raise ValueError("verification scope is incomplete")
        result: ConnectorResult = await self.verifier.observe(
            subject_ref=subject_ref,
            expected_postcondition=dict(expected),
        )
        if result.status is ConnectorStatus.UNAVAILABLE:
            return CapabilityResult(
                request_id=request.id,
                provider_id=self.descriptor.id,
                status="unavailable",
                error={
                    "code": result.error_code or "VerificationUnavailable",
                    "message": result.error_message or "verification unavailable",
                },
            )
        observed = result.observed_postcondition or {}
        objective = "pass" if observed == expected else "fail"
        return CapabilityResult(
            request_id=request.id,
            provider_id=self.descriptor.id,
            status="succeeded",
            metadata={"observed_postcondition": observed},
            verification_result=ClosedVerificationResult(
                result=objective,
                message="independent production administrative readback",
            ),
        )

    async def cancel(self, request_id: str) -> None:
        del request_id

    async def reconcile(self, request_id: str) -> CapabilityResult | None:
        del request_id
        return None


def _capability_result(
    request_id: str,
    provider_id: str,
    result: ConnectorResult,
) -> CapabilityResult:
    if result.status is ConnectorStatus.SUCCEEDED:
        return CapabilityResult(
            request_id=request_id,
            provider_id=provider_id,
            status="succeeded",
            external_operation_ref=result.external_operation_ref,
            reconciled=result.reconciled,
        )
    if result.status is ConnectorStatus.FAILED:
        status = "failed"
    elif result.status is ConnectorStatus.UNAVAILABLE:
        status = "unavailable"
    else:
        status = "unknown"
    return CapabilityResult(
        request_id=request_id,
        provider_id=provider_id,
        status=status,
        reconciled=result.reconciled,
        error={
            "code": result.error_code or "ConnectorFailure",
            "message": result.error_message or result.status.value,
        },
    )


def _remote_contract(
    capability: str, *, reversibility: str = "compensatable"
) -> CapabilityContract:
    return CapabilityContract(
        capability=capability,
        minimum_impact_class="write-remote",
        effect_semantics="reconcilable",
        reversibility=reversibility,
        authorization_requirement="required",
        minimum_procedure_profile="standard",
        resource_required=True,
        subject_version_required=True,
        default_independence_requirements=[],
        blast_radius=1,
        exposure=1,
    )


def _repeat_safe() -> ReconciliationRepeatabilityConfiguration:
    return ReconciliationRepeatabilityConfiguration(
        reconciliation_protocol_identity="administrative-production-request-readback",
        reconciliation_protocol_version="1",
        repeatability_mode="repeat-safe",
        contract_version="1",
    )


def build() -> tuple[Runtime, BoundedDomainEffectExecutionService]:
    settings = get_settings()
    if settings.runtime_profile not in {"staging", "production"}:
        raise RuntimeError(
            "production Kernel stack requires ADMIN_RUNTIME_PROFILE=staging or production"
        )
    state_path = os.getenv("PORTABLE_RUNTIME_ADMIN_PRODUCTION_STATE_PATH", "").strip()
    if not state_path:
        raise RuntimeError("PORTABLE_RUNTIME_ADMIN_PRODUCTION_STATE_PATH is required")

    store = BoundedDomainEffectRecoverySQLiteStateStore(Path(state_path))
    registry = ProviderRegistry()
    runtime = Runtime(
        store=store,
        registry=registry,
        contract_registry=CapabilityContractRegistry(
            contracts=[
                _remote_contract(IAM_CAPABILITY),
                _remote_contract(
                    ADMINISTRATIVE_HRIS_EMPLOYEE_DEACTIVATE,
                    reversibility="irreversible",
                ),
                _remote_contract(
                    ADMINISTRATIVE_IAM_IDENTITY_DISABLE,
                    reversibility="irreversible",
                ),
                _remote_contract(
                    ADMINISTRATIVE_IAM_SESSIONS_REVOKE,
                    reversibility="irreversible",
                ),
            ]
        ),
        reliability=ReliabilityControls(cooldown_seconds=0),
        runtime_id="runtime:administrative-production",
    )

    odoo_writer = OdooEmployeeEffectConnector(
        OdooEffectConnection(
            base_url=settings.odoo_base_url,
            database=settings.odoo_database,
            username=settings.odoo_writer_username,
            credential=CredentialRef("odoo:hris-writer", settings.odoo_writer_secret_env),
            request_ref_field=settings.odoo_request_ref_field,
            deactivate_request_ref_field=settings.odoo_deactivate_request_ref_field,
            timeout_seconds=settings.connector_timeout_seconds,
            allow_insecure_http=settings.oidc_allow_insecure_http,
        )
    )
    odoo_verifier_connector = OdooEmployeeEffectConnector(
        OdooEffectConnection(
            base_url=settings.odoo_base_url,
            database=settings.odoo_database,
            username=settings.odoo_verifier_username,
            credential=CredentialRef("odoo:hris-verifier", settings.odoo_verifier_secret_env),
            request_ref_field=settings.odoo_request_ref_field,
            deactivate_request_ref_field=settings.odoo_deactivate_request_ref_field,
            timeout_seconds=settings.connector_timeout_seconds,
            allow_insecure_http=settings.oidc_allow_insecure_http,
        )
    )
    keycloak_writer = KeycloakIdentityEffectConnector(
        KeycloakEffectConnection(
            base_url=settings.keycloak_base_url,
            realm=settings.keycloak_realm,
            client_id=settings.keycloak_writer_client_id,
            credential=CredentialRef("keycloak:iam-writer", settings.keycloak_writer_secret_env),
            request_ref_attribute=settings.keycloak_request_ref_attribute,
            disable_request_ref_attribute=settings.keycloak_disable_request_ref_attribute,
            session_revoke_request_ref_attribute=(
                settings.keycloak_session_revoke_request_ref_attribute
            ),
            timeout_seconds=settings.connector_timeout_seconds,
            allow_insecure_http=settings.oidc_allow_insecure_http,
        )
    )
    keycloak_verifier_connector = KeycloakIdentityEffectConnector(
        KeycloakEffectConnection(
            base_url=settings.keycloak_base_url,
            realm=settings.keycloak_realm,
            client_id=settings.keycloak_verifier_client_id,
            credential=CredentialRef("keycloak:iam-verifier", settings.keycloak_verifier_secret_env),
            request_ref_attribute=settings.keycloak_request_ref_attribute,
            disable_request_ref_attribute=settings.keycloak_disable_request_ref_attribute,
            session_revoke_request_ref_attribute=(
                settings.keycloak_session_revoke_request_ref_attribute
            ),
            timeout_seconds=settings.connector_timeout_seconds,
            allow_insecure_http=settings.oidc_allow_insecure_http,
        )
    )

    hris_provider = ProductionEffectProvider(
        provider_id="provider:administrative-production:odoo-writer",
        name="Administrative Odoo HRIS writer",
        capability=ADMINISTRATIVE_HRIS_EMPLOYEE_CREATE,
        family="odoo",
        execution_domain="odoo:hris",
        credential_configuration_ref="odoo:hris-writer",
        network_domain=_host(settings.odoo_base_url),
        connector=odoo_writer,
    )
    hris_verifier = ProductionReadbackVerifier(
        provider_id="provider:administrative-production:odoo-verifier",
        name="Administrative Odoo HRIS independent verifier",
        effect_capability=ADMINISTRATIVE_HRIS_EMPLOYEE_CREATE,
        family="odoo-readback",
        credential_configuration_ref="odoo:hris-verifier",
        network_domain=_host(settings.odoo_base_url),
        verifier=OdooEmployeeVerifier(odoo_verifier_connector),
    )
    iam_provider = ProductionEffectProvider(
        provider_id="provider:administrative-production:keycloak-writer",
        name="Administrative Keycloak IAM writer",
        capability=IAM_CAPABILITY,
        family="keycloak",
        execution_domain="keycloak:iam",
        credential_configuration_ref="keycloak:iam-writer",
        network_domain=_host(settings.keycloak_base_url),
        connector=keycloak_writer,
    )
    iam_verifier = ProductionReadbackVerifier(
        provider_id="provider:administrative-production:keycloak-verifier",
        name="Administrative Keycloak IAM independent verifier",
        effect_capability=IAM_CAPABILITY,
        family="keycloak-readback",
        credential_configuration_ref="keycloak:iam-verifier",
        network_domain=_host(settings.keycloak_base_url),
        verifier=KeycloakIdentityVerifier(keycloak_verifier_connector),
    )
    hris_deactivate_provider = ProductionEffectProvider(
        provider_id="provider:administrative-production:odoo-deactivate-writer",
        name="Administrative Odoo employee deactivate writer",
        capability=ADMINISTRATIVE_HRIS_EMPLOYEE_DEACTIVATE,
        family="odoo",
        execution_domain="odoo:hris",
        credential_configuration_ref="odoo:hris-writer",
        network_domain=_host(settings.odoo_base_url),
        connector=OdooEmployeeDeactivateConnector(odoo_writer),
        reversibility="irreversible",
    )
    hris_deactivate_verifier = ProductionReadbackVerifier(
        provider_id="provider:administrative-production:odoo-deactivate-verifier",
        name="Administrative Odoo employee deactivate verifier",
        effect_capability=ADMINISTRATIVE_HRIS_EMPLOYEE_DEACTIVATE,
        family="odoo-readback",
        credential_configuration_ref="odoo:hris-verifier",
        network_domain=_host(settings.odoo_base_url),
        verifier=OdooEmployeeDeactivateVerifier(
            OdooEmployeeDeactivateConnector(odoo_verifier_connector)
        ),
    )
    iam_disable_provider = ProductionEffectProvider(
        provider_id="provider:administrative-production:keycloak-disable-writer",
        name="Administrative Keycloak identity disable writer",
        capability=ADMINISTRATIVE_IAM_IDENTITY_DISABLE,
        family="keycloak",
        execution_domain="keycloak:iam",
        credential_configuration_ref="keycloak:iam-writer",
        network_domain=_host(settings.keycloak_base_url),
        connector=KeycloakIdentityDisableConnector(keycloak_writer),
        reversibility="irreversible",
    )
    iam_disable_verifier = ProductionReadbackVerifier(
        provider_id="provider:administrative-production:keycloak-disable-verifier",
        name="Administrative Keycloak identity disable verifier",
        effect_capability=ADMINISTRATIVE_IAM_IDENTITY_DISABLE,
        family="keycloak-readback",
        credential_configuration_ref="keycloak:iam-verifier",
        network_domain=_host(settings.keycloak_base_url),
        verifier=KeycloakIdentityDisableVerifier(keycloak_verifier_connector),
    )
    session_revoke_provider = ProductionEffectProvider(
        provider_id="provider:administrative-production:keycloak-session-revoke-writer",
        name="Administrative Keycloak session revoke writer",
        capability=ADMINISTRATIVE_IAM_SESSIONS_REVOKE,
        family="keycloak",
        execution_domain="keycloak:iam",
        credential_configuration_ref="keycloak:iam-writer",
        network_domain=_host(settings.keycloak_base_url),
        connector=KeycloakSessionRevokeConnector(keycloak_writer),
        reversibility="irreversible",
    )
    session_revoke_verifier = ProductionReadbackVerifier(
        provider_id="provider:administrative-production:keycloak-session-revoke-verifier",
        name="Administrative Keycloak session revoke verifier",
        effect_capability=ADMINISTRATIVE_IAM_SESSIONS_REVOKE,
        family="keycloak-readback",
        credential_configuration_ref="keycloak:iam-verifier",
        network_domain=_host(settings.keycloak_base_url),
        verifier=KeycloakSessionVerifier(keycloak_verifier_connector),
    )

    registrations = (
        (hris_provider, "odoo-writer", _repeat_safe()),
        (hris_verifier, "odoo-verifier", None),
        (iam_provider, "keycloak-writer", _repeat_safe()),
        (iam_verifier, "keycloak-verifier", None),
        (hris_deactivate_provider, "odoo-deactivate-writer", _repeat_safe()),
        (hris_deactivate_verifier, "odoo-deactivate-verifier", None),
        (iam_disable_provider, "keycloak-disable-writer", _repeat_safe()),
        (iam_disable_verifier, "keycloak-disable-verifier", None),
        (session_revoke_provider, "keycloak-session-revoke-writer", _repeat_safe()),
        (session_revoke_verifier, "keycloak-session-revoke-verifier", None),
    )
    for provider, configured_name, repeatability in registrations:
        registry.register(
            provider,
            configured_execution_identity=(
                f"configured:administrative-production:{configured_name}"
            ),
            authoritative_configuration_ref=(
                f"config:administrative-production:{configured_name}:v1"
            ),
            reconciliation_repeatability=repeatability,
        )

    profiles = [
        BoundedDomainEffectExecutionProfile(
            capability=ADMINISTRATIVE_HRIS_EMPLOYEE_CREATE,
            provider_id=hris_provider.descriptor.id,
            verifier_provider_id=hris_verifier.descriptor.id,
            semantic_contract=ProviderSemanticContract(
                id="semantic:administrative-production:odoo-employee-create",
                version="1",
                provider_id=hris_provider.descriptor.id,
            ),
            lease_owner="kernel:administrative-production",
        ),
        BoundedDomainEffectExecutionProfile(
            capability=ADMINISTRATIVE_HRIS_EMPLOYEE_DEACTIVATE,
            provider_id=hris_deactivate_provider.descriptor.id,
            verifier_provider_id=hris_deactivate_verifier.descriptor.id,
            semantic_contract=ProviderSemanticContract(
                id="semantic:administrative-production:odoo-employee-deactivate",
                version="1",
                provider_id=hris_deactivate_provider.descriptor.id,
            ),
            lease_owner="kernel:administrative-production",
        ),
        BoundedDomainEffectExecutionProfile(
            capability=ADMINISTRATIVE_IAM_IDENTITY_DISABLE,
            provider_id=iam_disable_provider.descriptor.id,
            verifier_provider_id=iam_disable_verifier.descriptor.id,
            semantic_contract=ProviderSemanticContract(
                id="semantic:administrative-production:keycloak-identity-disable",
                version="1",
                provider_id=iam_disable_provider.descriptor.id,
            ),
            lease_owner="kernel:administrative-production",
        ),
        BoundedDomainEffectExecutionProfile(
            capability=ADMINISTRATIVE_IAM_SESSIONS_REVOKE,
            provider_id=session_revoke_provider.descriptor.id,
            verifier_provider_id=session_revoke_verifier.descriptor.id,
            semantic_contract=ProviderSemanticContract(
                id="semantic:administrative-production:keycloak-sessions-revoke",
                version="1",
                provider_id=session_revoke_provider.descriptor.id,
            ),
            lease_owner="kernel:administrative-production",
        ),
        BoundedDomainEffectExecutionProfile(
            capability=IAM_CAPABILITY,
            provider_id=iam_provider.descriptor.id,
            verifier_provider_id=iam_verifier.descriptor.id,
            semantic_contract=ProviderSemanticContract(
                id="semantic:administrative-production:keycloak-identity-create",
                version="1",
                provider_id=iam_provider.descriptor.id,
            ),
            lease_owner="kernel:administrative-production",
        ),
    ]
    return runtime, BoundedDomainEffectExecutionService(runtime, profiles)


def _host(url: str) -> str:
    try:
        return httpx.URL(url).host or "unconfigured"
    except Exception:
        return "unconfigured"


__all__ = ["IAM_CAPABILITY", "ProductionEffectProvider", "ProductionReadbackVerifier", "build"]
