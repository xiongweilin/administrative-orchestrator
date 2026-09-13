from __future__ import annotations

from .communication_effects import (
    AdministrativeCommunicationEffectConnection,
    AdministrativeCommunicationEffectConnector,
    FeishuCommunicationVerifier,
)
from .effect_common import (
    ConnectorConfigurationError,
    ConnectorResult,
    ConnectorStatus,
    _ApplicationRejected,
    _TransportUnknown,
    _unavailable_result,
    _unknown_result,
    _validate_base_url,
)
from .keycloak_effects import (
    KeycloakEffectConnection,
    KeycloakIdentityDisableConnector,
    KeycloakIdentityDisableVerifier,
    KeycloakIdentityEffectConnector,
    KeycloakIdentityVerifier,
    KeycloakSessionRevokeConnector,
    KeycloakSessionVerifier,
)
from .odoo_effects import (
    OdooEffectConnection,
    OdooEmployeeDeactivateConnector,
    OdooEmployeeDeactivateVerifier,
    OdooEmployeeEffectConnector,
    OdooEmployeeVerifier,
    OdooFinancialEffectConnector,
    OdooFinancialVerifier,
    _many2one_id,
    _odoo_numeric_ref,
    _required_odoo_numeric_ref,
)

# This module remains the compatibility import surface for existing callers.
# Provider-specific implementation now lives in bounded integration modules.

__all__ = [
    "AdministrativeCommunicationEffectConnection",
    "AdministrativeCommunicationEffectConnector",
    "FeishuCommunicationVerifier",
    "ConnectorConfigurationError",
    "ConnectorResult",
    "ConnectorStatus",
    "KeycloakEffectConnection",
    "KeycloakIdentityDisableConnector",
    "KeycloakIdentityDisableVerifier",
    "KeycloakIdentityEffectConnector",
    "KeycloakIdentityVerifier",
    "KeycloakSessionRevokeConnector",
    "KeycloakSessionVerifier",
    "OdooEffectConnection",
    "OdooEmployeeDeactivateConnector",
    "OdooEmployeeDeactivateVerifier",
    "OdooEmployeeEffectConnector",
    "OdooEmployeeVerifier",
]
