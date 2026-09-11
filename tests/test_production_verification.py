from __future__ import annotations

from administrative_orchestrator.production_verification import (
    complete_readback_postcondition,
)


def test_readback_postcondition_carries_context_payload_into_evidence() -> None:
    expected = {
        "target_system": "hris",
        "operation": "employee.deactivate",
        "subject_ref": "odoo:hr.employee:4",
        "active": False,
        "payload": {
            "employee_ref": "odoo:hr.employee:4",
            "employment_episode_ref": "episode:1",
        },
    }
    observed = {
        "target_system": "hris",
        "operation": "employee.deactivate",
        "subject_ref": "odoo:hr.employee:4",
        "active": False,
    }

    assert complete_readback_postcondition(expected, observed) == expected


def test_readback_postcondition_does_not_mask_provider_payload_mismatch() -> None:
    expected = {
        "target_system": "hris",
        "operation": "employee.deactivate",
        "subject_ref": "odoo:hr.employee:4",
        "active": False,
        "payload": {"employment_episode_ref": "episode:1"},
    }
    observed = {
        "target_system": "hris",
        "operation": "employee.deactivate",
        "subject_ref": "odoo:hr.employee:4",
        "active": False,
        "payload": {"employment_episode_ref": "episode:2"},
    }

    assert complete_readback_postcondition(expected, observed) == observed
