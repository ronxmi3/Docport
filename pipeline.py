"""Orchestrates classification, extraction, normalisation, and comparison."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from classifier import classify_email
from comparator import compare_documents
from extractor import detect_document_type, extract_document
from inbox_adapter import coerce_email_record
from loader import Inbox
from models import Attachment, EmailRecord, REQUIRED_FIELDS
from normalizer import normalize_fields


def process_inbox(inbox: Iterable[object]) -> dict[str, dict[str, Any]]:
    """Process every email, including categories that do not need documents."""

    attachment_reader = getattr(inbox, "read_text", None)
    results: dict[str, dict[str, Any]] = {}
    for raw_email in inbox:
        email = coerce_email_record(raw_email, attachment_reader)
        results[email.email_id] = process_email(email)
    # Stable key order makes CLI files, regression tests, and future workers
    # reproducible even if an upstream source changes iteration order.
    return {email_id: results[email_id] for email_id in sorted(results)}


def process_email(email: EmailRecord) -> dict[str, Any]:
    """Run the core pipeline for one email and collect stage timings in ms."""

    total_start = time.perf_counter_ns()

    classification_start = time.perf_counter_ns()
    classification = classify_email(email)
    classification_ms = _elapsed_ms(classification_start)

    result: dict[str, Any] = {
        "category": classification.label,
        "classification_reasons": list(classification.reasons),
        "processing_status": "skipped",
        "mismatch_found": None,
        "comparison": None,
        "differences": {},
        "timings_ms": {
            "classification": classification_ms,
            "extraction": 0.0,
            "comparison": 0.0,
            "total": 0.0,
        },
    }

    if classification.label != "document_comparison":
        result["timings_ms"]["total"] = _elapsed_ms(total_start)
        return result

    extraction_start = time.perf_counter_ns()
    si_attachment, bl_attachment, selection_error = select_si_and_bl(email.attachments)
    if selection_error:
        result.update(
            {
                "processing_status": "incomplete",
                "mismatch_found": True,
                "error": selection_error,
            }
        )
        result["timings_ms"]["extraction"] = _elapsed_ms(extraction_start)
        result["timings_ms"]["total"] = _elapsed_ms(total_start)
        return result

    assert si_attachment is not None and bl_attachment is not None
    si_extraction = extract_document(si_attachment.content, "si")
    bl_extraction = extract_document(bl_attachment.content, "bl")
    si_normalized = normalize_fields(si_extraction.fields)
    bl_normalized = normalize_fields(bl_extraction.fields)
    result["timings_ms"]["extraction"] = _elapsed_ms(extraction_start)

    comparison_start = time.perf_counter_ns()
    comparison = compare_documents(si_normalized, bl_normalized)
    result["timings_ms"]["comparison"] = _elapsed_ms(comparison_start)

    comparison_dict = comparison.to_dict()
    differences = {
        field: comparison_dict["fields"][field]
        for field in comparison.mismatched_fields
    }
    result.update(
        {
            "processing_status": "completed" if comparison.status != "incomplete" else "incomplete",
            "mismatch_found": not comparison.is_match,
            "message": "No mismatch detected" if comparison.is_match else "Mismatch or missing field detected",
            "comparison": comparison_dict,
            "differences": differences,
            # Keeping raw and normalized values provides auditability without
            # changing the deterministic comparison contract.
            "documents": {
                "si": {
                    "attachment": si_attachment.filename,
                    "extracted": dict(si_extraction.fields),
                    "normalized": si_normalized,
                },
                "bl": {
                    "attachment": bl_attachment.filename,
                    "extracted": dict(bl_extraction.fields),
                    "normalized": bl_normalized,
                },
            },
        }
    )
    result["timings_ms"]["total"] = _elapsed_ms(total_start)
    return result


def select_si_and_bl(
    attachments: Iterable[Attachment],
) -> tuple[Attachment | None, Attachment | None, str | None]:
    """Select exactly one SI and one BL from an email's resolved attachments."""

    attachments = tuple(attachments)
    si_candidates: list[tuple[int, int, Attachment]] = []
    bl_candidates: list[tuple[int, int, Attachment]] = []
    for index, attachment in enumerate(attachments):
        si_score, bl_score = _document_scores(attachment)
        if si_score:
            si_candidates.append((si_score, index, attachment))
        if bl_score:
            bl_candidates.append((bl_score, index, attachment))

    si = _highest_unique(si_candidates)
    bl = _highest_unique(bl_candidates, excluded=si)
    errors: list[str] = []
    if si is None:
        errors.append("Shipping Instruction attachment not found")
    if bl is None:
        errors.append("Bill of Lading attachment not found")
    if si is not None and not si.content:
        errors.append(f"Shipping Instruction attachment is unreadable: {si.filename}")
    if bl is not None and not bl.content:
        errors.append(f"Bill of Lading attachment is unreadable: {bl.filename}")
    return si, bl, "; ".join(errors) if errors else None


def build_submission(
    results: Mapping[str, Mapping[str, Any]], sample_template: object | None = None
) -> dict[str, Any]:
    """Return the default keyed payload or project it onto sample JSON shape.

    The challenge's sample_submission.json is the source of truth for exact
    field names. Its supplied shape is applied only at this boundary so the
    processing logic is never coupled to an evaluation-specific schema.
    """

    ordered = {email_id: dict(results[email_id]) for email_id in sorted(results)}
    if sample_template is None:
        return ordered
    return _adapt_to_sample_template(ordered, sample_template)


def load_sample_template(path: str | Path) -> object:
    """Load a sample_submission.json file without imposing its shape."""

    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_submission(payload: Mapping[str, Any], output_path: str | Path) -> Path:
    """Write deterministic, human-readable JSON and create its parent folder."""

    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return target


def run_source(
    source: str | Path,
    sample_submission_path: str | Path | None = None,
) -> dict[str, Any]:
    """Load an Inbox source, process it, and produce a submission payload."""

    inbox = Inbox(source)
    results = process_inbox(inbox)
    template = load_sample_template(sample_submission_path) if sample_submission_path else None
    return build_submission(results, template)


def _document_scores(attachment: Attachment) -> tuple[int, int]:
    """Score explicit SI/BL titles in a filename and document heading."""

    name = attachment.filename.casefold()
    heading = attachment.content[:1500].casefold()
    metadata = " ".join(str(value).casefold() for value in attachment.metadata.values())
    evidence = f"{name}\n{heading}\n{metadata}"

    si_score = 0
    bl_score = 0
    if re.search(r"\bshipping\s+instruction(?:s)?\b|\bshipper'?s\s+instruction\b", evidence):
        si_score += 5
    if re.search(r"(?:^|[_\-\s])si(?:$|[_\-\s.])", name):
        si_score += 3
    if re.search(r"\bbill\s+of\s+lading\b|\bocean\s+bill\b", evidence):
        bl_score += 5
    if re.search(r"(?:^|[_\-\s])(?:bl|bol)(?:$|[_\-\s.])", name) or "b/l" in name:
        bl_score += 3

    detected = detect_document_type(attachment.content, attachment.filename)
    if detected == "si":
        si_score += 2
    elif detected == "bl":
        bl_score += 2
    return si_score, bl_score


def _highest_unique(
    candidates: list[tuple[int, int, Attachment]], excluded: Attachment | None = None
) -> Attachment | None:
    usable = [candidate for candidate in candidates if candidate[2] is not excluded]
    if not usable:
        return None
    # Filename/content score, then original attachment order is deterministic.
    usable.sort(key=lambda candidate: (-candidate[0], candidate[1]))
    return usable[0][2]


def _adapt_to_sample_template(
    results: Mapping[str, Mapping[str, Any]], sample_template: object
) -> dict[str, Any]:
    """Handle the documented keyed-by-email sample format conservatively."""

    if not isinstance(sample_template, Mapping):
        raise ValueError("sample_submission.json must be a JSON object keyed by email_id")
    prototype = next(iter(sample_template.values()), None)
    projected: dict[str, Any] = {}
    for email_id, result in results.items():
        shape = sample_template.get(email_id, prototype)
        projected[email_id] = _project_result(result, shape)
    return projected


def _project_result(result: Mapping[str, Any], shape: object) -> Any:
    """Project known submission aliases while preserving a template's nesting."""

    if shape is None:
        return dict(result)
    if isinstance(shape, list):
        return _project_differences(result, shape)
    if not isinstance(shape, Mapping):
        return result.get("mismatch_found")

    output: dict[str, Any] = {}
    aliases: dict[str, Any] = {
        "category": result.get("category"),
        "classification": result.get("category"),
        "email_category": result.get("category"),
        "email_type": result.get("category"),
        "mismatch_found": result.get("mismatch_found"),
        "mismatch": result.get("mismatch_found"),
        "mismatch_detected": result.get("mismatch_found"),
        "has_mismatch": result.get("mismatch_found"),
        "is_match": (result.get("comparison") or {}).get("is_match"),
        "status": result.get("processing_status"),
        "processing_status": result.get("processing_status"),
        "comparison": result.get("comparison"),
        "differences": result.get("differences"),
        "discrepancies": result.get("differences"),
        "different_fields": result.get("differences"),
        "mismatch_details": result.get("differences"),
        "mismatches": result.get("differences"),
        "mismatched_fields": list(result.get("differences", {}).keys()),
        "timings_ms": result.get("timings_ms"),
        "message": result.get("message"),
    }
    for key, child_shape in shape.items():
        if key in {"differences", "discrepancies", "different_fields", "mismatch_details", "mismatches", "mismatched_fields"}:
            output[key] = _project_differences(result, child_shape)
        elif key == "comparison":
            output[key] = _project_comparison(result.get("comparison"), child_shape)
        elif key in aliases:
            output[key] = aliases[key]
        elif key in result:
            output[key] = result[key]
        elif key in REQUIRED_FIELDS:
            output[key] = (result.get("comparison") or {}).get("fields", {}).get(key)
        else:
            # Keep a template-only field explicit rather than inserting a
            # fabricated value. This makes a new official schema easy to spot.
            output[key] = None
    return output


def _project_differences(result: Mapping[str, Any], shape: object) -> Any:
    """Render differing fields as either a map or a sample-shaped list."""

    differences = result.get("differences", {})
    if not isinstance(differences, Mapping):
        differences = {}
    if isinstance(shape, list):
        if not differences:
            return []
        if not shape or not isinstance(shape[0], Mapping):
            return [dict(detail) for detail in differences.values()]
        return [
            _project_difference(field, detail, shape[0])
            for field, detail in differences.items()
        ]
    if isinstance(shape, Mapping):
        return dict(differences)
    return bool(differences)


def _project_difference(field: str, detail: object, shape: Mapping[str, Any]) -> dict[str, Any]:
    """Map common SI/BL field-detail aliases in a list-shaped sample schema."""

    source = detail if isinstance(detail, Mapping) else {}
    values = {
        "field": field,
        "field_name": field,
        "label": source.get("label"),
        "si": source.get("si"),
        "si_value": source.get("si"),
        "expected": source.get("si"),
        "bl": source.get("bl"),
        "bl_value": source.get("bl"),
        "actual": source.get("bl"),
        "status": source.get("status"),
        "match": source.get("match"),
    }
    return {key: values.get(key) for key in shape}


def _project_comparison(comparison: object, shape: object) -> Any:
    """Keep an empty template useful while respecting known nested keys."""

    if not isinstance(comparison, Mapping) or not isinstance(shape, Mapping) or not shape:
        return comparison
    values = {
        "status": comparison.get("status"),
        "is_match": comparison.get("is_match"),
        "mismatched_fields": comparison.get("mismatched_fields"),
        "fields": comparison.get("fields"),
    }
    return {key: values.get(key) for key in shape}


def _elapsed_ms(start_ns: int) -> float:
    return round((time.perf_counter_ns() - start_ns) / 1_000_000, 3)
