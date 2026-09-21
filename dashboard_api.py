"""Read-only presentation API for the Averis dashboard.

This module deliberately composes the existing SDOC pipeline.  It contains no
classification, document selection, extraction, normalization, comparison, or
submission rules; those remain in the tested pipeline modules.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Any
import os
import time

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from audit_report import write_decision_audit_report
from main import ApplicationRun, run_application
from models import EMAIL_CATEGORIES, REQUIRED_FIELDS, Attachment, EmailDecision, EmailRecord
from submission import SubmissionValidationError, build_submission, load_submission_template, write_submission


PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_SOURCE = PROJECT_ROOT / "demo_data"
DEFAULT_OUTPUT = PROJECT_ROOT / "output" / "submission.json"
DEFAULT_REPORT = PROJECT_ROOT / "output" / "decision_report.pdf"


@dataclass(frozen=True)
class DashboardSnapshot:
    """A completed pipeline run and its measured end-to-end timing."""

    application_run: ApplicationRun
    runtime_seconds: float
    generated_at: float

    @property
    def report(self):
        return self.application_run.report


class DashboardState:
    """Small, process-local cache around the existing pipeline entry point."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._snapshot: DashboardSnapshot | None = None

    @property
    def source(self) -> Path:
        return Path(os.getenv("AVERIS_SOURCE", str(DEFAULT_SOURCE))).expanduser().resolve()

    @property
    def output_path(self) -> Path:
        return Path(os.getenv("AVERIS_OUTPUT", str(DEFAULT_OUTPUT))).expanduser().resolve()

    @property
    def report_path(self) -> Path:
        return Path(os.getenv("AVERIS_REPORT", str(DEFAULT_REPORT))).expanduser().resolve()

    @property
    def workers(self) -> int:
        value = int(os.getenv("AVERIS_WORKERS", "8"))
        return min(max(value, 1), 64)

    def get_snapshot(self) -> DashboardSnapshot:
        with self._lock:
            if self._snapshot is None:
                self._snapshot = self._execute(write_output=False)
            return self._snapshot

    def run_pipeline(self) -> DashboardSnapshot:
        """Use the canonical run/write path and atomically refresh dashboard data."""

        with self._lock:
            self._snapshot = self._execute(write_output=True)
            return self._snapshot

    def generate_report(self) -> tuple[DashboardSnapshot, dict[str, Any]]:
        with self._lock:
            snapshot = self.get_snapshot()
            emails = snapshot.application_run.dataset.emails
            result = write_decision_audit_report(
                self.report_path,
                emails,
                snapshot.report.decisions,
                runtime_seconds=snapshot.runtime_seconds,
                throughput=_throughput(snapshot),
            )
            return snapshot, {
                "exists": result.path.is_file(),
                "filename": result.path.name,
                "path": str(result.path),
                "included_count": result.included_count,
                "page_count": result.page_count,
                "generated_at": result.path.stat().st_mtime,
            }

    def _execute(self, *, write_output: bool) -> DashboardSnapshot:
        started = time.perf_counter()
        application_run = run_application(self.source, workers=self.workers)
        if write_output:
            template_path = application_run.dataset.sample_submission_path
            if template_path is None:
                raise SubmissionValidationError("Bundle is missing required sample_submission.json")
            payload = build_submission(application_run.report.decisions, load_submission_template(template_path))
            _write_submission_preserving_newline_style(payload, self.output_path)
        return DashboardSnapshot(
            application_run=application_run,
            runtime_seconds=time.perf_counter() - started,
            generated_at=time.time(),
        )


state = DashboardState()

app = FastAPI(
    title="Averis Shipping Intelligence API",
    version="1.0.0",
    description="Presentation API backed by the existing SDOC verification pipeline.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        origin.strip()
        for origin in os.getenv("AVERIS_CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(",")
    ],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "averis-dashboard-api"}


@app.get("/api/summary")
def summary() -> dict[str, Any]:
    return _summary(state.get_snapshot())


@app.get("/api/emails")
def emails(
    query: str | None = None,
    category: str | None = None,
    status: str | None = None,
    review_reason: str | None = None,
) -> dict[str, Any]:
    snapshot = state.get_snapshot()
    records = _record_map(snapshot)
    items = [_email_list_item(records[email_id], decision) for email_id, decision in snapshot.report.decisions.items()]
    normalized_query = (query or "").strip().casefold()
    if normalized_query:
        items = [item for item in items if normalized_query in item["email_id"].casefold() or normalized_query in item["subject"].casefold()]
    if category:
        items = [item for item in items if item["category"] == category]
    if status:
        items = [item for item in items if item["status"] == status]
    if review_reason:
        items = [item for item in items if item["review_reason"] == review_reason]
    return {"items": items, "total": len(items), "generated_at": snapshot.generated_at}


@app.get("/api/emails/{email_id}")
def email_detail(email_id: str) -> dict[str, Any]:
    snapshot = state.get_snapshot()
    decision = snapshot.report.decisions.get(email_id)
    record = _record_map(snapshot).get(email_id)
    if decision is None or record is None:
        raise HTTPException(status_code=404, detail=f"Email not found: {email_id}")
    return _email_detail(record, decision, snapshot.generated_at)


@app.get("/api/review")
def review_queue() -> dict[str, Any]:
    snapshot = state.get_snapshot()
    records = _record_map(snapshot)
    items = [
        _review_item(records[email_id], decision)
        for email_id, decision in snapshot.report.decisions.items()
        if decision.status == "NEEDS_REVIEW"
    ]
    return {"items": items, "total": len(items), "generated_at": snapshot.generated_at}


@app.post("/api/run")
def run() -> dict[str, Any]:
    """Run the tested pipeline and write its regular validated submission."""

    try:
        snapshot = state.run_pipeline()
    except (FileNotFoundError, RuntimeError, ValueError, SubmissionValidationError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"message": "Verification complete", "summary": _summary(snapshot), "output_path": str(state.output_path)}


@app.get("/api/report")
def report_status() -> dict[str, Any]:
    report_path = state.report_path
    exists = report_path.is_file()
    return {
        "exists": exists,
        "filename": report_path.name,
        "size_bytes": report_path.stat().st_size if exists else None,
        "generated_at": report_path.stat().st_mtime if exists else None,
        "download_url": "/api/report/download" if exists else None,
    }


@app.post("/api/report")
def generate_report() -> dict[str, Any]:
    try:
        _, result = state.generate_report()
    except (FileNotFoundError, RuntimeError, ValueError, SubmissionValidationError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {**result, "download_url": "/api/report/download"}


@app.get("/api/report/download")
def download_report() -> FileResponse:
    report_path = state.report_path
    if not report_path.is_file():
        raise HTTPException(status_code=404, detail="No audit report has been generated yet")
    return FileResponse(report_path, media_type="application/pdf", filename=report_path.name)


def _summary(snapshot: DashboardSnapshot) -> dict[str, Any]:
    decisions = tuple(snapshot.report.decisions.values())
    category_counts = Counter(decision.category for decision in decisions)
    outcome_counts = Counter(decision.status for decision in decisions if decision.status is not None)
    review_counts = Counter(decision.review_reason for decision in decisions if decision.review_reason is not None)
    return {
        "metrics": {
            "total_emails": snapshot.report.processed_count,
            "bl_comparisons": snapshot.report.comparison_count,
            "ok": outcome_counts["OK"],
            "mismatch": outcome_counts["MISMATCH"],
            "needs_review": outcome_counts["NEEDS_REVIEW"],
            "runtime_seconds": round(snapshot.runtime_seconds, 3),
            "throughput": round(_throughput(snapshot), 2),
        },
        "category_distribution": _distribution(category_counts, EMAIL_CATEGORIES),
        "outcome_distribution": _distribution(outcome_counts, ("OK", "MISMATCH", "NEEDS_REVIEW")),
        "review_distribution": _distribution(review_counts, tuple(sorted(review_counts))),
        "notable_cases": _notable_cases(snapshot),
        "source": str(snapshot.application_run.dataset.source),
        "loader": snapshot.application_run.dataset.loader_name,
        "generated_at": snapshot.generated_at,
    }


def _email_list_item(record: EmailRecord, decision: EmailDecision) -> dict[str, Any]:
    return {
        "email_id": record.email_id,
        "subject": record.subject,
        "category": decision.category,
        "status": decision.status,
        "defect_count": len(decision.defect_fields),
        "review_reason": decision.review_reason,
    }


def _email_detail(record: EmailRecord, decision: EmailDecision, generated_at: float) -> dict[str, Any]:
    assessments = {assessment.attachment.filename: assessment for assessment in decision.selection.assessments} if decision.selection else {}
    attachments = [_attachment_item(attachment, assessments.get(attachment.filename)) for attachment in record.attachments]
    fields: list[dict[str, Any]] = []
    for field in REQUIRED_FIELDS:
        comparison = decision.comparison.fields.get(field) if decision.comparison else None
        fields.append(
            {
                "field": field,
                "si_value": decision.si_extracted.get(field) if decision.si_extracted else None,
                "bl_value": decision.bl_extracted.get(field) if decision.bl_extracted else None,
                "si_normalized": decision.si_normalized.get(field) if decision.si_normalized else None,
                "bl_normalized": decision.bl_normalized.get(field) if decision.bl_normalized else None,
                "result": comparison.status.upper() if comparison else "UNAVAILABLE",
            }
        )
    return {
        "email_id": record.email_id,
        "subject": record.subject,
        "category": decision.category,
        "classification_reasons": list(decision.classification_reasons),
        "attachments": attachments,
        "selected_documents": {
            "si": decision.selection.si_attachment.filename if decision.selection and decision.selection.si_attachment else None,
            "bl": decision.selection.bl_attachment.filename if decision.selection and decision.selection.bl_attachment else None,
        },
        "extraction_status": _extraction_status(decision),
        "status": decision.status,
        "defect_fields": list(decision.defect_fields),
        "review_reason": decision.review_reason,
        "comparison_fields": fields if decision.category == "BL_COMPARISON" else [],
        "error": decision.error,
        "timings_ms": decision.timings.to_dict(),
        "generated_at": generated_at,
    }


def _attachment_item(attachment: Attachment, assessment: Any) -> dict[str, Any]:
    return {
        "filename": attachment.filename,
        "source_format": attachment.metadata.get("source_format"),
        "extraction": attachment.metadata.get("extraction"),
        "read_error": attachment.read_error,
        "detected_type": assessment.document_type if assessment else None,
        "evidence": list(assessment.reasons) if assessment else [],
    }


def _review_item(record: EmailRecord, decision: EmailDecision) -> dict[str, Any]:
    attachments = [_attachment_item(attachment, None) for attachment in record.attachments]
    assessment_evidence = []
    if decision.selection:
        assessment_evidence = [reason for assessment in decision.selection.assessments for reason in assessment.reasons]
    return {
        **_email_list_item(record, decision),
        "attachments": attachments,
        "evidence": [*decision.classification_reasons, *assessment_evidence],
    }


def _notable_cases(snapshot: DashboardSnapshot) -> list[dict[str, Any]]:
    records = _record_map(snapshot)
    ranked = sorted(
        snapshot.report.decisions.values(),
        key=lambda decision: (
            {"NEEDS_REVIEW": 0, "MISMATCH": 1, "OK": 2}.get(decision.status or "", 3),
            decision.email_id,
        ),
    )
    return [_email_list_item(records[decision.email_id], decision) for decision in ranked[:8]]


def _record_map(snapshot: DashboardSnapshot) -> dict[str, EmailRecord]:
    return {email.email_id: email for email in snapshot.application_run.dataset.emails}


def _distribution(counts: Counter[str], labels: tuple[str, ...]) -> list[dict[str, Any]]:
    return [{"name": label, "value": counts[label]} for label in labels if counts[label] > 0]


def _throughput(snapshot: DashboardSnapshot) -> float:
    return snapshot.report.processed_count / snapshot.runtime_seconds if snapshot.runtime_seconds > 0 else 0.0


def _extraction_status(decision: EmailDecision) -> str:
    if decision.status == "NEEDS_REVIEW":
        return "INCOMPLETE"
    if decision.category == "BL_COMPARISON":
        return "COMPLETE"
    return "NOT_REQUIRED"


def _write_submission_preserving_newline_style(payload: dict[str, Any], output_path: Path) -> Path:
    """Use the canonical writer while retaining an existing artifact's byte style.

    ``write_submission`` is the only serializer of decisions.  On Windows it
    writes CRLF in text mode; keeping an already-LF submission LF avoids a
    meaningless byte-level diff when the decisions are unchanged.
    """

    existing = output_path.read_bytes() if output_path.is_file() else b""
    expects_lf = b"\r\n" not in existing and b"\n" in existing
    target = write_submission(payload, output_path)
    if expects_lf:
        target.write_bytes(target.read_bytes().replace(b"\r\n", b"\n"))
    return target
