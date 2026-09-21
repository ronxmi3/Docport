"""Exact, deterministic comparison of normalized SI and BL fields."""

from __future__ import annotations

from typing import Mapping

from models import Comparison, FieldComparison, REQUIRED_FIELDS


def compare_documents(
    si_fields: Mapping[str, str | None], bl_fields: Mapping[str, str | None]
) -> Comparison:
    """Compare an SI (the reference) against a draft BL field by field.

    Missing values are intentionally not treated as matches. This makes an
    incomplete document visible to an operator instead of silently passing it.
    """

    results: dict[str, FieldComparison] = {}
    for field in REQUIRED_FIELDS:
        si_value = si_fields.get(field)
        bl_value = bl_fields.get(field)
        if si_value is None and bl_value is None:
            status = "missing_in_both"
        elif si_value is None:
            status = "missing_in_si"
        elif bl_value is None:
            status = "missing_in_bl"
        elif si_value == bl_value:
            status = "match"
        else:
            status = "mismatch"
        results[field] = FieldComparison(field, si_value, bl_value, status)

    statuses = {result.status for result in results.values()}
    if statuses == {"match"}:
        overall_status = "match"
    elif any(status.startswith("missing_") for status in statuses):
        overall_status = "incomplete"
    else:
        overall_status = "mismatch"
    return Comparison(fields=results, status=overall_status)
