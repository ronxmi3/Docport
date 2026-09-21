from pathlib import Path

import attachment_opener
from attachment_opener import open_email_attachments, resolve_attachment_path
from models import Attachment, EmailRecord


def test_resolves_bundle_relative_paths_and_opens_supported_files(tmp_path, monkeypatch, capsys) -> None:
    bundle = tmp_path / "bundle"
    attachment_root = bundle / "attachments"
    attachment_root.mkdir(parents=True)
    text_path = attachment_root / "email_502_SI.txt"
    pdf_path = attachment_root / "email_502_BL.pdf"
    text_path.write_text("SHIPPING INSTRUCTION", encoding="utf-8")
    pdf_path.write_bytes(b"%PDF-demo")
    missing_path = attachment_root / "email_502_missing.jpg"

    email = EmailRecord(
        email_id="email_502",
        attachments=(
            Attachment("email_502_SI.txt", "", source="attachments/email_502_SI.txt"),
            Attachment("email_502_BL.pdf", "", source="email_502_BL.pdf"),
            Attachment("email_502_missing.jpg", "", source="attachments/email_502_missing.jpg"),
        ),
    )
    opened: list[str] = []
    monkeypatch.setattr(attachment_opener.os, "startfile", opened.append, raising=False)

    assert resolve_attachment_path(bundle, email.attachments[0]) == text_path.resolve()
    assert resolve_attachment_path(bundle, email.attachments[1]) == pdf_path.resolve()

    open_email_attachments(bundle, email)

    assert opened == [str(text_path.resolve()), str(pdf_path.resolve())]
    output = capsys.readouterr().out
    assert f"Attachment: {text_path.resolve()}" in output
    assert f"Attachment: {pdf_path.resolve()}" in output
    assert f"warning: attachment does not exist: {missing_path.resolve()}" in output


def test_attachment_opener_refuses_to_escape_attachments_directory(tmp_path) -> None:
    bundle = tmp_path / "bundle"
    (bundle / "attachments").mkdir(parents=True)
    attachment = Attachment("outside.txt", "", source="../outside.txt")

    try:
        resolve_attachment_path(bundle, attachment)
    except ValueError as exc:
        assert "escapes" in str(exc)
    else:
        raise AssertionError("An attachment path outside the bundle must be rejected")
