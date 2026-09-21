"""Plain-text field extraction for Shipping Instructions and Bills of Lading.

This module only looks for explicit form labels and values. It deliberately
does not use OCR, an LLM, or heuristic entity recognition in this first build.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from models import Extraction, REQUIRED_FIELDS


# Each pattern is a label, not a value pattern. Longer aliases are selected
# first when two aliases overlap (for example "notify party" and "notify").
LABEL_PATTERNS: dict[str, tuple[str, ...]] = {
    "shipper": (
        r"shipper\s*\(\s*principal\s+or\s+seller\s*\)",
        r"shipper\s*(?:name\s*(?:and|&)\s*address)?",
        r"shipper(?:\s*(?:name|details|address))?",
        r"shipper\s*/\s*exporter",
        r"exporter",
        r"sender",
    ),
    "consignee": (
        r"consignee\s*\(\s*non[-\s]?negotiable\s*\)",
        r"consignee\s*(?:name\s*(?:and|&)\s*address)?",
        r"consignee(?:\s*(?:name|details|address))?",
        r"consigned\s+to",
        r"to\s+the\s+order\s+of",
        r"receiver",
    ),
    "notify_party": (
        r"notify\s+party\s*/\s*intermediate\s+consignee",
        r"notify\s+party\s*(?:name\s*(?:and|&)\s*address)?",
        r"notify\s+party(?:\s*(?:name|details|address))?",
        r"party\s+to\s+notify",
        r"notify(?:\s+address)?",
    ),
    "port_of_loading": (
        r"port\s+of\s+loading\s*\(\s*pol\s*\)",
        r"port\s+of\s+loading",
        r"load(?:ing)?\s+port",
        r"port\s+of\s+load",
        r"place\s+of\s+loading",
        r"port\s+load",
        r"p\.?\s*o\.?\s*l\.?",
        r"pol",
    ),
    "port_of_discharge": (
        r"port\s+of\s+discharge\s*\(\s*pod\s*\)",
        r"port\s+of\s+discharge",
        r"port\s+of\s+unloading",
        r"discharge\s+port",
        r"unloading\s+port",
        r"place\s+of\s+discharge",
        r"p\.?\s*o\.?\s*d\.?",
        r"pod",
    ),
    "container_count": (
        r"(?:no\.?|number)\s*of\s*containers?\s+or\s+packages?",
        r"total\s+(?:no\.?|number)?\s*of\s*containers?",
        r"number\s+of\s+containers?",
        r"(?:no\.?|number)\s*of\s*containers?",
        r"container\s+count",
        r"total\s+containers?",
        r"containers?",
    ),
    "gross_weight_kg": (
        # Some supplied forms place a translated token immediately after
        # "Gross Weight" (for example ``Gross Weight毛重(KGS)``). Keep that
        # token inside the label so the value still begins at the colon.
        r"gross\s+weight[^\s:()]*\s*\(\s*kg(?:s)?\s*\)",
        r"gross\s+(?:weight|wt\.?)\s*\([^)]*\)",
        r"gross\s+weight\s*(?:\(?\s*kg(?:s)?\s*\)?)?",
        r"total\s+gross\s+weight",
        r"gross\s+(?:weight|wt\.?)",
        r"g\.?\s*w\.?",
    ),
}

_DOCUMENT_TITLES = {
    "si": re.compile(
        r"\b(?:shipping\s+instruction|shipper'?s\s+instruction|bill\s+of\s+lading\s+instruction|bl\s+instruction|b\s*/\s*l\s+instruction|\bsi\b)\b",
        re.I,
    ),
    "bl": re.compile(r"\b(?:bill\s+of\s+lading|ocean\s+bill|\bb\s*/\s*l\b|\bbol\b)\b", re.I),
}


@dataclass(frozen=True)
class _LabelMatch:
    field: str
    start: int
    end: int


def extract_fields(text: str) -> dict[str, str | None]:
    """Extract the seven requested raw values from a plain-text document.

    Supports common `LABEL: value`, label-only/multiline, and simple tabular
    forms. Missing values are returned as ``None``; malformed documents never
    cause a comparison email to crash the entire inbox run.
    """

    fields: dict[str, str | None] = {field: None for field in REQUIRED_FIELDS}
    if not text:
        return fields

    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    for index, line in enumerate(lines):
        matches = _find_label_matches(line)
        if not matches:
            continue

        for position, label_match in enumerate(matches):
            field = label_match.field
            if fields[field] is not None:
                continue

            next_start = matches[position + 1].start if position + 1 < len(matches) else len(line)
            trailing = line[label_match.end:next_start]
            inline_value = _extract_inline_value(trailing)
            if inline_value:
                fields[field] = inline_value
                continue

            # A label-only form field commonly puts a party/address or a value
            # on the following line(s). Do not scan arbitrary prose beyond the
            # first form block.
            if not trailing.strip(" \t:=-|"):
                multiline = _collect_multiline_value(lines, index + 1)
                if multiline:
                    fields[field] = multiline

    return fields


def extract_document(text: str, document_type: str | None = None) -> Extraction:
    """Return an extraction object used by the pipeline's audit output."""

    return Extraction(
        fields=extract_fields(text),
        document_type=document_type or detect_document_type(text),
    )


def detect_document_type(text: str, filename: str = "") -> str | None:
    """Recognise SI/BL documents from explicit titles or filenames only."""

    evidence = f"{filename}\n{text[:1500]}"
    si_found = bool(_DOCUMENT_TITLES["si"].search(evidence))
    bl_found = bool(_DOCUMENT_TITLES["bl"].search(evidence))
    # An instruction-style title can legitimately contain "Bill of Lading";
    # it identifies the SI that feeds the BL, not a draft BL itself.
    if re.search(r"\b(?:bill\s+of\s+lading|bl|b\s*/\s*l)\s+instruction\b", evidence, re.I):
        return "si"
    if si_found and not bl_found:
        return "si"
    if bl_found and not si_found:
        return "bl"
    return None


def _find_label_matches(line: str) -> list[_LabelMatch]:
    candidates: list[_LabelMatch] = []
    for field, patterns in LABEL_PATTERNS.items():
        for pattern in patterns:
            for match in re.finditer(rf"(?<!\w)(?:{pattern})(?!\w)", line, re.I):
                if not _is_form_label_position(line, match.start()):
                    continue
                candidates.append(_LabelMatch(field, match.start(), match.end()))

    # Preserve left-to-right field order and discard shorter overlapping aliases.
    candidates.sort(key=lambda item: (item.start, -(item.end - item.start)))
    selected: list[_LabelMatch] = []
    for candidate in candidates:
        if selected and candidate.start < selected[-1].end:
            continue
        selected.append(candidate)
    return selected


def _is_form_label_position(line: str, start: int) -> bool:
    """Reject field words embedded in an already-extracted value/prose."""

    if start == 0 or not line[:start].strip():
        return True
    prefix = line[:start]
    # A second field on one line needs an explicit visual/table separator. This
    # keeps "Notify Party: Same as consignee" from treating consignee as a new
    # label and truncating its meaningful value.
    if re.search(r"(?:[:|/]|\t| {2,})$", prefix):
        return True
    return bool(re.fullmatch(r"\s*\d+[.)]\s*", prefix))


def _extract_inline_value(trailing: str) -> str | None:
    """Accept values only in a form-like column/delimiter position."""

    if not trailing:
        return None
    # `:`, `-`, `=`, `|`, tabs, or a visually aligned two-space column are
    # deliberate field separators. A lone prose space is not enough.
    has_separator = bool(re.match(r"\s*(?::|=|\||-|\t| {2,})", trailing))
    if not has_separator:
        return None
    value = re.sub(r"^\s*(?::|=|\||-)?\s*", "", trailing).strip(" \t|;")
    return _clean_value(value)


def _collect_multiline_value(lines: list[str], start_index: int) -> str | None:
    values: list[str] = []
    for line in lines[start_index : start_index + 6]:
        stripped = line.strip()
        if not stripped:
            if values:
                break
            continue
        if _find_label_matches(line):
            break
        if re.fullmatch(r"[-_=]{3,}", stripped):
            if values:
                break
            continue
        values.append(stripped)
    return _clean_value(" ".join(values))


def _clean_value(value: str) -> str | None:
    cleaned = re.sub(r"\s+", " ", value).strip()
    return cleaned or None
