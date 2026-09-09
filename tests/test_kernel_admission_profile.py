import pytest
from pydantic import ValidationError

from administrative_orchestrator.config import (
    DEFAULT_KERNEL_RESPONSIBILITY_ADMISSION_POLICY_REF,
    Settings,
)


def test_admission_mode_defaults_to_kernel_administrative_public_v2_profile() -> None:
    settings = Settings(kernel_bridge_mode="admission")

    assert (
        DEFAULT_KERNEL_RESPONSIBILITY_ADMISSION_POLICY_REF
        == "responsibility-admission:administrative-public@2"
    )
    assert (
        settings.kernel_responsibility_admission_policy_ref
        == DEFAULT_KERNEL_RESPONSIBILITY_ADMISSION_POLICY_REF
    )


def test_shadow_mode_does_not_require_a_work_admission_policy_guard() -> None:
    settings = Settings(
        kernel_bridge_mode="shadow",
        kernel_responsibility_admission_policy_ref="",
    )

    assert settings.kernel_responsibility_admission_policy_ref == ""


def test_admission_mode_rejects_an_empty_policy_guard() -> None:
    with pytest.raises(ValidationError, match="required in admission mode"):
        Settings(
            kernel_bridge_mode="admission",
            kernel_responsibility_admission_policy_ref="",
        )
