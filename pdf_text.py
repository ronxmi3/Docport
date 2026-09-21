"""Embedded-text extraction for PDFs; deliberately no OCR support."""

from __future__ import annotations

from io import BytesIO

from pypdf import PdfReader


class PdfTextExtractionError(ValueError):
    """Raised when a PDF cannot yield safe, usable embedded text."""


def extract_pdf_text(pdf_bytes: bytes) -> str:
    """Extract every PDF page's embedded text in page order.

    Image-only scans produce no embedded text and are intentionally rejected.
    This module never invokes OCR or tries to infer content from pixels.
    """

    if not pdf_bytes:
        raise PdfTextExtractionError("PDF is empty")

    try:
        reader = PdfReader(BytesIO(pdf_bytes))
        if reader.is_encrypted:
            raise PdfTextExtractionError("PDF is encrypted")

        page_text: list[str] = []
        for page in reader.pages:
            extracted = page.extract_text() or ""
            if extracted.strip():
                page_text.append(extracted)
    except PdfTextExtractionError:
        raise
    except Exception as exc:
        raise PdfTextExtractionError(f"PDF cannot be read: {exc}") from exc

    text = "\n".join(page_text).strip()
    if not text:
        raise PdfTextExtractionError("PDF has no usable embedded text (possibly image-only)")
    return text
