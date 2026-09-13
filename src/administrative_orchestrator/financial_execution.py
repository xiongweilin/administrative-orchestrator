from __future__ import annotations

from uuid import UUID

from .domain import AdministrativeCase
from .onboarding_execution import FinancialQualificationPending, OnboardingExecutionEngine
from .service import TransitionError
from .verified_obligation_execution import VerifiedObligationExecutor

FINANCIAL_CASE_KINDS = frozenset(
    {
        "procurement-request",
        "invoice-ap-preparation",
        "expense-reimbursement",
    }
)


class FinancialExecutionEngine(OnboardingExecutionEngine):
    """Reuse the governed effect lifecycle for bounded ERP preparations."""

    def run(self, case_id: UUID) -> AdministrativeCase:
        case = self._require_case(case_id)
        if case.case_kind not in FINANCIAL_CASE_KINDS:
            raise TransitionError(
                f"financial execution engine requires a financial case, got {case.case_kind!r}"
            )
        try:
            return VerifiedObligationExecutor(self).run(case_id)
        except FinancialQualificationPending:
            # Preserve the established asynchronous qualification wait: the
            # authorization remains current and no execution transition occurs.
            return self._require_case(case_id)

    def _drive_dispatch(self, case, effects, obligation_set, links):
        return VerifiedObligationExecutor(self).drive_dispatch(
            case, effects, obligation_set, links
        )

    def _verify_all(self, case, effects, obligation_set, links):
        return VerifiedObligationExecutor(self).verify_all(
            case, effects, obligation_set, links
        )


__all__ = ["FINANCIAL_CASE_KINDS", "FinancialExecutionEngine"]
