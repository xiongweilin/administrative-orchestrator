from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Protocol


class CredentialResolutionError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class CredentialRef:
    configuration_ref: str
    environment_variable: str


class CredentialResolver(Protocol):
    def resolve(self, ref: CredentialRef) -> str: ...


class EnvironmentCredentialResolver:
    """Resolve a secret at process edge without persisting its value.

    Domain records, Kernel contracts, logs and provider bindings should retain
    only `configuration_ref`; the resolved secret is intentionally ephemeral.
    """

    def resolve(self, ref: CredentialRef) -> str:
        value = os.environ.get(ref.environment_variable, "")
        if not value:
            raise CredentialResolutionError(
                f"credential configuration {ref.configuration_ref!r} is unavailable"
            )
        return value


__all__ = [
    "CredentialRef",
    "CredentialResolutionError",
    "CredentialResolver",
    "EnvironmentCredentialResolver",
]
