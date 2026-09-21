from document_handler import select_documents
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
