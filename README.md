# Averis shipping-document verification (v0.1)

This is the first, plain-text version of the Averis pipeline. It classifies
every inbox email, processes only `document_comparison` requests, extracts the
seven required SI/BL fields, normalizes them, and compares the BL to the SI
deterministically. The SI is always the reference document.

There is deliberately no LLM, OCR, database, Redis, Celery, Docker setup,
frontend, or distributed worker in this version. The core modules have no
FastAPI dependency, so those pieces can be added around the stable pipeline
later.

## Project structure

```text
Google Hackathon/
├── classifier.py       # explainable rules for the five email categories
├── extractor.py        # explicit-label plain-text SI/BL extraction
├── normalizer.py       # value/unit/label-equivalence normalisation
├── comparator.py       # exact SI-versus-BL comparison
├── pipeline.py         # orchestration, timing, and submission formatting
├── loader.py           # local JSON Inbox implementation / bundle-compatible API
├── inbox_adapter.py    # adapts supplied loader records into stable models
├── models.py           # dependency-free shared data contracts
├── main.py             # FastAPI app and CLI entry point
├── requirements.txt
├── examples/
│   ├── inbox.json
│   └── sample_submission.json
└── tests/
    ├── test_classifier.py
    ├── test_extractor.py
    ├── test_normalizer.py
    ├── test_comparator.py
    └── test_pipeline.py
```

## Install

Use a supported CPython release (3.11–3.13 is recommended).

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

If PowerShell blocks activation, run the venv interpreter directly instead:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## Run the pipeline

The challenge bundle can be passed as a directory, as documented by its
`Inbox` loader:

```powershell
python main.py --source data --output output/submission.json
```

Or pass an inbox JSON file directly:

```powershell
python main.py --source data/inbox.json --output output/submission.json
```

When a local `sample_submission.json` sits beside the input, `main.py` finds
it automatically and projects the result to its keyed-by-`email_id` shape.
You can specify it explicitly when it lives elsewhere:

```powershell
python main.py --source data --sample-submission data/sample_submission.json --output output/submission.json
```

The current workspace did not include the supplied Averis data bundle, so a
small self-contained example is included for an end-to-end smoke run:

```powershell
python main.py --source examples/inbox.json --sample-submission examples/sample_submission.json --output output/demo_submission.json
```

For the challenge's HTTP inbox, the optional submission path is available
through the loader contract:

```powershell
python main.py --source http://localhost:8080 --output output/submission.json --submit
```

## Output

The normal pipeline output is one JSON object keyed by `email_id`; it includes
every email, not only comparison requests. Each value includes:

- `category`: one of `document_comparison`, `new_si_request`, `invoice_query`,
  `general`, or `spam`.
- `mismatch_found`: only set for comparison requests.
- `differences`: SI and BL values side by side for every non-matching or
  missing required field.
- `timings_ms`: `classification`, `extraction`, `comparison`, and `total`.

Comparison values are normalized before comparison. Notable deterministic
rules include case/whitespace/punctuation handling, common company suffixes,
UN/LOCODE port aliases, container expressions such as `2 x 40HC + 1 x 20GP`,
and kg/metric-tonne/pound conversions. Missing values are deliberately marked
incomplete rather than treated as matching.

The exact evaluation field names are intentionally isolated in
`pipeline.build_submission()`. Once the provided `sample_submission.json` is
available, it is used as the output template without changing extraction or
comparison logic.

## Run the API

```powershell
uvicorn main:app --reload --port 8000
```

Then send a local source path:

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/process -ContentType 'application/json' -Body '{"source":"data"}'
```

`GET /health` returns a small readiness response. The API simply wraps the
same synchronous core pipeline; it does not introduce persistence or workers.

## Test

```powershell
python -m pytest -q
```

The tests cover explicit-label extraction (including multiline parties),
normalization and unit conversion, deterministic comparison/missing values,
and an end-to-end pipeline case that confirms non-comparison emails are not
sent through attachment extraction.
