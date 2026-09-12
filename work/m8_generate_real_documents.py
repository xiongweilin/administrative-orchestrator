from __future__ import annotations

import os
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

NAVY = colors.HexColor("#17324D")
BLUE = colors.HexColor("#2B6CB0")
PALE_BLUE = colors.HexColor("#EAF3FB")
PALE_GREEN = colors.HexColor("#EAF7F0")
PALE_YELLOW = colors.HexColor("#FFF7DE")
TEXT = colors.HexColor("#233142")
MUTED = colors.HexColor("#60758A")
BORDER = colors.HexColor("#C8D5E2")


def _styles():
    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            name="M8Title",
            parent=styles["Title"],
            fontName="Helvetica-Bold",
            fontSize=17,
            leading=21,
            textColor=NAVY,
            alignment=TA_LEFT,
            spaceAfter=2,
        )
    )
    styles.add(
        ParagraphStyle(
            name="M8Subtitle",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=9,
            leading=12,
            textColor=MUTED,
            alignment=TA_LEFT,
        )
    )
    styles.add(
        ParagraphStyle(
            name="M8Section",
            parent=styles["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=10.5,
            leading=13,
            textColor=NAVY,
            spaceBefore=7,
            spaceAfter=5,
        )
    )
    styles.add(
        ParagraphStyle(
            name="M8Body",
            parent=styles["BodyText"],
            fontName="Helvetica",
            fontSize=9.2,
            leading=12.5,
            textColor=TEXT,
        )
    )
    styles.add(
        ParagraphStyle(
            name="M8Small",
            parent=styles["BodyText"],
            fontName="Helvetica",
            fontSize=8,
            leading=10.5,
            textColor=MUTED,
        )
    )
    styles.add(
        ParagraphStyle(
            name="M8Label",
            parent=styles["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=8.5,
            leading=11,
            textColor=NAVY,
        )
    )
    styles.add(
        ParagraphStyle(
            name="M8Value",
            parent=styles["BodyText"],
            fontName="Helvetica",
            fontSize=9,
            leading=11.5,
            textColor=TEXT,
        )
    )
    styles.add(
        ParagraphStyle(
            name="M8Badge",
            parent=styles["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=7.4,
            leading=9,
            textColor=BLUE,
            alignment=TA_CENTER,
        )
    )
    return styles


def _paragraph(value: object, style: ParagraphStyle) -> Paragraph:
    return Paragraph(escape(str(value)), style)


def _field_table(fields: list[tuple[str, str]], styles) -> Table:
    rows = [
        [_paragraph(label, styles["M8Label"]), _paragraph(value, styles["M8Value"])]
        for label, value in fields
    ]
    table = Table(rows, colWidths=[43 * mm, 125 * mm], hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (0, -1), PALE_BLUE),
                ("BOX", (0, 0), (-1, -1), 0.6, BORDER),
                ("INNERGRID", (0, 0), (-1, -1), 0.35, BORDER),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    return table


def _line_table(headers: list[str], rows: list[list[str]], styles) -> Table:
    data = [[_paragraph(header, styles["M8Label"]) for header in headers]]
    data.extend(
        [[_paragraph(value, styles["M8Value"]) for value in row] for row in rows]
    )
    widths = [168 * mm / len(headers)] * len(headers)
    table = Table(data, colWidths=widths, hAlign="LEFT", repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), PALE_BLUE),
                ("BOX", (0, 0), (-1, -1), 0.6, BORDER),
                ("INNERGRID", (0, 0), (-1, -1), 0.35, BORDER),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    return table


def _notice(text: str, styles, background=PALE_YELLOW) -> Table:
    table = Table([[_paragraph(text, styles["M8Body"])]], colWidths=[168 * mm])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), background),
                ("BOX", (0, 0), (-1, -1), 0.7, BORDER),
                ("LEFTPADDING", (0, 0), (-1, -1), 9),
                ("RIGHTPADDING", (0, 0), (-1, -1), 9),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ]
        )
    )
    return table


def _footer(canvas, document) -> None:
    canvas.saveState()
    canvas.setStrokeColor(BORDER)
    canvas.setLineWidth(0.5)
    canvas.line(18 * mm, 14 * mm, 192 * mm, 14 * mm)
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(MUTED)
    canvas.drawString(18 * mm, 9 * mm, "M8 staging provider acceptance | synthetic data")
    canvas.drawRightString(192 * mm, 9 * mm, f"Page {document.page}")
    canvas.restoreState()


def _build_pdf(
    path: Path,
    *,
    title: str,
    subtitle: str,
    marker: str,
    fields: list[tuple[str, str]],
    headers: list[str],
    rows: list[list[str]],
    notice: str,
) -> None:
    styles = _styles()
    doc = SimpleDocTemplate(
        str(path),
        pagesize=A4,
        rightMargin=21 * mm,
        leftMargin=21 * mm,
        topMargin=18 * mm,
        bottomMargin=20 * mm,
        title=title,
        author="M8 staging preflight",
        subject="Synthetic M8 provider acceptance document",
    )
    badge = _paragraph("SYNTHETIC\nSTAGING INPUT", styles["M8Badge"])
    header = Table(
        [[
            [
                _paragraph(title, styles["M8Title"]),
                _paragraph(subtitle, styles["M8Subtitle"]),
            ],
            badge,
        ]],
        colWidths=[132 * mm, 36 * mm],
        hAlign="LEFT",
    )
    header.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("BACKGROUND", (1, 0), (1, 0), PALE_GREEN),
                ("BOX", (1, 0), (1, 0), 0.7, colors.HexColor("#9BC9AE")),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ]
        )
    )

    story = [
        header,
        Spacer(1, 4),
        Table(
            [[
                _paragraph("Provider marker", styles["M8Label"]),
                _paragraph(marker, styles["M8Value"]),
            ]],
            colWidths=[43 * mm, 125 * mm],
            style=TableStyle(
                [
                    ("BACKGROUND", (0, 0), (0, 0), PALE_BLUE),
                    ("BOX", (0, 0), (-1, -1), 0.6, BORDER),
                    ("INNERGRID", (0, 0), (-1, -1), 0.35, BORDER),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 7),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ]
            ),
        ),
        _paragraph("Bounded transaction facts", styles["M8Section"]),
        _field_table(fields, styles),
        _paragraph("Requested preparation", styles["M8Section"]),
        _line_table(headers, rows, styles),
        Spacer(1, 8),
        _notice(notice, styles),
        Spacer(1, 6),
        _paragraph(
            "This document is intentionally synthetic and is supplied only for the M8 staging acceptance run. It contains no credentials, bank data, or request to move money.",
            styles["M8Small"],
        ),
    ]
    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)


def main() -> None:
    desktop = Path(os.environ.get("M8_DOCUMENT_OUTPUT_DIR", Path.home() / "Desktop"))
    desktop.mkdir(parents=True, exist_ok=True)
    outputs = {
        "procurement": desktop / "M8-STAGING-REAL-20260912-P-procurement-request.pdf",
        "invoice": desktop / "M8-STAGING-REAL-20260912-I-invoice-ap.pdf",
        "expense": desktop / "M8-STAGING-REAL-20260912-E-expense-receipt.pdf",
    }
    if any(path.exists() for path in outputs.values()) and os.environ.get(
        "M8_ALLOW_OVERWRITE"
    ) != "1":
        raise FileExistsError("one or more requested desktop PDFs already exist")

    _build_pdf(
        outputs["procurement"],
        title="M8 staging procurement request",
        subtitle="Document-driven transaction preparation | purchase order draft",
        marker="M8-STAGING-REAL-20260912-P",
        fields=[
            ("Request type", "Procurement request"),
            ("Requester", "M8 synthetic requester"),
            ("Vendor", "M8 Acme Office Supplies"),
            ("Vendor reference", "odoo:res.partner:11"),
            ("Cost center", "CC-STAGING"),
            ("Needed by", "2026-10-01"),
            ("Quote reference", "m8-real-synthetic-quote-20260912-p"),
        ],
        headers=["Item", "Quantity", "Unit price", "Currency"],
        rows=[["Ergonomic office chairs", "2", "60.00", "USD"]],
        notice="Please prepare a bounded purchase order draft and, if the workflow requires it, a separate purchase order confirmation. No payment, bank transfer, settlement, or supplier remittance is requested.",
    )
    _build_pdf(
        outputs["invoice"],
        title="M8 staging invoice and AP preparation",
        subtitle="Document-driven transaction preparation | vendor bill draft",
        marker="M8-STAGING-REAL-20260912-I",
        fields=[
            ("Request type", "Invoice / AP preparation"),
            ("Vendor", "M8 Acme Office Supplies"),
            ("Vendor reference", "odoo:res.partner:11"),
            ("Invoice number", "M8-REAL-INV-20260912-I"),
            ("Invoice date", "2026-09-12"),
            ("Purchase order", "M8-REAL-PO-20260912-I"),
            ("Receipt reference", "m8-real-receipt-20260912-i"),
        ],
        headers=["Item", "Quantity", "Unit price", "Line total"],
        rows=[["Ergonomic office chairs", "2", "60.00 USD", "120.00 USD"]],
        notice="Please qualify the vendor, check duplicate invoice identity and the invoice/PO/receipt match, then prepare a vendor bill draft only. No payment is requested; do not post, pay, settle, or initiate any bank operation.",
    )
    _build_pdf(
        outputs["expense"],
        title="M8 staging expense receipt",
        subtitle="Document-driven transaction preparation | expense record",
        marker="M8-STAGING-REAL-20260912-E",
        fields=[
            ("Request type", "Expense reimbursement preparation"),
            ("Employee reference", "odoo:hr.employee:2"),
            ("Merchant", "M8 Acme Office Supplies"),
            ("Expense date", "2026-09-12"),
            ("Amount", "42.00 USD"),
            ("Category", "office-supplies"),
            ("Receipt reference", "m8-real-expense-receipt-20260912-e"),
            ("Business purpose", "M8 staging office supplies"),
        ],
        headers=["Expense item", "Amount", "Currency", "Receipt"],
        rows=[["Office supplies", "42.00", "USD", "m8-real-expense-receipt-20260912-e"]],
        notice="Please prepare a receipt-backed expense record only. No reimbursement, payment, bank transfer, settlement, or other movement of funds is requested.",
    )

    for path in outputs.values():
        print(path)


if __name__ == "__main__":
    main()
