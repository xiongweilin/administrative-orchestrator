from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from administrative_orchestrator.integrations.kernel.evidence import (
    EXPECTED_EVIDENCE_VIEW_SCHEMA,
    HttpKernelEvidenceClient,
    KernelEvidenceError,
)

NOW = datetime(2026, 9, 9, 6, 0, tzinfo=UTC)


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


def _evidence_payload() -> dict[str, object]:
    expected = {
        "target_system": "hris",
        "operation": "employee.create",
        "subject_ref": "employee:new",
        "active": True,
        "payload": {"employee_ref": "employee:new"},
    }
    return {
        "schema": EXPECTED_EVIDENCE_VIEW_SCHEMA,
        "evidence_ref": "evidence:kernel:1",
        "action_ref": "action:kernel:1",
        "work_ref": "work:kernel:1",
        "run_ref": "run:kernel:1",
        "objective_result": "pass",
        "observed_postcondition": dict(expected),
        "expected_postcondition": dict(expected),
        "verification_request_ref": "verification-request:kernel:1",
        "verification_attempt_ref": "verification-attempt:kernel:1",
        "verifier_provider_id": "provider:hris:readback",
        "verifier_provider_execution_binding_ref": "binding:hris:readback:1",
        "captured_at": NOW.isoformat(),
        "authority_bearing": False,
    }


def test_evidence_client_reads_actual_non_authoritative_verification_view(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, object] = {}

    def fake_get(url: str, *, timeout: float):
        seen.update({"url": url, "timeout": timeout})
        return StubResponse(_evidence_payload())

    monkeypatch.setattr(httpx, "get", fake_get)
    client = HttpKernelEvidenceClient("http://kernel.test", timeout_seconds=4.0)

    evidence = client.inspect("evidence:kernel:1")

    assert evidence is not None
    assert evidence.objective_result == "pass"
    assert evidence.observed_postcondition == evidence.expected_postcondition
    assert evidence.verifier_provider_id == "provider:hris:readback"
    assert evidence.captured_at == NOW
    assert seen["url"] == (
        "http://kernel.test/v1/domain-effects/evidence/evidence:kernel:1"
    )
    assert seen["timeout"] == 4.0


def test_evidence_client_returns_none_only_for_unknown_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        httpx,
        "get",
        lambda *args, **kwargs: StubResponse({}, status_code=404),
    )
    client = HttpKernelEvidenceClient("http://kernel.test")

    assert client.inspect("evidence:missing") is None


def test_evidence_client_rejects_authority_identity_schema_and_invalid_postconditions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = HttpKernelEvidenceClient("http://kernel.test")
    payload = _evidence_payload()

    cases = (
        ({**payload, "authority_bearing": True}, "non-authoritative"),
        ({**payload, "evidence_ref": "evidence:rebound"}, "identity rebound"),
        ({**payload, "schema": "domain-effect-verification-evidence-view-v2"}, "schema"),
        ({**payload, "objective_result": "unknown"}, "closed objective result"),
        ({**payload, "observed_postcondition": "not-an-object"}, "postcondition objects"),
    )
    for raw, message in cases:
        monkeypatch.setattr(httpx, "get", lambda *args, _raw=raw, **kwargs: StubResponse(_raw))
        with pytest.raises(KernelEvidenceError, match=message):
            client.inspect("evidence:kernel:1")
