"""CLI and optional FastAPI wrapper for the production-style SDOC pipeline."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import logging
from pathlib import Path
import sys
import time
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from attachment_opener import open_email_attachments
from audit_report import AuditReportResult, write_decision_audit_report
from dataset_loader import LoadedDataset, load_dataset
from explanation import format_email_explanation
from pipeline import PipelineReport, process_email, process_records
from submission import (
    SubmissionValidationError,
    build_submission,
    load_submission_template,
    write_submission,
)


LOGGER = logging.getLogger("sdoc")

app = FastAPI(
    title="SDOC Shipping Document Verification",
    version="1.0.0",
    description="Deterministic Shipping Instruction versus Bill of Lading verification.",
)


@dataclass(frozen=True)
class ApplicationRun:
    """The objects needed for CLI reporting without leaking them into output."""

    dataset: LoadedDataset
    report: PipelineReport
    load_seconds: float


class ProcessRequest(BaseModel):
    source: str = Field(..., description="Path to the SDOC participant bundle")
    workers: int = Field(default=1, ge=1, le=64)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/process")
def process(request: ProcessRequest) -> dict[str, Any]:
    """Process a mounted bundle and return the validated submission payload."""

    try:
        application_run = run_application(request.source, workers=request.workers)
        template_path = application_run.dataset.sample_submission_path
        if template_path is None:
            raise SubmissionValidationError("Bundle is missing sample_submission.json")
        template = load_submission_template(template_path)
        return build_submission(application_run.report.decisions, template)
    except (FileNotFoundError, RuntimeError, ValueError, SubmissionValidationError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def run_application(
    source: str | Path, workers: int = 1, email_id: str | None = None
) -> ApplicationRun:
    """Load once and process all, or one requested demo email, safely."""

    load_start = time.perf_counter()
    dataset = load_dataset(source)
    load_seconds = time.perf_counter() - load_start
    records = dataset.emails
    if email_id is not None:
        records = tuple(email for email in dataset.emails if email.email_id == email_id)
        if not records:
            raise ValueError(f"email ID not found: {email_id}")
    report = process_records(records, workers=workers, logger=LOGGER)
    return ApplicationRun(dataset=dataset, report=report, load_seconds=load_seconds)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Classify SDOC emails and compare Shipping Instructions against draft Bills of Lading."
    )
    parser.add_argument("--source", required=True, help="Path to the SDOC bundle root")
    parser.add_argument("--output", default="submission.json", help="Validated output JSON path")
    parser.add_argument("--workers", type=int, default=1, help="Independent email workers (default: 1)")
    parser.add_argument("--verbose", action="store_true", help="Show loader and per-email failure diagnostics")
    parser.add_argument("--benchmark", action="store_true", help="Print load, processing, and throughput metrics")
    parser.add_argument("--email", help="Inspect one email ID without writing a partial submission")
    parser.add_argument(
        "--explain",
        action="store_true",
        help="With --email, render the decision evidence as a human-readable report",
    )
    parser.add_argument(
        "--open-attachments",
        action="store_true",
        help="With --email, print and open supported attachment files using their Windows default apps",
    )
    parser.add_argument("--report", metavar="PATH", help="Write a PDF decision audit report to this path")
    parser.add_argument(
        "--report-only-problems",
        action="store_true",
        help="With --report, include only MISMATCH and NEEDS_REVIEW decisions",
    )
    return parser.parse_args()


def cli() -> int:
    """Execute the application command and return a shell-friendly exit code."""

    args = _parse_args()
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )
    # A malformed PDF is represented on its owning attachment and leads to a
    # safe review decision. Avoid leaking pypdf's low-level parser warnings
    # into normal CLI/demo output, where they lack the relevant email ID.
    logging.getLogger("pypdf").setLevel(logging.ERROR)
    if args.workers < 1:
        print("error: --workers must be at least 1", file=sys.stderr)
        return 2
    if args.open_attachments and not args.email:
        print("error: --open-attachments requires --email", file=sys.stderr)
        return 2
    if args.explain and not args.email:
        print("error: --explain requires --email", file=sys.stderr)
        return 2
    if args.report_only_problems and not args.report:
        print("error: --report-only-problems requires --report", file=sys.stderr)
        return 2

    try:
        application_run = run_application(args.source, workers=args.workers, email_id=args.email)
        if args.verbose:
            LOGGER.info("Loaded source via %s", application_run.dataset.loader_name)

        if args.email:
            decision = application_run.report.decisions.get(args.email)
            if decision is None:  # defensive: run_application validates this
                print(f"error: email ID not found: {args.email}", file=sys.stderr)
                return 2
            if args.explain:
                email = next(email for email in application_run.dataset.emails if email.email_id == args.email)
                _print_console(format_email_explanation(email, decision))
            else:
                _print_console(json.dumps(decision.to_debug_dict(), indent=2, ensure_ascii=False))
            if args.open_attachments:
                email = next(email for email in application_run.dataset.emails if email.email_id == args.email)
                open_email_attachments(application_run.dataset.source, email)
            if args.report:
                _print_report_result(_write_audit_report(application_run, args.report, args.report_only_problems))
            if args.benchmark or args.verbose:
                _print_benchmark(application_run)
            return 0

        template_path = application_run.dataset.sample_submission_path
        if template_path is None:
            raise SubmissionValidationError("Bundle is missing required sample_submission.json")
        template = load_submission_template(template_path)
        payload = build_submission(application_run.report.decisions, template)
        target = write_submission(payload, args.output)
        print(f"Wrote validated submission for {len(payload)} emails to {target}")
        if args.report:
            _print_report_result(_write_audit_report(application_run, args.report, args.report_only_problems))
        if args.benchmark or args.verbose:
            _print_benchmark(application_run)
        return 0
    except (FileNotFoundError, RuntimeError, ValueError, SubmissionValidationError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


def _write_audit_report(
    application_run: ApplicationRun, output_path: str, problems_only: bool
) -> AuditReportResult:
    """Render a presentation-only report for the exact emails this run processed."""

    email_ids = set(application_run.report.decisions)
    processed_emails = tuple(email for email in application_run.dataset.emails if email.email_id in email_ids)
    runtime_seconds = application_run.load_seconds + application_run.report.elapsed_seconds
    throughput = application_run.report.processed_count / runtime_seconds if runtime_seconds > 0 else 0.0
    return write_decision_audit_report(
        output_path,
        processed_emails,
        application_run.report.decisions,
        runtime_seconds=runtime_seconds,
        throughput=throughput,
        problems_only=problems_only,
    )


def _print_report_result(result: AuditReportResult) -> None:
    print(
        f"Wrote decision audit report for {result.included_count} emails "
        f"({result.page_count} pages) to {result.path}"
    )


def _print_benchmark(application_run: ApplicationRun) -> None:
    report = application_run.report
    total_seconds = application_run.load_seconds + report.elapsed_seconds
    throughput = report.processed_count / total_seconds if total_seconds > 0 else 0.0
    print(f"Loaded: {len(application_run.dataset.emails)} emails")
    print(f"Processed: {report.processed_count}")
    print(f"BL comparisons: {report.comparison_count}")
    print(f"Needs review: {report.needs_review_count}")
    print(f"Load time: {application_run.load_seconds:.2f} seconds")
    print(f"Processing time: {report.elapsed_seconds:.2f} seconds")
    print(f"Total time: {total_seconds:.2f} seconds")
    print(f"Throughput: {throughput:.2f} emails/sec")


def _print_console(text: str) -> None:
    """Print debug/report text even when an older Windows shell is CP1252."""

    try:
        print(text)
    except UnicodeEncodeError:
        # The report remains readable in a legacy console while retaining the
        # richer checkmarks/em-dashes in UTF-8 terminals and redirected output.
        fallback = text.replace("✓", "[ok]").replace("—", "-").replace("…", "...")
        encoding = getattr(sys.stdout, "encoding", None) or "ascii"
        print(fallback.encode(encoding, errors="replace").decode(encoding, errors="replace"))


if __name__ == "__main__":
    raise SystemExit(cli())
