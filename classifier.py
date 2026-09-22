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
# These subject phrases provide BL context, but cannot alone classify an email
# that has no attachments: replies often retain an older thread subject after
# the current message has changed topic.
_BL_CONVERSATION_PHRASES = (
    "to confirm docs",
    "check docs",
    "draft bl",
    "bl draft",
    "request bl draft",
    "amend bl",
    "verify bl",
    "confirm bl",
)
_CURRENT_COMPARISON_ACTIONS = (
    "compare",
    "verify",
    "check",
    "review",
    "confirm",
    "validate",
    "cross check",
)
_CURRENT_REQUEST_MARKERS = (
    "please",
    "kindly",
    "can you",
    "could you",
    "need you to",
    "request",
    "required",
)
_CURRENT_DOCUMENT_TERMS = (
    "si",
    "shipping instruction",
    "bl",
    "bill of lading",
    "draft bl",
    "draft bill",
    "document",
    "documents",
    "docs",
)
_THREAD_BOUNDARY = re.compile(
    r"^\s*(?:>{1,}|[-_ ]{3,}(?:original\s+message|forwarded\s+message)[-_ ]{3,}|from:\s|on\s+.+\s+wrote:)",
    re.IGNORECASE,
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
# Spam is scored from independent risk signals rather than a single business
# word.  In particular, legitimate freight/payment questions must not become
# spam merely because they mention an invoice or payment.
_SPAM_ACCOUNT_PHRASES = (
    "verify your account",
    "account verification",
    "confirm your account",
    "account suspended",
    "unusual account activity",
)
_SPAM_CREDENTIAL_TERMS = ("password", "credential", "login", "sign in", "security code")
_SPAM_URGENCY_TERMS = ("immediately", "act now", "urgent action", "within 24 hours", "final warning")
_SPAM_LINK_TERMS = ("click here", "click the link", "payment link", "redirect")
_SPAM_SUSPICIOUS_LINKS = ("bit ly", "tinyurl", "shorturl", "xyz", "top", "click")
_SPAM_PRIZE_TERMS = ("lottery", "you have won", "winner", "claim your prize", "free gift")
_SPAM_PROMOTION_TERMS = ("limited time offer", "exclusive offer", "unrealistic discount")
_SPAM_INVESTMENT_TERMS = ("crypto", "cryptocurrency", "guaranteed return", "guaranteed returns", "get rich quick", "earn money fast")
_SPAM_INVESTMENT_CONTEXT = ("bitcoin", "crypto", "cryptocurrency", "investment opportunity")


def classify_email(email: EmailRecord) -> Classification:
    """Assign exactly one official SDOC category using stable rules.

    Subject, body, filenames, attachment metadata, and short text headings are
    considered. Document content is capped so classification remains fast even
    for large attachments.
    """

    subject_body = _fold(" ".join((email.subject or "", email.body or "", email.sender or "")))
    attachment_text = _attachment_signals(email)
    combined = f"{subject_body} {attachment_text}".strip()

    spam_reasons = _spam_reasons(subject_body)
    if spam_reasons:
        return Classification("SPAM", tuple(spam_reasons))

    has_si = _has_term(combined, _SI_TERMS)
    has_bl = _has_term(combined, _BL_TERMS)
    comparison_hits = _matching_terms(combined, _COMPARISON_TERMS)
    phrase_hits = _matching_terms(combined, _COMPARISON_PHRASES)
    conversation_hits = _matching_terms(_fold(email.subject or ""), _BL_CONVERSATION_PHRASES)

    # Preserve attachment-bearing BL comparison behaviour.  Attachments are
    # contemporaneous evidence, unlike a reply subject that may describe an
    # earlier thread.
    if email.attachments and (
        phrase_hits or conversation_hits or (has_si and has_bl and (comparison_hits or len(email.attachments) >= 2))
    ):
        reasons = [*phrase_hits, *(f"BL conversation: {term}" for term in conversation_hits)]
        if has_si:
            reasons.append("SI signal")
        if has_bl:
            reasons.append("BL signal")
        if comparison_hits:
            reasons.append(f"action: {comparison_hits[0]}")
        return Classification("BL_COMPARISON", tuple(reasons))

    if not email.attachments:
        attachmentless_reasons = _attachmentless_bl_reasons(email, conversation_hits)
        if attachmentless_reasons:
            return Classification("BL_COMPARISON", tuple(attachmentless_reasons))

    si_request_hits, si_request_evidence = _si_request_evidence(email, combined, has_si)
    if si_request_evidence:
        return Classification("SI_REQUEST", tuple(si_request_hits or ("SI request language",)))

    invoice_hits = _matching_terms(combined, _INVOICE_TERMS)
    if invoice_hits:
        return Classification("INVOICE_QUERY", tuple(invoice_hits))

    return Classification("GENERAL", ())


def _attachmentless_bl_reasons(email: EmailRecord, subject_context: list[str]) -> list[str]:
    """Recognise a current no-attachment comparison request conservatively.

    Only the unquoted, current body can supply the request evidence.  A BL-ish
    subject is context at most; it does not decide the category by itself.
    """

    current_body = _fold(_current_message_body(email.body or ""))
    if not current_body:
        return []

    explicit_phrase = _matching_terms(current_body, _COMPARISON_PHRASES)
    action_hits = _matching_terms(current_body, _CURRENT_COMPARISON_ACTIONS)
    request_hits = _matching_terms(current_body, _CURRENT_REQUEST_MARKERS)
    current_document_hits = _matching_terms(current_body, _CURRENT_DOCUMENT_TERMS)
    current_request = bool(explicit_phrase) or bool(action_hits and request_hits)
    if not current_request:
        return []

    # A current body that names its documents is self-contained.  Otherwise a
    # BL conversation subject may provide the document context, but only after
    # the body has independently established an actual comparison request.
    if not current_document_hits and not subject_context:
        return []

    reasons = ["current body comparison request"]
    if explicit_phrase:
        reasons.append(f"current body phrase: {explicit_phrase[0]}")
    elif action_hits:
        reasons.append(f"current body action: {action_hits[0]}")
    if current_document_hits:
        reasons.append(f"current body document: {current_document_hits[0]}")
    elif subject_context:
        reasons.append(f"subject context: {subject_context[0]}")
    return reasons


def _si_request_evidence(email: EmailRecord, combined: str, has_si: bool) -> tuple[list[str], bool]:
    """Use the current body to resolve no-attachment subject/body conflicts.

    Email clients retain old subjects in long threads. For an attachmentless
    email with a substantive current body, a subject phrase like ``Submit SI``
    is context rather than a decision by itself. Empty bodies retain the
    existing subject-based fallback, and attachment-bearing records retain
    their combined document evidence.
    """

    if email.attachments:
        hits = _matching_terms(combined, _SI_REQUEST_TERMS)
        return hits, bool(hits or (has_si and _has_term(combined, _REQUEST_TERMS)))

    current_body = _fold(_current_message_body(email.body or ""))
    if not current_body:
        hits = _matching_terms(combined, _SI_REQUEST_TERMS)
        return hits, bool(hits or (has_si and _has_term(combined, _REQUEST_TERMS)))

    hits = _matching_terms(current_body, _SI_REQUEST_TERMS)
    current_has_si = _has_term(current_body, _SI_TERMS)
    return hits, bool(hits or (current_has_si and _has_term(current_body, _REQUEST_TERMS)))


def _current_message_body(body: str) -> str:
    """Discard common quoted-thread boundaries before attachmentless rules."""

    current_lines: list[str] = []
    for line in body.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if _THREAD_BOUNDARY.match(line):
            break
        current_lines.append(line)
    return "\n".join(current_lines)


def _spam_reasons(text: str) -> list[str]:
    """Return weighted, independently-supported spam evidence.

    The input is subject/body/sender only.  Attachment filenames can be
    arbitrary and should not turn a normal shipping record into spam.
    """

    account = _matching_terms(text, _SPAM_ACCOUNT_PHRASES)
    credentials = _matching_terms(text, _SPAM_CREDENTIAL_TERMS)
    urgency = _matching_terms(text, _SPAM_URGENCY_TERMS)
    links = _matching_terms(text, _SPAM_LINK_TERMS)
    suspicious_links = _matching_terms(text, _SPAM_SUSPICIOUS_LINKS)
    prizes = _matching_terms(text, _SPAM_PRIZE_TERMS)
    promotion = _matching_terms(text, _SPAM_PROMOTION_TERMS)
    investment = _matching_terms(text, _SPAM_INVESTMENT_TERMS)
    investment_context = _matching_terms(text, _SPAM_INVESTMENT_CONTEXT)
    guaranteed_percentage_return = bool(
        # ``text`` has already been punctuation-folded, so ``300% returns``
        # becomes ``300 returns`` while a written "percent" remains present.
        re.search(r"\bguaranteed\s+\d{2,4}\s*(?:percent\s+)?(?:return|returns)\b", text)
    )
    extreme_discount = bool(re.search(r"\b(?:9[0-9]|100)\s*(?:percent|off)\b", text))
    fake_invoice_redirect = (
        _has_term(text, ("invoice", "payment"))
        and bool(links or suspicious_links)
        and bool(urgency)
    )

    reasons: list[str] = []
    if account and (credentials or links or urgency):
        reasons.extend((f"account risk: {account[0]}", f"supporting risk: {(credentials or links or urgency)[0]}"))
    elif len(prizes) >= 2 or ("you have won" in prizes and "lottery" in prizes):
        reasons.extend(f"prize claim: {term}" for term in prizes)
    elif guaranteed_percentage_return and investment_context:
        reasons.extend(
            ("investment scam signal: guaranteed percentage return", f"investment context: {investment_context[0]}")
        )
    elif investment and (
        any(term in investment for term in ("guaranteed return", "guaranteed returns", "get rich quick", "earn money fast"))
        or ("crypto" in investment or "cryptocurrency" in investment) and len(investment) >= 2
    ):
        reasons.extend(f"investment scam signal: {term}" for term in investment)
    elif extreme_discount and (promotion or urgency or links):
        reasons.append("extreme discount: 90%+ off")
        reasons.append(f"supporting promotion: {(promotion or urgency or links)[0]}")
    elif fake_invoice_redirect:
        reasons.extend(("invoice/payment redirect", f"supporting urgency: {urgency[0]}"))
    elif suspicious_links and (urgency or credentials or account):
        reasons.extend((f"suspicious link: {suspicious_links[0]}", f"supporting risk: {(urgency or credentials or account)[0]}"))
    return reasons


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
