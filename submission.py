"""Official-schema submission rendering and fail-loud validation."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from models import (
    COMPARISON_STATUSES,
    EMAIL_CATEGORIES,
    EmailDecision,
    REQUIRED_FIELDS,
    REVIEW_REASONS,
)


class SubmissionValidationError(ValueError):
    """Raised when a generated result cannot safely be submitted."""


_KEY_ALIASES: dict[str, tuple[str, ...]] = {
    "email_id": ("email_id", "id"),
    "category": ("category", "classification", "email_category", "email_type"),
    "status": ("status", "comparison_status", "result"),
    "has_defect": ("has_defect", "mismatch_found", "has_mismatch", "mismatch_detected"),
    "defect_fields": ("defect_fields", "mismatched_fields", "mismatch_fields", "defects"),
    "review_reason": ("review_reason", "review_code", "needs_review_reason"),
}


def load_submission_template(path: str | Path) -> Mapping[str, Any]:
    """Read and validate the top-level structure of sample_submission.json."""

    try:
        template = json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SubmissionValidationError(f"sample_submission.json is invalid JSON: {path}") from exc
    if not isinstance(template, Mapping) or not template:
        raise SubmissionValidationError("sample_submission.json must be a non-empty object keyed by email_id")
    if not all(isinstance(email_id, str) and isinstance(value, Mapping) for email_id, value in template.items()):
        raise SubmissionValidationError("Every sample_submission entry must be an object keyed by a string email_id")
    _ensure_supported_schema(template)
    return template


def build_submission(
    decisions: Mapping[str, EmailDecision], template: Mapping[str, Any]
) -> dict[str, Any]:
    """Render canonical decisions into the exact key structure of a template."""

    expected_ids = set(template)
    actual_ids = set(decisions)
    if actual_ids != expected_ids:
        missing = sorted(expected_ids - actual_ids)
        unknown = sorted(actual_ids - expected_ids)
        raise SubmissionValidationError(
            f"Email IDs do not match sample_submission.json; missing={missing[:5]}, unknown={unknown[:5]}"
        )

    payload: dict[str, Any] = {}
    for email_id, shape in template.items():
        payload[email_id] = _render_shape(shape, decisions[email_id].to_submission_values())
    validate_submission(payload, expected_ids)
    return payload


def write_submission(payload: Mapping[str, Any], output_path: str | Path) -> Path:
    """Write validated deterministic JSON, creating only the output parent."""

    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return target


def validate_submission(payload: Mapping[str, Any], expected_ids: Iterable[str]) -> None:
    """Validate all participant README semantic invariants before disk output."""

    expected = set(expected_ids)
    if set(payload) != expected:
        raise SubmissionValidationError("Submission email IDs are not exactly the input email IDs")

    for email_id, entry in payload.items():
        if not isinstance(entry, Mapping):
            raise SubmissionValidationError(f"{email_id}: submission entry must be an object")
        values = _extract_semantic_values(entry)
        _validate_decision(email_id, values)


def _ensure_supported_schema(template: Mapping[str, Any]) -> None:
    """Fail early if the sample schema cannot express required semantics."""

    prototype = next(iter(template.values()))
    found = _find_semantic_keys(prototype)
    required = {"category", "status", "has_defect", "defect_fields", "review_reason"}
    missing = sorted(required - found)
    if missing:
        raise SubmissionValidationError(
            "sample_submission.json cannot express the required SDOC fields: " + ", ".join(missing)
        )


def _render_shape(shape: Any, values: Mapping[str, Any]) -> Any:
    if isinstance(shape, Mapping):
        rendered: dict[str, Any] = {}
        for key, child in shape.items():
            semantic = _semantic_for_key(key)
            if semantic is not None:
                rendered[key] = deepcopy(values[semantic])
            else:
                rendered[key] = _render_shape(child, values)
        return rendered
    if isinstance(shape, list):
        # Template arrays only describe structure; output fields are populated
        # through their enclosing semantic key, otherwise preserve the shape.
        return [_render_shape(item, values) for item in shape]
    return deepcopy(shape)


def _extract_semantic_values(entry: Mapping[str, Any]) -> dict[str, Any]:
    found: dict[str, Any] = {}

    def visit(value: Any) -> None:
        if isinstance(value, Mapping):
            for key, child in value.items():
                semantic = _semantic_for_key(key)
                if semantic is not None:
                    found[semantic] = child
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(entry)
    missing = {"category", "status", "has_defect", "defect_fields", "review_reason"} - set(found)
    if missing:
        raise SubmissionValidationError("Submission entry misses required semantic fields: " + ", ".join(sorted(missing)))
    return found


def _find_semantic_keys(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, Mapping):
        for key, child in value.items():
            semantic = _semantic_for_key(key)
            if semantic is not None:
                found.add(semantic)
            found.update(_find_semantic_keys(child))
    elif isinstance(value, list):
        for child in value:
            found.update(_find_semantic_keys(child))
    return found


def _semantic_for_key(key: str) -> str | None:
    folded = key.casefold()
    for semantic, aliases in _KEY_ALIASES.items():
        if folded in aliases:
            return semantic
    return None


def _validate_decision(email_id: str, values: Mapping[str, Any]) -> None:
    category = values["category"]
    status = values["status"]
    has_defect = values["has_defect"]
    defect_fields = values["defect_fields"]
    review_reason = values["review_reason"]

    if category not in EMAIL_CATEGORIES:
        raise SubmissionValidationError(f"{email_id}: invalid category {category!r}")
    if not isinstance(has_defect, bool):
        raise SubmissionValidationError(f"{email_id}: has_defect must be a boolean")
    if not isinstance(defect_fields, list):
        raise SubmissionValidationError(f"{email_id}: defect_fields must be a list")
    if any(field not in REQUIRED_FIELDS for field in defect_fields):
        raise SubmissionValidationError(f"{email_id}: defect_fields contains an unknown canonical field")
    if len(defect_fields) != len(set(defect_fields)):
        raise SubmissionValidationError(f"{email_id}: defect_fields contains duplicates")

    if category != "BL_COMPARISON":
        if status is not None or has_defect or defect_fields or review_reason is not None:
            raise SubmissionValidationError(f"{email_id}: non-comparison output must have null status and no defects")
        return

    if status not in COMPARISON_STATUSES:
        raise SubmissionValidationError(f"{email_id}: invalid BL comparison status {status!r}")
    if status == "OK":
        if has_defect or defect_fields or review_reason is not None:
            raise SubmissionValidationError(f"{email_id}: OK must have no defects and no review reason")
    elif status == "MISMATCH":
        if not has_defect or not defect_fields or review_reason is not None:
            raise SubmissionValidationError(f"{email_id}: MISMATCH requires defects and no review reason")
    else:  # NEEDS_REVIEW
        if has_defect or defect_fields or review_reason not in REVIEW_REASONS:
            raise SubmissionValidationError(
                f"{email_id}: NEEDS_REVIEW requires a valid review reason and no defect fields"
            )
