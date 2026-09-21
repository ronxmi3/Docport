from comparator import compare_documents
from models import REQUIRED_FIELDS
from normalizer import normalize_fields


def _reference_fields() -> dict[str, str | None]:
    return normalize_fields(
        {
            "shipper": "ACME Export Ltd.",
            "consignee": "Beta Imports Inc.",
            "notify_party": "Beta Imports Inc.",
            "port_of_loading": "Shanghai (CNSHA)",
            "port_of_discharge": "Los Angeles (USLAX)",
            "container_count": "2 x 40HC + 1 x 20GP",
            "gross_weight_kg": "12.5 MT",
        }
    )


def test_all_normalized_fields_match() -> None:
    si = _reference_fields()
    bl = normalize_fields(
        {
            "shipper": "acme export limited",
            "consignee": "BETA IMPORTS INCORPORATED",
            "notify_party": "beta imports incorporated",
            "port_of_loading": "Shanghai, China",
            "port_of_discharge": "Los Angeles, USA",
            "container_count": "3 containers",
            "gross_weight_kg": "12,500 KGS",
        }
    )

    comparison = compare_documents(si, bl)
    assert comparison.is_match is True
    assert comparison.status == "match"
    assert comparison.mismatched_fields == []


def test_comparison_reports_si_and_bl_values_in_canonical_order() -> None:
    si = _reference_fields()
    bl = dict(si)
    bl["container_count"] = "4"
    bl["gross_weight_kg"] = None

    comparison = compare_documents(si, bl)
    assert comparison.is_match is False
    assert comparison.status == "incomplete"
    assert comparison.mismatched_fields == ["container_count", "gross_weight_kg"]
    assert comparison.fields["container_count"].si_value == "3"
    assert comparison.fields["container_count"].bl_value == "4"
    assert comparison.fields["gross_weight_kg"].status == "missing_in_bl"
    assert tuple(comparison.fields) == REQUIRED_FIELDS


def test_comparison_reports_exact_multiple_canonical_defect_names() -> None:
    si = _reference_fields()
    bl = dict(si)
    bl["shipper"] = "other exporter"
    bl["port_of_discharge"] = "rotterdam"
    bl["container_count"] = "4"

    comparison = compare_documents(si, bl)

    assert comparison.status == "mismatch"
    assert comparison.mismatched_fields == [
        "shipper",
        "port_of_discharge",
        "container_count",
    ]
