# Runtime and test images intentionally receive only application source. The
# participant dataset and generated reports are bind-mounted at runtime.
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.txt ./
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir -r requirements.txt

FROM base AS app

# Explicit copies make the runtime image independent of any untracked local
# dataset, report, virtualenv, temporary directory, or secret in the context.
COPY attachment_opener.py audit_report.py classifier.py comparator.py dataset_loader.py ./
COPY document_handler.py docx_text.py explanation.py extractor.py inbox_adapter.py loader.py ./
COPY main.py models.py normalizer.py pdf_text.py pipeline.py submission.py xlsx_text.py ./

FROM app AS test

COPY requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements-dev.txt
COPY tests ./tests
COPY demo_data /app/demo_data
CMD ["python", "-m", "pytest", "-q"]

FROM app AS runtime

# The checked-in demo subset is intentionally separate from /data, which
# remains available for an externally mounted participant bundle at runtime.
COPY demo_data /demo_data

ENTRYPOINT ["python", "main.py"]
