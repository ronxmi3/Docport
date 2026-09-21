"""Adapter from supplied loader records to the pipeline's stable email model.

This lives outside ``loader.py`` on purpose: if a challenge bundle supplies its
own loader implementation, the rest of the pipeline still adapts its records
without depending on private loader helpers.
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any, Callable, Mapping

from models import Attachment, EmailRecord


def coerce_email_record(
    raw_email: object,
    attachment_reader: Callable[[object], str] | None = None,
    attachment_index: Mapping[str, Any] | None = None,
) -> EmailRecord:
    """Adapt dict- or attribute-shaped loader email records to ``EmailRecord``."""

    if isinstance(raw_email, EmailRecord):
        return raw_email

    email_id = get_value(raw_email, "email_id", "id", "emailId", "message_id", "messageId")
    if email_id is None:
        raise ValueError("Inbox email is missing an email_id (or id) field")
    subject = get_value(raw_email, "subject", "title") or ""
    body = get_value(raw_email, "body", "text", "content", "message") or ""
    sender = get_value(raw_email, "sender", "from", "from_address", "fromAddress") or ""
    raw_attachments = get_value(
        raw_email, "attachments", "attachment_paths", "attachment_refs", "files", "documents"
    ) or []
    if isinstance(raw_attachments, Mapping):
        raw_attachments = list(raw_attachments.values())
    elif not isinstance(raw_attachments, (list, tuple)):
        raw_attachments = [raw_attachments]

    # Support common separate SI/BL references without hard-coding a dataset.
    for key in (
        "si_attachment",
        "si_attachment_path",
        "si_path",
        "si_file",
        "si_document",
        "shipping_instruction",
        "shipping_instruction_path",
        "bl_attachment",
        "bl_attachment_path",
        "bl_path",
        "bl_file",
        "bl_document",
        "bill_of_lading",
        "bill_of_lading_path",
    ):
        value = get_value(raw_email, key)
        if value is not None:
            raw_attachments.append(value)
    attachment_ids = get_value(raw_email, "attachment_ids", "attachmentIds") or []
    if not isinstance(attachment_ids, (list, tuple)):
        attachment_ids = [attachment_ids]
    if attachment_index:
        raw_attachments.extend(attachment_index.get(str(item), item) for item in attachment_ids)

    attachments = tuple(
        coerce_attachment(item, attachment_reader, attachment_index) for item in raw_attachments
    )
    metadata = dict(raw_email) if isinstance(raw_email, Mapping) else {}
    return EmailRecord(
        email_id=str(email_id),
        subject=str(subject),
        body=str(body),
        sender=str(sender),
        attachments=attachments,
        metadata=metadata,
    )


def coerce_attachment(
    raw_attachment: object,
    attachment_reader: Callable[[object], str] | None,
    attachment_index: Mapping[str, Any] | None,
) -> Attachment:
    """Resolve inline or referenced text while preserving a read error as data."""

    if isinstance(raw_attachment, Attachment):
        return raw_attachment
    if isinstance(raw_attachment, str) and attachment_index and raw_attachment in attachment_index:
        raw_attachment = attachment_index[raw_attachment]

    filename = get_value(raw_attachment, "filename", "name", "file_name", "path", "file_path")
    source = get_value(raw_attachment, "path", "file_path", "file", "attachment_path", "url", "id")
    if isinstance(raw_attachment, str):
        filename = filename or Path(raw_attachment).name
        source = source or raw_attachment
    filename = str(filename or source or "unnamed_attachment.txt")

    inline = inline_attachment_text(raw_attachment) if isinstance(raw_attachment, Mapping) else None
    if inline is not None:
        content = inline
    elif attachment_reader is not None:
        try:
            content = str(attachment_reader(source if source is not None else raw_attachment))
        except Exception as exc:  # one bad file must not stop an inbox run
            return Attachment(
                filename=filename,
                content="",
                source=str(source) if source is not None else None,
                metadata={"read_error": str(exc), **mapping_metadata(raw_attachment)},
            )
    else:
        content = ""
    return Attachment(
        filename=filename,
        content=content,
        source=str(source) if source is not None else None,
        metadata=mapping_metadata(raw_attachment),
    )


def inline_attachment_text(item: Mapping[str, Any]) -> str | None:
    """Read supported inline text/base64 forms from a JSON attachment entry."""

    for key in ("content", "text", "plain_text", "plainText"):
        value = item.get(key)
        if value is not None:
            return str(value)
    for key in ("content_base64", "base64", "data_base64"):
        value = item.get(key)
        if value is not None:
            try:
                return base64.b64decode(str(value)).decode("utf-8", errors="replace")
            except (ValueError, UnicodeError):
                return None
    return None


def get_value(item: object, *keys: str) -> Any:
    """Read a value from either a mapping or a loader record object."""

    if isinstance(item, Mapping):
        for key in keys:
            if key in item and item[key] is not None:
                return item[key]
    for key in keys:
        if hasattr(item, key):
            value = getattr(item, key)
            if value is not None:
                return value
    return None


def first_present(item: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in item and item[key] is not None:
            return item[key]
    return None


def mapping_metadata(item: object) -> Mapping[str, Any]:
    return dict(item) if isinstance(item, Mapping) else {}
