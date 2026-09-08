from __future__ import annotations

from uuid import uuid4

import httpx
import pytest

from administrative_orchestrator.integrations.kernel.client import (
    HttpKernelResponsibilityClient,
    KernelWorkAdmissionError,
)
from administrative_orchestrator.integrations.kernel.models import (
    KernelProjectionStatus,
    KernelShadowProjection,
)

POLICY = "responsibility-admission:admin@1"
PROPOSAL = "proposal:admin:1"


class FakeResponse:
    def __init__(self, payload: object) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> object:
        return self.payload


def _projection() -> KernelShadowProjection:
    return KernelShadowProjection(
        projection_id=uuid4(),
        case_id=uuid4(),
        authority_epoch=1,
        grant_id=uuid4(),
        intent_id=uuid4(),
        obligation_id=uuid4(),
        contract_catalog="portable-runtime-contracts-v1",
        runtime_protocol="2.0",
        persistent_responsibility_contract="persistent-responsibility-v1",
        responsibility_payload={"id": "responsibility:admin:1"},
        admission_payload={"id": "responsibility-admission:admin:1"},
        assessment_payload={"id": "assessment:admin:1"},
        work_proposal_payload={"id": PROPOSAL},
        status=KernelProjectionStatus.SUBMITTED,
        kernel_responsibility_ref="responsibility:admin:1",
        kernel_admission_ref="responsibility-admission:admin:1",
        kernel_assessment_ref="assessment:admin:1",
        kernel_proposal_ref=PROPOSAL,
    )


def _receipt(**changes: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema": "responsibility-work-admission-receipt-v1",
        "status": "work-materialized",
        "proposal_ref": PROPOSAL,
        "policy_ref": POLICY,
        "priority_judgment_ref": "priority:1",
        "resource_pool_ref": "pool:1",
        "portfolio_admission_ref": "portfolio:1",
        "reservation_ref": "reservation:1",
        "commitment_ref": "commitment:1",
        "work_ref": "work:1",
        "processed_at": "2026-09-08T12:00:00Z",
        "authority_bearing": False,
    }
    payload.update(changes)
    return payload


def test_work_admission_client_accepts_complete_non_authoritative_receipt(monkeypatch) -> None:
    monkeypatch.setattr(httpx, "post", lambda *args, **kwargs: FakeResponse(_receipt()))

    receipt = HttpKernelResponsibilityClient("http://kernel").admit(
        _projection(), expected_policy_ref=POLICY
    )

    assert receipt.status == "work-materialized"
    assert receipt.proposal_ref == PROPOSAL
    assert receipt.policy_ref == POLICY
    assert receipt.work_ref == "work:1"


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"authority_bearing": True}, "non-authoritative"),
        ({"proposal_ref": "proposal:other"}, "proposal identity mismatch"),
        ({"policy_ref": "responsibility-admission:other@1"}, "policy identity mismatch"),
        ({"schema": "responsibility-work-admission-receipt-v2"}, "incompatible"),
        ({"status": "executed"}, "unknown Work admission status"),
        ({"priority_judgment_ref": None}, "priority judgment ref"),
        ({"work_ref": None}, "materialized Work admission receipt lacks refs"),
    ],
)
def test_work_admission_client_rejects_invalid_receipts(
    monkeypatch,
    changes: dict[str, object],
    message: str,
) -> None:
    monkeypatch.setattr(
        httpx,
        "post",
        lambda *args, **kwargs: FakeResponse(_receipt(**changes)),
    )

    with pytest.raises(KernelWorkAdmissionError, match=message):
        HttpKernelResponsibilityClient("http://kernel").admit(
            _projection(), expected_policy_ref=POLICY
        )


def test_priority_rejection_must_stop_before_resource_refs(monkeypatch) -> None:
    response = _receipt(
        status="priority-rejected",
        resource_pool_ref="pool:unexpected",
        portfolio_admission_ref=None,
        reservation_ref=None,
        commitment_ref=None,
        work_ref=None,
    )
    monkeypatch.setattr(httpx, "post", lambda *args, **kwargs: FakeResponse(response))

    with pytest.raises(KernelWorkAdmissionError, match="stop before resource"):
        HttpKernelResponsibilityClient("http://kernel").admit(
            _projection(), expected_policy_ref=POLICY
        )


def test_portfolio_rejection_requires_pool_and_portfolio_refs(monkeypatch) -> None:
    response = _receipt(
        status="portfolio-rejected",
        resource_pool_ref=None,
        portfolio_admission_ref=None,
        reservation_ref=None,
        commitment_ref=None,
        work_ref=None,
    )
    monkeypatch.setattr(httpx, "post", lambda *args, **kwargs: FakeResponse(response))

    with pytest.raises(KernelWorkAdmissionError, match="requires pool and portfolio"):
        HttpKernelResponsibilityClient("http://kernel").admit(
            _projection(), expected_policy_ref=POLICY
        )


def test_work_admission_transport_failure_is_fail_closed(monkeypatch) -> None:
    def fail(*args, **kwargs):
        raise httpx.TimeoutException("timeout")

    monkeypatch.setattr(httpx, "post", fail)

    with pytest.raises(KernelWorkAdmissionError, match="Work admission failed"):
        HttpKernelResponsibilityClient("http://kernel").admit(
            _projection(), expected_policy_ref=POLICY
        )
