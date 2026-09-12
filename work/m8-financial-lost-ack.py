from __future__ import annotations

import asyncio
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from administrative_orchestrator.config import get_settings
from administrative_orchestrator.domain import (
    AdministrativeCase,
    AuthorityClass,
    EffectRecord,
    EffectReversibility,
    FactAuthority,
    FactSnapshot,
    PolicyRef,
)
from administrative_orchestrator.effect_provider import ProviderExecutionStatus
from administrative_orchestrator.governance import GovernanceBasis
from administrative_orchestrator.integrations.credentials import CredentialRef
from administrative_orchestrator.integrations.kernel.bridge import KernelExecutionBridge
from administrative_orchestrator.integrations.kernel.client import (
    HttpKernelResponsibilityClient,
    KernelExecutionReceipt,
)
from administrative_orchestrator.integrations.kernel.effect_provider import (
    KernelCutoverEffectProvider,
)
from administrative_orchestrator.integrations.kernel.models import (
    KernelExecutionStatus,
    KernelProjectionStatus,
)
from administrative_orchestrator.integrations.production_effects import (
    OdooEffectConnection,
    OdooFinancialEffectConnector,
)
from administrative_orchestrator.persistence import SqlStore
from administrative_orchestrator.verification import (
    VerificationDisposition,
    verify_financial_observation,
)

FIXED_TIME = datetime(2026, 9, 12, 10, 30, tzinfo=UTC)
CASE_ID = UUID("d3f1f9f3-2e75-5c99-a7e2-2d1c9d8f8301")
SNAPSHOT_ID = UUID("d3f1f9f3-2e75-5c99-a7e2-2d1c9d8f8302")
GOVERNANCE_ID = UUID("d3f1f9f3-2e75-5c99-a7e2-2d1c9d8f8303")
APPROVAL_ID = UUID("d3f1f9f3-2e75-5c99-a7e2-2d1c9d8f8304")
OBLIGATION_ID = UUID("d3f1f9f3-2e75-5c99-a7e2-2d1c9d8f8305")
AUTHORIZATION_ID = UUID("d3f1f9f3-2e75-5c99-a7e2-2d1c9d8f8306")
EFFECT_ID = UUID("d3f1f9f3-2e75-5c99-a7e2-2d1c9d8f8307")
SUBJECT_REF = "m8:expense-recovery:8301"


class LostAckAfterKernelCompletion(RuntimeError):
    pass


class ForbiddenFallbackProvider:
    def __init__(self) -> None:
        self.execute_calls = 0
        self.observe_calls = 0

    def execute(self, effect, payload):
        del effect, payload
        self.execute_calls += 1
        raise AssertionError("legacy Administrative financial provider was invoked")

    def observe(self, effect):
        del effect
        self.observe_calls += 1
        raise AssertionError("legacy Administrative financial observer was invoked")


class LoseExecutionAckClient:
    def __init__(self, delegate: HttpKernelResponsibilityClient, receipt_path: Path) -> None:
        self.delegate = delegate
        self.receipt_path = receipt_path

    def submit(self, projection):
        return self.delegate.submit(projection)

    def admit(self, projection, *, expected_policy_ref: str):
        return self.delegate.admit(projection, expected_policy_ref=expected_policy_ref)

    def execute(self, projection, grant, intent):
        receipt = self.delegate.execute(projection, grant, intent)
        self.receipt_path.write_text(
            json.dumps(_receipt_dict(receipt), sort_keys=True),
            encoding="utf-8",
        )
        raise LostAckAfterKernelCompletion(
            "fault injection: Kernel completed before Administrative receipt persistence"
        )

    def inspect_execution(self, execution_ref: str, *, expected_work_ref: str | None = None):
        return self.delegate.inspect_execution(
            execution_ref,
            expected_work_ref=expected_work_ref,
        )


def _receipt_dict(receipt: KernelExecutionReceipt) -> dict[str, object]:
    return {
        "status": receipt.status,
        "execution_ref": receipt.execution_ref,
        "work_ref": receipt.work_ref,
        "run_ref": receipt.run_ref,
        "request_ref": receipt.request_ref,
        "authorization_ref": receipt.authorization_ref,
        "provider_id": receipt.provider_id,
        "action_ref": receipt.action_ref,
        "outcome_ref": receipt.outcome_ref,
        "evidence_ref": receipt.evidence_ref,
        "responsibility_ref": receipt.responsibility_ref,
    }


def _facts() -> dict[str, object]:
    return {
        "employee_ref": "odoo:hr.employee:1",
        "merchant": "M8 Recovery Supplies",
        "expense_date": "2026-09-12",
        "amount": {"amount": "17.00", "currency": "USD"},
        "category": "office-supplies",
        "business_purpose": "M8 outcome-unknown recovery draft",
        "receipt_ref": "m8-recovery-receipt-20260912",
    }


def _inputs() -> tuple[AdministrativeCase, GovernanceBasis, object]:
    policy = PolicyRef(
        policy_id="expense-reimbursement",
        version="v1",
        owner="administrative-orchestrator",
        effective_from=datetime(2026, 1, 1, tzinfo=UTC),
    )
    snapshot = FactSnapshot(
        snapshot_id=SNAPSHOT_ID,
        source="m8-financial-lost-ack",
        owner="person:m8-recovery-test",
        authority=FactAuthority.CLAIM,
        observed_at=FIXED_TIME,
        source_ref="m8-recovery-document",
        source_version="v1",
        facts=_facts(),
    )
    case = AdministrativeCase(
        case_id=CASE_ID,
        case_kind="expense-reimbursement",
        requester_principal_id="person:m8-recovery-test",
        subject_ref=SUBJECT_REF,
        status="authorized",
        authority_epoch=1,
        fact_snapshot=snapshot,
        policy_ref=policy,
        created_at=FIXED_TIME,
        updated_at=FIXED_TIME,
    )
    governance = GovernanceBasis(
        basis_id=GOVERNANCE_ID,
        case_id=CASE_ID,
        case_version_at_basis=case.version,
        authority_epoch=case.authority_epoch,
        fact_snapshot_id=SNAPSHOT_ID,
        fact_digest="m8-financial-lost-ack-facts",
        policy_ref=policy,
        policy_definition_digest="m8-financial-lost-ack-policy",
        organization_scope="*",
        approval_satisfaction_id=APPROVAL_ID,
        qualifications=(),
        authority_digest="m8-financial-lost-ack-authority",
        basis_digest="m8-financial-lost-ack-governance",
        created_at=FIXED_TIME,
    )
    expected = {
        "target_system": "erp",
        "operation": "expense_report.create",
        "subject_ref": SUBJECT_REF,
        "transaction_case_ref": str(CASE_ID),
        "authority_epoch": 1,
        "payload": _facts(),
        "preconditions": ["qualification_assessments_current"],
        "settlement": "forbidden",
    }
    from administrative_orchestrator.obligations import AdministrativeObligation

    obligation = AdministrativeObligation(
        obligation_id=OBLIGATION_ID,
        case_id=CASE_ID,
        authority_epoch=1,
        governance_basis_id=GOVERNANCE_ID,
        kind="erp.expense_report.create",
        subject_ref=SUBJECT_REF,
        target_system="erp",
        required_operation="expense_report.create",
        expected_postcondition=expected,
        authority_class=AuthorityClass.FINANCIAL,
    )
    return case, governance, obligation


def _settings():
    settings = get_settings()
    return settings.model_copy(
        update={
            "kernel_base_url": os.getenv("ADMIN_KERNEL_BASE_URL", "http://127.0.0.1:8020"),
            "kernel_bridge_mode": "cutover",
            "external_effects_enabled": True,
        }
    )


def _odoo_verifier(settings):
    return OdooFinancialEffectConnector(
        OdooEffectConnection(
            base_url=settings.odoo_base_url,
            database=settings.odoo_database,
            username=settings.odoo_financial_verifier_username,
            credential=CredentialRef(
                "odoo:erp-verifier",
                settings.odoo_financial_verifier_secret_env,
            ),
            transaction_request_ref_field=settings.odoo_transaction_request_ref_field,
            transaction_confirm_request_ref_field=(
                settings.odoo_transaction_confirm_request_ref_field
            ),
            transaction_subject_ref_field=settings.odoo_transaction_subject_ref_field,
            timeout_seconds=settings.connector_timeout_seconds,
            allow_insecure_http=settings.oidc_allow_insecure_http,
        )
    )


def main() -> None:
    settings = _settings()
    database_path = Path(os.environ.get("M8_LOST_ACK_DB_PATH", "/tmp/m8-financial-lost-ack.db"))
    receipt_path = Path(
        os.environ.get("M8_LOST_ACK_RECEIPT_PATH", "/tmp/m8-financial-lost-ack-receipt.json")
    )
    database_path.unlink(missing_ok=True)
    receipt_path.unlink(missing_ok=True)
    database_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.parent.mkdir(parents=True, exist_ok=True)

    case, governance, obligation = _inputs()
    store = SqlStore(f"sqlite+pysqlite:///{database_path}")
    store.init_schema()
    losing_client = LoseExecutionAckClient(
        HttpKernelResponsibilityClient(
            settings.kernel_base_url,
            timeout_seconds=settings.kernel_contract_timeout_seconds,
        ),
        receipt_path,
    )
    first_bridge = KernelExecutionBridge(store, settings=settings, client=losing_client)
    try:
        first_bridge.prepare(case, obligation, governance)
    except LostAckAfterKernelCompletion:
        pass
    else:
        raise RuntimeError("lost-ack fault injection did not interrupt after Kernel execution")

    admitted = first_bridge.repository.get_projection_for_obligation(OBLIGATION_ID)
    if admitted is None or admitted.status is not KernelProjectionStatus.ADMITTED:
        raise RuntimeError("lost-ack boundary did not persist an ADMITTED projection")
    if admitted.kernel_execution_status is not None:
        raise RuntimeError("Administrative store persisted a receipt despite lost ACK")

    recovered_bridge = KernelExecutionBridge(store, settings=settings)
    recovered = recovered_bridge.prepare(case, obligation, governance)
    if recovered is None or recovered.status is not KernelProjectionStatus.CUTOVER:
        raise RuntimeError("fresh bridge did not recover the financial execution")
    if recovered.kernel_execution_status is not KernelExecutionStatus.COMPLETED:
        raise RuntimeError("recovered financial execution is not completed")

    fallback = ForbiddenFallbackProvider()
    provider = KernelCutoverEffectProvider(fallback, recovered_bridge)
    effect = EffectRecord(
        effect_id=EFFECT_ID,
        case_id=CASE_ID,
        case_version=case.version,
        authority_epoch=case.authority_epoch,
        authorization_id=AUTHORIZATION_ID,
        obligation_id=OBLIGATION_ID,
        governance_basis_id=GOVERNANCE_ID,
        target_system="erp",
        operation="expense_report.create",
        subject_ref=SUBJECT_REF,
        reversibility=EffectReversibility.CORRECTABLE,
        authority_class=AuthorityClass.FINANCIAL,
        created_at=FIXED_TIME,
        updated_at=FIXED_TIME,
    )
    execution = provider.execute(effect, _facts())
    observation = provider.observe(effect)
    verification = verify_financial_observation(
        effect,
        observation,
        expected_postcondition=obligation.expected_postcondition,
    )
    if execution.status is not ProviderExecutionStatus.SUCCEEDED:
        raise RuntimeError(f"recovered financial execution was not successful: {execution.status}")
    if verification.disposition is not VerificationDisposition.VERIFIED:
        raise RuntimeError(f"recovered financial readback was not verified: {verification.reason}")
    if fallback.execute_calls != 0 or fallback.observe_calls != 0:
        raise RuntimeError("recovery touched the legacy Administrative provider")

    erp = asyncio.run(_odoo_verifier(settings).reconcile(recovered.kernel_request_ref or "", operation="expense_report.create"))
    if erp is None or erp.external_operation_ref is None:
        raise RuntimeError("Odoo readback did not find the recovered expense record")
    print(
        f"case={CASE_ID} boundary=execution-unknown projection={recovered.status.value} "
        f"kernel_status={recovered.kernel_execution_status.value} verification={verification.disposition.value} "
        f"odoo={erp.external_operation_ref} legacy_execute={fallback.execute_calls} "
        f"legacy_observe={fallback.observe_calls} receipt={receipt_path}"
    )


if __name__ == "__main__":
    main()
