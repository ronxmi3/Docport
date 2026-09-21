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


@pytest.mark.parametrize(
    "subject",
    ("TO CONFIRM DOCS", "Draft BL", "Please amend BL before release"),
)
def test_attachmentless_bl_subject_context_without_current_request_is_not_a_comparison(subject: str) -> None:
    decision = classify_email(EmailRecord(email_id="email-1", subject=subject, body="Please advise."))

    assert decision.label != "BL_COMPARISON"


@pytest.mark.parametrize(
    ("subject", "body"),
    (
        ("TO CONFIRM DOCS", "Please compare the current shipping instruction against the draft BL."),
        ("Draft BL", "Could you review the draft BL against the SI before release?"),
        ("Please amend BL before release", "Please verify the bill of lading and shipping instruction match."),
    ),
)
def test_attachmentless_bl_requires_a_current_body_comparison_request(subject: str, body: str) -> None:
    decision = classify_email(EmailRecord(email_id="email-1", subject=subject, body=body))

    assert decision.label == "BL_COMPARISON"
    assert "current body comparison request" in decision.reasons


def test_attachmentless_quoted_thread_comparison_does_not_count_as_current_request() -> None:
    decision = classify_email(
        EmailRecord(
            email_id="email-1",
            subject="Draft BL",
            body="Thanks, received.\n\n-----Original Message-----\nPlease compare the SI against the BL.",
        )
    )

    # Existing SI-request rules still see the quoted text; this regression is
    # specifically ensuring it cannot trigger the attachmentless BL path.
    assert decision.label != "BL_COMPARISON"


def test_attachmentless_ordinary_general_email_is_not_a_bl_comparison() -> None:
    decision = classify_email(
        EmailRecord(email_id="email-1", subject="Office administration update", body="Please confirm attendance.")
    )

    assert decision.label == "GENERAL"


@pytest.mark.parametrize(
    ("subject", "body"),
    (
        ("Account verification required", "Verify your account immediately and click here to login."),
        ("You have won a lottery", "Click here to claim your prize."),
        ("Crypto opportunity", "Guaranteed returns: earn money fast with cryptocurrency investment."),
        ("90% OFF today", "Limited time offer: click here immediately."),
    ),
)
def test_classifier_detects_spam_from_multiple_independent_signals(subject: str, body: str) -> None:
    assert classify_email(EmailRecord(email_id="email-1", subject=subject, body=body)).label == "SPAM"


def test_legitimate_invoice_query_is_not_spam() -> None:
    decision = classify_email(
        EmailRecord(
            email_id="email-1",
            subject="Invoice payment query",
            body="Please clarify the freight invoice and remittance reference.",
        )
    )

    assert decision.label == "INVOICE_QUERY"
