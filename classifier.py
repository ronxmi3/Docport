"""Rule-based email classification for the five Averis inbox categories."""

from __future__ import annotations

import re
from typing import Iterable

from models import Classification, EmailRecord


_COMPARISON_PHRASES = (
    "document comparison",
    "compare shipping instruction",
    "compare the si",
    "compare si",
    "si vs bl",
    "si versus bl",
    "check the bl",
    "check bl against",
    "verify the bl",
    "verify bill of lading",
    "review bill of lading",
    "bl discrepancy",
    "bill of lading discrepancy",
)
_SI_TERMS = ("shipping instruction", "shipping instructions", "shipper's instruction")
_BL_TERMS = ("bill of lading", "ocean bill", "b/l", "b l", "bol")
_COMPARISON_ACTIONS = ("compare", "verify", "check", "review", "match", "mismatch", "discrepancy")

_NEW_SI_PHRASES = (
    "new si",
    "new shipping instruction",
    "create si",
    "prepare si",
    "submit si",
    "shipping instruction request",
    "request for shipping instruction",
    "please issue si",
)
_INVOICE_TERMS = (
    "invoice",
    "invoicing",
    "billing",
    "payment",
    "remittance",
    "credit note",
    "debit note",
)
_SPAM_TERMS = (
    "unsubscribe",
    "click here to claim",
    "limited time offer",
    "act now",
    "you have won",
    "winner",
    "earn money fast",
    "cryptocurrency investment",
    "viagra",
    "lottery",
)


def classify_email(email: EmailRecord) -> Classification:
    """Classify one email using explainable, fixed-priority business rules.

    A strong SI/BL comparison signal wins over generic words such as "invoice"
    so an actual comparison request is not discarded just because it mentions a
    commercial invoice in passing.
    """

    text = _email_text(email)
    attachment_names = " ".join(attachment.filename.casefold() for attachment in email.attachments)
    combined = f"{text}\n{attachment_names}"

    has_si = _contains_any(combined, _SI_TERMS) or bool(re.search(r"\bsi\b", combined))
    has_bl = _contains_any(combined, _BL_TERMS) or bool(
        re.search(r"\b(?:bl|b\s*/\s*l)\b", combined)
    )
    comparison_actions = _matching_terms(combined, _COMPARISON_ACTIONS)
    comparison_phrases = _matching_terms(combined, _COMPARISON_PHRASES)

    # Both documents, an explicit comparison phrase, or a document pair plus
    # a verification action is sufficient evidence for the pipeline branch.
    if comparison_phrases or (has_si and has_bl and comparison_actions) or (has_si and has_bl and len(email.attachments) >= 2):
        reasons = list(comparison_phrases)
        if has_si:
            reasons.append("SI reference")
        if has_bl:
            reasons.append("BL reference")
        if comparison_actions:
            reasons.append(f"action: {comparison_actions[0]}")
        return Classification("document_comparison", tuple(reasons))

    spam_terms = _matching_terms(combined, _SPAM_TERMS)
    # One highly specific term is enough; generic marketing language needs two
    # signals so legitimate commercial email is not over-classified as spam.
    if len(spam_terms) >= 2 or any(term in spam_terms for term in ("viagra", "lottery", "cryptocurrency investment", "you have won")):
        return Classification("spam", tuple(spam_terms))

    new_si_phrases = _matching_terms(combined, _NEW_SI_PHRASES)
    if new_si_phrases or (has_si and _contains_any(combined, ("please prepare", "please create", "please submit", "need a new"))):
        return Classification("new_si_request", tuple(new_si_phrases or ["SI request language"]))

    invoice_terms = _matching_terms(combined, _INVOICE_TERMS)
    if invoice_terms:
        return Classification("invoice_query", tuple(invoice_terms))

    return Classification("general", ())


def _email_text(email: EmailRecord) -> str:
    return "\n".join((email.subject or "", email.body or "", email.sender or "")).casefold()


def _contains_any(text: str, terms: Iterable[str]) -> bool:
    return any(term in text for term in terms)


def _matching_terms(text: str, terms: Iterable[str]) -> list[str]:
    return [term for term in terms if term in text]
