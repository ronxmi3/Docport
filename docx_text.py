"""DOCX-to-text conversion for the shared SDOC attachment pipeline.

This module only exposes document text.  It deliberately does not identify
shipping documents or interpret fields; DOCX content follows the same shared
document detection, extraction, normalisation, and comparison path as TXT,
PDF, and XLSX attachments.
"""

from __future__ import annotations

from io import BytesIO
import re

from docx import Document
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from docx.table import Table
from docx.text.paragraph import Paragraph


class DocxTextExtractionError(ValueError):
    """Raised when a Word document cannot provide usable content safely."""


def extract_docx_text(document_bytes: bytes) -> str:
    """Extract paragraphs and table rows in document order.

    Tables are emitted as tab-delimited rows so a common ``label<TAB>value``
    layout remains understandable by the normal text field extractor.  Empty
    paragraphs/cells are skipped without fabricating replacement values.
    """

    if not document_bytes:
        raise DocxTextExtractionError("Word document is empty")
    try:
        document = Document(BytesIO(document_bytes))
    except Exception as exc:
        raise DocxTextExtractionError(f"Word document cannot be read: {exc}") from exc

    try:
        lines: list[str] = []
        for block in _iter_document_blocks(document):
            if isinstance(block, Paragraph):
                text = _clean_text(block.text)
                if text:
                    lines.append(text)
            else:
                lines.extend(_table_rows(block))
    except Exception as exc:
        raise DocxTextExtractionError(f"Word document content cannot be read: {exc}") from exc

    text = "\n".join(lines).strip()
    if not text:
        raise DocxTextExtractionError("Word document has no usable paragraph or table text")
    return text


def _iter_document_blocks(document):  # type: ignore[no-untyped-def]
    """Yield top-level paragraph/table blocks in the XML body order."""

    for child in document.element.body.iterchildren():
        if isinstance(child, CT_P):
            yield Paragraph(child, document)
        elif isinstance(child, CT_Tbl):
            yield Table(child, document)


def _table_rows(table: Table) -> list[str]:
    """Render each non-empty table row, avoiding duplicate merged cells."""

    rendered: list[str] = []
    for row in table.rows:
        seen_cells: set[int] = set()
        cells: list[str] = []
        for cell in row.cells:
            # openpyxl/docx repeat a merged cell through each covered column;
            # emitting it once keeps label/value rows meaningful.
            cell_identity = id(cell._tc)
            if cell_identity in seen_cells:
                continue
            seen_cells.add(cell_identity)
            text = _clean_text(cell.text)
            if text:
                cells.append(text)
        if cells:
            rendered.append("\t".join(cells))
    return rendered


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()
