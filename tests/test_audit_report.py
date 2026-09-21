"""Tests for presentation-only PDF decision audit reports."""

from __future__ import annotations

from pypdf import PdfReader

from audit_report import write_decision_audit_report
from dataset_loader import load_dataset
from pipeline import process_records
from submission import build_submission, load_submission_template
from tests.helpers import BL_TEXT, SI_TEXT, write_bundle


def _comparison_email(si_name: str = "shipment_si.txt", bl_name: str = "shipment_bl.txt") -> dict[str, object]:
    return {
        "subject": "Please compare attached SI against draft BL",
        "body": "Verify the bill of lading before release.",
        "attachments": [si_name, bl_name],
    }


def _run_bundle(tmp_path, emails, attachments):
    root = write_bundle(tmp_path / "bundle", emails, attachments)
    dataset = load_dataset(root)
    report = process_records(dataset.emails, workers=2)
    return root, dataset, report


def _report_text(path) -> str:
    return "\n".join(page.extract_text() or "" for page in PdfReader(str(path)).pages)


def test_generates_readable_pdf_report_from_stored_decisions(tmp_path) -> None:
    root, dataset, report = _run_bundle(
        tmp_path,
        {"email_001": _comparison_email(), "email_002": {"subject": "Office closure"}},
        {"shipment_si.txt": SI_TEXT, "shipment_bl.txt": BL_TEXT},
    )

    result = write_decision_audit_report(
        tmp_path / "decision_report.pdf",
        dataset.emails,
        report.decisions,
        runtime_seconds=1.25,
        throughput=1.6,
    )

    assert root.is_dir()
    assert result.path.is_file()
    assert result.page_count == len(PdfReader(str(result.path)).pages)
    assert result.included_email_ids == ("email_001", "email_002")
    text = _report_text(result.path)
    assert "SDOC Shipping Document Verification" in text
    assert "Decision Audit Report" in text
    assert "Category counts" in text
    assert "Email audit: email_001" in text


def test_one_email_report_includes_exactly_that_email(tmp_path) -> None:
    _, dataset, report = _run_bundle(
        tmp_path,
        {"email_001": _comparison_email(), "email_002": {"subject": "Office closure"}},
        {"shipment_si.txt": SI_TEXT, "shipment_bl.txt": BL_TEXT},
    )
    email = next(item for item in dataset.emails if item.email_id == "email_001")

    result = write_decision_audit_report(
        tmp_path / "one_email.pdf",
        (email,),
        {"email_001": report.decisions["email_001"]},
        runtime_seconds=0.2,
        throughput=5.0,
    )

    assert result.included_email_ids == ("email_001",)
    text = _report_text(result.path)
    assert "Email audit: email_001" in text
    assert "email_002" not in text


def test_problem_only_report_filters_ok_and_general_decisions(tmp_path) -> None:
    mismatched_bl = BL_TEXT.replace("Containers: 3 containers", "Containers: 4 containers")
    _, dataset, report = _run_bundle(
        tmp_path,
        {
            "email_001": _comparison_email("ok_si.txt", "ok_bl.txt"),
            "email_002": _comparison_email("bad_si.txt", "bad_bl.txt"),
            "email_003": {"subject": "Please compare SI and BL", "attachments": ["only_si.txt"]},
            "email_004": {"subject": "Office closure"},
        },
        {
            "ok_si.txt": SI_TEXT,
            "ok_bl.txt": BL_TEXT,
            "bad_si.txt": SI_TEXT,
            "bad_bl.txt": mismatched_bl,
            "only_si.txt": SI_TEXT,
        },
    )

    result = write_decision_audit_report(
        tmp_path / "problems_only.pdf",
        dataset.emails,
        report.decisions,
        runtime_seconds=1.0,
        throughput=4.0,
        problems_only=True,
    )

    assert result.included_email_ids == ("email_002", "email_003")
    text = _report_text(result.path)
    assert "Email audit: email_002" in text
    assert "Email audit: email_003" in text
    assert "Email audit: email_001" not in text
    assert "Email audit: email_004" not in text


def test_mismatch_report_contains_raw_normalized_field_table(tmp_path) -> None:
    mismatched_bl = BL_TEXT.replace("Containers: 3 containers", "Containers: 4 containers")
    _, dataset, report = _run_bundle(
        tmp_path,
        {"email_001": _comparison_email("shipment_si.txt", "shipment_bl.txt")},
        {"shipment_si.txt": SI_TEXT, "shipment_bl.txt": mismatched_bl},
    )

    result = write_decision_audit_report(
        tmp_path / "mismatch.pdf", dataset.emails, report.decisions, runtime_seconds=0.1, throughput=10.0
    )

    text = _report_text(result.path)
    assert "SI Raw" in text
    assert "BL Raw" in text
    assert "SI Normalized" in text
    assert "BL Normalized" in text
    assert "container_count" in text
    assert "MISMATCH" in text
    assert "4 containers" in text


def test_needs_review_report_includes_existing_explanation(tmp_path) -> None:
    incomplete_bl = BL_TEXT.replace("Notify Party: Beta Imports Incorporated\n", "")
    _, dataset, report = _run_bundle(
        tmp_path,
        {"email_001": _comparison_email("shipment_si.txt", "shipment_bl.txt")},
        {"shipment_si.txt": SI_TEXT, "shipment_bl.txt": incomplete_bl},
    )

    result = write_decision_audit_report(
        tmp_path / "review.pdf", dataset.emails, report.decisions, runtime_seconds=0.1, throughput=10.0
    )

    text = _report_text(result.path)
    assert "NEEDS_REVIEW" in text
    assert "missing_value" in text
    assert "Human-readable explanation" in text
    assert "No safe field comparison was performed." in " ".join(text.split())


def test_rendering_report_does_not_change_submission_payload(tmp_path) -> None:
    root, dataset, report = _run_bundle(
        tmp_path,
        {"email_001": _comparison_email()},
        {"shipment_si.txt": SI_TEXT, "shipment_bl.txt": BL_TEXT},
    )
    template = load_submission_template(root / "sample_submission.json")
    before = build_submission(report.decisions, template)

    write_decision_audit_report(
        tmp_path / "unchanged.pdf", dataset.emails, report.decisions, runtime_seconds=0.1, throughput=10.0
    )

    assert build_submission(report.decisions, template) == before


def test_report_keeps_final_heading_and_first_explanation_block_together(tmp_path) -> None:
    """Pagination must not leave the decision/explanation headings orphaned."""

    root, dataset, report = _run_bundle(
        tmp_path,
        {"email_001": _comparison_email()},
        {"shipment_si.txt": SI_TEXT, "shipment_bl.txt": BL_TEXT},
    )
    assert root.is_dir()
    result = write_decision_audit_report(
        tmp_path / "pagination.pdf", dataset.emails, report.decisions, runtime_seconds=0.1, throughput=10.0
    )

    page_texts = [page.extract_text() or "" for page in PdfReader(str(result.path)).pages]
    final_page = next(text for text in page_texts if "Final decision" in text)
    assert "Final status" in final_page
    assert "Human-readable explanation" in final_page
    assert "EMAIL: email_001" in final_page
