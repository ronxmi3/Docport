"""Generated workbook fixtures for XLSX attachment tests."""

from __future__ import annotations

from io import BytesIO
from typing import Iterable, Mapping

from openpyxl import Workbook


def make_workbook_bytes(sheets: Mapping[str, Iterable[Iterable[object | None]]]) -> bytes:
    """Create an in-memory workbook without committing binary test fixtures."""

    workbook = Workbook()
    first = True
    for title, rows in sheets.items():
        worksheet = workbook.active if first else workbook.create_sheet()
        worksheet.title = title
        for row in rows:
            worksheet.append(list(row))
        first = False
    if first:
        raise ValueError("At least one worksheet is required")
    output = BytesIO()
    workbook.save(output)
    workbook.close()
    return output.getvalue()


def text_document_rows(text: str) -> list[tuple[str, ...]]:
    """Turn a text fixture into label/value workbook rows for shared tests."""

    rows: list[tuple[str, ...]] = []
    for line in text.splitlines():
        if ":" in line:
            label, value = line.split(":", 1)
            rows.append((label, value.strip()))
        else:
            rows.append((line,))
    return rows
