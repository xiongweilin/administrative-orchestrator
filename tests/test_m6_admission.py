from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from administrative_orchestrator.admission import (
    AdmissionConflict,
    AdmissionRejected,
    IntakeAssessmentService,
    IntakePromotionService,
)
from administrative_orchestrator.domain import CaseStatus, FactAuthority
from administrative_orchestrator.intake.models import (
    CandidateAdministrativeRequest,
    CandidateAuthority,
    CandidateFactAssertion,
    CandidateStatus,
    IntakeAssessment,
    IntakeDisposition,
    IntakeReceipt,
    IntakeVerificationStatus,
)
from administrative_orchestrator.intake.repository import (
    AssessmentConflict,
    CandidateAdministrativeRequestRow,
    IntakeRepository,
    PromotionRecordRow,
)
from administrative_orchestrator.onboarding_admission import CandidateOnboardingAdmissionService
from administrative_orchestrator.persistence import CaseRow, RequestRow, SqlStore
from administrative_orchestrator.policy_plane import (
    PolicyRepository,
    default_onboarding_policy_version,
)


def _setup(
    *,
    candidate_status: CandidateStatus = CandidateStatus.ACTIVE,
    include_receipt: bool = True,
    receipt_status: IntakeVerificationStatus = IntakeVerificationStatus.VERIFIED,
    receipt_artifact: UUID | None = None,
) -> tuple[SqlStore, IntakeRepository, CandidateAdministrativeRequest]:
    store = SqlStore("sqlite+pysqlite:///:memory:")
    store.init_schema()
    repository = IntakeRepository(store)
    candidate = repository.append_candidate_request(
        CandidateAdministrativeRequest(
            conversation_ref="provider/tenant/thread:1",
            interpretation_refs=(uuid4(),),
            candidate_requester="external:actor:1",
            candidate_intent="onboard employee:1",
            source_refs=(uuid4(),),
            status=candidate_status,
        )
    )
    if include_receipt:
        repository.persist_intake_receipt(
            IntakeReceipt(
                source_system="test-provider",
                tenant_ref="tenant:test",
                source_event_id="event:1",
                verification_status=receipt_status,
                artifact_ref=(
                    candidate.source_refs[0]
                    if receipt_artifact is None
                    else receipt_artifact
                ),
                delivery_digest="delivery:1",
            )
        )
    return store, repository, candidate


def _final_admit(
    repository: IntakeRepository, candidate: CandidateAdministrativeRequest
) -> IntakeAssessment:
    return IntakeAssessmentService(repository).finalize_human(
        candidate.candidate_id,
        IntakeDisposition.ADMIT,
        reviewer_principal_id="principal:reviewer",
        basis={"reviewed": True},
    )


def test_model_suggestion_cannot_promote() -> None:
    store, repository, candidate = _setup()
    assessments = IntakeAssessmentService(repository)
    suggestion = assessments.suggest(
        candidate.candidate_id,
        IntakeDisposition.ADMIT,
        basis={"confidence": 0.99},
    )

    with pytest.raises(AdmissionRejected):
        IntakePromotionService(store, repository).promote(
            candidate,
            suggestion,
            source_system="test-provider",
            tenant_ref="tenant:test",
            source_event_id="event:1",
            requester_principal_id="principal:reviewer",
        )


def test_final_human_admission_is_atomic_and_idempotent() -> None:
    store, repository, candidate = _setup()
    assessment = IntakeAssessmentService(repository).finalize_human(
        candidate.candidate_id,
        IntakeDisposition.ADMIT,
        reviewer_principal_id="principal:reviewer",
        basis={"reviewed": True},
    )
    service = IntakePromotionService(store, repository)

    first = service.promote(
        candidate,
        assessment,
        source_system="test-provider",
        tenant_ref="tenant:test",
        source_event_id="event:1",
        requester_principal_id="principal:requester",
        case_kind="employee-onboarding",
        subject_ref="employee:1",
    )
    second = service.promote(
        candidate,
        assessment,
        source_system="test-provider",
        tenant_ref="tenant:test",
        source_event_id="event:1",
        requester_principal_id="principal:requester",
        case_kind="employee-onboarding",
        subject_ref="employee:1",
    )

    assert first.created is True
    assert second.created is False
    assert second.promotion.promotion_id == first.promotion.promotion_id
    assert second.request.request_id == first.request.request_id
    assert second.case.case_id == first.case.case_id
    assert repository.get_candidate(candidate.candidate_id).status is CandidateStatus.ADMITTED

    with store.sessions() as db:
        assert db.query(RequestRow).count() == 1
        assert db.query(CaseRow).count() == 1
        assert db.query(PromotionRecordRow).count() == 1


def test_redelivery_with_different_requester_is_rejected() -> None:
    store, repository, candidate = _setup()
    assessment = IntakeAssessmentService(repository).finalize_deterministic(
        candidate.candidate_id,
        IntakeDisposition.ADMIT,
        rule_ref="m6-test-rule-v1",
        input_digest="inputs:1",
        basis={"source_verified": True},
    )
    service = IntakePromotionService(store, repository)
    service.promote(
        candidate,
        assessment,
        source_system="test-provider",
        tenant_ref="tenant:test",
        source_event_id="event:1",
        requester_principal_id="principal:requester",
    )

    with pytest.raises(AdmissionConflict):
        service.promote(
            candidate,
            assessment,
            source_system="test-provider",
            tenant_ref="tenant:test",
            source_event_id="event:1",
            requester_principal_id="principal:other",
        )


def test_assessment_rejects_missing_proof_and_invalid_targets() -> None:
    _, repository, candidate = _setup()
    service = IntakeAssessmentService(repository)

    with pytest.raises(AdmissionRejected):
        service.suggest(uuid4(), IntakeDisposition.ADMIT)
    with pytest.raises(AdmissionRejected):
        service.finalize_deterministic(
            candidate.candidate_id,
            IntakeDisposition.ADMIT,
            rule_ref=" ",
            input_digest="inputs:1",
        )
    with pytest.raises(AdmissionRejected):
        service.finalize_human(
            candidate.candidate_id,
            IntakeDisposition.ADMIT,
            reviewer_principal_id=" ",
        )

    _, superseded_repository, superseded = _setup(
        candidate_status=CandidateStatus.SUPERSEDED
    )
    with pytest.raises(AdmissionRejected):
        IntakeAssessmentService(superseded_repository).finalize_human(
            superseded.candidate_id,
            IntakeDisposition.ADMIT,
            reviewer_principal_id="principal:reviewer",
            basis={"reviewed": True},
        )

def test_final_assessment_is_idempotent_and_conflicts_are_rejected() -> None:
    _, repository, candidate = _setup()
    service = IntakeAssessmentService(repository)
    first = _final_admit(repository, candidate)

    assert service.finalize_human(
        candidate.candidate_id,
        IntakeDisposition.ADMIT,
        reviewer_principal_id="principal:reviewer",
        basis={"reviewed": True},
    ) == first

    with pytest.raises(AssessmentConflict):
        service.finalize_deterministic(
            candidate.candidate_id,
            IntakeDisposition.ADMIT,
            rule_ref="m6-test-rule-v1",
            input_digest="inputs:1",
            basis={"reviewed": True},
        )


def test_promotion_rejects_invalid_context_and_lineage() -> None:
    store, repository, candidate = _setup()
    assessment = _final_admit(repository, candidate)
    service = IntakePromotionService(store, repository)

    with pytest.raises(AdmissionRejected):
        service.promote(
            candidate,
            assessment,
            source_system="test-provider",
            tenant_ref="tenant:test",
            source_event_id="event:1",
            requester_principal_id=" ",
        )

    tampered_candidate = candidate.model_copy(
        update={"candidate_intent": "tampered intent"}
    )
    with pytest.raises(AdmissionRejected):
        service.promote(
            tampered_candidate,
            assessment,
            source_system="test-provider",
            tenant_ref="tenant:test",
            source_event_id="event:1",
            requester_principal_id="principal:requester",
        )

    tampered_assessment = assessment.model_copy(
        update={"basis": {"reviewed": "tampered"}}
    )
    with pytest.raises(AdmissionRejected):
        service.promote(
            candidate,
            tampered_assessment,
            source_system="test-provider",
            tenant_ref="tenant:test",
            source_event_id="event:1",
            requester_principal_id="principal:requester",
        )


def test_promotion_rejects_non_active_candidate_and_non_admit_assessment() -> None:
    admitted_store, admitted_repository, admitted_candidate = _setup(
        candidate_status=CandidateStatus.ADMITTED
    )
    admitted_assessment = _final_admit(admitted_repository, admitted_candidate)
    with pytest.raises(AdmissionRejected):
        IntakePromotionService(admitted_store, admitted_repository).promote(
            admitted_candidate,
            admitted_assessment,
            source_system="test-provider",
            tenant_ref="tenant:test",
            source_event_id="event:1",
            requester_principal_id="principal:requester",
        )

    clarification_store, clarification_repository, clarification_candidate = _setup()
    clarification = IntakeAssessmentService(clarification_repository).finalize_human(
        clarification_candidate.candidate_id,
        IntakeDisposition.NEEDS_CLARIFICATION,
        reviewer_principal_id="principal:reviewer",
        basis={"reviewed": True},
    )
    with pytest.raises(AdmissionRejected):
        IntakePromotionService(clarification_store, clarification_repository).promote(
            clarification_candidate,
            clarification,
            source_system="test-provider",
            tenant_ref="tenant:test",
            source_event_id="event:1",
            requester_principal_id="principal:requester",
        )


def test_promotion_requires_verified_receipt_and_matching_artifact() -> None:
    missing_store, missing_repository, missing_candidate = _setup(include_receipt=False)
    missing_assessment = _final_admit(missing_repository, missing_candidate)
    with pytest.raises(AdmissionRejected):
        IntakePromotionService(missing_store, missing_repository).promote(
            missing_candidate,
            missing_assessment,
            source_system="test-provider",
            tenant_ref="tenant:test",
            source_event_id="event:1",
            requester_principal_id="principal:requester",
        )

    pending_store, pending_repository, pending_candidate = _setup(
        receipt_status=IntakeVerificationStatus.PENDING
    )
    pending_assessment = _final_admit(pending_repository, pending_candidate)
    with pytest.raises(AdmissionRejected):
        IntakePromotionService(pending_store, pending_repository).promote(
            pending_candidate,
            pending_assessment,
            source_system="test-provider",
            tenant_ref="tenant:test",
            source_event_id="event:1",
            requester_principal_id="principal:requester",
        )

    mismatch_store, mismatch_repository, mismatch_candidate = _setup(
        receipt_artifact=uuid4()
    )
    mismatch_assessment = _final_admit(mismatch_repository, mismatch_candidate)
    with pytest.raises(AdmissionRejected):
        IntakePromotionService(mismatch_store, mismatch_repository).promote(
            mismatch_candidate,
            mismatch_assessment,
            source_system="test-provider",
            tenant_ref="tenant:test",
            source_event_id="event:1",
            requester_principal_id="principal:requester",
        )


def test_human_admission_enters_existing_onboarding_facts_and_policy_path() -> None:
    store, repository, candidate = _setup()
    PolicyRepository(store).put_version(default_onboarding_policy_version())
    fact_refs = []
    for fact_key, value in (
        ("department_ref", "department:engineering"),
        ("manager_principal_id", "person:manager"),
        ("start_date", "2026-10-01"),
        ("employment_type", "full_time"),
        ("requested_systems", ["google-workspace"]),
        ("requires_privileged_access", False),
    ):
        fact = repository.append_candidate_fact(
            CandidateFactAssertion(
                fact_key=fact_key,
                value=value,
                authority=CandidateAuthority.CLAIM,
                source_refs=candidate.source_refs,
                no_evidence_reason="test source has no span for this contract fixture",
            )
        )
        fact_refs.append(fact.candidate_fact_id)
    candidate = candidate.model_copy(
        update={
            "candidate_fact_refs": tuple(fact_refs)
        }
    )
    with store.sessions.begin() as db:
        row = db.get(CandidateAdministrativeRequestRow, candidate.candidate_id)
        assert row is not None
        row.candidate_fact_refs_json = [str(ref) for ref in candidate.candidate_fact_refs]

    assessment = _final_admit(repository, candidate)
    first = CandidateOnboardingAdmissionService(store, repository).promote_and_evaluate(
        candidate,
        assessment,
        source_system="test-provider",
        tenant_ref="tenant:test",
        source_event_id="event:1",
        requester_principal_id="principal:requester",
        subject_ref="employee:1",
    )

    assert first.created is True
    assert first.case.case_kind == "employee-onboarding"
    assert first.case.status is CaseStatus.AWAITING_DECISION
    assert first.policy_evaluation.required_decision_roles == ("hr_approver",)
    assert first.case.fact_snapshot is not None
    assert first.case.fact_snapshot.authority is FactAuthority.CLAIM
    assert first.case.fact_snapshot.facts["employee_ref"] == "employee:1"
    assert all(
        assertion.authority is FactAuthority.CLAIM
        for assertion in first.case.fact_snapshot.assertions.values()
    )

    replay = CandidateOnboardingAdmissionService(store, repository).promote_and_evaluate(
        candidate,
        assessment,
        source_system="test-provider",
        tenant_ref="tenant:test",
        source_event_id="event:1",
        requester_principal_id="principal:requester",
        subject_ref="employee:1",
    )
    assert replay.created is False
    assert replay.case.case_id == first.case.case_id
    assert replay.policy_evaluation.policy_ref == first.policy_evaluation.policy_ref
