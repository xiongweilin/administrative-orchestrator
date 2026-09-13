from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Protocol
from uuid import UUID

from .integrations.kernel.models import KernelExecutionStatus
from .integrations.kernel.recovery import KernelRecoveryClient, KernelRecoveryError
from .integrations.kernel.repository import KernelBridgeRepository


class KernelReconciliationVerificationError(RuntimeError):
    pass


class KernelReconciliationVerifier(Protocol):
    def verify(
        self,
        case_id: UUID,
        authority_epoch: int,
        reconciliation_ref: str,
    ) -> None:
        """Prove that Kernel completed reconciliation for this case reference."""


class UnavailableKernelReconciliationVerifier:
    def verify(
        self,
        case_id: UUID,
        authority_epoch: int,
        reconciliation_ref: str,
    ) -> None:
        del case_id, authority_epoch, reconciliation_ref
        raise KernelReconciliationVerificationError(
            "Kernel reconciliation verifier is unavailable"
        )


@dataclass(frozen=True, slots=True)
class LocalKernelReconciliationVerifier:
    """Validate a reconciliation reference against Administrative's Kernel projection.

    The projection identifies the exact historical execution. The resolution is
    read from Kernel through its recovery contract; Administrative never calls a
    provider or infers reconciliation from an arbitrary caller-supplied string.
    """

    repository: KernelBridgeRepository
    recovery_client: KernelRecoveryClient

    _TERMINAL_RECONCILIATION_STATUSES: ClassVar[frozenset[str]] = frozenset(
        {
            "authorization-rejected",
            "execution-failed",
            "verified-fail",
            "completed",
            "recovered-failed",
            "recovered-verified-fail",
            "recovered-completed",
        }
    )

    def verify(
        self,
        case_id: UUID,
        authority_epoch: int,
        reconciliation_ref: str,
    ) -> None:
        reference = reconciliation_ref.strip()
        if not reference:
            raise KernelReconciliationVerificationError(
                "Kernel reconciliation reference must not be blank"
            )
        projection = next(
            (
                item
                for item in self.repository.list_projections_for_case(case_id)
                if item.kernel_execution_ref == reference
            ),
            None,
        )
        if projection is None:
            raise KernelReconciliationVerificationError(
                "Kernel reconciliation reference is not bound to this case"
            )
        if projection.authority_epoch > authority_epoch:
            raise KernelReconciliationVerificationError(
                "Kernel reconciliation reference belongs to a future authority epoch"
            )
        if projection.kernel_execution_status is not KernelExecutionStatus.EXECUTION_UNKNOWN:
            raise KernelReconciliationVerificationError(
                "Kernel reconciliation reference is not an execution-unknown target"
            )
        try:
            resolution = self.recovery_client.inspect(
                reference,
                expected_work_ref=projection.kernel_work_ref,
            )
        except KernelRecoveryError as exc:
            raise KernelReconciliationVerificationError(
                "Kernel reconciliation resolution is unavailable"
            ) from exc
        if resolution is None:
            raise KernelReconciliationVerificationError(
                "Kernel reconciliation resolution is unavailable"
            )
        if resolution.current_status not in self._TERMINAL_RECONCILIATION_STATUSES:
            raise KernelReconciliationVerificationError(
                "Kernel reconciliation has not reached a terminal resolution"
            )


__all__ = [
    "KernelReconciliationVerificationError",
    "KernelReconciliationVerifier",
    "LocalKernelReconciliationVerifier",
    "UnavailableKernelReconciliationVerifier",
]
