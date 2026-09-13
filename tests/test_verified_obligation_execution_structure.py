from __future__ import annotations

import inspect

from administrative_orchestrator.financial_execution import FinancialExecutionEngine
from administrative_orchestrator.offboarding_execution import OffboardingExecutionEngine
from administrative_orchestrator.onboarding_execution import OnboardingExecutionEngine
from administrative_orchestrator.verified_obligation_execution import (
    VerifiedObligationExecutor,
)


def test_existing_execution_inheritance_surface_is_preserved() -> None:
    assert issubclass(FinancialExecutionEngine, OnboardingExecutionEngine)
    assert issubclass(OffboardingExecutionEngine, OnboardingExecutionEngine)


def test_child_domains_compose_the_verified_obligation_executor() -> None:
    financial_run = inspect.getsource(FinancialExecutionEngine.run)
    offboarding_run = inspect.getsource(OffboardingExecutionEngine.run)
    offboarding_dispatch = inspect.getsource(OffboardingExecutionEngine._drive_dispatch)
    offboarding_verify = inspect.getsource(OffboardingExecutionEngine._verify_all)

    assert "VerifiedObligationExecutor(self).run" in financial_run
    assert "VerifiedObligationExecutor(self).run" in offboarding_run
    assert "VerifiedObligationExecutor(self).drive_dispatch" in offboarding_dispatch
    assert "VerifiedObligationExecutor(self).verify_all" in offboarding_verify


def test_generic_executor_does_not_own_domain_interpretation() -> None:
    source = inspect.getsource(VerifiedObligationExecutor)

    forbidden = (
        "employee-offboarding",
        "procurement-request",
        "invoice-ap-preparation",
        "expense-reimbursement",
        "derive_offboarding_obligations",
        "derive_financial_obligations",
        "derive_onboarding_obligations",
        "TransactionQualification",
        "authoritative_effective_time",
        "role_assignment.transfer",
        "purchase_order.confirm",
    )
    for token in forbidden:
        assert token not in source


def test_generic_executor_calls_domain_owned_hooks() -> None:
    source = inspect.getsource(VerifiedObligationExecutor)

    for hook in (
        "_plan_current_effects",
        "_validate_current_governance",
        "_drive_dispatch",
        "_verify_all",
        "_assess_completion",
        "_handle_completion_blocked",
        "_verify_observation",
        "_payload_for_effect",
    ):
        assert hook in source
