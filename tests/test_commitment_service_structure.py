from __future__ import annotations

from administrative_orchestrator import commitment_service
from administrative_orchestrator.commitment_communication import CommitmentCommunicationCoordinator
from administrative_orchestrator.commitment_service import (
    CommitmentIntakeError,
    KernelCommitmentResponsibilityProvisioner,
    MeetingCommitmentService,
    ResponsibilityProvisioner,
    ResponsibilityRefs,
)


def test_commitment_service_keeps_public_facade_and_compatibility_seams() -> None:
    assert MeetingCommitmentService.__module__ == "administrative_orchestrator.commitment_service"
    assert issubclass(CommitmentIntakeError, ValueError)
    assert KernelCommitmentResponsibilityProvisioner.__module__ == (
        "administrative_orchestrator.commitment_service"
    )
    assert ResponsibilityProvisioner is not None
    assert ResponsibilityRefs is not None
    assert hasattr(commitment_service, "httpx")
    assert hasattr(commitment_service, "KernelExecutionBridge")
    assert callable(CommitmentCommunicationCoordinator.communication_text)
