from __future__ import annotations

from typing import Any

import httpx
from pydantic import BaseModel


EXPECTED_CATALOG_VERSION = "portable-runtime-contracts-v1"
EXPECTED_OWNER = "portable-runtime/contracts"
EXPECTED_RUNTIME_PROTOCOL = "2.0"
EXPECTED_PERSISTENT_RESPONSIBILITY = "persistent-responsibility-v1"


class KernelCompatibilityError(RuntimeError):
    pass


class KernelContractIdentity(BaseModel):
    catalog_version: str
    owner: str
    runtime_protocol: str
    persistent_responsibility_contract: str


def validate_kernel_catalog(raw: dict[str, Any]) -> KernelContractIdentity:
    try:
        persistent = raw["contracts"]["persistent_responsibility"]["current"]
        identity = KernelContractIdentity(
            catalog_version=str(raw["catalog_version"]),
            owner=str(raw["owner"]),
            runtime_protocol=str(raw["runtime_protocol"]),
            persistent_responsibility_contract=str(persistent),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise KernelCompatibilityError("kernel contract catalog is structurally incomplete") from exc

    mismatches: list[str] = []
    if identity.catalog_version != EXPECTED_CATALOG_VERSION:
        mismatches.append(
            f"catalog_version={identity.catalog_version!r}, expected {EXPECTED_CATALOG_VERSION!r}"
        )
    if identity.owner != EXPECTED_OWNER:
        mismatches.append(f"owner={identity.owner!r}, expected {EXPECTED_OWNER!r}")
    if identity.runtime_protocol != EXPECTED_RUNTIME_PROTOCOL:
        mismatches.append(
            f"runtime_protocol={identity.runtime_protocol!r}, expected {EXPECTED_RUNTIME_PROTOCOL!r}"
        )
    if identity.persistent_responsibility_contract != EXPECTED_PERSISTENT_RESPONSIBILITY:
        mismatches.append(
            "persistent_responsibility="
            f"{identity.persistent_responsibility_contract!r}, "
            f"expected {EXPECTED_PERSISTENT_RESPONSIBILITY!r}"
        )
    if mismatches:
        raise KernelCompatibilityError("incompatible agent-kernel contracts: " + "; ".join(mismatches))
    return identity


class HttpKernelContractProbe:
    def __init__(self, base_url: str, *, timeout_seconds: float = 3.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def fetch_identity(self) -> KernelContractIdentity:
        try:
            response = httpx.get(
                f"{self.base_url}/v1/contracts",
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise KernelCompatibilityError(f"agent-kernel contract probe unavailable: {exc}") from exc
        if not isinstance(payload, dict):
            raise KernelCompatibilityError("agent-kernel contract catalog must be a JSON object")
        return validate_kernel_catalog(payload)


__all__ = [
    "EXPECTED_CATALOG_VERSION",
    "EXPECTED_OWNER",
    "EXPECTED_PERSISTENT_RESPONSIBILITY",
    "EXPECTED_RUNTIME_PROTOCOL",
    "HttpKernelContractProbe",
    "KernelCompatibilityError",
    "KernelContractIdentity",
    "validate_kernel_catalog",
]
