"""Windows-only attachment viewing support for the SDOC CLI.

This module is intentionally outside the document pipeline. It receives the
already-loaded email record, resolves attachment locations below the selected
participant bundle, and opens supported files through the Windows shell.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Callable

from models import Attachment, EmailRecord


SUPPORTED_ATTACHMENT_SUFFIXES = frozenset({".pdf", ".png", ".jpg", ".jpeg", ".txt"})


def resolve_attachment_path(bundle_root: str | Path, attachment: Attachment) -> Path:
    """Resolve an attachment below ``<bundle>/attachments`` safely.

    Organizer loaders commonly expose ``attachments/email_001_BL.txt`` while
    some expose just the filename. Both forms resolve to the same path. A
    source path outside the bundle is never followed by this CLI helper.
    """

    attachment_root = (Path(bundle_root).resolve() / "attachments").resolve()
    reference = Path(str(attachment.source or attachment.filename))

    if reference.is_absolute():
        # The CLI contract is bundle-relative even if a custom loader stores an
        # absolute source path. Its filename is the safe, expected reference.
        reference = Path(reference.name)
    elif reference.parts and reference.parts[0].casefold() == "attachments":
        reference = Path(*reference.parts[1:])

    resolved = (attachment_root / reference).resolve()
    try:
        resolved.relative_to(attachment_root)
    except ValueError as exc:
        raise ValueError(f"Attachment path escapes the bundle attachments directory: {reference}") from exc
    return resolved


def open_email_attachments(bundle_root: str | Path, email: EmailRecord) -> None:
    """Print and open supported attachment files without interrupting a demo.

    ``os.startfile`` is available on Windows and delegates PDF, image, and text
    files to their user-configured default applications. Missing/unsupported
    files produce clear warnings instead of ending the CLI process.
    """

    if not email.attachments:
        print("No attachments found for this email.")
        return

    startfile: Callable[[str], object] | None = getattr(os, "startfile", None)
    for attachment in email.attachments:
        try:
            path = resolve_attachment_path(bundle_root, attachment)
        except ValueError as exc:
            print(f"warning: {exc}")
            continue

        # Always show an absolute path first; this makes a hackathon demo easy
        # to follow and lets users manually open an unsupported file if needed.
        print(f"Attachment: {path}")
        if not path.is_file():
            print(f"warning: attachment does not exist: {path}")
            continue
        if path.suffix.casefold() not in SUPPORTED_ATTACHMENT_SUFFIXES:
            print(f"warning: unsupported attachment type (not opened): {path.suffix or '[no extension]'}")
            continue
        if startfile is None:
            print("warning: opening attachments requires Windows os.startfile().")
            continue
        try:
            startfile(str(path))
        except OSError as exc:
            print(f"warning: could not open attachment {path}: {exc}")
