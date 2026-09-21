"""Workbook-to-text conversion for the shared SDOC attachment pipeline.

The converter intentionally stops at extracting cell values.  It does not
interpret shipping fields itself: workbook text is passed to the same content
identification, field extraction, normalization, and comparison stages used by
TXT and embedded-text PDF attachments.
"""

from __future__ import annotations

from datetime import date, datetime, time
from io import BytesIO
from numbers import Integral, Real

from openpyxl import load_workbook


class XlsxTextExtractionError(ValueError):
    """Raised when a workbook cannot provide usable cell text safely."""


def extract_xlsx_text(workbook_bytes: bytes) -> str:
    """Return all non-empty workbook rows as deterministic tab-delimited text.

    Each worksheet is read in workbook order with ``data_only=True`` so the
    pipeline receives cached calculated values rather than formula syntax.
    Cells in the same source row remain tab-separated, which preserves common
    ``label<TAB>value`` shipping-document layouts for ``extractor.py``.
    """

    if not workbook_bytes:
        raise XlsxTextExtractionError("Excel workbook is empty")

    try:
        workbook = load_workbook(BytesIO(workbook_bytes), read_only=True, data_only=True)
    except Exception as exc:
        raise XlsxTextExtractionError(f"Excel workbook cannot be read: {exc}") from exc

    try:
        lines: list[str] = []
        for worksheet in workbook.worksheets:
            sheet_lines: list[str] = []
            for row in worksheet.iter_rows(values_only=True):
                values = [_cell_text(value) for value in row]
                populated = [value for value in values if value is not None]
                if populated:
                    # Tabs preserve the label/value relationship. Empty cells
                    # do not add fictitious data, but intentional rows remain
                    # distinct so the ordinary text extractor can inspect them.
                    sheet_lines.append("\t".join(populated))
            if sheet_lines:
                lines.append(f"[Worksheet: {worksheet.title}]")
                lines.extend(sheet_lines)
    except Exception as exc:
        raise XlsxTextExtractionError(f"Excel workbook cells cannot be read: {exc}") from exc
    finally:
        workbook.close()

    text = "\n".join(lines).strip()
    if not text:
        raise XlsxTextExtractionError("Excel workbook has no usable cell values")
    return text


def _cell_text(value: object | None) -> str | None:
    """Render stored values without changing their shipping-document meaning."""

    if value is None:
        return None
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (datetime, date, time)):
        return value.isoformat(sep=" ") if isinstance(value, datetime) else value.isoformat()
    if isinstance(value, Integral):
        return str(value)
    if isinstance(value, Real):
        return format(value, "g")
    text = str(value).strip()
    return text or None
