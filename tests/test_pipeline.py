import json

import pytest

from dataset_loader import load_dataset
from pipeline import process_records
from submission import (
    SubmissionValidationError,
    build_submission,
    load_submission_template,
    validate_submission,
)
from tests.helpers import BL_TEXT, SI_TEXT, write_bundle
from tests.pdf_helpers import make_blank_pdf, make_text_pdf
from tests.xlsx_helpers import make_workbook_bytes, text_document_rows


def _comparison_email(si_name: str = "shipment_si.txt", bl_name: str = "shipment_bl.txt") -> dict[str, object]:
    return {
        "subject": "Please compare attached SI against draft BL",
        "body": "Verify the bill of lading before release.",
        "attachments": [si_name, bl_name],
    }


def _run_bundle(tmp_path, emails, attachments, workers: int = 1):
    root = write_bundle(tmp_path / "bundle", emails, attachments)
    dataset = load_dataset(root)
    return root, dataset, process_records(dataset.emails, workers=workers)


def test_end_to_end_official_folder_layout_generates_complete_submission(tmp_path) -> None:
    emails = {
        "email_001": _comparison_email(),
        "email_002": {"subject": "Please prepare a new SI", "body": "New shipping instruction request."},
        "email_003": {"subject": "Invoice query", "body": "Please clarify payment terms."},
        "email_004": {"subject": "Office closure", "body": "Holiday notice."},
        "email_005": {"subject": "You have won a lottery", "body": "Click here to claim."},
    }
    root, dataset, report = _run_bundle(
        tmp_path,
        emails,
        {"shipment_si.txt": SI_TEXT, "shipment_bl.txt": BL_TEXT},
    )

    assert dataset.loader_name == "folder layout"
    assert list(report.decisions) == sorted(emails)
    assert report.decisions["email_001"].status == "OK"
    assert report.decisions["email_002"].category == "SI_REQUEST"
    assert report.decisions["email_003"].category == "INVOICE_QUERY"
    assert report.decisions["email_004"].category == "GENERAL"
    assert report.decisions["email_005"].category == "SPAM"

    payload = build_submission(report.decisions, load_submission_template(root / "sample_submission.json"))
    validate_submission(payload, emails)
    assert list(payload) == list(emails)
    assert payload["email_001"] == {
        "category": "BL_COMPARISON",
        "status": "OK",
        "has_defect": False,
        "defect_fields": [],
        "review_reason": None,
    }


def test_one_and_multiple_defects_are_exact_and_deterministic(tmp_path) -> None:
    one_defect_bl = BL_TEXT.replace("Containers: 3 containers", "Containers: 4 containers")
    many_defect_bl = (
        BL_TEXT.replace("Shipper: ACME EXPORT LIMITED", "Shipper: Other Exporter")
        .replace("Discharge Port: Los Angeles, USA", "Discharge Port: Rotterdam")
        .replace("Containers: 3 containers", "Containers: 4 containers")
    )
    _, _, report = _run_bundle(
        tmp_path,
        {
            "email_001": _comparison_email("si_one.txt", "bl_one.txt"),
            "email_002": _comparison_email("si_many.txt", "bl_many.txt"),
        },
        {
            "si_one.txt": SI_TEXT,
            "bl_one.txt": one_defect_bl,
            "si_many.txt": SI_TEXT,
            "bl_many.txt": many_defect_bl,
        },
    )

    one = report.decisions["email_001"]
    many = report.decisions["email_002"]
    assert (one.status, one.has_defect, one.defect_fields) == (
        "MISMATCH",
        True,
        ("container_count",),
    )
    assert many.defect_fields == ("shipper", "port_of_discharge", "container_count")


@pytest.mark.parametrize(
    ("attachments", "files", "reason"),
    [
        (["only_si.txt"], {"only_si.txt": SI_TEXT}, "missing_attachment"),
        (["invoice.txt"], {"invoice.txt": "COMMERCIAL INVOICE"}, "wrong_doc_type"),
        (["invoice_a.txt", "invoice_b.txt"], {"invoice_a.txt": "COMMERCIAL INVOICE", "invoice_b.txt": "INVOICE"}, "wrong_doc_type"),
        (["broken_si.txt", "broken_bl.txt"], {"broken_si.txt": b"\x00\xff", "broken_bl.txt": b"\x00\xff"}, "unreadable"),
    ],
)
def test_document_failures_become_safe_needs_review(tmp_path, attachments, files, reason) -> None:
    emails = {
        "email_001": {
            "subject": "Compare SI and BL",
            "body": "Please verify documents.",
            "attachments": attachments,
        }
    }
    _, _, report = _run_bundle(tmp_path, emails, files)

    decision = report.decisions["email_001"]
    assert decision.category == "BL_COMPARISON"
    assert decision.status == "NEEDS_REVIEW"
    assert decision.has_defect is False
    assert decision.defect_fields == ()
    assert decision.review_reason == reason


def test_missing_required_value_becomes_needs_review(tmp_path) -> None:
    incomplete_bl = BL_TEXT.replace("Notify Party: Beta Imports Incorporated\n", "")
    _, _, report = _run_bundle(
        tmp_path,
        {"email_001": _comparison_email()},
        {"shipment_si.txt": SI_TEXT, "shipment_bl.txt": incomplete_bl},
    )

    decision = report.decisions["email_001"]
    assert decision.status == "NEEDS_REVIEW"
    assert decision.review_reason == "missing_value"
    assert decision.has_defect is False
    assert decision.defect_fields == ()


def test_parallel_processing_has_deterministic_semantic_output(tmp_path) -> None:
    emails = {
        f"email_{number:03d}": _comparison_email(f"si_{number}.txt", f"bl_{number}.txt")
        for number in range(1, 13)
    }
    attachments = {
        name: content
        for number in range(1, 13)
        for name, content in ((f"si_{number}.txt", SI_TEXT), (f"bl_{number}.txt", BL_TEXT))
    }
    root = write_bundle(tmp_path / "bundle", emails, attachments)
    dataset = load_dataset(root)

    single = process_records(dataset.emails, workers=1)
    parallel = process_records(dataset.emails, workers=4)

    assert [decision.to_submission_values() for decision in single.decisions.values()] == [
        decision.to_submission_values() for decision in parallel.decisions.values()
    ]
    assert list(single.decisions) == list(parallel.decisions)


def test_submission_validation_rejects_inconsistent_semantics(tmp_path) -> None:
    emails = {"email_001": _comparison_email()}
    root, _, report = _run_bundle(
        tmp_path,
        emails,
        {"shipment_si.txt": SI_TEXT, "shipment_bl.txt": BL_TEXT},
    )
    payload = build_submission(report.decisions, load_submission_template(root / "sample_submission.json"))
    payload["email_001"]["status"] = "MISMATCH"

    with pytest.raises(SubmissionValidationError):
        validate_submission(payload, emails)


def test_dataset_loader_prefers_an_official_inbox_abstraction(tmp_path) -> None:
    emails = {"email_001": _comparison_email()}
    root = write_bundle(
        tmp_path / "bundle",
        emails,
        {"shipment_si.txt": SI_TEXT, "shipment_bl.txt": BL_TEXT},
    )
    (root / "loader.py").write_text(
        """from pathlib import Path
class Inbox:
    def __init__(self, source):
        self.root = Path(source)
    def __iter__(self):
        return iter([{
            'email_id': 'email_001',
            'subject': 'Please compare SI and BL',
            'attachments': ['shipment_si.txt', 'shipment_bl.txt'],
        }])
    def read_text(self, path):
        return (self.root / 'attachments' / path).read_text(encoding='utf-8')
""",
        encoding="utf-8",
    )

    dataset = load_dataset(root)

    assert dataset.loader_name == "official Inbox"
    assert [email.email_id for email in dataset.emails] == ["email_001"]


def test_submission_writer_preserves_nested_template_structure(tmp_path) -> None:
    emails = {"email_001": _comparison_email()}
    root, _, report = _run_bundle(
        tmp_path,
        emails,
        {"shipment_si.txt": SI_TEXT, "shipment_bl.txt": BL_TEXT},
    )
    nested_template = {
        "email_001": {
            "payload": {
                "category": None,
                "status": None,
                "has_defect": False,
                "defect_fields": [],
                "review_reason": None,
            },
            "schema_version": "1.0",
        }
    }
    template_path = root / "sample_submission.json"
    template_path.write_text(json.dumps(nested_template), encoding="utf-8")

    payload = build_submission(report.decisions, load_submission_template(template_path))

    assert payload["email_001"]["schema_version"] == "1.0"
    assert payload["email_001"]["payload"]["status"] == "OK"


def test_pdf_with_embedded_text_participates_in_a_successful_comparison(tmp_path) -> None:
    _, dataset, report = _run_bundle(
        tmp_path,
        {"email_001": _comparison_email("shipment_si.txt", "draft_bl.pdf")},
        {"shipment_si.txt": SI_TEXT, "draft_bl.pdf": make_text_pdf([BL_TEXT])},
    )

    pdf_attachment = next(attachment for attachment in dataset.emails[0].attachments if attachment.filename.endswith(".pdf"))
    decision = report.decisions["email_001"]
    assert pdf_attachment.metadata["source_format"] == "PDF"
    assert pdf_attachment.metadata["extraction"] == "embedded text"
    assert "BILL OF LADING" in pdf_attachment.content
    assert decision.status == "OK"


def test_pdf_with_embedded_text_reports_exact_mismatch_fields(tmp_path) -> None:
    mismatched_bl = BL_TEXT.replace("Containers: 3 containers", "Containers: 4 containers")
    _, _, report = _run_bundle(
        tmp_path,
        {"email_001": _comparison_email("shipment_si.txt", "draft_bl.pdf")},
        {"shipment_si.txt": SI_TEXT, "draft_bl.pdf": make_text_pdf([mismatched_bl])},
    )

    decision = report.decisions["email_001"]
    assert decision.status == "MISMATCH"
    assert decision.defect_fields == ("container_count",)


@pytest.mark.parametrize("pdf_bytes", [make_blank_pdf(), b"not a valid PDF"])
def test_unreadable_pdf_becomes_needs_review_without_crashing(tmp_path, pdf_bytes) -> None:
    _, _, report = _run_bundle(
        tmp_path,
        {"email_001": _comparison_email("shipment_si.txt", "draft_bl.pdf")},
        {"shipment_si.txt": SI_TEXT, "draft_bl.pdf": pdf_bytes},
    )

    decision = report.decisions["email_001"]
    assert decision.status == "NEEDS_REVIEW"
    assert decision.review_reason == "unreadable"


def test_txt_attachment_loading_remains_plain_text(tmp_path) -> None:
    _, dataset, report = _run_bundle(
        tmp_path,
        {"email_001": _comparison_email()},
        {"shipment_si.txt": SI_TEXT, "shipment_bl.txt": BL_TEXT},
    )

    si_attachment = next(attachment for attachment in dataset.emails[0].attachments if attachment.filename.endswith("_si.txt"))
    assert si_attachment.content == SI_TEXT
    assert si_attachment.metadata["source_format"] == "TXT"
    assert si_attachment.metadata["extraction"] == "plain text"
    assert report.decisions["email_001"].status == "OK"


def test_readable_xlsx_si_and_bl_use_the_shared_field_pipeline(tmp_path) -> None:
    _, dataset, report = _run_bundle(
        tmp_path,
        {"email_001": _comparison_email("shipment_si.xlsx", "shipment_bl.xlsx")},
        {
            "shipment_si.xlsx": make_workbook_bytes({"SI": text_document_rows(SI_TEXT)}),
            "shipment_bl.xlsx": make_workbook_bytes({"BL": text_document_rows(BL_TEXT)}),
        },
    )

    decision = report.decisions["email_001"]
    attachments = {attachment.filename: attachment for attachment in dataset.emails[0].attachments}
    assert attachments["shipment_si.xlsx"].metadata["source_format"] == "XLSX"
    assert attachments["shipment_si.xlsx"].metadata["extraction"] == "openpyxl"
    assert "SHIPPING INSTRUCTION" in attachments["shipment_si.xlsx"].content
    assert decision.si_extracted["shipper"] == "Acme Export Ltd."
    assert decision.bl_extracted["gross_weight_kg"] == "12,500 KGS"
    assert decision.status == "OK"


def test_xlsx_bl_instruction_heading_is_content_evidence_for_si(tmp_path) -> None:
    si_rows = text_document_rows(SI_TEXT.replace("SHIPPING INSTRUCTION", "BL INSTRUCTION"))
    _, _, report = _run_bundle(
        tmp_path,
        {"email_001": _comparison_email("shipment_si.xlsx", "shipment_bl.xlsx")},
        {
            "shipment_si.xlsx": make_workbook_bytes({"S.I.": si_rows}),
            "shipment_bl.xlsx": make_workbook_bytes({"BL": text_document_rows(BL_TEXT)}),
        },
    )

    assessment = next(
        item for item in report.decisions["email_001"].selection.assessments if item.attachment.filename == "shipment_si.xlsx"
    )
    assert assessment.document_type == "SI"
    assert "content heading: BL instruction" in assessment.reasons


def test_xlsx_documents_report_exact_field_mismatches(tmp_path) -> None:
    mismatched_bl = BL_TEXT.replace("Containers: 3 containers", "Containers: 4 containers")
    _, _, report = _run_bundle(
        tmp_path,
        {"email_001": _comparison_email("shipment_si.xlsx", "shipment_bl.xlsx")},
        {
            "shipment_si.xlsx": make_workbook_bytes({"SI": text_document_rows(SI_TEXT)}),
            "shipment_bl.xlsx": make_workbook_bytes({"BL": text_document_rows(mismatched_bl)}),
        },
    )

    decision = report.decisions["email_001"]
    assert decision.status == "MISMATCH"
    assert decision.defect_fields == ("container_count",)


def test_corrupt_xlsx_becomes_needs_review_without_crashing(tmp_path) -> None:
    _, dataset, report = _run_bundle(
        tmp_path,
        {"email_001": _comparison_email("shipment_si.xlsx", "shipment_bl.xlsx")},
        {"shipment_si.xlsx": make_workbook_bytes({"SI": text_document_rows(SI_TEXT)}), "shipment_bl.xlsx": b"bad xlsx"},
    )

    broken = next(attachment for attachment in dataset.emails[0].attachments if attachment.filename == "shipment_bl.xlsx")
    decision = report.decisions["email_001"]
    assert broken.metadata["source_format"] == "XLSX"
    assert broken.metadata["extraction"] == "unreadable"
    assert decision.status == "NEEDS_REVIEW"
    assert decision.review_reason == "unreadable"


def test_xlsm_uses_the_same_workbook_attachment_path(tmp_path) -> None:
    _, dataset, report = _run_bundle(
        tmp_path,
        {"email_001": _comparison_email("shipment_si.xlsm", "shipment_bl.xlsm")},
        {
            "shipment_si.xlsm": make_workbook_bytes({"SI": text_document_rows(SI_TEXT)}),
            "shipment_bl.xlsm": make_workbook_bytes({"BL": text_document_rows(BL_TEXT)}),
        },
    )

    attachments = {attachment.filename: attachment for attachment in dataset.emails[0].attachments}
    assert attachments["shipment_si.xlsm"].metadata["source_format"] == "XLSM"
    assert attachments["shipment_si.xlsm"].metadata["extraction"] == "openpyxl"
    assert report.decisions["email_001"].status == "OK"
