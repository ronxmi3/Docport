from extractor import extract_fields


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
