"""Agent Kernel integration boundary.

Administrative business semantics stay outside this package.  This package may
project those semantics into canonical Agent Kernel public contracts, but it
must not mint or reconstruct Kernel runtime authority.
"""

from .bridge import KernelExecutionBridge
from .compatibility import KernelCompatibilityError, KernelContractIdentity
from .models import AdministrativeEffectIntent, AdministrativeExecutionGrant

__all__ = [
    "AdministrativeEffectIntent",
    "AdministrativeExecutionGrant",
    "KernelCompatibilityError",
    "KernelContractIdentity",
    "KernelExecutionBridge",
]
