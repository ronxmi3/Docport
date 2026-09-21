import pytest

from normalizer import (
    normalize_container_count,
    normalize_fields,
    normalize_party,
    normalize_port,
    normalize_weight_kg,
)


def test_normalizes_equivalent_party_port_container_and_weight_values() -> None:
    assert normalize_party("ACME, Ltd.\n12 Harbour Road") == normalize_party(
        "acme limited 12 harbour road"
    )
    assert normalize_port("Shanghai (CNSHA)") == "shanghai"
    assert normalize_port("Los Angeles, USA (USLAX)") == "los angeles"
    assert normalize_container_count("2 x 40'HC + 1 x 20'GP") == "3"
    assert normalize_weight_kg("12,500 KG") == "12500"
    assert normalize_weight_kg("12.5 MT") == "12500"
    assert normalize_weight_kg("27,557.783 LB") == "12500"


def test_normalize_fields_resolves_notify_party_reference_and_preserves_difference() -> None:
    normalized = normalize_fields(
        {
            "shipper": "ACME CO., LTD.",
            "consignee": "Beta Imports Inc.",
            "notify_party": "Same as consignee",
            "port_of_loading": "Port Klang",
            "port_of_discharge": "Rotterdam, Netherlands",
            "container_count": "03 containers",
            "gross_weight_kg": "12500 kgs",
        }
    )

    assert normalized["notify_party"] == normalized["consignee"]
    assert normalized["container_count"] == "3"
    assert normalized["gross_weight_kg"] == "12500"
    assert normalize_port("Hamburg") != normalize_port("Rotterdam")
    assert normalize_weight_kg("12500.01 KG") != normalize_weight_kg("12500 KG")


def test_port_normalization_preserves_conflicting_names_even_with_the_same_code() -> None:
    assert normalize_port("Singapore (SGSIN)") == normalize_port("SINGAPORE")
    assert normalize_port("Port Klang (MYMYP)") == normalize_port("Port Klang")
    assert normalize_port("Singapore (SGSIN)") != normalize_port("Port Klang (Westport), Malaysia (SGSIN)")
    assert normalize_port("Port Klang, Malaysia") == normalize_port("port klang malaysia")


@pytest.mark.parametrize(
    ("field", "placeholder"),
    (
        ("port_of_loading", "TBA"),
        ("port_of_discharge", "to be confirmed"),
        ("consignee", "N/A"),
        ("notify_party", "unknown"),
        ("container_count", "NIL"),
        ("gross_weight_kg", "____MT"),
    ),
)
def test_placeholders_are_not_normalized_as_required_values(field: str, placeholder: str) -> None:
    raw = {
        "shipper": "Acme Export Ltd.",
        "consignee": "Beta Imports Inc.",
        "notify_party": "Beta Imports Inc.",
        "port_of_loading": "Shanghai",
        "port_of_discharge": "Los Angeles",
        "container_count": "3",
        "gross_weight_kg": "12500 KG",
    }
    raw[field] = placeholder

    assert normalize_fields(raw)[field] is None
