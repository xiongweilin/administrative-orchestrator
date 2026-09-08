from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Any

API_BASE = os.getenv("ADMIN_E2E_API_BASE", "http://127.0.0.1:8000")
SANDBOX_BASE = os.getenv("ADMIN_E2E_SANDBOX_BASE", "http://127.0.0.1:8010")
TIMEOUT_SECONDS = float(os.getenv("ADMIN_E2E_TIMEOUT_SECONDS", "90"))


def _request(method: str, url: str, payload: dict[str, Any] | None = None) -> Any:
    body = None
    headers: dict[str, str] = {}
    if payload is not None:
        body = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.loads(response.read().decode())


def _wait_json(url: str, predicate, *, description: str) -> Any:
    deadline = time.monotonic() + TIMEOUT_SECONDS
    last_error: Exception | None = None
    last_value: Any = None
    while time.monotonic() < deadline:
        try:
            last_value = _request("GET", url)
            if predicate(last_value):
                return last_value
        except (OSError, urllib.error.HTTPError, urllib.error.URLError) as exc:
            last_error = exc
        time.sleep(0.25)
    raise AssertionError(
        f"timed out waiting for {description}; last_value={last_value!r}; "
        f"last_error={last_error!r}"
    )


def main() -> None:
    _wait_json(
        f"{API_BASE}/readyz",
        lambda value: value.get("status") == "ready",
        description="API readiness",
    )
    _wait_json(
        f"{SANDBOX_BASE}/healthz",
        lambda value: value.get("status") == "ok",
        description="authoritative sandbox readiness",
    )

    created = _request(
        "POST",
        f"{API_BASE}/v1/onboarding",
        {
            "requester_principal_id": "person:e2e-requester",
            "employee_ref": "employee:e2e-new-hire",
            "department_ref": "department:engineering",
            "manager_principal_id": "person:e2e-manager",
            "start_date": "2026-09-15",
            "employment_type": "full-time",
            "requested_systems": [],
            "requires_privileged_access": False,
            "channel": "compose-e2e",
        },
    )
    case = created["case"]
    assert case["status"] == "awaiting_decision", created
    case_id = case["case_id"]
    initial_epoch = case["authority_epoch"]

    decision = _request(
        "POST",
        f"{API_BASE}/v1/cases/{case_id}/decisions",
        {
            "principal_id": "person:e2e-hr-approver",
            "disposition": "approve",
            "rationale": "compose e2e approval",
        },
    )
    assert decision["case"]["status"] == "authorized", decision
    assert decision["case"]["authority_epoch"] == initial_epoch, decision

    completed = _wait_json(
        f"{API_BASE}/v1/cases/{case_id}",
        lambda value: value.get("status") == "completed",
        description="onboarding completion",
    )
    assert completed["authority_epoch"] == initial_epoch, completed

    effects = _request("GET", f"{API_BASE}/v1/cases/{case_id}/effects")
    assert len(effects) == 2, effects
    expected_effects = {
        ("hris", "employee.create"),
        ("iam", "identity.create"),
    }
    actual_effects = {(item["target_system"], item["operation"]) for item in effects}
    assert actual_effects == expected_effects, effects
    assert {item["status"] for item in effects} == {"succeeded"}, effects

    for effect in effects:
        observation = _request(
            "GET",
            f"{SANDBOX_BASE}/v1/effects/{effect['effect_id']}",
        )
        assert observation["found"] is True, observation
        assert observation["target_system"] == effect["target_system"], observation
        assert observation["operation"] == effect["operation"], observation
        assert observation["subject_ref"] == effect["subject_ref"], observation
        assert observation["state"]["active"] is True, observation

    outcomes = _request("GET", f"{API_BASE}/v1/cases/{case_id}/outcomes")
    assert len(outcomes) == 2, outcomes
    assert {item["effect_id"] for item in outcomes} == {
        item["effect_id"] for item in effects
    }, outcomes
    assert {item["authority_epoch"] for item in outcomes} == {initial_epoch}, outcomes
    assert {item["outcome_kind"] for item in outcomes} == {
        "hris.employee.create.verified",
        "iam.identity.create.verified",
    }, outcomes
    assert all(item["evidence"] for item in outcomes), outcomes

    audit = _request("GET", f"{API_BASE}/v1/cases/{case_id}/audit")
    event_types = [item["event_type"] for item in audit]
    for required in (
        "case.created",
        "policy.evaluated",
        "decision.recorded",
        "authorization.issued",
        "effect.planned",
        "effect.realization_assessed",
        "outcome.confirmed",
        "case.completed",
    ):
        assert required in event_types, (required, event_types)

    print(
        json.dumps(
            {
                "case_id": case_id,
                "status": completed["status"],
                "authority_epoch": initial_epoch,
                "effects": effects,
                "outcomes": outcomes,
                "audit_event_count": len(audit),
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
