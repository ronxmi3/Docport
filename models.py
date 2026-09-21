"""Shared, dependency-free data structures for the Averis pipeline.

Keeping the transport objects here makes the rules in the other modules easy to
unit test and leaves room for a future API, queue worker, or database adapter.
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
    """A plain-text attachment resolved by the loader.

    ``source`` is retained for debugging, while ``content`` is all the core
    pipeline needs. OCR deliberately does not belong in this first version.
    """

    filename: str
    content: str
    source: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


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
