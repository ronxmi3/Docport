# SDOC Shipping Document Verification Pipeline

Deterministic, production-style classification and Shipping Instruction (SI)
versus draft Bill of Lading (BL) verification for the SDOC hackathon. It uses
only participant email and attachment text: no LLM, database, or scoring data.
TXT files, embedded-text PDFs, and image-only PDFs are supported. PDFs use
Tesseract OCR only when their embedded text is empty or insufficient; a failed
or low-confidence OCR pass is safely routed to review.

## What it does

Every email is classified as exactly one of:

- `BL_COMPARISON`
- `SI_REQUEST`
- `INVOICE_QUERY`
- `GENERAL`
- `SPAM`

For BL comparisons, it extracts and compares these canonical fields:

```text
shipper              consignee             notify_party
port_of_loading      port_of_discharge     container_count
gross_weight_kg
```

| Status | Meaning |
| --- | --- |
| `OK` | All seven normalized values agree. |
| `MISMATCH` | Values differ; `defect_fields` contains exact canonical names. |
| `NEEDS_REVIEW` | Safe comparison is impossible: `wrong_doc_type`, `missing_attachment`, `unreadable`, or `missing_value`. |

`NEEDS_REVIEW` never fabricates a discrepancy: it has `has_defect: false` and
an empty `defect_fields` list.

## Architecture

```text
SDOC bundle / official Inbox
           |
           v
      dataset_loader
           |
           v
      classifier.py  ----> five official categories
           |
           v
  document_handler.py ----> content-first SI/BL selection
           |
           v
      extractor.py -> normalizer.py -> comparator.py
           |
           v
      pipeline.py  ----> safe per-email result + timings
           |
           v
    submission.py  ----> template rendering + validation
```

Core processing modules are independent from CLI, FastAPI, Docker, and future
worker layers, keeping each stage testable.

## Expected participant bundle

Point `--source` at the real participant bundle:

```text
sdoc-hackathon-bundle/
|-- attachments/
|-- inbox/
|   |-- email_001.json
|   |-- ...
|   `-- email_520.json
|-- sample_submission.json
|-- loader.py
`-- README.md
```

The organizer `loader.py`/`Inbox` abstraction is used first when supplied.
The documented `attachments/` plus `inbox/email_*.json` layout is also read
directly as a safe fallback.

## Setup

Use Python 3.11+ (Docker uses Python 3.12).

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

Use `requirements.txt` for runtime-only installation.

### OCR for scanned PDFs

The Python packages render scanned PDF pages locally, while Tesseract performs
the OCR. Docker installs Tesseract automatically. For local Windows runs,
install [UB Mannheim Tesseract](https://github.com/UB-Mannheim/tesseract/wiki)
and ensure `tesseract.exe` is on `PATH` (or set `pytesseract.pytesseract.tesseract_cmd`
in your local environment). If it is unavailable or cannot read a scan, the
pipeline preserves the existing `NEEDS_REVIEW / unreadable` outcome.

## Run locally

```powershell
python main.py --source "C:\path\to\sdoc-hackathon-bundle" --output submission.json
```

Use deterministic parallelism and performance measurements:

```powershell
python main.py --source "C:\path\to\sdoc-hackathon-bundle" --output submission.json --workers 8 --benchmark
```

`--workers` does not alter output order or decisions. Attachments are loaded
once before workers begin.

## Optional FastAPI interface

The same orchestration is available for a later UI or worker integration:

```powershell
uvicorn main:app --host 0.0.0.0 --port 8000
```

`POST /process` accepts `{"source": "C:\\path\\to\\sdoc-hackathon-bundle", "workers": 8}`
and returns the same validated payload as the CLI. The core pipeline itself
does not depend on the web layer.

## Inspect one email for a demo

```powershell
python main.py --source "C:\path\to\sdoc-hackathon-bundle" --email email_004 --verbose
```

This prints category, attachment evidence, document types, extracted and
normalized SI/BL fields, final status, defect fields/review reason, and timing.
It never writes an invalid partial submission.

For an audit-friendly report built directly from stored classifier, document,
and comparison evidence, add `--explain`:

```powershell
python main.py --source "C:\path\to\sdoc-hackathon-bundle" --email email_004 --verbose --explain
```

To show the resolved full paths and open PDF/image/text attachments with their
Windows default applications, add `--open-attachments` to an `--email` demo:

```powershell
python main.py --source "C:\path\to\sdoc-hackathon-bundle" --email email_004 --verbose --open-attachments
```

`--explain` and `--open-attachments` can be combined. Opening files never
changes the decision pipeline; PDFs are parsed with `pypdf` for embedded text
only, while scanned/image-only files remain `NEEDS_REVIEW: unreadable`.

## Decision audit PDFs

Create a printable audit trail from the existing stored decisions and evidence:

```powershell
python main.py --source "C:\path\to\sdoc-hackathon-bundle" --output output\submission.json --workers 8 --report output\decision_report.pdf
```

To include only `MISMATCH` and `NEEDS_REVIEW` decisions:

```powershell
python main.py --source "C:\path\to\sdoc-hackathon-bundle" --output output\submission.json --workers 8 --report output\problems_only.pdf --report-only-problems
```

For a one-email demo report, combine `--email`, `--explain`, and `--report`.
The report does not re-run inference and does not alter `submission.json`; it
only presents the exact decision, document evidence, raw values, normalized
values, comparison outcome, and existing human-readable explanation.

## Benchmark output

`--benchmark` or `--verbose` prints measured output such as:

```text
Loaded: 520 emails
Processed: 520
BL comparisons: 143
Needs review: 7
Load time: 0.42 seconds
Processing time: 0.31 seconds
Total time: 0.73 seconds
Throughput: 712.33 emails/sec
```

Those values are illustrative; the program measures real runtime values.

## Output validation

The output is one JSON object keyed by every input `email_id` and uses
`sample_submission.json` as its structural template. Before writing, the
pipeline validates ID coverage, official categories/statuses/review reasons,
boolean and list types, canonical defect names, and all status semantics.

## Test

```powershell
python -m pytest -q
```

Tests cover classification, aliases, normalization, no/one/multiple defects,
missing attachments, wrong documents, malformed content, missing values,
deterministic parallel execution, submission validation, and a temporary
end-to-end bundle in the official directory layout. No fake monolithic
`inbox.json` is used.

## Docker

Build the minimal runtime image:

```powershell
docker build -t sdoc-pipeline:latest .
```

Run the full test suite in the separate test target. Tests are not copied into
the final runtime image:

```powershell
docker build --target test -t sdoc-pipeline:test .
docker run --rm sdoc-pipeline:test
```

Create a host output directory, then run the mounted participant bundle. The
bundle is read-only at `/data`; only `/output` is writable:

```powershell
New-Item -ItemType Directory -Force .\output | Out-Null

docker run --rm `
  -v "C:\path\to\sdoc-hackathon-bundle:/data:ro" `
  -v "${PWD}\output:/output" `
  sdoc-pipeline:latest `
  --source /data `
  --output /output/submission.json `
  --workers 8 `
  --benchmark
```

The final image explicitly copies only application modules. Its Docker context
also excludes participant/scoring data, reports, caches, virtual environments,
temporary files, and common secret files. DOCX, XLSX/XLSM, PDF, and report
files remain host-mounted data rather than image contents.

### Bundled demo data

For a self-contained demo, the reviewed `demo_data/` subset is copied into the
runtime image at `/demo_data`. It contains only inbox records, attachments,
`sample_submission.json`, the participant `loader.py`, and its README; scorer
data, answer keys, reports, caches, archives, and secret files are excluded.

```powershell
docker build -t sdoc-pipeline:latest .

docker run --rm `
  -v "${PWD}\output:/output" `
  sdoc-pipeline:latest `
  --source /demo_data `
  --output /output/submission.json `
  --workers 8 `
  --benchmark
```

Mounted participant bundles remain supported with `--source /data` as shown
above.

## Project structure

```text
classifier.py          deterministic five-category classification
document_handler.py    content-first SI/BL selection and review decisions
extractor.py           canonical field extraction from plain text
normalizer.py          conservative field/value normalization
comparator.py          deterministic SI-versus-BL comparison
dataset_loader.py      official Inbox integration and folder-layout fallback
submission.py          template rendering and strict output validation
audit_report.py        presentation-only PDF decision audit reports
pipeline.py            safe per-email orchestration and parallel processing
models.py              typed core contracts
main.py                CLI and FastAPI entry points
tests/                 unit and end-to-end temporary-bundle tests
Dockerfile             lightweight runtime container
```
