"""Regression coverage for real supplied hackathon-bundle documents."""

from __future__ import annotations

from pathlib import Path
import shutil

import pytest

from dataset_loader import load_dataset
from pipeline import process_records


DEMO_DATA = Path(__file__).resolve().parents[1] / "demo_data"
PRIVATE_BUNDLE_AVAILABLE = (
    DEMO_DATA / "inbox" / "email_059.json"
).is_file()

pytestmark = pytest.mark.skipif(
    not PRIVATE_BUNDLE_AVAILABLE,
    reason="requires private SDOC challenge bundle fixtures",
)


def _decision_for(email_id: str):
    dataset = load_dataset(DEMO_DATA)
    email = next(item for item in dataset.emails if item.email_id == email_id)
    return process_records((email,)).decisions[email_id]


def test_email_059_pdf_uses_total_gross_weight_not_container_identifiers() -> None:
    """The supplied PDF pair has a gross-weight table before its total field."""

    decision = _decision_for("email_059")

    assert decision.status == "OK"
    assert decision.si_extracted is not None and decision.bl_extracted is not None
    assert decision.si_extracted["port_of_discharge"] == "FREMANTLE, AUSTRALIA"
    assert decision.bl_extracted["port_of_discharge"] == "FREMANTLE, AUSTRALIA"
    assert decision.si_extracted["gross_weight_kg"] == "131,322 KG"
    assert decision.bl_extracted["gross_weight_kg"] == "131,322 KG"


def test_email_055_docx_table_values_flow_through_shared_extractor() -> None:
    """The supplied BL is a python-docx table, not a second parsing format."""

    decision = _decision_for("email_055")

    assert decision.status == "OK"
    assert decision.review_reason is None
    assert decision.bl_extracted is not None
    assert decision.bl_extracted["shipper"] == (
        "APRIL FINE PAPER TRADING ON BEHALF OF VITAL SOLUTIONS PTE LTD "
        "77 ROBINSON ROAD, #21-01 SINGAPORE 068896"
    )
    assert decision.bl_extracted["port_of_discharge"] == "KARACHI, PAKISTAN"
    assert decision.bl_extracted["gross_weight_kg"] == "243,588"


def test_email_116_strong_investment_spam_evidence_beats_payment_language() -> None:
    decision = _decision_for("email_116")

    assert decision.category == "SPAM"
    assert "investment scam signal: guaranteed percentage return" in decision.classification_reasons


def test_legitimate_bundle_invoice_query_remains_an_invoice_query() -> None:
    assert _decision_for("email_002").category == "INVOICE_QUERY"


def test_email_012_current_body_overrides_a_stale_si_subject_phrase() -> None:
    decision = _decision_for("email_012")

    assert decision.category == "GENERAL"


def test_normal_bundle_si_request_with_current_body_evidence_remains_si_request() -> None:
    assert _decision_for("email_007").category == "SI_REQUEST"


@pytest.mark.skipif(shutil.which("tesseract") is None, reason="requires the documented local Tesseract dependency")
def test_email_512_scanned_pdfs_use_ocr_before_document_review() -> None:
    decision = _decision_for("email_512")

    # The supplied scans are identified and extracted through OCR. Their
    # incomplete field data must still take the safe unreadable route rather
    # than fabricating a comparison or a mismatch.
    assert decision.status == "NEEDS_REVIEW"
    assert decision.review_reason == "unreadable"
    assert decision.selection is not None
    assert all(assessment.attachment.metadata["extraction"] == "OCR (Tesseract)" for assessment in decision.selection.assessments)
