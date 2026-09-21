import pytest

from document_handler import assess_attachment, select_documents
from models import Attachment
from tests.helpers import BL_TEXT, SI_TEXT


def test_content_title_beats_a_misleading_filename() -> None:
    selection = select_documents(
        (
            Attachment("looks_like_bl.txt", SI_TEXT),
            Attachment("looks_like_si.txt", BL_TEXT),
        )
    )

    assert selection.review_reason is None
    assert selection.si_attachment is not None
    assert selection.bl_attachment is not None
    assert selection.si_attachment.filename == "looks_like_bl.txt"
    assert selection.bl_attachment.filename == "looks_like_si.txt"


def test_pdf_without_embedded_text_is_unreadable() -> None:
    selection = select_documents(
        (
            Attachment(
                "shipping_instruction.pdf",
                "",
                metadata={"source_format": "PDF", "extraction": "unreadable", "read_error": "no text"},
            ),
            Attachment(
                "draft_bill_of_lading.pdf",
                "",
                metadata={"source_format": "PDF", "extraction": "unreadable", "read_error": "no text"},
            ),
        )
    )

    assert selection.review_reason == "unreadable"


def test_content_title_rejects_a_packing_list_misnamed_as_a_bl() -> None:
    selection = select_documents(
        (
            Attachment("shipment_si.txt", SI_TEXT),
            Attachment("shipment_bl.txt", "PACKING LIST\nShipper: Acme Export Ltd."),
        )
    )

    assert selection.review_reason == "wrong_doc_type"


@pytest.mark.parametrize(
    ("filename", "content", "expected"),
    (
        ("instruction.pdf", "BILL OF LADING INSTRUCTION", "SI"),
        ("instruction.pdf", "BL INSTRUCTION", "SI"),
        ("instruction.pdf", "B/L INSTRUCTION", "SI"),
        ("instruction.pdf", "BILL OF LADING", "BL"),
        ("shipment_si.pdf", "BILL OF LADING", "BL"),
        ("shipment_bl.pdf", "BILL OF LADING INSTRUCTION", "SI"),
    ),
)
def test_instruction_style_content_wins_over_generic_bl_or_filename(
    filename: str, content: str, expected: str
) -> None:
    assessment = assess_attachment(Attachment(filename, content))

    assert assessment.document_type == expected
