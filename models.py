"""Typed, dependency-free contracts shared by the SDOC pipeline.

The core remains deliberately independent from CLI, FastAPI, Docker, and any
future worker implementation. That keeps every stage straightforward to test
and lets transports evolve without changing the document rules.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


# The order is intentional: comparison output is deterministic and follows the
# order in the problem statement rather than whichever order a document used.
REQUIRED_FIELDS: tuple[str, ...] = (
    "shipper",
    "consignee",
    "notify_party",
    "port_of_loading",
    "port_of_discharge",
    "container_count",
    "gross_weight_kg",
)

# These strings are the participant README's public contract. Keep them in one
# place so classification, validation, tests, and output cannot drift apart.
EMAIL_CATEGORIES: tuple[str, ...] = (
    "BL_COMPARISON",
    "SI_REQUEST",
    "INVOICE_QUERY",
    "GENERAL",
    "SPAM",
)
COMPARISON_STATUSES: tuple[str, ...] = ("OK", "MISMATCH", "NEEDS_REVIEW")
REVIEW_REASONS: tuple[str, ...] = (
    "wrong_doc_type",
    "missing_attachment",
    "unreadable",
    "missing_value",
)

FIELD_DISPLAY_NAMES: Mapping[str, str] = {
    "shipper": "shipper",
    "consignee": "consignee",
    "notify_party": "notify party",
    "port_of_loading": "port of loading",
    "port_of_discharge": "port of discharge",
    "container_count": "container count",
    "gross_weight_kg": "gross weight in kilograms",
}


@dataclass(frozen=True)
class Attachment:
    """An attachment with processable text resolved by the loader.

    ``content`` is plain text for TXT files, embedded text from a PDF, ordered
    paragraph/table text from a DOCX, or tab-delimited cell text from an
    XLSX/XLSM workbook. ``source`` retains the original file so the CLI can
    still open it. OCR deliberately does not belong in this first version.
    """

    filename: str
    content: str
    source: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def read_error(self) -> str | None:
        """Expose loader failures without making the pipeline re-read a file."""

        value = self.metadata.get("read_error")
        return str(value) if value else None


@dataclass(frozen=True)
class EmailRecord:
    """The small email contract used by classification and processing."""

    email_id: str
    subject: str = ""
    body: str = ""
    sender: str = ""
    attachments: tuple[Attachment, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Classification:
    """A deterministic category and the evidence that selected it."""

    label: str
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class DocumentAssessment:
    """Content-first document identification evidence for one attachment."""

    attachment: Attachment
    document_type: str | None
    si_score: int
    bl_score: int
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class DocumentSelection:
    """The selected SI/BL pair, or a safe reason to request review."""

    si_attachment: Attachment | None
    bl_attachment: Attachment | None
    assessments: tuple[DocumentAssessment, ...]
    review_reason: str | None = None


@dataclass(frozen=True)
class Extraction:
    """Raw field values found in one source document.

    Values remain strings at this stage. ``normalizer.py`` converts equivalent
    spelling, container syntax, and weight units into comparable values.
    """

    fields: Mapping[str, str | None]
    document_type: str | None = None


@dataclass(frozen=True)
class FieldComparison:
    """The outcome for one canonical comparison field."""

    field: str
    si_value: str | None
    bl_value: str | None
    status: str

    @property
    def matches(self) -> bool:
        return self.status == "match"

    def to_dict(self) -> dict[str, Any]:
        return {
            "field": self.field,
            "label": FIELD_DISPLAY_NAMES[self.field],
            "si": self.si_value,
            "bl": self.bl_value,
            "status": self.status,
            "match": self.matches,
        }


@dataclass(frozen=True)
class Comparison:
    """A complete SI-versus-BL comparison."""

    fields: Mapping[str, FieldComparison]
    status: str

    @property
    def is_match(self) -> bool:
        return self.status == "match"

    @property
    def mismatched_fields(self) -> list[str]:
        return [
            field
            for field in REQUIRED_FIELDS
            if self.fields[field].status != "match"
        ]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "is_match": self.is_match,
            "mismatched_fields": self.mismatched_fields,
            "fields": {
                field: self.fields[field].to_dict() for field in REQUIRED_FIELDS
            },
        }


@dataclass(frozen=True)
class StageTimings:
    """Per-email timings in milliseconds, useful for diagnostics only."""

    classification_ms: float = 0.0
    document_handling_ms: float = 0.0
    extraction_ms: float = 0.0
    comparison_ms: float = 0.0
    total_ms: float = 0.0

    def to_dict(self) -> dict[str, float]:
        return {
            "classification": self.classification_ms,
            "document_handling": self.document_handling_ms,
            "extraction": self.extraction_ms,
            "comparison": self.comparison_ms,
            "total": self.total_ms,
        }


@dataclass(frozen=True)
class EmailDecision:
    """Canonical result for one inbox email before template rendering.

    The submission writer intentionally receives this small semantic object,
    not debug output. That protects the judged submission from timing and
    extraction implementation details.
    """

    email_id: str
    category: str
    status: str | None = None
    has_defect: bool = False
    defect_fields: tuple[str, ...] = ()
    review_reason: str | None = None
    classification_reasons: tuple[str, ...] = ()
    selection: DocumentSelection | None = None
    si_extracted: Mapping[str, str | None] | None = None
    bl_extracted: Mapping[str, str | None] | None = None
    si_normalized: Mapping[str, str | None] | None = None
    bl_normalized: Mapping[str, str | None] | None = None
    comparison: Comparison | None = None
    timings: StageTimings = field(default_factory=StageTimings)
    error: str | None = None

    def to_submission_values(self) -> dict[str, Any]:
        """Return only the values that the official submission can expose."""

        return {
            "email_id": self.email_id,
            "category": self.category,
            "status": self.status,
            "has_defect": self.has_defect,
            "defect_fields": list(self.defect_fields),
            "review_reason": self.review_reason,
        }

    def to_debug_dict(self) -> dict[str, Any]:
        """Return a complete, serialisable explanation for ``--email``."""

        assessments = []
        if self.selection:
            for assessment in self.selection.assessments:
                assessments.append(
                    {
                        "filename": assessment.attachment.filename,
                        "source": assessment.attachment.source,
                        "source_format": assessment.attachment.metadata.get("source_format"),
                        "extraction": assessment.attachment.metadata.get("extraction"),
                        "read_error": assessment.attachment.read_error,
                        "detected_type": assessment.document_type,
                        "si_score": assessment.si_score,
                        "bl_score": assessment.bl_score,
                        "evidence": list(assessment.reasons),
                    }
                )
        return {
            "email_id": self.email_id,
            "category": self.category,
            "classification_reasons": list(self.classification_reasons),
            "attachments_detected": assessments,
            "selected_documents": {
                "si": self.selection.si_attachment.filename if self.selection and self.selection.si_attachment else None,
                "bl": self.selection.bl_attachment.filename if self.selection and self.selection.bl_attachment else None,
            },
            "fields_extracted": {"si": self.si_extracted, "bl": self.bl_extracted},
            "normalized_values": {"si": self.si_normalized, "bl": self.bl_normalized},
            "final_status": self.status,
            "has_defect": self.has_defect,
            "defect_fields": list(self.defect_fields),
            "review_reason": self.review_reason,
            "timings_ms": self.timings.to_dict(),
            "error": self.error,
        }
