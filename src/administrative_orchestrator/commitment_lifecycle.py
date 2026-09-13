from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from .commitment_models import CommitmentRecord


class CommitmentLifecycleCoordinator:
    """Own bounded commitment lifecycle transitions outside candidate admission."""

    def __init__(self, service: Any) -> None:
        self.service = service

    def attest_fulfillment(
        self,
        case_id: UUID,
        *,
        principal_id: str,
        basis: dict[str, Any],
        at: datetime | None = None,
    ) -> CommitmentRecord:
        return self.service._attest_fulfillment_impl(
            case_id,
            principal_id=principal_id,
            basis=basis,
            at=at,
        )


__all__ = ["CommitmentLifecycleCoordinator"]
