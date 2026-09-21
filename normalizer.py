"""Deterministic normalisation for shipping-document values.

No model calls are made here. Rules intentionally favour transparent, stable
transformations over clever guesses so a reviewer can explain every match.
"""

from __future__ import annotations

import re
import unicodedata
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Mapping

from models import REQUIRED_FIELDS


_LEGAL_WORDS = {
    "co": "company",
    "corp": "corporation",
    "inc": "incorporated",
    "ltd": "limited",
    "llc": "limited liability company",
    "plc": "public limited company",
    "pte": "private",
    "pvt": "private",
}

# Common UN/LOCODE and spelling variants can be extended without changing
# comparison logic. Unknown ports still normalize consistently as text.
_PORT_ALIASES = {
    "cns ha": "shanghai",  # protects odd spacing after punctuation cleanup
    "cnsha": "shanghai",
    "shanghai china": "shanghai",
    "uslax": "los angeles",
    "los angeles usa": "los angeles",
    "sgsin": "singapore",
    "singapore singapore": "singapore",
    "nlrtm": "rotterdam",
    "rotterdam netherlands": "rotterdam",
    "deham": "hamburg",
    "hamburg germany": "hamburg",
    "aumed": "melbourne",
    "mymyp": "port klang",
    "port kelang": "port klang",
}

_NUMBER_WORDS = {
    "zero": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
}

# A required field filled with one of these placeholders is not a value that
# can safely be compared.  Keep this check before punctuation cleanup: for
# example, ``____MT`` would otherwise become the misleading text ``mt``.
_PLACEHOLDER_PATTERN = re.compile(
    r"""^\s*(?:
        tba|tbd|n\s*/?\s*a|nil|unknown|pending|
        to\s+be\s+(?:advised|confirmed)|
        [-_]+|
        _+\s*(?:kg|kgs|kilograms?|mt|mts|metric\s*tons?)
    )\s*$""",
    re.IGNORECASE | re.VERBOSE,
)


def is_placeholder_value(value: object | None) -> bool:
    """Return whether a source value is explicitly absent or provisional."""

    if value is None:
        return True
    text = unicodedata.normalize("NFKC", str(value)).strip()
    return not text or bool(_PLACEHOLDER_PATTERN.fullmatch(text))


def normalize_text(value: str | None) -> str | None:
    """Return a case- and punctuation-insensitive text representation."""

    if is_placeholder_value(value):
        return None
    text = unicodedata.normalize("NFKD", str(value))
    text = "".join(character for character in text if not unicodedata.combining(character))
    text = text.casefold().replace("&", " and ")
    # New lines and decorative punctuation should not create a false mismatch.
    text = re.sub(r"[\W_]+", " ", text, flags=re.UNICODE)
    words = [_LEGAL_WORDS.get(word, word) for word in text.split()]
    normalised = " ".join(words).strip()
    return normalised or None


def normalize_party(value: str | None) -> str | None:
    """Normalize a company/person and address block without dropping content."""

    normalized = normalize_text(value)
    if normalized in {"same as consignee", "same as cnee"}:
        return "__same_as_consignee__"
    if normalized in {"same as shipper", "same as exporter"}:
        return "__same_as_shipper__"
    return normalized


def normalize_port(value: str | None) -> str | None:
    """Normalize port spelling while treating a UN/LOCODE as supporting data.

    A named location is retained whenever present.  This avoids a malformed
    code making two different ports equal, while still allowing code-only and
    name-plus-code renderings of the same port to match.
    """

    normalized = normalize_text(value)
    if not normalized:
        return None

    # First normalize explicit name aliases (including a code-only value).
    direct = _port_alias(normalized)
    if direct is not None:
        return direct

    tokens = normalized.split()
    known_codes = [token for token in tokens if len(token) == 5 and token in _PORT_ALIASES]
    named_location = " ".join(token for token in tokens if token not in known_codes)
    if named_location:
        # Names win over codes.  The code can corroborate a name but can never
        # erase a conflicting location name from another document.
        return _port_alias(named_location) or named_location
    if known_codes:
        return _PORT_ALIASES[known_codes[0]]
    return normalized


def _port_alias(value: str) -> str | None:
    """Resolve a whole normalized port value, never a substring within it."""

    compact = value.replace(" ", "")
    return _PORT_ALIASES.get(value) or _PORT_ALIASES.get(compact)


def _decimal_from_text(number_text: str) -> Decimal | None:
    """Parse common international thousands/decimal formats deterministically."""

    compact = number_text.strip().replace(" ", "")
    if not compact:
        return None

    if "," in compact and "." in compact:
        # The last separator is treated as the decimal separator: 12.500,25
        # versus 12,500.25.
        if compact.rfind(",") > compact.rfind("."):
            compact = compact.replace(".", "").replace(",", ".")
        else:
            compact = compact.replace(",", "")
    elif "," in compact:
        tail = compact.rsplit(",", 1)[1]
        compact = compact.replace(",", "") if len(tail) == 3 else compact.replace(",", ".")
    elif "." in compact:
        tail = compact.rsplit(".", 1)[1]
        # A single three-digit suffix is conventionally a thousands grouping
        # in document weights ("12.500 KG").
        if len(tail) == 3 and compact.count(".") == 1:
            compact = compact.replace(".", "")

    try:
        return Decimal(compact)
    except InvalidOperation:
        return None


def normalize_weight_kg(value: str | int | float | Decimal | None) -> str | None:
    """Convert a labeled gross weight to a canonical kilograms string.

    Plain unlabeled numbers are treated as kilograms because the requested
    comparison field is gross weight in kg. Unsupported units are left missing
    rather than guessed.
    """

    if is_placeholder_value(value):
        return None
    raw = str(value).strip()
    if not raw:
        return None

    number_match = re.search(r"[-+]?\d[\d\s,\.]*", raw)
    if not number_match:
        return None
    amount = _decimal_from_text(number_match.group(0))
    if amount is None or amount < 0:
        return None

    unit_text = raw.casefold()
    if re.search(r"\b(?:kg|kgs|kilogram|kilograms|kilo)\b", unit_text):
        kilograms = amount
    elif re.search(r"\b(?:mt|mts|metric\s*ton(?:ne)?s?)\b", unit_text):
        kilograms = amount * Decimal("1000")
    elif re.search(r"\b(?:lb|lbs|pound|pounds)\b", unit_text):
        kilograms = amount * Decimal("0.45359237")
    elif re.search(r"\b(?:ton|tons|tonne|tonnes)\b", unit_text):
        # "ton" without "metric" is ambiguous. Do not silently interpret it.
        return None
    else:
        kilograms = amount

    # Milligram precision is far beyond the source documents but avoids float
    # representation noise and keeps a value such as 12.5 MT readable.
    kilograms = kilograms.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
    rendered = format(kilograms, "f").rstrip("0").rstrip(".")
    return rendered or "0"


def normalize_container_count(value: str | int | None) -> str | None:
    """Return the total number of containers encoded in common SI/BL syntax."""

    if is_placeholder_value(value):
        return None
    raw = str(value).strip()
    if not raw:
        return None
    compact = raw.casefold()

    if compact in _NUMBER_WORDS:
        return str(_NUMBER_WORDS[compact])

    # "2 x 40HC + 1 x 20GP" means three containers, not 2 or 1.
    multiplicands = re.findall(
        r"\b(\d+)\s*(?:x|×)\s*(?:\d{2,3}(?:\s*['\"]?\s*(?:gp|hc|hq|dv|rf|ot|ft))?|containers?)",
        compact,
    )
    if multiplicands:
        return str(sum(int(number) for number in multiplicands))

    explicit = re.search(
        r"\b(\d+)\s*(?:containers?|cntrs?|units?)\b", compact,
    )
    if explicit:
        return str(int(explicit.group(1)))

    # A field already labelled "container count" often contains only "3".
    if re.fullmatch(r"\d+", compact):
        return str(int(compact))
    return None


def normalize_fields(raw_fields: Mapping[str, object]) -> dict[str, str | None]:
    """Normalize all seven fields and resolve explicit party references."""

    normalized: dict[str, str | None] = {
        "shipper": normalize_party(_as_optional_text(raw_fields.get("shipper"))),
        "consignee": normalize_party(_as_optional_text(raw_fields.get("consignee"))),
        "notify_party": normalize_party(_as_optional_text(raw_fields.get("notify_party"))),
        "port_of_loading": normalize_port(_as_optional_text(raw_fields.get("port_of_loading"))),
        "port_of_discharge": normalize_port(_as_optional_text(raw_fields.get("port_of_discharge"))),
        "container_count": normalize_container_count(raw_fields.get("container_count")),
        "gross_weight_kg": normalize_weight_kg(raw_fields.get("gross_weight_kg")),
    }

    # These form phrases genuinely mean the referenced party, so resolving them
    # here is safer and more transparent than a fuzzy comparison later.
    if normalized["notify_party"] == "__same_as_consignee__":
        normalized["notify_party"] = normalized["consignee"]
    elif normalized["notify_party"] == "__same_as_shipper__":
        normalized["notify_party"] = normalized["shipper"]

    # Keep the return contract stable if future callers pass a partial mapping.
    return {field: normalized.get(field) for field in REQUIRED_FIELDS}


def _as_optional_text(value: object) -> str | None:
    return None if value is None else str(value)
