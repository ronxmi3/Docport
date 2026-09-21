"""DOCX extraction tests using the same SDOC processing path as other files."""

from __future__ import annotations

import pytest

from dataset_loader import load_dataset
from docx_text import DocxTextExtractionError, extract_docx_text
from explanation import format_email_explanation
from pipeline import process_records
from tests.docx_helpers import make_docx_bytes, text_document_blocks
from tests.helpers import BL_TEXT, SI_TEXT, write_bundle
from tests.xlsx_helpers import make_workbook_bytes, text_document_rows


def _comparison_email(si_name: str, bl_name: str) -> dict[str, object]:
    return {
        "subject": "Please compare attached SI against draft BL",
        "body": "Verify the bill of lading before release.",
        "attachments": [si_name, bl_name],
    }


def _run_bundle(tmp_path, attachments):
    root = write_bundle(
        tmp_path / "bundle",
        {"email_001": _comparison_email(*tuple(attachments))},
        attachments,
    )
    dataset = load_dataset(root)
    return dataset, process_records(dataset.emails)


def test_docx_text_keeps_paragraphs_and_tables_in_document_order() -> None:
    content = extract_docx_text(
        make_docx_bytes(
            [
                ("paragraph", "SHIPPING INSTRUCTION"),
                ("table", [("Shipper", "Acme Export Ltd."), ("Consignee", "Beta Imports Inc.")]),
                ("paragraph", "END OF INSTRUCTION"),
            ]
        )
    )

    assert content.index("SHIPPING INSTRUCTION") < content.index("Shipper\tAcme Export Ltd.")
    assert content.index("Shipper\tAcme Export Ltd.") < content.index("END OF INSTRUCTION")


def test_readable_docx_si_and_bl_use_shared_comparison_pipeline(tmp_path) -> None:
    dataset, report = _run_bundle(
        tmp_path,
        {
            "shipment_si.docx": make_docx_bytes(text_document_blocks(SI_TEXT)),
            "shipment_bl.docx": make_docx_bytes(text_document_blocks(BL_TEXT)),
        },
    )

    attachments = {attachment.filename: attachment for attachment in dataset.emails[0].attachments}
    decision = report.decisions["email_001"]
    assert attachments["shipment_si.docx"].metadata["source_format"] == "DOCX"
    assert attachments["shipment_si.docx"].metadata["extraction"] == "python-docx"
    assert "SHIPPING INSTRUCTION" in attachments["shipment_si.docx"].content
    assert decision.si_extracted["shipper"] == "Acme Export Ltd."
    assert decision.bl_extracted["gross_weight_kg"] == "12,500 KGS"
    assert decision.status == "OK"
    explanation = format_email_explanation(dataset.emails[0], decision)
    assert "Source format: DOCX" in explanation
    assert "Extraction: python-docx" in explanation


def test_xlsx_si_and_docx_bl_match_in_the_shared_pipeline(tmp_path) -> None:
    _, report = _run_bundle(
        tmp_path,
        {
            "shipment_si.xlsx": make_workbook_bytes({"SI": text_document_rows(SI_TEXT)}),
            "shipment_bl.docx": make_docx_bytes(text_document_blocks(BL_TEXT)),
        },
    )

    assert report.decisions["email_001"].status == "OK"


def test_docx_mismatch_reports_the_exact_field(tmp_path) -> None:
    mismatched_bl = BL_TEXT.replace("Containers: 3 containers", "Containers: 4 containers")
    _, report = _run_bundle(
        tmp_path,
        {
            "shipment_si.docx": make_docx_bytes(text_document_blocks(SI_TEXT)),
            "shipment_bl.docx": make_docx_bytes(text_document_blocks(mismatched_bl)),
        },
    )

    decision = report.decisions["email_001"]
    assert decision.status == "MISMATCH"
    assert decision.defect_fields == ("container_count",)


def test_corrupt_docx_becomes_needs_review_without_crashing(tmp_path) -> None:
    dataset, report = _run_bundle(
        tmp_path,
        {
            "shipment_si.docx": make_docx_bytes(text_document_blocks(SI_TEXT)),
            "shipment_bl.docx": b"not a Word document",
        },
    )

    broken = next(attachment for attachment in dataset.emails[0].attachments if attachment.filename == "shipment_bl.docx")
    decision = report.decisions["email_001"]
    assert broken.metadata["source_format"] == "DOCX"
    assert broken.metadata["extraction"] == "unreadable"
    assert decision.status == "NEEDS_REVIEW"
    assert decision.review_reason == "unreadable"


def test_empty_docx_is_unreadable() -> None:
    with pytest.raises(DocxTextExtractionError, match="no usable"):
        extract_docx_text(make_docx_bytes([]))
