# DocPort Synthetic Demo Dataset

This directory contains a small synthetic dataset for demonstrating DocPort from a clean repository clone.

No private challenge data, scoring data, ground truth, or hidden answers are included.

The demo contains five fictional emails covering:

- email_001: BL_COMPARISON / OK
- email_002: BL_COMPARISON / MISMATCH
- email_003: BL_COMPARISON / NEEDS_REVIEW
- email_004: INVOICE_QUERY
- email_005: SPAM

The same DocPort pipeline can process an external SDOC-compatible dataset by using the --source option or mounting a dataset into Docker.
