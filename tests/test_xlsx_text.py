import pytest

from tests.xlsx_helpers import make_workbook_bytes
from xlsx_text import XlsxTextExtractionError, extract_xlsx_text


def test_extracts_non_empty_rows_from_every_worksheet_in_order() -> None:
    text = extract_xlsx_text(
        make_workbook_bytes(
            {
                "Shipping Instruction": [("SHIPPING INSTRUCTION",), ("Shipper", "Acme Export Ltd."), (None, None)],
                "Ports": [("Port of Loading", "Port Klang")],
            }
        )
    )

    assert "[Worksheet: Shipping Instruction]" in text
    assert "Shipper\tAcme Export Ltd." in text
    assert text.index("[Worksheet: Shipping Instruction]") < text.index("[Worksheet: Ports]")
    assert "Port of Loading\tPort Klang" in text


def test_empty_or_malformed_workbooks_are_safe_extraction_errors() -> None:
    empty = make_workbook_bytes({"Sheet": [(None, None)]})

    with pytest.raises(XlsxTextExtractionError, match="no usable cell values"):
        extract_xlsx_text(empty)
    with pytest.raises(XlsxTextExtractionError, match="cannot be read"):
        extract_xlsx_text(b"not an Excel workbook")
