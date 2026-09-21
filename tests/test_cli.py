import sys

import attachment_opener
from main import cli
from tests.helpers import BL_TEXT, SI_TEXT, write_bundle


def test_cli_generates_a_valid_submission_from_folder_bundle(tmp_path, monkeypatch) -> None:
    root = write_bundle(
        tmp_path / "bundle",
        {
            "email_001": {
                "subject": "Please compare SI and BL",
                "body": "Verify the attached draft.",
                "attachments": ["shipment_si.txt", "shipment_bl.txt"],
            }
        },
        {"shipment_si.txt": SI_TEXT, "shipment_bl.txt": BL_TEXT},
    )
    output = tmp_path / "submission.json"
    monkeypatch.setattr(
        sys,
        "argv",
        ["main.py", "--source", str(root), "--output", str(output), "--workers", "2", "--benchmark"],
    )

    assert cli() == 0
    assert output.is_file()
    assert '"status": "OK"' in output.read_text(encoding="utf-8")


def test_cli_email_mode_prints_debug_without_writing_partial_submission(tmp_path, monkeypatch, capsys) -> None:
    root = write_bundle(
        tmp_path / "bundle",
        {
            "email_004": {
                "subject": "Please compare SI and BL",
                "attachments": ["shipment_si.txt", "shipment_bl.txt"],
            }
        },
        {"shipment_si.txt": SI_TEXT, "shipment_bl.txt": BL_TEXT},
    )
    monkeypatch.setattr(sys, "argv", ["main.py", "--source", str(root), "--email", "email_004", "--verbose"])

    assert cli() == 0
    output = capsys.readouterr().out
    assert '"category": "BL_COMPARISON"' in output
    assert '"final_status": "OK"' in output
    assert '"fields_extracted"' in output


def test_cli_open_attachments_requires_email(monkeypatch, capsys) -> None:
    monkeypatch.setattr(sys, "argv", ["main.py", "--source", "ignored", "--open-attachments"])

    assert cli() == 2
    assert "requires --email" in capsys.readouterr().err


def test_cli_explain_requires_email(monkeypatch, capsys) -> None:
    monkeypatch.setattr(sys, "argv", ["main.py", "--source", "ignored", "--explain"])

    assert cli() == 2
    assert "requires --email" in capsys.readouterr().err


def test_cli_email_mode_opens_attachments_with_mocked_windows_startfile(tmp_path, monkeypatch, capsys) -> None:
    root = write_bundle(
        tmp_path / "bundle",
        {
            "email_502": {
                "subject": "Please compare SI and BL",
                "attachments": ["email_502_SI.txt", "email_502_BL.txt"],
            }
        },
        {"email_502_SI.txt": SI_TEXT, "email_502_BL.txt": BL_TEXT},
    )
    opened: list[str] = []
    monkeypatch.setattr(attachment_opener.os, "startfile", opened.append, raising=False)
    monkeypatch.setattr(
        sys,
        "argv",
        ["main.py", "--source", str(root), "--email", "email_502", "--open-attachments"],
    )

    assert cli() == 0
    assert opened == [
        str((root / "attachments" / "email_502_SI.txt").resolve()),
        str((root / "attachments" / "email_502_BL.txt").resolve()),
    ]
    assert "Attachment:" in capsys.readouterr().out


def test_cli_explain_renders_the_human_readable_decision(tmp_path, monkeypatch, capsys) -> None:
    root = write_bundle(
        tmp_path / "bundle",
        {
            "email_004": {
                "subject": "Please compare SI and BL",
                "attachments": ["shipment_si.txt", "shipment_bl.txt"],
            }
        },
        {"shipment_si.txt": SI_TEXT, "shipment_bl.txt": BL_TEXT},
    )
    monkeypatch.setattr(sys, "argv", ["main.py", "--source", str(root), "--email", "email_004", "--explain"])

    assert cli() == 0
    output = capsys.readouterr().out
    assert "EMAIL: email_004" in output
    assert "CLASSIFICATION" in output
    assert "FIELD COMPARISON" in output
    assert "FINAL DECISION" in output


def test_cli_email_mode_writes_one_email_audit_report(tmp_path, monkeypatch, capsys) -> None:
    root = write_bundle(
        tmp_path / "bundle",
        {"email_004": {"subject": "Please compare SI and BL", "attachments": ["shipment_si.txt", "shipment_bl.txt"]}},
        {"shipment_si.txt": SI_TEXT, "shipment_bl.txt": BL_TEXT},
    )
    report_path = tmp_path / "email_004.pdf"
    monkeypatch.setattr(
        sys,
        "argv",
        ["main.py", "--source", str(root), "--email", "email_004", "--explain", "--report", str(report_path)],
    )

    assert cli() == 0
    assert report_path.is_file()
    assert "Wrote decision audit report for 1 emails" in capsys.readouterr().out


def test_cli_problem_only_requires_report(monkeypatch, capsys) -> None:
    monkeypatch.setattr(sys, "argv", ["main.py", "--source", "ignored", "--report-only-problems"])

    assert cli() == 2
    assert "requires --report" in capsys.readouterr().err
