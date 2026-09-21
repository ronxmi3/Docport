"""Content-first SI/BL attachment identification and safe selection."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

from models import Attachment, DocumentAssessment, DocumentSelection


_SI_CONTENT_PATTERNS = (
    (re.compile(r"\bshipping\s+instructions?\b", re.I), "content heading: shipping instruction"),
    (re.compile(r"\bshipper'?s\s+instructions?\b", re.I), "content heading: shipper instruction"),
    # Many carrier templates label the instruction form "BL INSTRUCTION".
    # This is the instruction that feeds a BL, not a draft bill itself.
    (re.compile(r"\bbl\s+instructions?\b", re.I), "content heading: BL instruction"),
)
_BL_CONTENT_PATTERNS = (
    (re.compile(r"\bbill\s+of\s+lading\b", re.I), "content heading: bill of lading"),
    (re.compile(r"\bocean\s+bill\b", re.I), "content heading: ocean bill"),
)
# A recognizable non-SI/BL document title is stronger evidence than a filename
# such as ``*_BL.txt``. The patterns are title-anchored to avoid treating an
# incidental invoice reference inside a valid shipping document as its type.
_OTHER_DOCUMENT_TITLE_PATTERNS = (
    (re.compile(r"^\s*(?:commercial\s+|proforma\s+)?invoice\b", re.I), "content heading: invoice"),
    (re.compile(r"^\s*packing\s+list\b", re.I), "content heading: packing list"),
    (re.compile(r"^\s*certificate\s+of\s+origin\b", re.I), "content heading: certificate of origin"),
)
_SI_FILENAME = re.compile(r"(?:^|[_\-\s.])(?:si|shipping[_\-\s]?instruction)(?:$|[_\-\s.])", re.I)
_BL_FILENAME = re.compile(r"(?:^|[_\-\s.])(?:bl|bol|bill[_\-\s]?of[_\-\s]?lading)(?:$|[_\-\s.])", re.I)

# PDFs with usable embedded text and XLSX/XLSM workbooks with cell values are
# converted before they reach this stage. Other Office/image formats still need
# a future parser or OCR layer, so arbitrary binary bytes must never look
# readable here.
_UNSUPPORTED_BINARY_SUFFIXES = {
    ".doc", ".docx", ".xls", ".png", ".jpg", ".jpeg", ".tif", ".tiff",
}


def assess_attachment(attachment: Attachment) -> DocumentAssessment:
    """Score one attachment, with text evidence stronger than its filename."""

    reasons: list[str] = []
    si_score = 0
    bl_score = 0
    name = attachment.filename
    heading = attachment.content[:2_000]
    metadata = " ".join(
        str(attachment.metadata[key])
        for key in ("document_type", "type", "kind", "content_type", "mime_type")
        if key in attachment.metadata
    )

    if attachment.read_error:
        reasons.append("unreadable attachment")
    if not _is_plain_text(attachment):
        reasons.append("non-text or malformed content")

    # Content is intentionally weighted above filenames: a mislabeled file
    # should be diagnosed from its actual document title where possible.
    for pattern, label in _SI_CONTENT_PATTERNS:
        if pattern.search(heading):
            si_score += 10
            reasons.append(label)
    for pattern, label in _BL_CONTENT_PATTERNS:
        if pattern.search(heading):
            bl_score += 10
            reasons.append(label)
    other_document = False
    for pattern, label in _OTHER_DOCUMENT_TITLE_PATTERNS:
        if pattern.search(heading):
            other_document = True
            reasons.append(label)
    if _SI_FILENAME.search(name):
        si_score += 3
        reasons.append("filename: SI")
    if _BL_FILENAME.search(name):
        bl_score += 3
        reasons.append("filename: BL")

    metadata_folded = metadata.casefold()
    if "shipping instruction" in metadata_folded or re.search(r"\bsi\b", metadata_folded):
        si_score += 2
        reasons.append("metadata: SI")
    if "bill of lading" in metadata_folded or re.search(r"\bbl\b", metadata_folded):
        bl_score += 2
        reasons.append("metadata: BL")

    document_type: str | None
    if other_document:
        # Do not let a weak filename vote turn a packing list into a BL.
        document_type = "OTHER"
    elif max(si_score, bl_score) == 0:
        document_type = None
    elif si_score == bl_score:
        document_type = None
        reasons.append("ambiguous SI/BL evidence")
    elif si_score > bl_score:
        document_type = "SI"
    else:
        document_type = "BL"

    return DocumentAssessment(
        attachment=attachment,
        document_type=document_type,
        si_score=si_score,
        bl_score=bl_score,
        reasons=tuple(reasons),
    )


def select_documents(attachments: Iterable[Attachment]) -> DocumentSelection:
    """Select one unambiguous readable SI and BL, else return a review reason."""

    attachment_list = tuple(attachments)
    assessments = tuple(assess_attachment(attachment) for attachment in attachment_list)
    if not attachment_list:
        return DocumentSelection(None, None, assessments, "missing_attachment")

    readable_assessments = [
        assessment
        for assessment in assessments
        if _is_plain_text(assessment.attachment) and not assessment.attachment.read_error
    ]
    if not readable_assessments:
        return DocumentSelection(None, None, assessments, "unreadable")

    si_candidates = [assessment for assessment in readable_assessments if assessment.document_type == "SI"]
    bl_candidates = [assessment for assessment in readable_assessments if assessment.document_type == "BL"]

    if not si_candidates or not bl_candidates:
        # If a document that could fill the missing role is unreadable, report
        # unreadable rather than pretending it simply was not attached.
        if any(assessment.attachment.read_error or not _is_plain_text(assessment.attachment) for assessment in assessments):
            return DocumentSelection(None, None, assessments, "unreadable")
        # One *recognisable* SI or BL with no partner is genuinely missing its
        # counterpart. A readable file that is not either document type (for
        # example an invoice) is instead a wrong-document-type case, even if
        # it is the only attachment.
        if len(attachment_list) == 1 and (si_candidates or bl_candidates):
            return DocumentSelection(None, None, assessments, "missing_attachment")
        return DocumentSelection(None, None, assessments, "wrong_doc_type")

    si = _choose_best(si_candidates, "SI")
    bl = _choose_best(bl_candidates, "BL")
    if si is None or bl is None:
        return DocumentSelection(None, None, assessments, "wrong_doc_type")
    if si.attachment is bl.attachment:
        return DocumentSelection(None, None, assessments, "wrong_doc_type")
    return DocumentSelection(si.attachment, bl.attachment, assessments)


def _choose_best(candidates: list[DocumentAssessment], document_type: str) -> DocumentAssessment | None:
    """Reject tied top candidates because choosing one would be speculative."""

    score = (lambda candidate: candidate.si_score) if document_type == "SI" else (lambda candidate: candidate.bl_score)
    ordered = sorted(candidates, key=lambda candidate: (-score(candidate), candidate.attachment.filename.casefold()))
    if len(ordered) > 1 and score(ordered[0]) == score(ordered[1]):
        return None
    return ordered[0]


def _is_plain_text(attachment: Attachment) -> bool:
    """Reject empty/binary-looking content before extracting fabricated values."""

    if Path(attachment.filename).suffix.casefold() in _UNSUPPORTED_BINARY_SUFFIXES:
        return False
    content = attachment.content
    if not content or not content.strip() or "\x00" in content:
        return False
    replacement_ratio = content.count("\ufffd") / max(len(content), 1)
    return replacement_ratio < 0.05
