from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import httpx
import pytest

from administrative_orchestrator.integrations.kernel.client import (
    HttpKernelResponsibilityClient,
    KernelResponsibilityDischargeError,
    KernelSubmissionError,
)
from administrative_orchestrator.integrations.kernel.models import KernelShadowProjection


def _projection() -> KernelShadowProjection:
    return KernelShadowProjection(
        projection_id=uuid4(),
        case_id=uuid4(),
        authority_epoch=2,
        grant_id=uuid4(),
        intent_id=uuid4(),
        obligation_id=uuid4(),
        contract_catalog="portable-runtime-contracts-v1",
        runtime_protocol="2.0",
        persistent_responsibility_contract="persistent-responsibility-v1",
        responsibility_payload={"id": "resp-1", "object_type": "StandingResponsibility"},
        admission_payload={"id": "admission-1", "object_type": "ResponsibilityAdmission"},
        assessment_payload={"id": "assessment-1", "object_type": "ResponsibilityAssessment"},
        work_proposal_payload={"id": "proposal-1", "object_type": "WorkProposal"},
    )


def _receipt(**updates):
    value = {
        "schema": "domain-responsibility-proposal-receipt-v1",
        "status": "proposal-recorded",
        "responsibility_ref": "resp-1",
        "admission_ref": "admission-1",
        "assessment_ref": "assessment-1",
        "proposal_ref": "proposal-1",
        "authority_bearing": False,
    }
    value.update(updates)
    return value


def _response(payload, *, status_code: int = 200) -> httpx.Response:
    request = httpx.Request("POST", "http://kernel.test/v1/responsibilities/domain-proposals")
    return httpx.Response(status_code, json=payload, request=request)


def test_http_kernel_client_accepts_only_matching_non_authoritative_receipt(monkeypatch) -> None:
    observed = {}

    def post(url, *, json, timeout):
        observed["url"] = url
        observed["json"] = json
        observed["timeout"] = timeout
        return _response(_receipt())

    monkeypatch.setattr(httpx, "post", post)
    receipt = HttpKernelResponsibilityClient(
        "http://kernel.test/",
        timeout_seconds=1.5,
    ).submit(_projection())

    assert receipt.responsibility_ref == "resp-1"
    assert receipt.admission_ref == "admission-1"
    assert receipt.assessment_ref == "assessment-1"
    assert receipt.proposal_ref == "proposal-1"
    assert observed["url"] == "http://kernel.test/v1/responsibilities/domain-proposals"
    assert observed["timeout"] == 1.5
    assert observed["json"]["schema"] == "domain-responsibility-proposal-v1"
    assert set(observed["json"]) == {
        "schema",
        "responsibility",
        "admission",
        "assessment",
        "proposal",
    }


@pytest.mark.parametrize(
    "payload,match",
    [
        (_receipt(schema="domain-responsibility-proposal-receipt-v2"), "receipt schema"),
        (_receipt(status="work-materialized"), "did not confirm"),
        (_receipt(authority_bearing=True), "non-authoritative"),
        (_receipt(proposal_ref="proposal-other"), "proposal_ref"),
        ([], "JSON object"),
    ],
)
def test_http_kernel_client_rejects_noncanonical_receipts(monkeypatch, payload, match) -> None:
    monkeypatch.setattr(httpx, "post", lambda *args, **kwargs: _response(payload))

    with pytest.raises(KernelSubmissionError, match=match):
        HttpKernelResponsibilityClient("http://kernel.test").submit(_projection())


def test_http_kernel_client_fails_closed_on_transport_error(monkeypatch) -> None:
    def fail(*args, **kwargs):
        request = httpx.Request("POST", "http://kernel.test/v1/responsibilities/domain-proposals")
        raise httpx.ReadTimeout("lost response", request=request)

    monkeypatch.setattr(httpx, "post", fail)

    with pytest.raises(KernelSubmissionError, match="submission failed"):
        HttpKernelResponsibilityClient("http://kernel.test").submit(_projection())


def test_http_kernel_client_fails_closed_on_http_rejection(monkeypatch) -> None:
    monkeypatch.setattr(
        httpx,
        "post",
        lambda *args, **kwargs: _response({"detail": "rejected"}, status_code=409),
    )

    with pytest.raises(KernelSubmissionError, match="submission failed"):
        HttpKernelResponsibilityClient("http://kernel.test").submit(_projection())


def test_http_kernel_client_discharge_contracts_are_typed_and_separate(monkeypatch) -> None:
    now = datetime(2026, 9, 11, tzinfo=UTC)
    calls: list[tuple[str, dict[str, object]]] = []
    status = {"value": "active"}

    def post(url, *, json, timeout):
        del timeout
        calls.append((url, json))
        if url.endswith("/assessments"):
            return _response(
                {
                    "schema": "responsibility-assessment-receipt-v1",
                    "assessment": {
                        "id": "assessment-final",
                        "object_type": "ResponsibilityAssessment",
                        "responsibility_ref": "resp-1",
                        "responsibility_version": 1,
                    },
                    "authority_bearing": False,
                }
            )
        if url.endswith("/discharge-decisions"):
            return _response(
                {
                    "schema": "responsibility-discharge-decision-receipt-v1",
                    "decision": {
                        "id": "decision-final",
                        "object_type": "ResponsibilityDischargeDecision",
                        "responsibility_ref": "resp-1",
                        "responsibility_version": 1,
                        "assessment_ref": "assessment-final",
                    },
                    "status_after_decision": "active",
                    "authority_bearing": False,
                }
            )
        status["value"] = "discharged"
        return _response(
            {
                "schema": "responsibility-lifecycle-transition-receipt-v1",
                    "transition": {
                        "id": "transition-final",
                        "object_type": "ResponsibilityLifecycleTransition",
                        "responsibility_ref": "resp-1",
                        "responsibility_version": 1,
                        "from_status": "active",
                        "to_status": "discharged",
                        "decision_ref": "decision-final",
                    },
                "current_status": "discharged",
                "authority_bearing": False,
            }
        )

    def get(url, *, timeout):
        del timeout
        return httpx.Response(
            200,
            json={
                "schema": "responsibility-status-view-v1",
                "responsibility_ref": "resp-1",
                "responsibility_version": 1,
                "current_status": status["value"],
                "observed_at": now.isoformat(),
                "authority_bearing": False,
            },
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(httpx, "post", post)
    monkeypatch.setattr(httpx, "get", get)
    client = HttpKernelResponsibilityClient("http://kernel.test", timeout_seconds=1.5)

    assessment = client.record_assessment(
        assessment_ref="assessment-final",
        responsibility_ref="resp-1",
        responsibility_version=1,
        subject_ref="employee:1",
        assessment_kind="administrative-responsibility-discharge-reassessment",
        basis_refs=("completion:1",),
        assessed_at=now,
        fresh_until=None,
        rationale="verified",
        created_at=now,
    )
    decision = client.record_discharge_decision(
        decision_ref="decision-final",
        responsibility_ref="resp-1",
        responsibility_version=1,
        assessment_ref=assessment.assessment_ref,
        basis_refs=(assessment.assessment_ref,),
        policy_ref="policy:offboarding:v1",
        decided_at=now,
        rationale="discharge",
        created_at=now,
    )
    transition = client.apply_lifecycle_transition(
        transition_ref="transition-final",
        responsibility_ref="resp-1",
        responsibility_version=1,
        decision_ref=decision.decision_ref,
        basis_refs=(decision.decision_ref,),
        applied_at=now,
        reason="complete",
        created_at=now,
    )

    assert transition.current_status == "discharged"
    assert [url.rsplit("/", 1)[-1] for url, _ in calls] == [
        "assessments",
        "discharge-decisions",
        "lifecycle-transitions",
    ]
    assert calls[0][1]["schema"] == "responsibility-assessment-record-v1"
    assert calls[1][1]["schema"] == "responsibility-discharge-decision-record-v1"
    assert calls[2][1]["schema"] == "responsibility-lifecycle-transition-apply-v1"


@pytest.mark.parametrize(
    "payload,match",
    [
        (
            {
                "schema": "responsibility-discharge-decision-receipt-v1",
                "decision": {
                    "id": "decision-final",
                    "object_type": "ResponsibilityDischargeDecision",
                    "responsibility_ref": "resp-1",
                    "responsibility_version": 1,
                    "assessment_ref": "assessment-final",
                },
                "status_after_decision": "discharged",
                "authority_bearing": False,
            },
            "leave responsibility active",
        ),
        (
            {
                "schema": "responsibility-assessment-receipt-v1",
                "assessment": [],
                "authority_bearing": False,
            },
            "JSON object",
        ),
        (
            {
                "schema": "responsibility-assessment-receipt-v1",
                "assessment": {
                    "id": "assessment-final",
                    "object_type": "ResponsibilityAssessment",
                    "responsibility_ref": "resp-other",
                    "responsibility_version": 1,
                },
                "authority_bearing": False,
            },
            "identity rebound",
        ),
    ],
)
def test_http_kernel_client_rejects_malformed_discharge_receipts(
    monkeypatch, payload, match
) -> None:
    now = datetime(2026, 9, 11, tzinfo=UTC)
    monkeypatch.setattr(
        httpx,
        "post",
        lambda *args, **kwargs: _response(payload),
    )
    client = HttpKernelResponsibilityClient("http://kernel.test")

    if "decision" in payload:
        with pytest.raises(KernelResponsibilityDischargeError, match=match):
            client.record_discharge_decision(
                decision_ref="decision-final",
                responsibility_ref="resp-1",
                responsibility_version=1,
                assessment_ref="assessment-final",
                basis_refs=("assessment-final",),
                policy_ref="policy:offboarding:v1",
                decided_at=now,
                rationale="discharge",
                created_at=now,
            )
    else:
        with pytest.raises(KernelResponsibilityDischargeError, match=match):
            client.record_assessment(
                assessment_ref="assessment-final",
                responsibility_ref="resp-1",
                responsibility_version=1,
                subject_ref="employee:1",
                assessment_kind="discharge",
                basis_refs=("completion:1",),
                assessed_at=now,
                fresh_until=None,
                rationale="verified",
                created_at=now,
            )
