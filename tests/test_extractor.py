import pytest

from extractor import detect_document_type, extract_fields


DOCUMENT_TEXT = """SHIPPING INSTRUCTION
SHIPPER / EXPORTER:
Acme Export Ltd
12 Harbour Road
CONSIGNEE: Beta Imports, Inc.
NOTIFY PARTY: Same as consignee
Load Port: Shanghai (CNSHA)
Port of Discharge: Los Angeles, USA (USLAX)
TOTAL NO. OF CONTAINERS: 2 x 40'HC + 1 x 20'GP
G.W.: 12,500.00 KGS
"""


def test_extracts_all_required_plain_text_fields() -> None:
    fields = extract_fields(DOCUMENT_TEXT)

    assert fields == {
        "shipper": "Acme Export Ltd 12 Harbour Road",
        "consignee": "Beta Imports, Inc.",
        "notify_party": "Same as consignee",
        "port_of_loading": "Shanghai (CNSHA)",
        "port_of_discharge": "Los Angeles, USA (USLAX)",
        "container_count": "2 x 40'HC + 1 x 20'GP",
        "gross_weight_kg": "12,500.00 KGS",
    }


def test_aliases_and_missing_values_are_handled_without_guessing() -> None:
    fields = extract_fields(
        """Exporter: One Co.
Receiver: Two Co.
Notify: Three Co.
POL: Singapore
POD: Rotterdam
Container Count: 3
Gross Wt: 500 KG
No. of Packages: 1000 CTNS
"""
    )

    assert fields["shipper"] == "One Co."
    assert fields["consignee"] == "Two Co."
    assert fields["notify_party"] == "Three Co."
    assert fields["port_of_loading"] == "Singapore"
    assert fields["port_of_discharge"] == "Rotterdam"
    assert fields["container_count"] == "3"
    assert fields["gross_weight_kg"] == "500 KG"

    missing = extract_fields("No form labels are present here.")
    assert all(value is None for value in missing.values())


def test_label_aliases_map_to_the_same_canonical_fields() -> None:
    fields = extract_fields(
        """Shipper Name and Address: Acme Ltd.
Consigned To: Beta Inc.
Party to Notify: Beta Inc.
Load Port: Singapore
POD: Rotterdam
Number of Containers: 03
Total Gross Weight: 7,000 KG
"""
    )

    assert fields["shipper"] == "Acme Ltd."
    assert fields["consignee"] == "Beta Inc."
    assert fields["notify_party"] == "Beta Inc."
    assert fields["port_of_loading"] == "Singapore"
    assert fields["port_of_discharge"] == "Rotterdam"
    assert fields["container_count"] == "03"
    assert fields["gross_weight_kg"] == "7,000 KG"


def test_extracts_parenthesized_and_translated_form_label_variants() -> None:
    fields = extract_fields(
        """Shipper (Principal or Seller): Acme Ltd.
Consignee (Non-Negotiable): Beta Inc.
Notify Party/Intermediate Consignee: Gamma Inc.
Port of Loading (POL): Port Klang
Port of Discharge (POD): Rotterdam
No. of Containers or Packages: 1 x 40HC
Gross Weight毛重(KGS): 21,577 KG
"""
    )

    assert fields == {
        "shipper": "Acme Ltd.",
        "consignee": "Beta Inc.",
        "notify_party": "Gamma Inc.",
        "port_of_loading": "Port Klang",
        "port_of_discharge": "Rotterdam",
        "container_count": "1 x 40HC",
        "gross_weight_kg": "21,577 KG",
    }


def test_to_the_order_of_is_a_consignee_alias() -> None:
    fields = extract_fields("To the Order of: Beta Imports Inc.")

    assert fields["consignee"] == "Beta Imports Inc."


@pytest.mark.parametrize(
    ("text", "expected"),
    (
        ("BILL OF LADING INSTRUCTION", "si"),
        ("BL INSTRUCTION", "si"),
        ("B/L INSTRUCTION", "si"),
        ("BILL OF LADING", "bl"),
    ),
)
def test_document_type_detection_treats_instruction_titles_as_si(text: str, expected: str) -> None:
    assert detect_document_type(text) == expected
