"""Human-readable rendering of evidence already produced by the pipeline."""

from __future__ import annotations

from pathlib import Path

from models import EmailDecision, EmailRecord, REQUIRED_FIELDS


def format_email_explanation(email: EmailRecord, decision: EmailDecision) -> str:
    """Render an audit-friendly email explanation without new inference.

    Every conclusion below comes from the stored classifier reasons, document
    assessments, normalized comparison fields, and final decision. This is a
    presentation layer only; it never reclassifies or re-extracts a document.
    """

    lines = [f"EMAIL: {email.email_id}", f"Subject: {email.subject}", "", "CLASSIFICATION"]
    lines.extend((f"Decision: {decision.category}", "", "Why:"))
    if decision.classification_reasons:
        lines.extend(f"✓ {_display_classification_reason(reason)}" for reason in decision.classification_reasons)
    else:
        lines.append("✓ no category-specific rule signal; default GENERAL rule applied")

    lines.extend(("", "DOCUMENT IDENTIFICATION", ""))
    assessments = decision.selection.assessments if decision.selection else ()
    if assessments:
        for index, assessment in enumerate(assessments):
            attachment = assessment.attachment
            lines.append(f"Attachment: {attachment.filename}")
            lines.append(f"Detected type: {assessment.document_type or 'UNRESOLVED'}")
            lines.append(f"Source format: {_source_format(attachment.filename, attachment.metadata.get('source_format'))}")
            lines.append(f"Extraction: {_extraction_method(attachment.filename, attachment.metadata.get('extraction'))}")
            lines.append("Evidence:")
            evidence = assessment.reasons or ("no SI/BL identification signal",)
            lines.extend(f"✓ {_display_document_evidence(reason)}" for reason in evidence)
            if index != len(assessments) - 1:
                lines.append("")
    elif email.attachments:
        for attachment in email.attachments:
            lines.append(f"Attachment: {attachment.filename}")
            lines.append("Detected type: not evaluated (not a BL comparison)")
            lines.append(f"Source format: {_source_format(attachment.filename, attachment.metadata.get('source_format'))}")
            lines.append(f"Extraction: {_extraction_method(attachment.filename, attachment.metadata.get('extraction'))}")
    else:
        lines.append("No attachments found.")

    lines.extend(("", "FIELD COMPARISON", ""))
    if decision.comparison:
        lines.extend(_comparison_table(decision))
    else:
        lines.append("No safe field comparison was performed.")

    lines.extend(("", "FINAL DECISION", "", decision.status or "Not applicable"))
    if decision.status == "MISMATCH":
        lines.extend(("", "Defect fields:"))
        lines.extend(f"- {field}" for field in decision.defect_fields)
        lines.extend(("", "Reason:"))
        for field in decision.defect_fields:
            comparison = decision.comparison.fields[field] if decision.comparison else None
            if comparison is None:
                continue
            lines.append(f"{field} differs after normalization")
            lines.append(f"SI = {_display_value(comparison.si_value)}")
            lines.append(f"BL = {_display_value(comparison.bl_value)}")
    elif decision.status == "NEEDS_REVIEW":
        lines.extend(("", "Reason:", decision.review_reason or "unreadable"))
    elif decision.status == "OK":
        lines.extend(("", "Reason:", "all seven required fields match after normalization"))

    return "\n".join(lines)


def _comparison_table(decision: EmailDecision) -> list[str]:
    """Format stored normalized values in the public canonical field order."""

    field_width = 22
    value_width = 29
    rows = [
        f"{'Field':<{field_width}} {'SI':<{value_width}} {'BL':<{value_width}} Result",
        "-" * (field_width + (value_width * 2) + 9),
    ]
    for field in REQUIRED_FIELDS:
        comparison = decision.comparison.fields[field]
        result = "MATCH" if comparison.status == "match" else comparison.status.upper()
        rows.append(
            f"{field:<{field_width}} "
            f"{_cell(comparison.si_value, value_width):<{value_width}} "
            f"{_cell(comparison.bl_value, value_width):<{value_width}} "
            f"{result}"
        )
    return rows


def _display_classification_reason(reason: str) -> str:
    """Turn stored classifier signals into concise labels without new rules."""

    if reason == "SI signal":
        return "SI detected"
    if reason == "BL signal":
        return "BL detected"
    if reason.startswith("action: "):
        return f"comparison wording detected ({reason.removeprefix('action: ')})"
    return reason


def _display_document_evidence(reason: str) -> str:
    if reason.startswith("content heading: "):
        return f"heading: {reason.removeprefix('content heading: ').upper()}"
    return reason


def _source_format(filename: str, metadata_value: object) -> str:
    if metadata_value:
        return str(metadata_value)
    suffix = Path(filename).suffix.removeprefix(".").upper()
    return suffix or "UNKNOWN"


def _extraction_method(filename: str, metadata_value: object) -> str:
    if metadata_value:
        return str(metadata_value)
    return "plain text" if Path(filename).suffix.casefold() == ".txt" else "unavailable"


def _cell(value: str | None, width: int) -> str:
    text = _display_value(value)
    return f"{text[: width - 1]}…" if len(text) > width else text


def _display_value(value: str | None) -> str:
    return "—" if value is None else " ".join(str(value).split())
