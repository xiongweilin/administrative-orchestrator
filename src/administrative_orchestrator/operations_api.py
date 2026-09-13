from __future__ import annotations

from fastapi import FastAPI, HTTPException

from .admission import IntakeAssessmentService, IntakePromotionService
from .integrations.kernel.bridge import KernelExecutionBridge
from .operations import projection as _projection
from .operations.administration import (
    _apply_authoritative_refresh as _apply_authoritative_refresh_impl,
)
from .operations.administration import build_administration_router
from .operations.cases import build_case_router
from .operations.commitments import build_commitment_router
from .operations.intake import _admission_bridge as _admission_bridge_impl
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
from .production_readiness import (
    ProductionReadinessError,
    validate_kernel_runtime_compatibility,
)
from .responsibility_discharge import AdministrativeResponsibilityDischargeService

app = FastAPI(title="Administrative Operations API", version="0.3.0")
_runtime: OperationsRuntime = build_operations_runtime()

# Compatibility aliases for existing tests, operational probes, and local
# tooling. Ownership and construction live in operations.runtime; these names
# remain mutable because the pre-refactor module was an established test seam.
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


class _CompatibilityRuntime:
    """Resolve router collaborators through the legacy mutable module seam."""

    @property
    def settings(self):
        return _settings

    @property
    def store(self):
        return _store

    @property
    def authority(self):
        return _authority

    @property
    def access(self):
        return _access

    @property
    def authenticator(self):
        return _authenticator

    @property
    def lifecycle(self):
        return _lifecycle

    @property
    def execution(self):
        return _execution

    @property
    def governance(self):
        return _governance

    @property
    def obligations(self):
        return _obligations

    @property
    def policies(self):
        return _policies

    @property
    def transactions(self):
        return _transactions

    @property
    def uow(self):
        return _uow

    @property
    def intake(self):
        return _intake

    @property
    def intake_assessments(self):
        return _intake_assessments

    @property
    def intake_promotions(self):
        return _intake_promotions

    @property
    def commitments(self):
        return _commitments

    @property
    def commitment_service(self):
        return _commitment_service

    @property
    def investigations(self):
        return _investigations

    @property
    def investigation_service(self):
        return _investigation_service

    def actor(self, request):
        return _actor(request)

    def require(self, actor, permission, *, case=None) -> None:
        _require(actor, permission, case=case)

    def require_intake_review(self, actor) -> None:
        _require_intake_review(actor)


_http_runtime = _CompatibilityRuntime()


def _actor(request):
    return _authenticator.authenticate(request)


def _require(actor, permission, *, case=None) -> None:
    try:
        _access.require(
            actor.principal_id,
            permission,
            case=case,
            organization_scope="*" if case is None else None,
        )
    except Exception as exc:
        from .access_policy import AccessDenied

        if isinstance(exc, AccessDenied):
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        raise


def _require_intake_review(actor) -> None:
    from .access_policy import AdministrativePermission

    _require(actor, AdministrativePermission.INTAKE_REVIEW)


# Preserve helper names previously defined by operations_api.py without
# keeping their implementation in the HTTP composition root.
_case_completion_assessment = _projection.case_completion_assessment
_dedupe_json_records = _projection.dedupe_json_records
_kernel_projection_snapshot = _projection.kernel_projection_snapshot
_termination_snapshot = _projection.termination_snapshot


def _authority_snapshot(case):
    return _projection.authority_snapshot(_http_runtime, case)


def _responsibility_snapshot(case, obligation_set, completion, projections):
    return _projection.responsibility_snapshot(
        _http_runtime,
        case,
        obligation_set,
        completion,
        projections,
        bridge_factory=KernelExecutionBridge,
        discharge_service_factory=AdministrativeResponsibilityDischargeService,
    )


def _apply_authoritative_refresh(case, record):
    return _apply_authoritative_refresh_impl(_http_runtime, case, record)


def _admission_bridge(case_kind):
    return _admission_bridge_impl(_http_runtime, case_kind)


def readyz() -> dict[str, str]:
    if (
        _settings.runtime_profile in {"staging", "production"}
        and _settings.kernel_bridge_mode != "disabled"
    ):
        try:
            validate_kernel_runtime_compatibility(_settings)
        except ProductionReadinessError as exc:
            raise HTTPException(
                status_code=503,
                detail="Agent Kernel compatibility/readiness check failed",
            ) from exc
    return {
        "status": "ready",
        "auth_mode": _settings.auth_mode,
        "runtime_profile": _settings.runtime_profile,
        "hris_source": _settings.hris_source_kind,
        "iam_source": _settings.iam_source_kind,
        "authority_mutation_shortcuts": "forbidden",
        "kernel_revision": (
            _settings.kernel_supported_revision
            if _settings.runtime_profile in {"staging", "production"}
            else "not-required"
        ),
    }


app.include_router(build_case_router(_http_runtime))
app.include_router(build_investigation_router(_http_runtime))
app.include_router(build_transaction_router(_http_runtime))
app.include_router(build_intake_router(_http_runtime))
app.include_router(build_commitment_router(_http_runtime))
app.include_router(build_administration_router(_http_runtime))


def _endpoint(name: str):
    for route in app.routes:
        endpoint = getattr(route, "endpoint", None)
        if endpoint is not None and getattr(endpoint, "__name__", None) == name:
            return endpoint
    raise RuntimeError(f"operations route endpoint {name!r} is unavailable")


# The old module exposed its route functions directly. Keep those callable
# names as aliases to the newly owned router endpoints so existing tests and
# operational scripts retain the exact monkeypatch surface.
healthz = _endpoint("healthz")
case_queue = _endpoint("case_queue")
case_detail = _endpoint("case_detail")
request_case_investigation = _endpoint("request_case_investigation")
list_case_investigations = _endpoint("list_case_investigations")
investigation_detail = _endpoint("investigation_detail")
run_investigation = _endpoint("run_investigation")
record_investigation_proposal = _endpoint("record_investigation_proposal")
request_investigation_evidence = _endpoint("request_investigation_evidence")
add_investigation_evidence = _endpoint("add_investigation_evidence")
assess_investigation_reopen = _endpoint("assess_investigation_reopen")
assess_case_reopen = _endpoint("assess_case_reopen")
authorize_case_reopen = _endpoint("authorize_case_reopen")
case_reopen_history = _endpoint("case_reopen_history")
append_qualification_assessment = _endpoint("append_qualification_assessment")
apply_financial_document_revision = _endpoint("apply_financial_document_revision")
intake_candidate_queue = _endpoint("intake_candidate_queue")
intake_candidate_detail = _endpoint("intake_candidate_detail")
finalize_intake_assessment = _endpoint("finalize_intake_assessment")
promote_intake_candidate = _endpoint("promote_intake_candidate")
commitment_candidate_queue = _endpoint("commitment_candidate_queue")
commitment_candidate_detail = _endpoint("commitment_candidate_detail")
resolve_commitment_speaker = _endpoint("resolve_commitment_speaker")
confirm_commitment_candidate = _endpoint("confirm_commitment_candidate")
commitment_detail = _endpoint("commitment_detail")
attest_commitment_fulfillment = _endpoint("attest_commitment_fulfillment")
revise_commitment_due = _endpoint("revise_commitment_due")
cancel_commitment = _endpoint("cancel_commitment")
refresh_authoritative_facts = _endpoint("refresh_authoritative_facts")
replay_dead_letter = _endpoint("replay_dead_letter")
bind_identity = _endpoint("bind_identity")
revoke_identity = _endpoint("revoke_identity")
deactivate_principal = _endpoint("deactivate_principal")
expire_role_assignment = _endpoint("expire_role_assignment")
expire_delegation = _endpoint("expire_delegation")
authority_events = _endpoint("authority_events")


__all__ = [
    "app",
    "AdministrativeResponsibilityDischargeService",
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
    "IntakeAssessmentService",
    "IntakeCandidateDetail",
    "IntakePromotionBody",
    "IntakePromotionResponse",
    "IntakePromotionService",
    "IntakeQueueItem",
    "InvestigationEvidenceBody",
    "InvestigationEvidenceRequestBody",
    "InvestigationProposalBody",
    "InvestigationRequestBody",
    "KernelExecutionBridge",
    "OutboxReplayResponse",
    "QualificationAssessmentBody",
    "QueueItem",
    "RefreshFactsResponse",
    "ReopenAssessmentBody",
    "ReopenCaseBody",
    "validate_kernel_runtime_compatibility",
]
