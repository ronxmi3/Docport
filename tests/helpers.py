"""Small, realistic SDOC bundle builders used only by tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping


SI_TEXT = """SHIPPING INSTRUCTION
Shipper / Exporter: Acme Export Ltd.
Consignee: Beta Imports Inc.
Notify Party: Beta Imports Inc.
Port of Loading: Shanghai (CNSHA)
Port of Discharge: Los Angeles (USLAX)
No. of Containers: 2 x 40HC + 1 x 20GP
Total Gross Weight: 12.5 MT
"""

BL_TEXT = """DRAFT BILL OF LADING
Shipper: ACME EXPORT LIMITED
Consignee: BETA IMPORTS INCORPORATED
Notify Party: Beta Imports Incorporated
Load Port: Shanghai, China
Discharge Port: Los Angeles, USA
Containers: 3 containers
Gross Weight KG: 12,500 KGS
"""


def write_bundle(
    root: Path,
    emails: Mapping[str, Mapping[str, object]],
    attachments: Mapping[str, str | bytes],
) -> Path:
    """Create the documented per-email bundle layout, never a monolithic inbox."""

    inbox_dir = root / "inbox"
    attachment_dir = root / "attachments"
    inbox_dir.mkdir(parents=True)
    attachment_dir.mkdir()

    for email_id, payload in emails.items():
        entry = {"email_id": email_id, **payload}
        (inbox_dir / f"{email_id}.json").write_text(json.dumps(entry), encoding="utf-8")
    for filename, content in attachments.items():
        target = attachment_dir / filename
        if isinstance(content, bytes):
            target.write_bytes(content)
        else:
            target.write_text(content, encoding="utf-8")

    template = {
        email_id: {
            "category": None,
            "status": None,
            "has_defect": False,
            "defect_fields": [],
            "review_reason": None,
        }
        for email_id in emails
    }
    (root / "sample_submission.json").write_text(json.dumps(template, indent=2), encoding="utf-8")
    return root
