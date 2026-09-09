from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from administrative_orchestrator.integrations.kernel.client import (
    EXPECTED_EXECUTION_COMMAND_SCHEMA,
    EXPECTED_EXECUTION_RECEIPT_SCHEMA,
    HttpKernelResponsibilityClient,
    KernelExecutionError,
)
from administrative_orchestrator.integrations.kernel.models import KernelProjectionStatus

NOW = datetime(2026, 9, 9, 2, 0, tzinfo=UTC)


class StubResponse:
    def __init__(self, payload: object, *, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            request = httpx.Request("GET", "http://kernel.test")
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}",
                request=request,
                response=response,
            )

    def json(self) -> object:
        return self._payload


def _inputs():
    grant_id = uuid4()
    intent_id = uuid4()
    obligation_id = uuid4()
    work_ref = "work:kernel:1"
    projection = SimpleNamespace(
        status=KernelProjectionStatus.ADMITTED,
        kernel_work_ref=work_ref,
        grant_id=grant_id,
        intent_id=intent_id,
    )
    grant = SimpleNamespace(
        grant_id=grant_id,
        obligation_id=obligation_id,
        governance_basis_id=uuid4(),
        approval_satisfaction_id=uuid4(),
    )
    intent = SimpleNamespace(
        intent_id=intent_id,
        grant_id=grant_id,
        obligation_id=obligation_id,
        capability="administrative.hris.employee.create.v1",
        subject_ref="employee:new",
        authority_epoch=2,
        parameters={"employee_ref": "employee:new"},
        expected_postcondition={
            "target_system": "hris",
            "operation": "employee.create",
            "subject_ref": "employee:new",
            "active": True,
        },
        created_at=NOW,
    )
    return projection, grant, intent


def _completed_receipt(work_ref: str = "work:kernel:1") -> dict[str, object]:
    return {
        "schema": EXPECTED_EXECUTION_RECEIPT_SCHEMA,
        "execution_ref": "execution:kernel:1",
        "status": "completed",
        "work_ref": work_ref,
        "run_ref": "run:kernel:1",
        "request_ref": "request:kernel:1",
        "authorization_ref": "authorization:kernel:1",
        "provider_id": "provider:hris:kernel",
        "action_ref": "action:kernel:1",
        "outcome_ref": "outcome:kernel:1",
        "evidence_ref": "evidence:kernel:1",
        "responsibility_ref": "responsibility:kernel:1",
        "processed_at": NOW.isoformat(),
        "authority_bearing": False,
    }


def test_execute_posts_only_domain_evidence_and_accepts_complete_non_authoritative_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    projection, grant, intent = _inputs()
    seen: dict[str, object] = {}

    def fake_post(url: str, *, json: dict[str, object], timeout: float):
        seen.update({"url": url, "json": json, "timeout": timeout})
        return StubResponse(_completed_receipt())

    monkeypatch.setattr(httpx, "post", fake_post)
    client = HttpKernelResponsibilityClient("http://kernel.test", timeout_seconds=4.5)

    receipt = client.execute(projection, grant, intent)

    assert receipt.status == "completed"
    assert receipt.work_ref == projection.kernel_work_ref
    assert receipt.provider_id == "provider:hris:kernel"
    assert receipt.outcome_ref == "outcome:kernel:1"
    assert seen["url"] == "http://kernel.test/v1/domain-effects/executions"
    assert seen["timeout"] == 4.5
    payload = seen["json"]
    assert isinstance(payload, dict)
    assert payload["schema"] == EXPECTED_EXECUTION_COMMAND_SCHEMA
    assert payload["work_ref"] == projection.kernel_work_ref
    assert payload["domain_intent_ref"] == str(intent.intent_id)
    assert payload["domain_grant_ref"] == str(grant.grant_id)
    assert payload["governance_basis_ref"] == str(grant.governance_basis_id)
    assert payload["approval_satisfaction_ref"] == str(grant.approval_satisfaction_id)
    for forbidden in ("provider_id", "verifier_provider_id", "lease_owner", "authorization_ref"):
        assert forbidden not in payload


def test_execute_rejects_projection_and_domain_identity_rebounds() -> None:
    projection, grant, intent = _inputs()
    client = HttpKernelResponsibilityClient("http://kernel.test")

    with pytest.raises(KernelExecutionError, match="requires admitted Work"):
        client.execute(
            SimpleNamespace(**{**projection.__dict__, "status": KernelProjectionStatus.SUBMITTED}),
            grant,
            intent,
        )
    with pytest.raises(KernelExecutionError, match="lacks Kernel Work"):
        client.execute(
            SimpleNamespace(**{**projection.__dict__, "kernel_work_ref": None}),
            grant,
            intent,
        )
    with pytest.raises(KernelExecutionError, match="persisted projection"):
        client.execute(
            SimpleNamespace(**{**projection.__dict__, "grant_id": uuid4()}),
            grant,
            intent,
        )
    with pytest.raises(KernelExecutionError, match="identities rebound"):
        client.execute(
            projection,
            SimpleNamespace(**{**grant.__dict__, "obligation_id": uuid4()}),
            intent,
        )


def test_execution_receipt_rejects_authority_work_rebound_and_incomplete_completion() -> None:
    raw = _completed_receipt()
    with pytest.raises(KernelExecutionError, match="must be non-authoritative"):
        HttpKernelResponsibilityClient._execution_receipt(
            {**raw, "authority_bearing": True},
            expected_work_ref="work:kernel:1",
        )
    with pytest.raises(KernelExecutionError, match="Work identity rebound"):
        HttpKernelResponsibilityClient._execution_receipt(
            raw,
            expected_work_ref="work:different",
        )
    with pytest.raises(KernelExecutionError, match="completed execution receipt lacks refs"):
        HttpKernelResponsibilityClient._execution_receipt(
            {**raw, "outcome_ref": None},
            expected_work_ref="work:kernel:1",
        )
    with pytest.raises(KernelExecutionError, match="unknown execution status"):
        HttpKernelResponsibilityClient._execution_receipt(
            {**raw, "status": "made-up"},
            expected_work_ref="work:kernel:1",
        )


def test_verified_fail_requires_verification_lineage_and_parses_valid_receipt() -> None:
    raw = {
        **_completed_receipt(),
        "status": "verified-fail",
        "responsibility_ref": None,
    }
    receipt = HttpKernelResponsibilityClient._execution_receipt(
        raw,
        expected_work_ref="work:kernel:1",
    )
    assert receipt.status == "verified-fail"
    assert receipt.outcome_ref == "outcome:kernel:1"

    with pytest.raises(KernelExecutionError, match="verified-fail receipt lacks refs"):
        HttpKernelResponsibilityClient._execution_receipt(
            {**raw, "evidence_ref": None},
            expected_work_ref="work:kernel:1",
        )


def test_inspection_handles_not_found_and_rejects_execution_identity_rebound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = HttpKernelResponsibilityClient("http://kernel.test")

    monkeypatch.setattr(
        httpx,
        "get",
        lambda *args, **kwargs: StubResponse({}, status_code=404),
    )
    assert client.inspect_execution("execution:missing") is None

    monkeypatch.setattr(
        httpx,
        "get",
        lambda *args, **kwargs: StubResponse(_completed_receipt()),
    )
    with pytest.raises(KernelExecutionError, match="inspection identity rebound"):
        client.inspect_execution(
            "execution:different",
            expected_work_ref="work:kernel:1",
        )


def test_http_failures_are_wrapped_as_kernel_execution_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    projection, grant, intent = _inputs()

    def fail_post(*args, **kwargs):
        request = httpx.Request("POST", "http://kernel.test/v1/domain-effects/executions")
        raise httpx.ConnectError("offline", request=request)

    monkeypatch.setattr(httpx, "post", fail_post)
    with pytest.raises(KernelExecutionError, match="bounded execution failed"):
        HttpKernelResponsibilityClient("http://kernel.test").execute(
            projection,
            grant,
            intent,
        )
