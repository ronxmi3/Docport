from explanation import format_email_explanation
from models import Attachment, EmailRecord
from pipeline import process_email
from tests.helpers import BL_TEXT, SI_TEXT


def test_human_readable_explanation_uses_pipeline_evidence_and_normalized_values() -> None:
    email = EmailRecord(
        email_id="email_173",
        subject="Please verify attached draft BL",
        body="Compare the SI against the Bill of Lading.",
        attachments=(
            Attachment("email_173_SI.txt", SI_TEXT, metadata={"source_format": "TXT", "extraction": "plain text"}),
            Attachment(
                "email_173_BL.pdf",
                BL_TEXT.replace("Containers: 3 containers", "Containers: 4 containers"),
                metadata={"source_format": "PDF", "extraction": "embedded text"},
            ),
        ),
    )
    decision = process_email(email)

    explanation = format_email_explanation(email, decision)

    assert decision.status == "MISMATCH"
    assert "EMAIL: email_173" in explanation
    assert "Decision: BL_COMPARISON" in explanation
    assert "comparison wording detected" in explanation
    assert "Attachment: email_173_BL.pdf" in explanation
    assert "Detected type: BL" in explanation
    assert "Source format: PDF" in explanation
    assert "Extraction: embedded text" in explanation
    assert "✓ heading: BILL OF LADING" in explanation
    assert "FIELD COMPARISON" in explanation
    assert "container_count" in explanation
    assert "MISMATCH" in explanation
    assert "container_count differs after normalization" in explanation
    assert "SI = 3" in explanation
    assert "BL = 4" in explanation
