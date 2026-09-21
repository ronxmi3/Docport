"""Deterministic, explainable SDOC email classification."""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Iterable

from models import Classification, EmailRecord


# Phrases are deliberately broad enough for ordinary business email while the
# final category is still decided by combinations of independent signals.
_SI_TERMS = (
    "shipping instruction",
    "shipping instructions",
    "shipper instruction",
    "shipper s instruction",
    "si",
)
_BL_TERMS = (
    "bill of lading",
    "ocean bill",
    "draft bl",
    "draft bill",
    "bl",
    "bol",
)
_COMPARISON_TERMS = (
    "compare",
    "comparison",
    "verify",
    "verification",
    "check",
    "review",
    "cross check",
    "match",
    "mismatch",
    "discrepancy",
    "difference",
    "validate",
)
_COMPARISON_PHRASES = (
    "si vs bl",
    "si versus bl",
    "shipping instruction against",
    "bill of lading against",
    "document comparison",
    "compare documents",
)
_SI_REQUEST_TERMS = (
    "new si",
    "new shipping instruction",
    "create si",
    "prepare si",
    "submit si",
    "issue si",
    "amend si",
    "update si",
    "shipping instruction request",
    "request shipping instruction",
)
_REQUEST_TERMS = (
    "please",
    "request",
    "need",
    "provide",
    "prepare",
    "create",
    "submit",
    "issue",
    "amend",
)
_INVOICE_TERMS = (
    "invoice",
    "commercial invoice",
    "proforma",
    "billing",
    "payment",
    "remittance",
    "credit note",
    "debit note",
    "freight charge",
)
_SPAM_STRONG_TERMS = (
    "lottery",
    "you have won",
    "cryptocurrency investment",
    "viagra",
    "inheritance fund",
)
_SPAM_SUPPORTING_TERMS = (
    "unsubscribe",
    "click here to claim",
    "limited time offer",
    "act now",
    "earn money fast",
    "winner",
    "free gift",
)


def classify_email(email: EmailRecord) -> Classification:
    """Assign exactly one official SDOC category using stable rules.

    Subject, body, filenames, attachment metadata, and short text headings are
    considered. Document content is capped so classification remains fast even
    for large attachments.
    """

    subject_body = _fold(" ".join((email.subject or "", email.body or "", email.sender or "")))
    attachment_text = _attachment_signals(email)
    combined = f"{subject_body} {attachment_text}".strip()

    has_si = _has_term(combined, _SI_TERMS)
    has_bl = _has_term(combined, _BL_TERMS)
    comparison_hits = _matching_terms(combined, _COMPARISON_TERMS)
    phrase_hits = _matching_terms(combined, _COMPARISON_PHRASES)

    # A direct phrase is decisive. Otherwise require evidence for both document
    # types plus either a comparison action or a plausible two-document bundle.
    if phrase_hits or (has_si and has_bl and (comparison_hits or len(email.attachments) >= 2)):
        reasons = [*phrase_hits]
        if has_si:
            reasons.append("SI signal")
        if has_bl:
            reasons.append("BL signal")
        if comparison_hits:
            reasons.append(f"action: {comparison_hits[0]}")
        return Classification("BL_COMPARISON", tuple(reasons))

    strong_spam = _matching_terms(combined, _SPAM_STRONG_TERMS)
    supporting_spam = _matching_terms(combined, _SPAM_SUPPORTING_TERMS)
    if strong_spam or len(supporting_spam) >= 2:
        return Classification("SPAM", tuple([*strong_spam, *supporting_spam]))

    si_request_hits = _matching_terms(combined, _SI_REQUEST_TERMS)
    if si_request_hits or (has_si and _has_term(combined, _REQUEST_TERMS)):
        return Classification("SI_REQUEST", tuple(si_request_hits or ("SI request language",)))

    invoice_hits = _matching_terms(combined, _INVOICE_TERMS)
    if invoice_hits:
        return Classification("INVOICE_QUERY", tuple(invoice_hits))

    return Classification("GENERAL", ())


def normalize_classification_text(value: str) -> str:
    """Fold case, punctuation, and repeated whitespace for rule matching."""

    return _fold(value)


def _attachment_signals(email: EmailRecord) -> str:
    parts: list[str] = []
    for attachment in email.attachments:
        parts.append(attachment.filename)
        # Metadata may contain the full inline document body. Only use compact
        # type hints here; attachment text itself is deliberately capped below.
        for key in ("document_type", "type", "kind", "content_type", "mime_type"):
            value = attachment.metadata.get(key)
            if isinstance(value, (str, int)):
                parts.append(str(value))
        # A heading carries more signal than a filename but avoids scanning the
        # entire attachment again at classification time.
        parts.append(attachment.content[:500])
    return _fold(" ".join(parts))


def _fold(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", value.casefold())).strip()


def _has_term(text: str, terms: Iterable[str]) -> bool:
    return any(_term_pattern(term).search(text) for term in terms)


def _matching_terms(text: str, terms: Iterable[str]) -> list[str]:
    return [term for term in terms if _term_pattern(term).search(text)]


@lru_cache(maxsize=None)
def _term_pattern(term: str) -> re.Pattern[str]:
    # Terms are static module constants, so this remains insignificant compared
    # with attachment I/O and keeps token boundaries explicit.
    return re.compile(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])")
