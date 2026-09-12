from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import FastAPI, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from .access_policy import AccessDenied, AdministrativeAccessPolicy, AdministrativePermission
from .admission import (
    AdmissionConflict,
    AdmissionRejected,
    IntakeAssessmentService,
    IntakePromotionService,
)
from .auth import AuthenticatedPrincipal, Authenticator
from .authority import AuthorityError, AuthorityRepository, IdentityBinding
from .authority_lifecycle import AuthorityLifecycleEvent, AuthorityLifecycleRepository
from .candidate_admission import CandidateAdministrativeAdmissionService
from .completion import CompletionAssessment, assess_administrative_completion
from .config import get_settings
from .conversation import ConversationMessageRow, ConversationRow
from .domain import (
    AdministrativeCase,
    AdministrativeRequest,
    CaseStatus,
    FactAuthority,
    FactSnapshot,
    utcnow,
)
from .execution_repository import ExecutionRepository
from .fact_acquisition import (
    FactAcquisitionError,
    build_hris_source,
    merge_authoritative_offboarding_facts,
    merge_authoritative_onboarding_facts,
)
from .fact_transitions import replace_facts_for_reevaluation
from .financial import (
    AdministrativeCaseEvidenceLink,
    ExpenseFacts,
    InvoiceFacts,
    ProcurementFacts,
    TransactionQualificationAssessment,
    TransactionQualificationResult,
    has_material_financial_revision,
)
from .financial_admission import (
    CandidateExpenseAdmissionService,
    CandidateInvoiceAPAdmissionService,
    CandidateProcurementAdmissionService,
)
from .governance import GovernanceRepository
from .inspection import list_authorizations, list_decisions, list_realizations
from .intake.models import (
    CandidateAdministrativeRequest,
    CandidateStatus,
    IntakeAssessment,
    IntakeDisposition,
    PromotionRecord,
)
from .intake.repository import AssessmentConflict, IntakeRepository
from .integrations.kernel.bridge import KernelExecutionBridge
from .integrations.kernel.client import KernelResponsibilityDischargeError
from .integrations.kernel.repository import KernelBridgeRepository
from .messaging import (
    OutboxEventNotFailed,
    OutboxEventNotFound,
    replay_failed_outbox,
)
from .obligations import ObligationRepository
from .offboarding_admission import CandidateOffboardingAdmissionService
from .onboarding_admission import (
    CandidateOnboardingAdmissionService,
    OnboardingAdmissionError,
)
from .persistence import CaseRow, ConcurrencyConflict, SqlStore
from .policy import OffboardingFacts, OnboardingFacts, PolicyEvaluation
from .policy_plane import (
    PolicyPlaneError,
    PolicyRepository,
    compile_expense_policy,
    compile_invoice_ap_policy,
    compile_offboarding_policy,
    compile_onboarding_policy,
    compile_procurement_policy,
)
from .production_readiness import (
    ProductionReadinessError,
    validate_kernel_runtime_compatibility,
)
from .responsibility_discharge import (
    AdministrativeResponsibilityDischargeService,
    ResponsibilityDischargeBlocked,
)
from .service import TransitionError, apply_policy_evaluation, start_policy_evaluation
from .transaction_repository import TransactionRepository
from .transfer import TransferRequirementRepository
from .unit_of_work import AdministrativeUnitOfWork

app = FastAPI(title="Administrative Operations API", version="0.3.0")

_settings = get_settings()
_store = SqlStore(_settings.database_url)
_authority = AuthorityRepository(_store)
_access = AdministrativeAccessPolicy(_authority)
_authenticator = Authenticator(_store, _settings)
_lifecycle = AuthorityLifecycleRepository(_store)
_execution = ExecutionRepository(_store)
_governance = GovernanceRepository(_store)
_obligations = ObligationRepository(_store)
_policies = PolicyRepository(_store)
_transactions = TransactionRepository(_store)
_uow = AdministrativeUnitOfWork(_store)
_intake = IntakeRepository(_store)
_intake_assessments = IntakeAssessmentService(_intake)
_intake_promotions = IntakePromotionService(_store, _intake)
_CONVERSATION_SCHEMA = (ConversationRow, ConversationMessageRow)
if _settings.auto_create_schema:
    _store.init_schema()


class QueueItem(BaseModel):
    case_id: UUID
    case_kind: str
    status: CaseStatus
    subject_ref: str
    requester_principal_id: str
    version: int
    authority_epoch: int
    updated_at: datetime


class RefreshFactsResponse(BaseModel):
    case: AdministrativeCase
    source: str
    source_ref: str
    source_version: str
    source_digest: str


class BindIdentityBody(BaseModel):
    provider: str = Field(min_length=1, max_length=255)
    external_subject: str = Field(min_length=1, max_length=512)
    principal_id: str = Field(min_length=1, max_length=255)
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    reason: str = Field(min_length=1, max_length=2000)


class ReasonBody(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)


class QualificationAssessmentBody(BaseModel):
    assessment_kind: str = Field(min_length=1, max_length=128)
    input_refs: tuple[str, ...] = Field(min_length=1)
    rule_ref: str = Field(min_length=1, max_length=512)
    result: TransactionQualificationResult
    blocking_reasons: tuple[str, ...] = ()


class FinancialDocumentRevisionBody(BaseModel):
    facts: dict[str, Any]
    source_ref: str = Field(min_length=1, max_length=1000)
    source_version: str = Field(min_length=1, max_length=256)
    artifact_ref: UUID | None = None
    representation_ref: UUID | None = None
    declared_role: str = Field(default="material-revision", min_length=1, max_length=128)


class OutboxReplayResponse(BaseModel):
    event_id: UUID
    status: str
    attempts: int
    audit_id: UUID


class ExpireAuthorityBody(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)
    at: datetime | None = None


class IntakeQueueItem(BaseModel):
    candidate_id: UUID
    conversation_ref: str
    candidate_requester: str
    candidate_intent: str
    status: CandidateStatus
    created_at: datetime
    latest_assessment: IntakeAssessment | None = None


class IntakeCandidateDetail(BaseModel):
    candidate: CandidateAdministrativeRequest
    assessments: list[IntakeAssessment]
    promotion: PromotionRecord | None = None


class IntakeAssessmentBody(BaseModel):
    disposition: IntakeDisposition
    basis: dict[str, Any] = Field(default_factory=dict)


class IntakePromotionBody(BaseModel):
    assessment_id: UUID
    source_system: str = Field(min_length=1, max_length=128)
    tenant_ref: str = Field(min_length=1, max_length=512)
    source_event_id: str = Field(min_length=1, max_length=512)
    requester_principal_id: str = Field(min_length=1, max_length=255)
    channel: str = Field(default="intake", min_length=1, max_length=64)
    case_kind: str = Field(default="intake", min_length=1, max_length=128)
    subject_ref: str | None = Field(default=None, max_length=512)
    bridge_to_m5: bool = False
    bridge_to_m8: bool = False
    promotion_policy_ref: str = Field(
        default="m6-human-confirmed-v1", min_length=1, max_length=512
    )


class IntakePromotionResponse(BaseModel):
    promotion: PromotionRecord
    request: AdministrativeRequest
    case: AdministrativeCase
    created: bool
    policy_evaluation: PolicyEvaluation | None = None


def _actor(request: Request) -> AuthenticatedPrincipal:
    return _authenticator.authenticate(request)


def _require(
    actor: AuthenticatedPrincipal,
    permission: AdministrativePermission,
    *,
    case: AdministrativeCase | None = None,
) -> None:
    try:
        _access.require(
            actor.principal_id,
            permission,
            case=case,
            organization_scope="*" if case is None else None,
        )
    except AccessDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


def _require_intake_review(actor: AuthenticatedPrincipal) -> None:
    _require(actor, AdministrativePermission.INTAKE_REVIEW)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz")
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


@app.get("/v1/operations/cases", response_model=list[QueueItem])
def case_queue(
    request: Request,
    status_filter: Annotated[list[CaseStatus] | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
) -> list[QueueItem]:
    actor = _actor(request)
    _require(actor, AdministrativePermission.OPERATIONS_READ)
    with _store.sessions() as db:
        statement = select(CaseRow).order_by(CaseRow.updated_at.desc()).limit(limit)
        if status_filter:
            statement = statement.where(CaseRow.status.in_([item.value for item in status_filter]))
        rows = db.execute(statement).scalars().all()
    return [
        QueueItem(
            case_id=row.case_id,
            case_kind=row.case_kind,
            status=CaseStatus(row.status),
            subject_ref=row.subject_ref,
            requester_principal_id=row.requester_principal_id,
            version=row.version,
            authority_epoch=row.authority_epoch,
            updated_at=row.updated_at,
        )
        for row in rows
    ]


@app.get("/v1/operations/cases/{case_id}")
def case_detail(case_id: UUID, request: Request) -> dict:
    actor = _actor(request)
    case = _store.get_case(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="case not found")
    _require(actor, AdministrativePermission.OPERATIONS_READ)

    obligation_set = _obligations.get_current(case.case_id, case.authority_epoch)
    effects = _execution.list_effects(case.case_id, case.authority_epoch)
    outcomes = _execution.list_outcomes(case.case_id, case.authority_epoch)
    realizations = _execution.list_realizations(case.case_id, case.authority_epoch)
    links = _obligations.list_links(case.case_id, case.authority_epoch)
    fulfillments = _obligations.list_domain_state_fulfillments(
        case.case_id, case.authority_epoch
    )
    completion = _case_completion_assessment(
        obligation_set,
        effects,
        outcomes,
        realizations=realizations,
        links=links,
        fulfillments=fulfillments,
    )
    projections = KernelBridgeRepository(_store).list_projections_for_case(case.case_id)
    transfers = TransferRequirementRepository(_store).list_for_case(
        case.case_id, case.authority_epoch
    )
    authority = _authority_snapshot(case)
    audit = None
    if _access.allows(actor.principal_id, AdministrativePermission.AUDIT_READ, case=case):
        audit = _store.list_audit_events(case.case_id)
    return {
        "case": case.model_dump(mode="json"),
        "policy": (
            evaluation.model_dump(mode="json")
            if (evaluation := _store.get_latest_policy_evaluation(case.case_id)) is not None
            else None
        ),
        "governance": (
            basis.model_dump(mode="json")
            if (basis := _governance.get_current_for_case(case.case_id, case.authority_epoch))
            is not None
            else None
        ),
        "obligations": obligation_set.model_dump(mode="json") if obligation_set else None,
        "effects": [item.model_dump(mode="json") for item in effects],
        "realizations": [
            item.model_dump(mode="json") for item in list_realizations(_store, case.case_id)
        ],
        "outcomes": [item.model_dump(mode="json") for item in outcomes],
        "decisions": [
            item.model_dump(mode="json") for item in list_decisions(_store, case.case_id)
        ],
        "authorizations": [
            item.model_dump(mode="json") for item in list_authorizations(_store, case.case_id)
        ],
        "termination": _termination_snapshot(case),
        "authority": authority,
        "transfers": [item.model_dump(mode="json") for item in transfers],
        "domain_fulfillments": [item.model_dump(mode="json") for item in fulfillments],
        "evidence_links": [
            item.model_dump(mode="json")
            for item in _transactions.list_evidence_links(case.case_id, case.authority_epoch)
        ],
        "qualification_assessments": [
            item.model_dump(mode="json")
            for item in _transactions.list_assessments(case.case_id, case.authority_epoch)
        ],
        "completion_assessment": completion.model_dump(mode="json"),
        "kernel_projections": [_kernel_projection_snapshot(item) for item in projections],
        "responsibility_discharge": _responsibility_snapshot(
            case,
            obligation_set,
            completion,
            projections,
        ),
        "audit": audit,
    }


@app.post(
    "/v1/operations/cases/{case_id}/qualification-assessments",
    response_model=TransactionQualificationAssessment,
)
def append_qualification_assessment(
    case_id: UUID,
    payload: QualificationAssessmentBody,
    request: Request,
) -> TransactionQualificationAssessment:
    actor = _actor(request)
    case = _store.get_case(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="case not found")
    if case.case_kind not in {
        "procurement-request",
        "invoice-ap-preparation",
        "expense-reimbursement",
    }:
        raise HTTPException(status_code=409, detail="case kind is not a transaction case")
    _require(actor, AdministrativePermission.FACTS_ATTEST, case=case)
    assessment = TransactionQualificationAssessment(
        case_id=case.case_id,
        authority_epoch=case.authority_epoch,
        assessment_kind=payload.assessment_kind,
        input_refs=payload.input_refs,
        rule_ref=payload.rule_ref,
        result=payload.result,
        blocking_reasons=payload.blocking_reasons,
    )
    return _transactions.append_assessment(assessment)


@app.post(
    "/v1/operations/cases/{case_id}/document-revision",
    response_model=AdministrativeCase,
)
def apply_financial_document_revision(
    case_id: UUID,
    payload: FinancialDocumentRevisionBody,
    request: Request,
) -> AdministrativeCase:
    """Invalidate the current financial governance world for a new document revision."""

    actor = _actor(request)
    case = _store.get_case(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="case not found")
    if case.case_kind not in {
        "procurement-request",
        "invoice-ap-preparation",
        "expense-reimbursement",
    }:
        raise HTTPException(status_code=409, detail="case kind is not a transaction case")
    _require(actor, AdministrativePermission.FACTS_ATTEST, case=case)
    if case.fact_snapshot is None:
        raise HTTPException(status_code=409, detail="case has no current document facts")
    if case.status in {CaseStatus.COMPLETED, CaseStatus.CANCELLED}:
        raise HTTPException(status_code=409, detail="terminal case cannot accept a document revision")

    typed_facts: Any
    if case.case_kind == "procurement-request":
        typed_facts = ProcurementFacts.model_validate(payload.facts)
    elif case.case_kind == "invoice-ap-preparation":
        typed_facts = InvoiceFacts.model_validate(payload.facts)
    else:
        typed_facts = ExpenseFacts.model_validate(payload.facts)
    facts = typed_facts.model_dump(mode="json")
    try:
        material = has_material_financial_revision(
            case.case_kind,
            case.fact_snapshot.facts,
            facts,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not material:
        raise HTTPException(status_code=409, detail="document revision has no material financial change")

    snapshot = FactSnapshot(
        source=f"document-revision:{actor.principal_id}",
        owner=actor.principal_id,
        authority=FactAuthority.CLAIM,
        source_ref=payload.source_ref,
        source_version=payload.source_version,
        facts=facts,
    )
    changed = replace_facts_for_reevaluation(case, snapshot)
    try:
        policy_record = _policies.resolve_current(
            {
                "procurement-request": "procurement-request",
                "invoice-ap-preparation": "invoice-ap-preparation",
                "expense-reimbursement": "expense-reimbursement",
            }[case.case_kind]
        )
        if case.case_kind == "procurement-request":
            evaluation = compile_procurement_policy(policy_record).evaluate(typed_facts)
        elif case.case_kind == "invoice-ap-preparation":
            evaluation = compile_invoice_ap_policy(policy_record).evaluate(typed_facts)
        else:
            evaluation = compile_expense_policy(policy_record).evaluate(typed_facts)
        updated = apply_policy_evaluation(changed, evaluation)
        _uow.replace_facts_and_apply_policy(case, updated, evaluation)
    except (ConcurrencyConflict, TransitionError, PolicyPlaneError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    if payload.artifact_ref is not None:
        _transactions.append_evidence_link(
            AdministrativeCaseEvidenceLink(
                case_id=updated.case_id,
                authority_epoch=updated.authority_epoch,
                artifact_ref=payload.artifact_ref,
                representation_ref=payload.representation_ref,
                declared_role=payload.declared_role,
                source=payload.source_ref,
                linked_by=actor.principal_id,
            )
        )
    return updated


def _case_completion_assessment(
    obligation_set,
    effects,
    outcomes,
    *,
    realizations,
    links,
    fulfillments,
) -> CompletionAssessment:
    if obligation_set is None:
        return CompletionAssessment(
            requirement_id="missing-current-obligation-set",
            satisfied=False,
            blocking_reasons=("missing current obligation set",),
        )
    return assess_administrative_completion(
        obligation_set,
        effects,
        outcomes,
        realizations=realizations,
        links=links,
        fulfillments=fulfillments,
    )


def _termination_snapshot(case: AdministrativeCase) -> dict[str, Any]:
    facts = case.fact_snapshot.facts if case.fact_snapshot is not None else {}
    return {
        "termination_status": facts.get("termination_status"),
        "termination_effective_at": facts.get("termination_effective_at"),
        "employment_episode_ref": facts.get("employment_episode_ref"),
        "authoritative_fact_snapshot": (
            case.fact_snapshot.model_dump(mode="json") if case.fact_snapshot else None
        ),
    }


def _authority_snapshot(case: AdministrativeCase) -> dict[str, list[dict[str, Any]]]:
    facts = case.fact_snapshot.facts if case.fact_snapshot is not None else {}
    principal_ids = {
        str(value)
        for key, value in facts.items()
        if key.endswith("principal_id") and isinstance(value, str) and value.strip()
    }
    principal_ids.add(case.requester_principal_id)
    bindings: list[dict[str, Any]] = []
    roles: list[dict[str, Any]] = []
    delegations: list[dict[str, Any]] = []
    observed_at = utcnow()
    for principal_id in sorted(principal_ids):
        bindings.extend(
            item.model_dump(mode="json")
            for item in _authority.list_current_identity_bindings(
                principal_id, at=observed_at
            )
        )
        roles.extend(
            item.model_dump(mode="json")
            for item in _authority.list_current_role_assignments(
                principal_id, at=observed_at
            )
        )
        delegations.extend(
            item.model_dump(mode="json")
            for item in _authority.list_current_delegations_involving(
                principal_id, at=observed_at
            )
        )
    return {
        "bindings": _dedupe_json_records(bindings),
        "role_assignments": _dedupe_json_records(roles),
        "delegations": _dedupe_json_records(delegations),
    }


def _kernel_projection_snapshot(projection) -> dict[str, Any]:
    return {
        "projection_id": str(projection.projection_id),
        "obligation_id": str(projection.obligation_id),
        "authority_epoch": projection.authority_epoch,
        "status": projection.status.value,
        "responsibility_ref": projection.kernel_responsibility_ref,
        "responsibility_version": projection.admission_payload.get("responsibility_version"),
        "admission_ref": projection.kernel_admission_ref,
        "assessment_ref": projection.kernel_assessment_ref,
        "proposal_ref": projection.kernel_proposal_ref,
        "work_ref": projection.kernel_work_ref,
        "execution": {
            "status": (
                projection.kernel_execution_status.value
                if projection.kernel_execution_status is not None
                else None
            ),
            "execution_ref": projection.kernel_execution_ref,
            "run_ref": projection.kernel_run_ref,
            "request_ref": projection.kernel_request_ref,
            "authorization_ref": projection.kernel_authorization_ref,
            "provider_id": projection.kernel_provider_id,
            "action_ref": projection.kernel_action_ref,
            "outcome_ref": projection.kernel_outcome_ref,
            "evidence_ref": projection.kernel_evidence_ref,
            "responsibility_ref": projection.kernel_execution_responsibility_ref,
            "processed_at": (
                projection.kernel_execution_processed_at.isoformat()
                if projection.kernel_execution_processed_at is not None
                else None
            ),
        },
    }


def _responsibility_snapshot(
    case: AdministrativeCase,
    obligation_set,
    completion: CompletionAssessment,
    projections,
) -> dict[str, Any]:
    if obligation_set is None:
        return {
            "status": "pending",
            "blocker": "missing_current_obligation_set",
            "responsibilities": [],
            "completion_satisfied": completion.satisfied,
        }
    if not completion.satisfied:
        return {
            "status": "pending",
            "blocker": "completion_assessment_not_satisfied",
            "responsibilities": [],
            "completion_satisfied": False,
        }

    bridge = None
    if _settings.kernel_bridge_mode != "disabled":
        bridge = KernelExecutionBridge(
            _store,
            settings=_settings,
            require_responsibility_discharge=True,
        )
    if bridge is None or not bridge.cutover:
        return {
            "status": "pending",
            "blocker": "kernel_cutover_required",
            "responsibilities": [],
            "completion_satisfied": completion.satisfied,
        }

    service = AdministrativeResponsibilityDischargeService(_store, bridge)
    try:
        handles = service.project_responsibility_set(case, obligation_set)
    except ResponsibilityDischargeBlocked as exc:
        return {
            "status": "pending",
            "blocker": str(exc),
            "responsibilities": [],
            "completion_satisfied": completion.satisfied,
        }

    client = bridge.client()
    observations: list[dict[str, Any]] = []
    for handle in handles:
        assessment_ref, decision_ref, transition_ref = service.discharge_chain_refs(
            case, handle
        )
        current_status = "unknown"
        blocker = None
        try:
            current_status = client.get_responsibility_status(
                handle.responsibility_ref,
                expected_version=handle.responsibility_version,
            ).current_status
        except KernelResponsibilityDischargeError:
            blocker = "kernel_responsibility_status_unavailable"
        observations.append(
            {
                "responsibility_ref": handle.responsibility_ref,
                "responsibility_version": handle.responsibility_version,
                "obligation_ids": [str(item) for item in handle.obligation_ids],
                "current_status": current_status,
                "assessment_ref": assessment_ref,
                "decision_ref": decision_ref,
                "transition_ref": transition_ref,
                "blocker": blocker,
            }
        )

    statuses = {item["current_status"] for item in observations}
    if not observations or statuses == {"discharged"}:
        overall = "discharged"
        blocker = None
    else:
        overall = "pending"
        blocker = next(
            (item["blocker"] for item in observations if item["blocker"]),
            "responsibility_set_not_discharged",
        )
    return {
        "status": overall,
        "blocker": blocker,
        "completion_satisfied": completion.satisfied,
        "responsibilities": observations,
    }


def _dedupe_json_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: dict[str, dict[str, Any]] = {}
    for record in records:
        key = repr(sorted(record.items()))
        unique[key] = record
    return [unique[key] for key in sorted(unique)]


@app.get("/v1/operations/intake/candidates", response_model=list[IntakeQueueItem])
def intake_candidate_queue(
    request: Request,
    status_filter: Annotated[CandidateStatus | None, Query(alias="status")] = CandidateStatus.ACTIVE,
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
) -> list[IntakeQueueItem]:
    actor = _actor(request)
    _require(actor, AdministrativePermission.OPERATIONS_READ)
    candidates = _intake.list_candidates(status=status_filter, limit=limit)
    result: list[IntakeQueueItem] = []
    for candidate in candidates:
        assessments = _intake.list_assessments(candidate.candidate_id)
        result.append(
            IntakeQueueItem(
                candidate_id=candidate.candidate_id,
                conversation_ref=candidate.conversation_ref,
                candidate_requester=candidate.candidate_requester,
                candidate_intent=candidate.candidate_intent,
                status=candidate.status,
                created_at=candidate.created_at,
                latest_assessment=assessments[-1] if assessments else None,
            )
        )
    return result


@app.get(
    "/v1/operations/intake/candidates/{candidate_id}",
    response_model=IntakeCandidateDetail,
)
def intake_candidate_detail(candidate_id: UUID, request: Request) -> IntakeCandidateDetail:
    actor = _actor(request)
    candidate = _intake.get_candidate(candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="intake candidate not found")
    _require(actor, AdministrativePermission.OPERATIONS_READ)
    return IntakeCandidateDetail(
        candidate=candidate,
        assessments=_intake.list_assessments(candidate_id),
        promotion=_intake.get_promotion(candidate_id),
    )


@app.post(
    "/v1/operations/intake/candidates/{candidate_id}/assessments",
    response_model=IntakeAssessment,
)
def finalize_intake_assessment(
    candidate_id: UUID,
    payload: IntakeAssessmentBody,
    request: Request,
) -> IntakeAssessment:
    actor = _actor(request)
    _require_intake_review(actor)
    if _intake.get_candidate(candidate_id) is None:
        raise HTTPException(status_code=404, detail="intake candidate not found")
    try:
        return _intake_assessments.finalize_human(
            candidate_id,
            payload.disposition,
            reviewer_principal_id=actor.principal_id,
            basis=payload.basis,
        )
    except (AdmissionRejected, AssessmentConflict, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


def _admission_bridge(case_kind: str) -> CandidateAdministrativeAdmissionService:
    """Select the typed candidate admission service for one case kind."""
    if case_kind == "employee-onboarding":
        return CandidateOnboardingAdmissionService(
            _store, _intake, _intake_promotions, policies=_policies, uow=_uow
        )
    if case_kind == "employee-offboarding":
        return CandidateOffboardingAdmissionService(
            _store, _intake, _intake_promotions, policies=_policies, uow=_uow
        )
    if case_kind == "procurement-request":
        return CandidateProcurementAdmissionService(
            _store, _intake, _intake_promotions, policies=_policies, uow=_uow
        )
    if case_kind == "invoice-ap-preparation":
        return CandidateInvoiceAPAdmissionService(
            _store, _intake, _intake_promotions, policies=_policies, uow=_uow
        )
    if case_kind == "expense-reimbursement":
        return CandidateExpenseAdmissionService(
            _store, _intake, _intake_promotions, policies=_policies, uow=_uow
        )
    raise OnboardingAdmissionError(
        f"typed admission does not support case_kind={case_kind!r}"
    )


@app.post(
    "/v1/operations/intake/candidates/{candidate_id}/promote",
    response_model=IntakePromotionResponse,
)
def promote_intake_candidate(
    candidate_id: UUID,
    payload: IntakePromotionBody,
    request: Request,
) -> IntakePromotionResponse:
    actor = _actor(request)
    _require_intake_review(actor)
    candidate = _intake.get_candidate(candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="intake candidate not found")
    assessment = _intake.get_assessment(payload.assessment_id)
    if assessment is None or assessment.candidate_ref != candidate_id:
        raise HTTPException(status_code=404, detail="intake assessment not found")
    try:
        if payload.bridge_to_m5 or payload.bridge_to_m8:
            if payload.subject_ref is None:
                raise OnboardingAdmissionError(
                    "typed promotion requires subject_ref"
                )
            admission = _admission_bridge(payload.case_kind).promote_and_evaluate(
                candidate,
                assessment,
                source_system=payload.source_system,
                tenant_ref=payload.tenant_ref,
                source_event_id=payload.source_event_id,
                requester_principal_id=payload.requester_principal_id,
                subject_ref=payload.subject_ref,
                channel=payload.channel,
                promotion_policy_ref=payload.promotion_policy_ref,
            )
            result = admission.promotion
            promoted_case = admission.case
            policy_evaluation = admission.policy_evaluation
        else:
            result = _intake_promotions.promote(
                candidate,
                assessment,
                source_system=payload.source_system,
                tenant_ref=payload.tenant_ref,
                source_event_id=payload.source_event_id,
                requester_principal_id=payload.requester_principal_id,
                channel=payload.channel,
                case_kind=payload.case_kind,
                subject_ref=payload.subject_ref,
                promotion_policy_ref=payload.promotion_policy_ref,
            )
            promoted_case = result.case
            policy_evaluation = None
    except (AdmissionConflict, AdmissionRejected, OnboardingAdmissionError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return IntakePromotionResponse(
        promotion=result.promotion,
        request=result.request,
        case=promoted_case,
        created=result.created,
        policy_evaluation=policy_evaluation,
    )


def _apply_authoritative_refresh(
    case: AdministrativeCase,
    record: object,
) -> AdministrativeCase:
    """Merge authoritative HR facts and re-evaluate the case-kind policy."""
    if case.case_kind == "employee-onboarding":
        snapshot = merge_authoritative_onboarding_facts(case, record)  # type: ignore[arg-type]
        policy_id = "employee-onboarding"
        facts_model = OnboardingFacts
        compile_policy = compile_onboarding_policy
    elif case.case_kind == "employee-offboarding":
        snapshot = merge_authoritative_offboarding_facts(case, record)  # type: ignore[arg-type]
        policy_id = "employee-offboarding"
        facts_model = OffboardingFacts
        compile_policy = compile_offboarding_policy
    else:
        raise FactAcquisitionError(
            f"authoritative refresh does not support case kind {case.case_kind!r}"
        )
    changed = replace_facts_for_reevaluation(case, snapshot)
    ready = start_policy_evaluation(changed)
    policy_record = _policies.resolve_current(policy_id)
    facts = facts_model.model_validate(snapshot.facts)
    evaluation = compile_policy(policy_record).evaluate(facts)
    updated = apply_policy_evaluation(ready, evaluation)
    _uow.replace_facts_and_apply_policy(case, updated, evaluation)
    return updated


@app.post(
    "/v1/operations/cases/{case_id}/authoritative-facts/refresh",
    response_model=RefreshFactsResponse,
)
def refresh_authoritative_facts(case_id: UUID, request: Request) -> RefreshFactsResponse:
    actor = _actor(request)
    case = _store.get_case(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="case not found")
    _require(actor, AdministrativePermission.FACTS_REFRESH_AUTHORITATIVE, case=case)
    if case.case_kind not in {"employee-onboarding", "employee-offboarding"}:
        raise HTTPException(
            status_code=409, detail="authoritative refresh does not support this case kind"
        )
    source = build_hris_source(_settings)
    if source is None:
        raise HTTPException(status_code=503, detail="authoritative HRIS source is not configured")
    try:
        record = source.read_employee(case.subject_ref)
        if not record.is_fresh_at(
            utcnow(),
            max_age_seconds=_settings.authoritative_fact_max_age_seconds,
        ):
            raise FactAcquisitionError("authoritative HRIS observation is stale")
        updated = _apply_authoritative_refresh(case, record)
    except (
        FactAcquisitionError,
        PolicyPlaneError,
        TransitionError,
        ConcurrencyConflict,
        ValueError,
    ) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return RefreshFactsResponse(
        case=updated,
        source=record.source,
        source_ref=record.source_ref,
        source_version=record.source_version,
        source_digest=record.digest,
    )


@app.post(
    "/v1/operations/outbox/dead-letter/{event_id}/replay",
    response_model=OutboxReplayResponse,
)
def replay_dead_letter(
    event_id: UUID,
    payload: ReasonBody,
    request: Request,
) -> OutboxReplayResponse:
    actor = _actor(request)
    _require(actor, AdministrativePermission.DEAD_LETTER_REPLAY)
    try:
        replayed = replay_failed_outbox(
            _store,
            event_id,
            reason=payload.reason,
            actor_principal_id=actor.principal_id,
        )
    except OutboxEventNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except OutboxEventNotFailed as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return OutboxReplayResponse(
        event_id=replayed.event_id,
        status=replayed.status,
        attempts=replayed.attempts,
        audit_id=replayed.audit_id,
    )


@app.post("/v1/operations/identities/bind", response_model=AuthorityLifecycleEvent)
def bind_identity(payload: BindIdentityBody, request: Request) -> AuthorityLifecycleEvent:
    actor = _actor(request)
    _require(actor, AdministrativePermission.IDENTITY_MANAGE)
    valid_from = payload.valid_from or utcnow()
    try:
        binding = IdentityBinding(
            provider=payload.provider.rstrip("/"),
            external_subject=payload.external_subject,
            principal_id=payload.principal_id,
            valid_from=valid_from,
            valid_until=payload.valid_until,
        )
        return _lifecycle.bind_identity(
            binding,
            actor_principal_id=actor.principal_id,
            reason=payload.reason,
        )
    except (AuthorityError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post(
    "/v1/operations/identities/{binding_id}/revoke",
    response_model=AuthorityLifecycleEvent,
)
def revoke_identity(
    binding_id: UUID,
    payload: ReasonBody,
    request: Request,
) -> AuthorityLifecycleEvent:
    actor = _actor(request)
    _require(actor, AdministrativePermission.IDENTITY_MANAGE)
    try:
        return _lifecycle.expire_identity_binding(
            binding_id,
            actor_principal_id=actor.principal_id,
            reason=payload.reason,
        )
    except AuthorityError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post(
    "/v1/operations/principals/{principal_id}/deactivate",
    response_model=AuthorityLifecycleEvent,
)
def deactivate_principal(
    principal_id: str,
    payload: ReasonBody,
    request: Request,
) -> AuthorityLifecycleEvent:
    actor = _actor(request)
    _require(actor, AdministrativePermission.IDENTITY_MANAGE)
    try:
        return _lifecycle.deactivate_principal(
            principal_id,
            actor_principal_id=actor.principal_id,
            reason=payload.reason,
        )
    except AuthorityError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post(
    "/v1/operations/role-assignments/{assignment_id}/expire",
    response_model=AuthorityLifecycleEvent,
)
def expire_role_assignment(
    assignment_id: UUID,
    payload: ExpireAuthorityBody,
    request: Request,
) -> AuthorityLifecycleEvent:
    actor = _actor(request)
    _require(actor, AdministrativePermission.IDENTITY_MANAGE)
    try:
        return _lifecycle.expire_role_assignment(
            assignment_id,
            actor_principal_id=actor.principal_id,
            reason=payload.reason,
            at=payload.at,
        )
    except (AuthorityError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post(
    "/v1/operations/delegations/{delegation_id}/expire",
    response_model=AuthorityLifecycleEvent,
)
def expire_delegation(
    delegation_id: UUID,
    payload: ExpireAuthorityBody,
    request: Request,
) -> AuthorityLifecycleEvent:
    actor = _actor(request)
    _require(actor, AdministrativePermission.IDENTITY_MANAGE)
    try:
        return _lifecycle.expire_delegation(
            delegation_id,
            actor_principal_id=actor.principal_id,
            reason=payload.reason,
            at=payload.at,
        )
    except (AuthorityError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/v1/operations/authority-events", response_model=list[AuthorityLifecycleEvent])
def authority_events(
    request: Request,
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
) -> list[AuthorityLifecycleEvent]:
    actor = _actor(request)
    _require(actor, AdministrativePermission.OPERATIONS_READ)
    return _lifecycle.list_events(limit=limit)
