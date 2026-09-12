from __future__ import annotations

import asyncio
import os
from uuid import UUID, uuid5

from administrative_orchestrator.config import get_settings
from administrative_orchestrator.financial import (
    InvoiceFacts,
    TransactionQualificationAssessment,
    VendorMasterRecord,
    qualify_invoice_transaction,
)
from administrative_orchestrator.integrations.credentials import CredentialRef
from administrative_orchestrator.integrations.production_effects import (
    OdooEffectConnection,
    OdooFinancialEffectConnector,
)
from administrative_orchestrator.persistence import SqlStore
from administrative_orchestrator.transaction_repository import TransactionRepository

ASSESSMENT_NAMESPACE = UUID("4cbf1c1b-3c31-55c9-b1a3-7a9bb9f44d67")


def main() -> None:
    raw_case = os.environ.get("M8_CASE_ID", "").strip()
    if not raw_case:
        raise RuntimeError("M8_CASE_ID is required")
    case_id = UUID(raw_case)
    settings = get_settings()
    store = SqlStore(settings.worker_database_url or settings.database_url)
    case = store.get_case(case_id)
    if case is None or case.fact_snapshot is None:
        raise RuntimeError(f"invoice case or fact snapshot not found: {case_id}")

    invoice = InvoiceFacts.model_validate(case.fact_snapshot.facts)
    if invoice.total is None or invoice.po_number is None or invoice.vendor_ref is None:
        raise RuntimeError("invoice facts are not complete for deterministic qualification")
    line_items = [
        {
            "quantity": str(line.quantity),
            "unit_price": str(line.unit_price.amount),
            "currency": line.unit_price.currency,
        }
        for line in invoice.line_items
    ]
    purchase_order = {
        "po_number": invoice.po_number,
        "vendor_ref": invoice.vendor_ref,
        "currency": invoice.total.currency,
        "total": str(invoice.total.amount),
        "receipt_ref": f"m8-receipt:{invoice.po_number}",
        "line_items": line_items,
    }
    receipt = {
        "receipt_ref": purchase_order["receipt_ref"],
        "line_items": [{"quantity": item["quantity"]} for item in line_items],
    }
    input_refs = (
        f"document-digest:{invoice.document_digest}",
        f"po:{invoice.po_number}",
        f"receipt:{receipt['receipt_ref']}",
    )
    verifier = OdooFinancialEffectConnector(
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
    existing_rows = asyncio.run(
        verifier.find_existing_vendor_bills(
            vendor_ref=invoice.vendor_ref,
            invoice_number=invoice.invoice_number or "",
        )
    )
    existing_invoices = tuple(
        {
            "vendor_ref": invoice.vendor_ref,
            "invoice_number": str(row.get("ref") or ""),
        }
        for row in existing_rows
    )
    summary, assessments = qualify_invoice_transaction(
        case_id=case.case_id,
        authority_epoch=case.authority_epoch,
        invoice=invoice,
        vendor_records=(
            VendorMasterRecord(
                vendor_ref=invoice.vendor_ref,
                legal_name=invoice.vendor_name or "M8 Acme Office Supplies",
            ),
        ),
        purchase_order=purchase_order,
        receipt=receipt,
        existing_invoices=existing_invoices,
        input_refs=input_refs,
        rule_ref="m8-staging-invoice-qualification-v1",
        existing_artifacts=(),
    )
    repository = TransactionRepository(store)
    stored: list[TransactionQualificationAssessment] = []
    for assessment in assessments:
        assessment = assessment.model_copy(
            update={
                "assessment_id": uuid5(
                    ASSESSMENT_NAMESPACE,
                    f"{assessment.case_id}:{assessment.authority_epoch}:{assessment.assessment_kind}",
                )
            }
        )
        stored.append(repository.append_assessment(assessment))
    print(
        f"case={case.case_id} summary={summary.result.value} "
        f"erp_duplicate_rows={len(existing_rows)} "
        f"assessments="
        + ",".join(f"{item.assessment_kind}:{item.result.value}:{item.assessment_id}" for item in stored)
    )


if __name__ == "__main__":
    main()
