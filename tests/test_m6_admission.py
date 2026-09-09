from __future__ import annotations

from uuid import uuid4

import pytest

from administrative_orchestrator.admission import (
    AdmissionConflict,
    AdmissionRejected,
    IntakeAssessmentService,
    IntakePromotionService,
)
from administrative_orchestrator.intake.models import (
    CandidateAdministrativeRequest,
    CandidateStatus,
    IntakeDisposition,
    IntakeReceipt,
    IntakeVerificationStatus,
)
from administrative_orchestrator.intake.repository import IntakeRepository, PromotionRecordRow
from administrative_orchestrator.persistence import CaseRow, RequestRow, SqlStore


def _setup() -> tuple[SqlStore, IntakeRepository, CandidateAdministrativeRequest]:
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
        )
    )
    repository.persist_intake_receipt(
        IntakeReceipt(
            source_system="test-provider",
            tenant_ref="tenant:test",
            source_event_id="event:1",
            verification_status=IntakeVerificationStatus.VERIFIED,
            artifact_ref=candidate.source_refs[0],
            delivery_digest="delivery:1",
        )
    )
    return store, repository, candidate


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
