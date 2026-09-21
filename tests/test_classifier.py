import pytest

from classifier import classify_email
from models import Attachment, EmailRecord


@pytest.mark.parametrize(
    ("subject", "body", "attachments", "expected"),
    [
        (
            "Please compare SI and BL",
            "Verify the two documents before release.",
            (Attachment("SI.txt", ""), Attachment("BL.txt", "")),
            "BL_COMPARISON",
        ),
        ("New SI request", "Please prepare a new SI.", (), "SI_REQUEST"),
        ("Invoice query", "Please clarify this payment.", (), "INVOICE_QUERY"),
        ("Holiday notice", "Our office is closed.", (), "GENERAL"),
        ("You have won a lottery", "Click here to claim.", (), "SPAM"),
    ],
)
def test_classifier_covers_all_required_categories(
    subject: str, body: str, attachments: tuple[Attachment, ...], expected: str
) -> None:
    email = EmailRecord(
        email_id="email-1", subject=subject, body=body, attachments=attachments
    )

    assert classify_email(email).label == expected
