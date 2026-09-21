"""Local JSON loader with the same small interface used by the Averis bundle.

The official challenge bundle exposes ``Inbox`` with iteration, ``read_text``
and (optionally) ``submit``. This implementation makes the project runnable
before that bundle is mounted while keeping the pipeline compatible with the
same interface when it is available.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, Mapping
from urllib.error import URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from models import Attachment, EmailRecord
from docx_text import extract_docx_text
from pdf_text import extract_pdf_text
from xlsx_text import extract_xlsx_text


class Inbox:
    """Read a local inbox JSON file/directory, or a JSON endpoint.

    Supported local payloads are a list of email objects or an object with an
    ``emails``, ``inbox``, ``messages``, or ``data`` list. Attachment entries
    can carry inline ``content``/``text`` or a relative ``path``/``file``.
    """

    def __init__(self, source: str | Path):
        self.source = str(source)
        self._base_path: Path | None = None
        self._attachment_root: Path | None = None
        self._attachment_index: dict[str, Any] = {}
        self._submit_url: str | None = None

        payload = self._load_payload(source)
        raw_emails = _extract_email_list(payload)
        self._build_attachment_index(payload)
        self._emails = [
            coerce_email_record(raw, self.read_text, self._attachment_index, self.read_bytes)
            for raw in raw_emails
        ]

    def __iter__(self) -> Iterator[EmailRecord]:
        return iter(self._emails)

    def __len__(self) -> int:
        return len(self._emails)

    @property
    def emails(self) -> tuple[EmailRecord, ...]:
        """Expose loaded records for callers that prefer attribute access."""

        return tuple(self._emails)

    def read_bytes(self, reference: object) -> bytes:
        """Resolve an attachment reference to raw bytes.

        This mirrors the official participant loader's interface. PDF handling
        consumes these bytes with pypdf, while ``read_text`` below remains the
        unchanged path for text attachments.
        """
        if isinstance(reference, Mapping):
            for key in ("content_base64", "base64", "data_base64"):
                value = reference.get(key)
                if value is not None:
                    try:
                        return base64.b64decode(str(value))
                    except ValueError:
                        break
            inline = _inline_attachment_text(reference)
            if inline is not None:
                return inline.encode("utf-8")
            reference = _first_present(reference, "path", "file_path", "file", "attachment_path", "url", "id")
        if reference is None:
            raise ValueError("Attachment has no readable bytes or path")
        reference_text = str(reference)

        if reference_text in self._attachment_index:
            entry = self._attachment_index[reference_text]
            if entry is not reference:
                return self.read_bytes(entry)

        if reference_text.startswith(("http://", "https://")):
            with urlopen(reference_text, timeout=20) as response:  # nosec B310 - user-supplied challenge source
                return response.read()

        if self.source.startswith(("http://", "https://")):
            attachment_url = urljoin(self.source.rstrip("/") + "/", reference_text)
            with urlopen(attachment_url, timeout=20) as response:  # nosec B310 - local challenge service
                return response.read()

        for candidate in self._local_candidates(reference_text):
            if candidate.is_file():
                return candidate.read_bytes()
        raise FileNotFoundError(f"Unable to resolve attachment: {reference_text}")

    def read_text(self, reference: object, encoding: str = "utf-8") -> str:
        """Resolve a text attachment while keeping binary access available."""

        # ``Path.read_text`` previously used universal-newline mode. Preserve
        # that TXT behavior after routing through ``read_bytes`` for PDF work.
        text = self.read_bytes(reference).decode(encoding, errors="replace")
        return text.replace("\r\n", "\n").replace("\r", "\n")

    def submit(self, payload: Mapping[str, Any]) -> Any:
        """POST a result only when this inbox was created from an HTTP source."""

        if not self._submit_url:
            raise RuntimeError("submit() is only available for an HTTP inbox source")
        body = json.dumps(payload).encode("utf-8")
        request = Request(
            self._submit_url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=30) as response:  # nosec B310 - explicit challenge endpoint
            response_body = response.read().decode("utf-8", errors="replace")
        try:
            return json.loads(response_body)
        except json.JSONDecodeError:
            return response_body

    def _load_payload(self, source: str | Path) -> Any:
        source_text = str(source)
        if source_text.startswith(("http://", "https://")):
            self._submit_url = urljoin(source_text.rstrip("/") + "/", "submit")
            try:
                with urlopen(source_text, timeout=20) as response:  # nosec B310 - explicit source URL
                    return json.loads(response.read().decode("utf-8"))
            except (URLError, json.JSONDecodeError) as exc:
                raise RuntimeError(f"Could not load inbox URL {source_text}: {exc}") from exc

        path = Path(source_text)
        if path.is_dir():
            self._base_path = path.resolve()
            try:
                inbox_path = _find_inbox_json(path)
            except FileNotFoundError:
                payload = _load_email_json_directory(path / "inbox")
                if payload is None:
                    raise
                self._attachment_root = _first_existing_directory(
                    self._base_path / "attachments",
                    self._base_path.parent / "attachments",
                )
                return payload
        else:
            inbox_path = path
            self._base_path = path.parent.resolve()
        if not inbox_path.is_file():
            raise FileNotFoundError(
                f"Could not find inbox JSON at {inbox_path}. "
                "Pass a JSON file or a directory containing inbox.json."
            )
        self._attachment_root = _first_existing_directory(
            self._base_path / "attachments",
            inbox_path.parent / "attachments",
            self._base_path.parent / "attachments",
        )
        try:
            return json.loads(inbox_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Inbox file is not valid JSON: {inbox_path}") from exc

    def _build_attachment_index(self, payload: Any) -> None:
        if not isinstance(payload, Mapping):
            return
        attachments = payload.get("attachments")
        if isinstance(attachments, Mapping):
            self._attachment_index = {str(key): value for key, value in attachments.items()}
        elif isinstance(attachments, list):
            for attachment in attachments:
                identifier = _get_value(attachment, "id", "attachment_id", "path", "filename", "name")
                if identifier is not None:
                    self._attachment_index[str(identifier)] = attachment

    def _local_candidates(self, reference: str) -> Iterable[Path]:
        path = Path(reference)
        if path.is_absolute():
            yield path
            return
        roots = [root for root in (self._base_path, self._attachment_root) if root is not None]
        for root in roots:
            yield root / path
            # Some JSON files store only a filename while attachments live in a
            # sibling directory. This fallback remains deterministic.
            yield root / "attachments" / path.name


def load_inbox(source: str | Path) -> Inbox:
    """Convenience factory used by the CLI and FastAPI endpoint."""

    return Inbox(source)


def coerce_email_record(
    raw_email: object,
    attachment_reader: Callable[[object], str] | None = None,
    attachment_index: Mapping[str, Any] | None = None,
    attachment_bytes_reader: Callable[[object], bytes] | None = None,
) -> EmailRecord:
    """Adapt dict- or attribute-shaped challenge email records to ``EmailRecord``."""

    if isinstance(raw_email, EmailRecord):
        return raw_email

    email_id = _get_value(raw_email, "email_id", "id", "emailId", "message_id", "messageId")
    if email_id is None:
        raise ValueError("Inbox email is missing an email_id (or id) field")
    subject = _get_value(raw_email, "subject", "title") or ""
    body = _get_value(raw_email, "body", "text", "content", "message") or ""
    sender = _get_value(raw_email, "sender", "from", "from_address", "fromAddress") or ""
    raw_attachments = _get_value(
        raw_email, "attachments", "attachment_paths", "attachment_refs", "files", "documents"
    ) or []
    if isinstance(raw_attachments, Mapping):
        raw_attachments = list(raw_attachments.values())
    elif not isinstance(raw_attachments, (list, tuple)):
        raw_attachments = [raw_attachments]

    # Support common separate SI/BL reference fields without forcing a schema.
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
        value = _get_value(raw_email, key)
        if value is not None:
            raw_attachments.append(value)
    attachment_ids = _get_value(raw_email, "attachment_ids", "attachmentIds") or []
    if not isinstance(attachment_ids, (list, tuple)):
        attachment_ids = [attachment_ids]
    if attachment_index:
        raw_attachments.extend(attachment_index.get(str(item), item) for item in attachment_ids)

    attachments = tuple(
        _coerce_attachment(item, attachment_reader, attachment_index, attachment_bytes_reader)
        for item in raw_attachments
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


def _coerce_attachment(
    raw_attachment: object,
    attachment_reader: Callable[[object], str] | None,
    attachment_index: Mapping[str, Any] | None,
    attachment_bytes_reader: Callable[[object], bytes] | None = None,
) -> Attachment:
    if isinstance(raw_attachment, Attachment):
        return raw_attachment
    if isinstance(raw_attachment, str) and attachment_index and raw_attachment in attachment_index:
        raw_attachment = attachment_index[raw_attachment]

    filename = _get_value(raw_attachment, "filename", "name", "file_name", "path", "file_path")
    source = _get_value(raw_attachment, "path", "file_path", "file", "attachment_path", "url", "id")
    if isinstance(raw_attachment, str):
        filename = filename or Path(raw_attachment).name
        source = source or raw_attachment
    filename = str(filename or source or "unnamed_attachment.txt")
    source_reference = source if source is not None else raw_attachment
    metadata = dict(_mapping_metadata(raw_attachment))

    suffix = Path(filename).suffix.casefold()
    if suffix == ".pdf":
        if attachment_bytes_reader is None:
            return _unreadable_attachment(
                filename, source, metadata, "PDF extraction requires an attachment bytes reader"
            )
        try:
            content = extract_pdf_text(attachment_bytes_reader(source_reference))
        except Exception as exc:  # a failed PDF read is local to this attachment
            return _unreadable_attachment(filename, source, metadata, str(exc), source_format="PDF")
        metadata.update({"source_format": "PDF", "extraction": "embedded text"})
    elif suffix == ".docx":
        if attachment_bytes_reader is None:
            return _unreadable_attachment(
                filename, source, metadata, "DOCX extraction requires an attachment bytes reader", source_format="DOCX"
            )
        try:
            content = extract_docx_text(attachment_bytes_reader(source_reference))
        except Exception as exc:  # a failed Word read is local to this attachment
            return _unreadable_attachment(filename, source, metadata, str(exc), source_format="DOCX")
        metadata.update({"source_format": "DOCX", "extraction": "python-docx"})
    elif suffix in {".xlsx", ".xlsm"}:
        if attachment_bytes_reader is None:
            return _unreadable_attachment(
                filename,
                source,
                metadata,
                "Excel extraction requires an attachment bytes reader",
                source_format=suffix.removeprefix(".").upper(),
            )
        try:
            content = extract_xlsx_text(attachment_bytes_reader(source_reference))
        except Exception as exc:  # a broken workbook belongs only to this email
            return _unreadable_attachment(
                filename, source, metadata, str(exc), source_format=suffix.removeprefix(".").upper()
            )
        metadata.update({"source_format": suffix.removeprefix(".").upper(), "extraction": "openpyxl"})
    else:
        inline = _inline_attachment_text(raw_attachment) if isinstance(raw_attachment, Mapping) else None
        if inline is not None:
            content = inline
        elif attachment_reader is not None:
            try:
                content = str(attachment_reader(source_reference))
            except Exception as exc:  # kept as metadata so one bad file does not stop an inbox run
                return _unreadable_attachment(filename, source, metadata, str(exc))
        else:
            content = ""
        if suffix == ".txt":
            metadata.setdefault("source_format", "TXT")
            metadata.setdefault("extraction", "plain text")

    return Attachment(
        filename=filename,
        content=content,
        source=str(source) if source is not None else None,
        metadata=metadata,
    )


def _unreadable_attachment(
    filename: str,
    source: object | None,
    metadata: Mapping[str, Any],
    error: str,
    source_format: str | None = None,
) -> Attachment:
    """Keep attachment-load errors local to the email that owns them."""

    updated_metadata = dict(metadata)
    if source_format:
        updated_metadata["source_format"] = source_format
    updated_metadata["extraction"] = "unreadable"
    updated_metadata["read_error"] = error
    return Attachment(
        filename=filename,
        content="",
        source=str(source) if source is not None else None,
        metadata=updated_metadata,
    )


def _extract_email_list(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, Mapping):
        raise ValueError("Inbox JSON must be a list or an object containing an email list")
    for key in ("emails", "inbox", "messages", "data"):
        candidate = payload.get(key)
        if isinstance(candidate, list):
            return candidate
    # A few simple exports use ``{email_id: {subject: ...}}`` rather than an
    # explicit emails list. Preserve the map key as email_id in that case.
    if payload and all(isinstance(value, Mapping) for value in payload.values()):
        records: list[dict[str, Any]] = []
        for email_id, value in payload.items():
            record = dict(value)
            record.setdefault("email_id", str(email_id))
            records.append(record)
        return records
    raise ValueError("Inbox JSON has no emails/inbox/messages/data list")


def _find_inbox_json(directory: Path) -> Path:
    preferred = (
        directory / "inbox.json",
        directory / "emails.json",
        directory / "inbox" / "inbox.json",
        directory / "inbox" / "emails.json",
    )
    for candidate in preferred:
        if candidate.is_file():
            return candidate
    json_files = sorted(
        candidate
        for candidate in directory.glob("*.json")
        if candidate.name.casefold() != "sample_submission.json"
    )
    if len(json_files) == 1:
        return json_files[0]
    raise FileNotFoundError(
        f"No inbox JSON found under {directory}. Expected inbox.json or emails.json."
    )


def _load_email_json_directory(directory: Path) -> dict[str, list[Any]] | None:
    """Support a bundle whose ``inbox/`` directory has one JSON per email."""

    if not directory.is_dir():
        return None
    records: list[Any] = []
    for json_file in sorted(directory.glob("*.json")):
        try:
            payload = json.loads(json_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Inbox file is not valid JSON: {json_file}") from exc
        if isinstance(payload, list):
            records.extend(payload)
        elif isinstance(payload, Mapping):
            try:
                records.extend(_extract_email_list(payload))
            except ValueError:
                records.append(payload)
        else:
            raise ValueError(f"Inbox record must be a JSON object or list: {json_file}")
    return {"emails": records} if records else None


def _first_existing_directory(*candidates: Path) -> Path | None:
    return next((candidate for candidate in candidates if candidate.is_dir()), None)


def _inline_attachment_text(item: Mapping[str, Any]) -> str | None:
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


def _get_value(item: object, *keys: str) -> Any:
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


def _first_present(item: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in item and item[key] is not None:
            return item[key]
    return None


def _mapping_metadata(item: object) -> Mapping[str, Any]:
    return dict(item) if isinstance(item, Mapping) else {}
