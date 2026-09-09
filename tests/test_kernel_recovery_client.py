from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from administrative_orchestrator.integrations.kernel.recovery import (
    EXPECTED_RECOVERY_COMMAND_SCHEMA,
    EXPECTED_RESOLUTION_SCHEMA,
    HttpKernelRecoveryClient,
    KernelRecoveryError,
)

NOW = datetime(2026, 9, 9, 7, 45, tzinfo=UTC)


class StubResponse:
    def __init__(self, payload: object, *, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            request = httpx.Request("POST", "http://kernel.test")
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}",
                request=request,
                response=response,
            )

    def json(self) -> object:
        return self._payload


def _resolution_payload() -> dict[str, object]:
    return {
        "schema": EXPECTED_RESOLUTION_SCHEMA,
        "execution_ref": "execution:kernel:1",
        "original_status": "execution-unknown",
        "current_status": "recovered-completed",
        "work_ref": "work:kernel:1",
        "run_ref": "run:kernel:1",
        "request_ref": "request:kernel:1",
        "recovery_observation_ref": "recovery-observation:kernel:1",
        "recovery_disposition_ref": "recovery-disposition:kernel:1",
        "recovery_application_ref": "recovery-application:kernel:1",
        "outcome_ref": "outcome:kernel:1",
        "evidence_ref": "evidence:kernel:1",
        "responsibility_ref": "responsibility:kernel:1",
        "reason": "authority-bound reconciliation and verification completed",
        "processed_at": NOW.isoformat(),
        "authority_bearing": False,
    }


def test_recovery_client_submits_only_historical_execution_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, object] = {}

    def fake_post(url: str, *, json: object, timeout: float):
        seen.update({"url": url, "json": json, "timeout": timeout})
        return StubResponse(_resolution_payload())

    monkeypatch.setattr(httpx, "post", fake_post)
    client = HttpKernelRecoveryClient("http://kernel.test", timeout_seconds=4.0)

    resolution = client.recover(
        "execution:kernel:1",
        expected_work_ref="work:kernel:1",
    )

    assert resolution.original_status == "execution-unknown"
    assert resolution.current_status == "recovered-completed"
    assert resolution.evidence_ref == "evidence:kernel:1"
    assert resolution.processed_at == NOW
    assert seen == {
        "url": "http://kernel.test/v1/domain-effects/recoveries",
        "json": {
            "schema": EXPECTED_RECOVERY_COMMAND_SCHEMA,
            "execution_ref": "execution:kernel:1",
        },
        "timeout": 4.0,
    }


def test_resolution_inspection_returns_current_resolution_and_preserves_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, object] = {}

    def fake_get(url: str, *, timeout: float):
        seen.update({"url": url, "timeout": timeout})
        return StubResponse(_resolution_payload())

    monkeypatch.setattr(httpx, "get", fake_get)
    client = HttpKernelRecoveryClient("http://kernel.test/", timeout_seconds=2.5)

    resolution = client.inspect(
        "execution:kernel:1",
        expected_work_ref="work:kernel:1",
    )

    assert resolution is not None
    assert resolution.current_status == "recovered-completed"
    assert resolution.recovery_application_ref == "recovery-application:kernel:1"
    assert seen == {
        "url": (
            "http://kernel.test/v1/domain-effects/executions/"
            "execution:kernel:1/resolution"
        ),
        "timeout": 2.5,
    }


def test_resolution_inspection_returns_none_only_for_unknown_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        httpx,
        "get",
        lambda *args, **kwargs: StubResponse({}, status_code=404),
    )
    client = HttpKernelRecoveryClient("http://kernel.test")

    assert client.inspect("execution:missing") is None


def test_recovery_transport_and_empty_identity_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = HttpKernelRecoveryClient("http://kernel.test")

    with pytest.raises(KernelRecoveryError, match="requires execution_ref"):
        client.recover("   ")
    with pytest.raises(KernelRecoveryError, match="inspection requires execution_ref"):
        client.inspect("")

    monkeypatch.setattr(
        httpx,
        "post",
        lambda *args, **kwargs: StubResponse({}, status_code=503),
    )
    with pytest.raises(KernelRecoveryError, match="recovery request failed"):
        client.recover("execution:kernel:1")

    monkeypatch.setattr(
        httpx,
        "get",
        lambda *args, **kwargs: StubResponse({}, status_code=503),
    )
    with pytest.raises(KernelRecoveryError, match="resolution inspection failed"):
        client.inspect("execution:kernel:1")


def test_recovery_client_rejects_authority_schema_identity_and_incomplete_completion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = HttpKernelRecoveryClient("http://kernel.test")
    payload = _resolution_payload()

    cases = (
        ({**payload, "authority_bearing": True}, "non-authoritative"),
        ({**payload, "schema": "bounded-domain-effect-resolution-v2"}, "schema"),
        ({**payload, "execution_ref": "execution:rebound"}, "execution identity rebound"),
        ({**payload, "work_ref": "work:rebound"}, "Work identity rebound"),
        ({**payload, "current_status": "retry-approved"}, "unknown recovery status"),
        ({**payload, "evidence_ref": None}, "lacks refs"),
        ({**payload, "processed_at": "not-a-date"}, "processed_at is invalid"),
        ({**payload, "reason": None}, "reason must be a string"),
    )
    for raw, message in cases:
        monkeypatch.setattr(
            httpx,
            "post",
            lambda *args, _raw=raw, **kwargs: StubResponse(_raw),
        )
        with pytest.raises(KernelRecoveryError, match=message):
            client.recover(
                "execution:kernel:1",
                expected_work_ref="work:kernel:1",
            )
