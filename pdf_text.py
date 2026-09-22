"""PDF text extraction with a conservative OCR fallback for image-only scans."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import re

from pypdf import PdfReader


class PdfTextExtractionError(ValueError):
    """Raised when a PDF cannot yield safe, usable text."""


@dataclass(frozen=True)
class PdfTextResult:
    """Text plus the extraction method recorded in attachment metadata."""

    text: str
    method: str


def extract_pdf_text(pdf_bytes: bytes) -> str:
    """Return PDF text while retaining the legacy string-only API."""

    return extract_pdf_text_result(pdf_bytes).text


def extract_pdf_text_result(pdf_bytes: bytes) -> PdfTextResult:
    """Use embedded text first and invoke OCR only when it is not usable."""

    embedded_text = _extract_embedded_text(pdf_bytes)
    if _has_usable_text(embedded_text):
        return PdfTextResult(embedded_text, "embedded text")

    try:
        ocr_text = _extract_ocr_text(pdf_bytes)
    except PdfTextExtractionError as exc:
        raise PdfTextExtractionError(f"PDF has no usable embedded text and OCR is unavailable: {exc}") from exc
    if not _has_usable_text(ocr_text):
        raise PdfTextExtractionError("PDF has no usable embedded text and OCR produced no usable text")
    return PdfTextResult(ocr_text, "OCR (Tesseract)")


def _extract_embedded_text(pdf_bytes: bytes) -> str:
    """Extract every PDF page's embedded text in page order."""

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

    return "\n".join(page_text).strip()


def _extract_ocr_text(pdf_bytes: bytes) -> str:
    """Render every page and keep only sufficiently confident OCR output."""

    try:
        import pypdfium2 as pdfium
        import pytesseract
    except ImportError as exc:
        raise PdfTextExtractionError("PDF OCR dependencies are not installed") from exc

    try:
        # This explicit probe turns a missing Windows Tesseract executable into
        # a normal unreadable attachment rather than a pipeline exception.
        pytesseract.get_tesseract_version()
        document = pdfium.PdfDocument(pdf_bytes)
    except Exception as exc:
        raise PdfTextExtractionError(f"PDF OCR is unavailable: {exc}") from exc

    page_text: list[str] = []
    try:
        for page_index in range(len(document)):
            page = document[page_index]
            bitmap = page.render(scale=2.5)
            image = bitmap.to_pil()
            try:
                text = pytesseract.image_to_string(image, config="--psm 6")
                confidence = _ocr_confidence(pytesseract, image)
            finally:
                image.close()
                bitmap.close()
                page.close()
            if _has_usable_text(text) and confidence >= 30:
                page_text.append(text)
    except Exception as exc:
        raise PdfTextExtractionError(f"PDF OCR failed: {exc}") from exc
    finally:
        document.close()

    return "\n".join(page_text).strip()


def _ocr_confidence(pytesseract, image) -> float:  # type: ignore[no-untyped-def]
    """Return mean word confidence; Tesseract uses -1 for non-word boxes."""

    data = pytesseract.image_to_data(image, config="--psm 6", output_type=pytesseract.Output.DICT)
    scores = [
        float(score)
        for word, score in zip(data["text"], data["conf"])
        if word.strip() and str(score).strip() not in {"", "-1"}
    ]
    return sum(scores) / len(scores) if scores else 0.0


def _has_usable_text(text: str) -> bool:
    """Avoid treating a PDF title or OCR noise as extractable document text."""

    return len(re.sub(r"[^A-Za-z0-9]+", "", text)) >= 8
