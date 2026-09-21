"""FastAPI and command-line entry points for the first Averis pipeline."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from loader import Inbox
from pipeline import build_submission, load_sample_template, process_inbox, write_submission


app = FastAPI(
    title="Averis Shipping Document Verification",
    version="0.1.0",
    description="Deterministic plain-text SI versus BL verification pipeline.",
)


class ProcessRequest(BaseModel):
    """Local source configuration for the minimal backend endpoint."""

    source: str = Field(..., description="Inbox JSON path, data directory, or challenge inbox URL")
    sample_submission_path: str | None = Field(
        default=None,
        description="Optional sample_submission.json used to project exact output shape",
    )


@app.get("/health")
def health() -> dict[str, str]:
    """Small readiness endpoint; no queue, OCR, or database is involved."""

    return {"status": "ok"}


@app.post("/process")
def process(request: ProcessRequest) -> dict[str, Any]:
    """Run the same deterministic pipeline exposed by the CLI."""

    try:
        payload = _run(request.source, request.sample_submission_path)
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return payload


def _run(source: str, sample_submission_path: str | None = None) -> dict[str, Any]:
    inbox = Inbox(source)
    results = process_inbox(inbox)
    template_path = sample_submission_path or _find_sample_submission(source)
    template = load_sample_template(template_path) if template_path else None
    return build_submission(results, template)


def _find_sample_submission(source: str) -> Path | None:
    """Locate the bundle's template when a local source directory is used."""

    if source.startswith(("http://", "https://")):
        return None
    path = Path(source)
    roots = (path, path.parent) if path.is_file() else (path,)
    for root in roots:
        candidate = root / "sample_submission.json"
        if candidate.is_file():
            return candidate
    return None


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Classify Averis inbox email and compare plain-text SI/BL documents."
    )
    parser.add_argument(
        "--source",
        "--inbox",
        dest="source",
        required=True,
        help="Inbox JSON file, bundle directory, or challenge Inbox URL",
    )
    parser.add_argument(
        "--output",
        default="output/submission.json",
        help="Where to write the keyed submission JSON",
    )
    parser.add_argument(
        "--sample-submission",
        dest="sample_submission_path",
        help="Optional sample_submission.json schema template",
    )
    parser.add_argument(
        "--submit",
        action="store_true",
        help="POST the generated payload through Inbox.submit() (HTTP sources only)",
    )
    return parser.parse_args()


def cli() -> None:
    """Run locally and optionally submit through an HTTP Inbox implementation."""

    args = _parse_args()
    payload = _run(args.source, args.sample_submission_path)
    target = write_submission(payload, args.output)
    print(f"Processed {len(payload)} emails. Wrote submission to {target}")
    if args.submit:
        inbox = Inbox(args.source)
        response = inbox.submit(payload)
        print(f"Submission response: {response}")


if __name__ == "__main__":
    cli()
