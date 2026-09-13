from __future__ import annotations

from fastapi import FastAPI

from .operations import projection as _projection
from .operations.administration import build_administration_router
from .operations.cases import build_case_router
from .operations.commitments import build_commitment_router
from .operations.intake import build_intake_router
from .operations.investigations import build_investigation_router
from .operations.models import (
    BindIdentityBody,
    CommitmentCancellationBody,
    CommitmentCandidateQueueItem,
    CommitmentConfirmationBody,
    CommitmentDueRevisionBody,
    CommitmentFulfillmentBody,
    CommitmentSpeakerResolutionBody,
    ExpireAuthorityBody,
    FinancialDocumentRevisionBody,
    IntakeAssessmentBody,
    IntakeCandidateDetail,
    IntakePromotionBody,
    IntakePromotionResponse,
    IntakeQueueItem,
    InvestigationEvidenceBody,
    InvestigationEvidenceRequestBody,
    InvestigationProposalBody,
    InvestigationRequestBody,
    OutboxReplayResponse,
    QualificationAssessmentBody,
    QueueItem,
    RefreshFactsResponse,
    ReopenAssessmentBody,
    ReopenCaseBody,
)
from .operations.runtime import OperationsRuntime, build_operations_runtime
from .operations.transactions import build_transaction_router

app = FastAPI(title="Administrative Operations API", version="0.3.0")
_runtime: OperationsRuntime = build_operations_runtime()

# Compatibility aliases for existing tests, operational probes, and local
# tooling. The ownership and construction of these collaborators now lives in
# operations.runtime rather than this HTTP composition root.
_settings = _runtime.settings
_store = _runtime.store
_authority = _runtime.authority
_access = _runtime.access
_authenticator = _runtime.authenticator
_lifecycle = _runtime.lifecycle
_execution = _runtime.execution
_governance = _runtime.governance
_obligations = _runtime.obligations
_policies = _runtime.policies
_transactions = _runtime.transactions
_uow = _runtime.uow
_intake = _runtime.intake
_intake_assessments = _runtime.intake_assessments
_intake_promotions = _runtime.intake_promotions
_commitments = _runtime.commitments
_commitment_service = _runtime.commitment_service
_investigations = _runtime.investigations
_investigation_service = _runtime.investigation_service

# Preserve helper names previously defined by operations_api.py without
# keeping their implementation in the HTTP composition root.
_case_completion_assessment = _projection.case_completion_assessment
_dedupe_json_records = _projection.dedupe_json_records
_kernel_projection_snapshot = _projection.kernel_projection_snapshot
_termination_snapshot = _projection.termination_snapshot


def _actor(request):
    return _runtime.actor(request)


def _require(actor, permission, *, case=None) -> None:
    _runtime.require(actor, permission, case=case)


def _require_intake_review(actor) -> None:
    _runtime.require_intake_review(actor)


def _authority_snapshot(case):
    return _projection.authority_snapshot(_runtime, case)


def _responsibility_snapshot(case, obligation_set, completion, projections):
    return _projection.responsibility_snapshot(
        _runtime,
        case,
        obligation_set,
        completion,
        projections,
    )


app.include_router(build_case_router(_runtime))
app.include_router(build_investigation_router(_runtime))
app.include_router(build_transaction_router(_runtime))
app.include_router(build_intake_router(_runtime))
app.include_router(build_commitment_router(_runtime))
app.include_router(build_administration_router(_runtime))


__all__ = [
    "app",
    "BindIdentityBody",
    "CommitmentCancellationBody",
    "CommitmentCandidateQueueItem",
    "CommitmentConfirmationBody",
    "CommitmentDueRevisionBody",
    "CommitmentFulfillmentBody",
    "CommitmentSpeakerResolutionBody",
    "ExpireAuthorityBody",
    "FinancialDocumentRevisionBody",
    "IntakeAssessmentBody",
    "IntakeCandidateDetail",
    "IntakePromotionBody",
    "IntakePromotionResponse",
    "IntakeQueueItem",
    "InvestigationEvidenceBody",
    "InvestigationEvidenceRequestBody",
    "InvestigationProposalBody",
    "InvestigationRequestBody",
    "OutboxReplayResponse",
    "QualificationAssessmentBody",
    "QueueItem",
    "RefreshFactsResponse",
    "ReopenAssessmentBody",
    "ReopenCaseBody",
]
