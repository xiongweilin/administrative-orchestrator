from __future__ import annotations

from uuid import uuid4

import httpx
import pytest

from administrative_orchestrator.integrations.kernel.client import (
    HttpKernelResponsibilityClient,
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
