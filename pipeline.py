"""End-to-end, per-email-safe SDOC processing orchestration."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import logging
import time
from typing import Iterable, Mapping

from classifier import classify_email
from comparator import compare_documents
from document_handler import select_documents
from extractor import extract_fields
from models import (
    EMAIL_CATEGORIES,
    Comparison,
    DocumentSelection,
    EmailDecision,
    EmailRecord,
    REQUIRED_FIELDS,
    StageTimings,
)
from normalizer import normalize_fields


LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class PipelineReport:
    """Deterministic results and aggregate performance information."""

    decisions: Mapping[str, EmailDecision]
    elapsed_seconds: float

    @property
    def processed_count(self) -> int:
        return len(self.decisions)

    @property
    def comparison_count(self) -> int:
        return sum(decision.category == "BL_COMPARISON" for decision in self.decisions.values())

    @property
    def needs_review_count(self) -> int:
        return sum(decision.status == "NEEDS_REVIEW" for decision in self.decisions.values())

    @property
    def throughput(self) -> float:
        return self.processed_count / self.elapsed_seconds if self.elapsed_seconds > 0 else 0.0


def process_records(
    emails: Iterable[EmailRecord], workers: int = 1, logger: logging.Logger | None = None
) -> PipelineReport:
    """Process independent emails concurrently while preserving sorted output.

    Attachments are resolved once by the dataset loader before this function is
    invoked. Worker tasks only inspect immutable records, so there is no shared
    mutation or repeated disk/network I/O.
    """

    if workers < 1:
        raise ValueError("workers must be at least 1")
    ordered_emails = tuple(sorted(emails, key=lambda email: email.email_id))
    if len({email.email_id for email in ordered_emails}) != len(ordered_emails):
        raise ValueError("Duplicate email_id values cannot be processed safely")

    start = time.perf_counter()
    selected_logger = logger or LOGGER
    if workers == 1:
        decisions = [process_email(email, selected_logger) for email in ordered_emails]
    else:
        # executor.map preserves input order, and final key sorting makes output
        # deterministic even if task scheduling changes between runs.
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="sdoc") as executor:
            decisions = list(executor.map(lambda email: process_email(email, selected_logger), ordered_emails))

    result_map = {decision.email_id: decision for decision in decisions}
    stable_map = {email_id: result_map[email_id] for email_id in sorted(result_map)}
    return PipelineReport(decisions=stable_map, elapsed_seconds=time.perf_counter() - start)


def process_email(email: EmailRecord, logger: logging.Logger | None = None) -> EmailDecision:
    """Process one email without allowing a failure to stop the entire run."""

    selected_logger = logger or LOGGER
    total_start = time.perf_counter_ns()
    classification_ms = document_ms = extraction_ms = comparison_ms = 0.0
    classification = None
    selection = None
    si_raw = bl_raw = si_normalized = bl_normalized = None
    comparison = None

    try:
        classification_start = time.perf_counter_ns()
        classification = classify_email(email)
        classification_ms = _elapsed_ms(classification_start)

        if classification.label != "BL_COMPARISON":
            return _decision(
                email=email,
                category=classification.label,
                classification_reasons=classification.reasons,
                classification_ms=classification_ms,
                document_ms=document_ms,
                extraction_ms=extraction_ms,
                comparison_ms=comparison_ms,
                total_start=total_start,
            )

        document_start = time.perf_counter_ns()
        selection = select_documents(email.attachments)
        document_ms = _elapsed_ms(document_start)
        if selection.review_reason:
            return _decision(
                email=email,
                category=classification.label,
                status="NEEDS_REVIEW",
                review_reason=selection.review_reason,
                classification_reasons=classification.reasons,
                selection=selection,
                classification_ms=classification_ms,
                document_ms=document_ms,
                extraction_ms=extraction_ms,
                comparison_ms=comparison_ms,
                total_start=total_start,
            )

        assert selection.si_attachment is not None and selection.bl_attachment is not None
        extraction_start = time.perf_counter_ns()
        si_raw = extract_fields(selection.si_attachment.content)
        bl_raw = extract_fields(selection.bl_attachment.content)
        si_normalized = normalize_fields(si_raw)
        bl_normalized = normalize_fields(bl_raw)
        extraction_ms = _elapsed_ms(extraction_start)

        # Do not compare absent or invalid values: that would turn a document
        # quality problem into a fabricated mismatch.
        if _has_missing_value(si_normalized) or _has_missing_value(bl_normalized):
            # OCR text follows the same extractor as embedded text. If it
            # cannot provide all required values, retain the safe unreadable
            # outcome when a scan cannot provide a safe complete comparison.
            review_reason = "unreadable" if _ocr_data_is_insufficient(selection) else "missing_value"
            return _decision(
                email=email,
                category=classification.label,
                status="NEEDS_REVIEW",
                review_reason=review_reason,
                classification_reasons=classification.reasons,
                selection=selection,
                si_raw=si_raw,
                bl_raw=bl_raw,
                si_normalized=si_normalized,
                bl_normalized=bl_normalized,
                classification_ms=classification_ms,
                document_ms=document_ms,
                extraction_ms=extraction_ms,
                comparison_ms=comparison_ms,
                total_start=total_start,
            )

        comparison_start = time.perf_counter_ns()
        comparison = compare_documents(si_normalized, bl_normalized)
        comparison_ms = _elapsed_ms(comparison_start)
        if comparison.is_match:
            return _decision(
                email=email,
                category=classification.label,
                status="OK",
                classification_reasons=classification.reasons,
                selection=selection,
                si_raw=si_raw,
                bl_raw=bl_raw,
                si_normalized=si_normalized,
                bl_normalized=bl_normalized,
                comparison=comparison,
                classification_ms=classification_ms,
                document_ms=document_ms,
                extraction_ms=extraction_ms,
                comparison_ms=comparison_ms,
                total_start=total_start,
            )
        return _decision(
            email=email,
            category=classification.label,
            status="MISMATCH",
            has_defect=True,
            defect_fields=tuple(comparison.mismatched_fields),
            classification_reasons=classification.reasons,
            selection=selection,
            si_raw=si_raw,
            bl_raw=bl_raw,
            si_normalized=si_normalized,
            bl_normalized=bl_normalized,
            comparison=comparison,
            classification_ms=classification_ms,
            document_ms=document_ms,
            extraction_ms=extraction_ms,
            comparison_ms=comparison_ms,
            total_start=total_start,
        )
    except Exception as exc:  # per-email boundary: never lose the whole inbox
        selected_logger.exception("Email %s failed safely: %s", email.email_id, exc)
        category = classification.label if classification and classification.label in EMAIL_CATEGORIES else "GENERAL"
        if category == "BL_COMPARISON":
            return _decision(
                email=email,
                category=category,
                status="NEEDS_REVIEW",
                review_reason="unreadable",
                classification_reasons=classification.reasons if classification else (),
                selection=selection,
                si_raw=si_raw,
                bl_raw=bl_raw,
                si_normalized=si_normalized,
                bl_normalized=bl_normalized,
                comparison=comparison,
                classification_ms=classification_ms,
                document_ms=document_ms,
                extraction_ms=extraction_ms,
                comparison_ms=comparison_ms,
                total_start=total_start,
                error=f"{type(exc).__name__}: {exc}",
            )
        return _decision(
            email=email,
            category=category,
            classification_reasons=classification.reasons if classification else (),
            classification_ms=classification_ms,
            document_ms=document_ms,
            extraction_ms=extraction_ms,
            comparison_ms=comparison_ms,
            total_start=total_start,
            error=f"{type(exc).__name__}: {exc}",
        )


def process_inbox(inbox: Iterable[EmailRecord], workers: int = 1) -> dict[str, dict[str, object]]:
    """Compatibility wrapper returning serialisable diagnostics by email ID."""

    report = process_records(inbox, workers=workers)
    return {email_id: decision.to_debug_dict() for email_id, decision in report.decisions.items()}


def _has_missing_value(values: Mapping[str, str | None]) -> bool:
    return any(values.get(field) is None for field in REQUIRED_FIELDS)


def _ocr_data_is_insufficient(selection: DocumentSelection) -> bool:
    """Whether a selected scan reached extraction but lacks comparison data."""

    return any(
        attachment is not None and attachment.metadata.get("extraction") == "OCR (Tesseract)"
        for attachment in (selection.si_attachment, selection.bl_attachment)
    )


def _decision(
    *,
    email: EmailRecord,
    category: str,
    status: str | None = None,
    has_defect: bool = False,
    defect_fields: tuple[str, ...] = (),
    review_reason: str | None = None,
    classification_reasons: tuple[str, ...] = (),
    selection: DocumentSelection | None = None,
    si_raw: Mapping[str, str | None] | None = None,
    bl_raw: Mapping[str, str | None] | None = None,
    si_normalized: Mapping[str, str | None] | None = None,
    bl_normalized: Mapping[str, str | None] | None = None,
    comparison: Comparison | None = None,
    classification_ms: float = 0.0,
    document_ms: float = 0.0,
    extraction_ms: float = 0.0,
    comparison_ms: float = 0.0,
    total_start: int,
    error: str | None = None,
) -> EmailDecision:
    """Centralise safe result construction so semantics never drift by branch."""

    return EmailDecision(
        email_id=email.email_id,
        category=category,
        status=status,
        has_defect=has_defect,
        defect_fields=defect_fields,
        review_reason=review_reason,
        classification_reasons=classification_reasons,
        selection=selection,
        si_extracted=si_raw,
        bl_extracted=bl_raw,
        si_normalized=si_normalized,
        bl_normalized=bl_normalized,
        comparison=comparison,
        timings=StageTimings(
            classification_ms=classification_ms,
            document_handling_ms=document_ms,
            extraction_ms=extraction_ms,
            comparison_ms=comparison_ms,
            total_ms=_elapsed_ms(total_start),
        ),
        error=error,
    )


def _elapsed_ms(start_ns: int) -> float:
    return round((time.perf_counter_ns() - start_ns) / 1_000_000, 3)
