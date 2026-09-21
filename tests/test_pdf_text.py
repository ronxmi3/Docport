import pytest

from pdf_text import PdfTextExtractionError, extract_pdf_text
from tests.pdf_helpers import make_blank_pdf, make_text_pdf


def test_extracts_embedded_text_from_a_pdf() -> None:
    text = extract_pdf_text(make_text_pdf(["BILL OF LADING\nShipper: Acme Export Ltd."]))

    assert "BILL OF LADING" in text
    assert "Shipper: Acme Export Ltd." in text


def test_extracts_all_pdf_pages_in_order() -> None:
    text = extract_pdf_text(make_text_pdf(["FIRST PAGE", "SECOND PAGE"]))

    assert text.index("FIRST PAGE") < text.index("SECOND PAGE")


def test_pdf_with_no_embedded_text_is_unreadable() -> None:
    with pytest.raises(PdfTextExtractionError, match="no usable embedded text"):
        extract_pdf_text(make_blank_pdf())


def test_malformed_pdf_is_unreadable() -> None:
    with pytest.raises(PdfTextExtractionError, match="cannot be read"):
        extract_pdf_text(b"this is not a PDF")
