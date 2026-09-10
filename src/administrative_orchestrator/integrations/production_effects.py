from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

import httpx

from .credentials import CredentialRef, CredentialResolver, EnvironmentCredentialResolver


class ConnectorStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    UNKNOWN = "unknown"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class ConnectorResult:
    status: ConnectorStatus
    external_operation_ref: str | None = None
    observed_postcondition: dict[str, Any] | None = None
    error_code: str | None = None
    error_message: str | None = None
    reconciled: bool = False


class ConnectorConfigurationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class OdooEffectConnection:
    base_url: str
    database: str
    username: str
    credential: CredentialRef
    request_ref_field: str = "x_administrative_request_ref"
    subject_ref_field: str = "x_administrative_subject_ref"
    timeout_seconds: float = 10.0
    allow_insecure_http: bool = False

    def __post_init__(self) -> None:
        _validate_base_url(self.base_url, allow_insecure_http=self.allow_insecure_http)
        if not self.database.strip() or not self.username.strip():
            raise ConnectorConfigurationError("Odoo database and username are required")
        for field in (self.request_ref_field, self.subject_ref_field):
            if not field.startswith("x_"):
                raise ConnectorConfigurationError(
                    "Odoo integration identity fields must be custom x_ fields"
                )


class OdooEmployeeEffectConnector:
    """Kernel-facing Odoo employee writer/reconciler.

    Production Odoo must expose durable custom request/subject identity fields.
    A transport failure after create is UNKNOWN, never retry permission; Kernel
    recovery calls `reconcile(request_ref)` instead of re-invoking create.
    """

    def __init__(
        self,
        connection: OdooEffectConnection,
        *,
        credentials: CredentialResolver | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.connection = connection
        self.credentials = credentials or EnvironmentCredentialResolver()
        self._client = client

    async def invoke(
        self,
        *,
        request_ref: str,
        subject_ref: str,
        parameters: dict[str, Any],
    ) -> ConnectorResult:
        try:
            existing = await self._lookup(self.connection.request_ref_field, request_ref)
            if len(existing) > 1:
                return ConnectorResult(
                    ConnectorStatus.FAILED,
                    error_code="DuplicateExternalRequestIdentity",
                    error_message="multiple Odoo employees share the same request_ref",
                )
            if existing:
                return ConnectorResult(
                    ConnectorStatus.SUCCEEDED,
                    external_operation_ref=f"odoo:hr.employee:{existing[0]['id']}",
                    reconciled=True,
                )

            values: dict[str, Any] = {
                self.connection.request_ref_field: request_ref,
                self.connection.subject_ref_field: subject_ref,
                "name": str(parameters.get("name") or parameters.get("employee_ref") or subject_ref),
                "active": True,
            }
            if parameters.get("work_email"):
                values["work_email"] = parameters["work_email"]
            department_id = _odoo_numeric_ref(parameters.get("department_ref"), "hr.department")
            if department_id is not None:
                values["department_id"] = department_id
            manager_id = _odoo_numeric_ref(parameters.get("manager_ref"), "hr.employee")
            if manager_id is not None:
                values["parent_id"] = manager_id
            for source_key, target_field in {
                "manager_principal_id": "x_administrative_manager_principal_id",
                "employment_type": "x_administrative_employment_type",
                "start_date": "x_administrative_start_date",
            }.items():
                if parameters.get(source_key) is not None:
                    values[target_field] = parameters[source_key]

            employee_id = await self._execute_kw("hr.employee", "create", [values], {})
            if not isinstance(employee_id, int) or employee_id <= 0:
                return ConnectorResult(
                    ConnectorStatus.FAILED,
                    error_code="InvalidOdooCreateResult",
                    error_message="Odoo did not return a valid employee id",
                )
            return ConnectorResult(
                ConnectorStatus.SUCCEEDED,
                external_operation_ref=f"odoo:hr.employee:{employee_id}",
            )
        except _TransportUnknown as exc:
            return ConnectorResult(
                ConnectorStatus.UNKNOWN,
                error_code=type(exc.__cause__).__name__ if exc.__cause__ else type(exc).__name__,
                error_message=str(exc),
            )
        except _ApplicationRejected as exc:
            return ConnectorResult(
                ConnectorStatus.FAILED,
                error_code="OdooApplicationRejected",
                error_message=str(exc),
            )

    async def reconcile(self, request_ref: str) -> ConnectorResult | None:
        try:
            rows = await self._lookup(self.connection.request_ref_field, request_ref)
        except _TransportUnknown as exc:
            return ConnectorResult(
                ConnectorStatus.UNKNOWN,
                error_code=type(exc.__cause__).__name__ if exc.__cause__ else type(exc).__name__,
                error_message=str(exc),
                reconciled=True,
            )
        except _ApplicationRejected as exc:
            return ConnectorResult(
                ConnectorStatus.FAILED,
                error_code="OdooApplicationRejected",
                error_message=str(exc),
                reconciled=True,
            )
        if not rows:
            return None
        if len(rows) != 1:
            return ConnectorResult(
                ConnectorStatus.FAILED,
                error_code="DuplicateExternalRequestIdentity",
                error_message="reconciliation found multiple Odoo employee operations",
                reconciled=True,
            )
        return ConnectorResult(
            ConnectorStatus.SUCCEEDED,
            external_operation_ref=f"odoo:hr.employee:{rows[0]['id']}",
            reconciled=True,
        )

    async def _lookup(self, field: str, value: str) -> list[dict[str, Any]]:
        rows = await self._execute_kw(
            "hr.employee",
            "search_read",
            [[(field, "=", value)]],
            {"fields": ["id", field], "limit": 2},
        )
        return rows if isinstance(rows, list) else []

    async def _execute_kw(
        self,
        model: str,
        method: str,
        args: list[Any],
        kwargs: dict[str, Any],
    ) -> Any:
        secret = self.credentials.resolve(self.connection.credential)
        uid = await self._rpc(
            "common",
            "authenticate",
            [self.connection.database, self.connection.username, secret, {}],
        )
        if not isinstance(uid, int) or uid <= 0:
            raise _ApplicationRejected("Odoo connector authentication rejected")
        return await self._rpc(
            "object",
            "execute_kw",
            [self.connection.database, uid, secret, model, method, args, kwargs],
        )

    async def _rpc(self, service: str, method: str, args: list[Any]) -> Any:
        payload = {
            "jsonrpc": "2.0",
            "method": "call",
            "params": {"service": service, "method": method, "args": args},
            "id": str(uuid4()),
        }
        url = f"{self.connection.base_url.rstrip('/')}/jsonrpc"
        try:
            if self._client is not None:
                response = await self._client.post(url, json=payload)
            else:
                async with httpx.AsyncClient(timeout=self.connection.timeout_seconds) as client:
                    response = await client.post(url, json=payload)
            response.raise_for_status()
            raw = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise _TransportUnknown("Odoo transport/result is ambiguous") from exc
        if not isinstance(raw, dict):
            raise _ApplicationRejected("Odoo returned a non-object JSON-RPC response")
        if raw.get("error") is not None:
            raise _ApplicationRejected("Odoo JSON-RPC rejected the operation")
        return raw.get("result")


class OdooEmployeeVerifier:
    """Independent Odoo readback under a separate credential identity."""

    def __init__(self, connector: OdooEmployeeEffectConnector) -> None:
        self.connector = connector

    async def observe(
        self,
        *,
        subject_ref: str,
        expected_postcondition: dict[str, Any],
    ) -> ConnectorResult:
        try:
            rows = await self.connector._lookup(self.connector.connection.subject_ref_field, subject_ref)
            if len(rows) != 1:
                observed: dict[str, Any] = {}
            else:
                employee_id = rows[0]["id"]
                full = await self.connector._execute_kw(
                    "hr.employee",
                    "read",
                    [[employee_id]],
                    {
                        "fields": [
                            "id",
                            "department_id",
                            "parent_id",
                            "work_email",
                            "active",
                            "x_administrative_manager_principal_id",
                            "x_administrative_employment_type",
                            "x_administrative_start_date",
                            self.connector.connection.subject_ref_field,
                        ]
                    },
                )
                row = full[0] if isinstance(full, list) and full else {}
                expected_payload = expected_postcondition.get("payload")
                expected_payload = expected_payload if isinstance(expected_payload, dict) else {}
                payload: dict[str, Any] = {}
                for key in expected_payload:
                    if key == "employee_ref":
                        payload[key] = subject_ref
                    elif key == "department_ref":
                        dep = _many2one_id(row.get("department_id"))
                        payload[key] = f"odoo:hr.department:{dep}" if dep is not None else None
                    elif key == "manager_principal_id":
                        payload[key] = row.get("x_administrative_manager_principal_id") or None
                    elif key == "employment_type":
                        payload[key] = row.get("x_administrative_employment_type") or None
                    elif key == "start_date":
                        payload[key] = row.get("x_administrative_start_date") or None
                    else:
                        payload[key] = expected_payload[key]
                observed = {
                    "target_system": "hris",
                    "operation": "employee.create",
                    "subject_ref": subject_ref,
                    "active": bool(row.get("active", False)),
                    "payload": payload,
                }
            return ConnectorResult(
                ConnectorStatus.SUCCEEDED,
                observed_postcondition=observed,
            )
        except _TransportUnknown as exc:
            return ConnectorResult(
                ConnectorStatus.UNAVAILABLE,
                error_code=type(exc.__cause__).__name__ if exc.__cause__ else type(exc).__name__,
                error_message=str(exc),
            )
        except _ApplicationRejected as exc:
            return ConnectorResult(
                ConnectorStatus.UNAVAILABLE,
                error_code="OdooVerificationRejected",
                error_message=str(exc),
            )


@dataclass(frozen=True, slots=True)
class KeycloakEffectConnection:
    base_url: str
    realm: str
    client_id: str
    credential: CredentialRef
    request_ref_attribute: str = "administrative_request_ref"
    subject_ref_attribute: str = "administrative_subject_ref"
    timeout_seconds: float = 10.0
    allow_insecure_http: bool = False

    def __post_init__(self) -> None:
        _validate_base_url(self.base_url, allow_insecure_http=self.allow_insecure_http)
        if not self.realm.strip() or not self.client_id.strip():
            raise ConnectorConfigurationError("Keycloak realm and client_id are required")


class KeycloakIdentityEffectConnector:
    def __init__(
        self,
        connection: KeycloakEffectConnection,
        *,
        credentials: CredentialResolver | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.connection = connection
        self.credentials = credentials or EnvironmentCredentialResolver()
        self._client = client

    async def invoke(
        self,
        *,
        request_ref: str,
        subject_ref: str,
        parameters: dict[str, Any],
    ) -> ConnectorResult:
        try:
            existing = await self._find_by_attribute(self.connection.request_ref_attribute, request_ref)
            if len(existing) > 1:
                return ConnectorResult(
                    ConnectorStatus.FAILED,
                    error_code="DuplicateExternalRequestIdentity",
                    error_message="multiple Keycloak users share the same request_ref",
                )
            if existing:
                return ConnectorResult(
                    ConnectorStatus.SUCCEEDED,
                    external_operation_ref=f"keycloak:user:{existing[0]['id']}",
                    reconciled=True,
                )

            by_subject = await self._find_by_attribute(
                self.connection.subject_ref_attribute,
                subject_ref,
            )
            if len(by_subject) > 1:
                return ConnectorResult(
                    ConnectorStatus.FAILED,
                    error_code="DuplicateExternalSubjectIdentity",
                    error_message="multiple Keycloak users share the same subject_ref",
                )
            if by_subject:
                # An earlier attempt or run already created the identity for
                # this subject; reconcile instead of creating a duplicate.
                return ConnectorResult(
                    ConnectorStatus.SUCCEEDED,
                    external_operation_ref=f"keycloak:user:{by_subject[0]['id']}",
                    reconciled=True,
                )

            username = str(
                parameters.get("username")
                or parameters.get("work_email")
                or parameters.get("employee_ref")
                or subject_ref
            )
            attributes = {
                self.connection.request_ref_attribute: [request_ref],
                self.connection.subject_ref_attribute: [subject_ref],
            }
            for key in (
                "employee_ref",
                "department_ref",
                "manager_principal_id",
                "start_date",
                "employment_type",
            ):
                value = parameters.get(key)
                if value is not None:
                    attributes[f"administrative_{key}"] = [str(value)]
            body = {
                "username": username,
                "email": parameters.get("work_email") or None,
                "enabled": True,
                "attributes": attributes,
            }
            response = await self._request(
                "POST",
                f"/admin/realms/{self.connection.realm}/users",
                json_body=body,
            )
            if response.status_code >= 500:
                return ConnectorResult(
                    ConnectorStatus.UNKNOWN,
                    error_code="KeycloakServerResultAmbiguous",
                    error_message=f"Keycloak create returned HTTP {response.status_code}",
                )
            if response.status_code not in {201, 204}:
                return ConnectorResult(
                    ConnectorStatus.FAILED,
                    error_code="KeycloakCreateRejected",
                    error_message=f"Keycloak create returned HTTP {response.status_code}",
                )
            location = response.headers.get("Location", "")
            user_id = location.rstrip("/").rsplit("/", 1)[-1] if location else ""
            if not user_id:
                found = await self._find_by_attribute(self.connection.request_ref_attribute, request_ref)
                if len(found) == 1:
                    user_id = str(found[0]["id"])
            return ConnectorResult(
                ConnectorStatus.SUCCEEDED,
                external_operation_ref=(f"keycloak:user:{user_id}" if user_id else None),
            )
        except _TransportUnknown as exc:
            return ConnectorResult(
                ConnectorStatus.UNKNOWN,
                error_code=type(exc.__cause__).__name__ if exc.__cause__ else type(exc).__name__,
                error_message=str(exc),
            )

    async def reconcile(self, request_ref: str) -> ConnectorResult | None:
        try:
            rows = await self._find_by_attribute(self.connection.request_ref_attribute, request_ref)
        except _TransportUnknown as exc:
            return ConnectorResult(
                ConnectorStatus.UNKNOWN,
                error_code=type(exc.__cause__).__name__ if exc.__cause__ else type(exc).__name__,
                error_message=str(exc),
                reconciled=True,
            )
        if not rows:
            return None
        if len(rows) != 1:
            return ConnectorResult(
                ConnectorStatus.FAILED,
                error_code="DuplicateExternalRequestIdentity",
                error_message="reconciliation found multiple Keycloak users",
                reconciled=True,
            )
        return ConnectorResult(
            ConnectorStatus.SUCCEEDED,
            external_operation_ref=f"keycloak:user:{rows[0]['id']}",
            reconciled=True,
        )

    async def _find_by_attribute(self, name: str, value: str) -> list[dict[str, Any]]:
        response = await self._request(
            "GET",
            f"/admin/realms/{self.connection.realm}/users",
            params={"q": f"{name}:{value}", "max": "2"},
        )
        if response.status_code >= 500:
            raise _TransportUnknown(f"Keycloak search returned HTTP {response.status_code}")
        if response.status_code != 200:
            raise _ApplicationRejected(f"Keycloak search rejected HTTP {response.status_code}")
        try:
            raw = response.json()
        except ValueError as exc:
            raise _TransportUnknown("Keycloak search returned invalid JSON") from exc
        return [item for item in raw if isinstance(item, dict)] if isinstance(raw, list) else []

    async def _get_user(self, user_id: str) -> dict[str, Any]:
        response = await self._request(
            "GET",
            f"/admin/realms/{self.connection.realm}/users/{user_id}",
        )
        if response.status_code >= 500:
            raise _TransportUnknown(f"Keycloak user read returned HTTP {response.status_code}")
        if response.status_code != 200:
            raise _ApplicationRejected(f"Keycloak user read rejected HTTP {response.status_code}")
        try:
            raw = response.json()
        except ValueError as exc:
            raise _TransportUnknown("Keycloak user read returned invalid JSON") from exc
        if not isinstance(raw, dict):
            raise _TransportUnknown("Keycloak user read returned invalid representation")
        return raw

    async def _token(self) -> str:
        secret = self.credentials.resolve(self.connection.credential)
        url = (
            f"{self.connection.base_url.rstrip('/')}/realms/{self.connection.realm}"
            "/protocol/openid-connect/token"
        )
        data = {
            "grant_type": "client_credentials",
            "client_id": self.connection.client_id,
            "client_secret": secret,
        }
        try:
            if self._client is not None:
                response = await self._client.post(url, data=data)
            else:
                async with httpx.AsyncClient(timeout=self.connection.timeout_seconds) as client:
                    response = await client.post(url, data=data)
            response.raise_for_status()
            raw = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise _TransportUnknown("Keycloak client-credential authentication is ambiguous") from exc
        token = raw.get("access_token") if isinstance(raw, dict) else None
        if not isinstance(token, str) or not token:
            raise _TransportUnknown("Keycloak token response lacks access_token")
        return token

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> httpx.Response:
        token = await self._token()
        url = f"{self.connection.base_url.rstrip('/')}{path}"
        try:
            if self._client is not None:
                return await self._client.request(
                    method,
                    url,
                    params=params,
                    json=json_body,
                    headers={"Authorization": f"Bearer {token}"},
                )
            async with httpx.AsyncClient(timeout=self.connection.timeout_seconds) as client:
                return await client.request(
                    method,
                    url,
                    params=params,
                    json=json_body,
                    headers={"Authorization": f"Bearer {token}"},
                )
        except httpx.HTTPError as exc:
            raise _TransportUnknown("Keycloak transport/result is ambiguous") from exc


class KeycloakIdentityVerifier:
    def __init__(self, connector: KeycloakIdentityEffectConnector) -> None:
        self.connector = connector

    async def observe(
        self,
        *,
        subject_ref: str,
        expected_postcondition: dict[str, Any],
    ) -> ConnectorResult:
        try:
            users = await self.connector._find_by_attribute(
                self.connector.connection.subject_ref_attribute,
                subject_ref,
            )
            if len(users) != 1 or not users[0].get("id"):
                observed: dict[str, Any] = {}
            else:
                user = await self.connector._get_user(str(users[0]["id"]))
                attributes = (
                    user.get("attributes") if isinstance(user.get("attributes"), dict) else {}
                )
                expected_payload = expected_postcondition.get("payload")
                expected_payload = expected_payload if isinstance(expected_payload, dict) else {}
                payload: dict[str, Any] = {}
                for key in expected_payload:
                    if key == "employee_ref":
                        payload[key] = (
                            _first_attribute(attributes, "administrative_employee_ref")
                            or subject_ref
                        )
                    else:
                        payload[key] = _first_attribute(attributes, f"administrative_{key}")
                observed = {
                    "target_system": "iam",
                    "operation": "identity.create",
                    "subject_ref": subject_ref,
                    "active": bool(user.get("enabled", False)),
                    "payload": payload,
                }
            return ConnectorResult(
                ConnectorStatus.SUCCEEDED,
                observed_postcondition=observed,
            )
        except (_TransportUnknown, _ApplicationRejected) as exc:
            return ConnectorResult(
                ConnectorStatus.UNAVAILABLE,
                error_code=type(exc.__cause__).__name__ if exc.__cause__ else type(exc).__name__,
                error_message=str(exc),
            )


class _TransportUnknown(RuntimeError):
    pass


class _ApplicationRejected(RuntimeError):
    pass


def _validate_base_url(value: str, *, allow_insecure_http: bool) -> None:
    parsed = urlparse(value)
    allowed = {"https"} if not allow_insecure_http else {"http", "https"}
    if parsed.scheme not in allowed or not parsed.hostname:
        raise ConnectorConfigurationError("connector base URL is not permitted")


def _odoo_numeric_ref(value: Any, model: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if not isinstance(value, str):
        return None
    prefix = f"odoo:{model}:"
    if value.startswith(prefix) and value[len(prefix) :].isdigit():
        return int(value[len(prefix) :])
    if value.isdigit():
        return int(value)
    return None


def _many2one_id(value: Any) -> int | None:
    if isinstance(value, (list, tuple)) and value and isinstance(value[0], int):
        return value[0]
    if isinstance(value, int):
        return value
    return None


def _first_attribute(attributes: dict[str, Any], name: str) -> str | None:
    value = attributes.get(name)
    if isinstance(value, list) and value and isinstance(value[0], str):
        return value[0]
    if isinstance(value, str):
        return value
    return None


__all__ = [
    "ConnectorConfigurationError",
    "ConnectorResult",
    "ConnectorStatus",
    "KeycloakEffectConnection",
    "KeycloakIdentityEffectConnector",
    "KeycloakIdentityVerifier",
    "OdooEffectConnection",
    "OdooEmployeeEffectConnector",
    "OdooEmployeeVerifier",
]
