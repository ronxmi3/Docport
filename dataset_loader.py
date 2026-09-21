"""Dataset entry point for the official SDOC bundle and its Inbox API."""

from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from types import ModuleType
from typing import Any, Iterable

from inbox_adapter import coerce_email_record
from loader import Inbox as FolderInbox
from models import EmailRecord


_OFFICIAL_LOADER_IMPORT_LOCK = RLock()


@dataclass(frozen=True)
class LoadedDataset:
    """In-memory records plus the sample template needed to write a submission."""

    source: Path
    emails: tuple[EmailRecord, ...]
    sample_submission_path: Path | None
    loader_name: str


def load_dataset(source: str | Path, prefer_official_loader: bool = True) -> LoadedDataset:
    """Load an SDOC bundle once, preferring its supplied ``Inbox`` abstraction.

    The documented folder layout is fully supported without a bundle loader:
    ``attachments/``, ``inbox/email_*.json``, and ``sample_submission.json``.
    If the organizer's loader is present, it is imported under an isolated name
    and used first so private attachment conventions remain authoritative.
    """

    source_path = Path(source).expanduser().resolve()
    if not source_path.exists():
        raise FileNotFoundError(f"SDOC source does not exist: {source_path}")
    if not source_path.is_dir():
        raise ValueError("--source must point to the SDOC bundle directory")

    if prefer_official_loader:
        official_loader = source_path / "loader.py"
        if official_loader.is_file() and official_loader.resolve() != Path(__file__).with_name("loader.py").resolve():
            try:
                emails = _load_with_official_inbox(official_loader, source_path)
                return LoadedDataset(
                    source=source_path,
                    emails=emails,
                    sample_submission_path=_find_sample_submission(source_path),
                    loader_name="official Inbox",
                )
            except Exception as exc:
                # The fallback remains useful for a valid plain folder bundle;
                # retain the official failure in the raised error if fallback
                # cannot read it either.
                try:
                    fallback = _load_with_folder_inbox(source_path)
                except Exception as fallback_exc:
                    raise RuntimeError(
                        f"Official loader failed ({exc}); folder fallback also failed ({fallback_exc})"
                    ) from fallback_exc
                return LoadedDataset(
                    source=source_path,
                    emails=fallback,
                    sample_submission_path=_find_sample_submission(source_path),
                    loader_name="folder fallback after official loader error",
                )

    return LoadedDataset(
        source=source_path,
        emails=_load_with_folder_inbox(source_path),
        sample_submission_path=_find_sample_submission(source_path),
        loader_name="folder layout",
    )


def _load_with_official_inbox(loader_path: Path, source: Path) -> tuple[EmailRecord, ...]:
    module = _load_module(loader_path)
    inbox_class = getattr(module, "Inbox", None)
    if inbox_class is None:
        raise AttributeError(f"{loader_path} does not expose Inbox")
    inbox = inbox_class(str(source))
    reader = getattr(inbox, "read_text", None)
    if not callable(reader):
        raise AttributeError("Official Inbox must expose read_text(path)")
    bytes_reader = getattr(inbox, "read_bytes", None)
    return _coerce_all(inbox, reader, bytes_reader if callable(bytes_reader) else None)


def _load_with_folder_inbox(source: Path) -> tuple[EmailRecord, ...]:
    inbox = FolderInbox(source)
    return _coerce_all(inbox, inbox.read_text, inbox.read_bytes)


def _coerce_all(
    raw_emails: Iterable[object], reader: Any, bytes_reader: Any | None = None
) -> tuple[EmailRecord, ...]:
    records: list[EmailRecord] = []
    seen: set[str] = set()
    for raw_email in raw_emails:
        record = coerce_email_record(raw_email, reader, attachment_bytes_reader=bytes_reader)
        if record.email_id in seen:
            raise ValueError(f"Duplicate email_id in source: {record.email_id}")
        seen.add(record.email_id)
        records.append(record)
    if not records:
        raise ValueError("No email records were loaded from the SDOC bundle")
    return tuple(sorted(records, key=lambda record: record.email_id))


def _load_module(loader_path: Path) -> ModuleType:
    """Load the organizer module without shadowing this project's loader.py."""

    # Importing a source-local loader temporarily changes ``sys.path``. The
    # lock matters when the optional FastAPI endpoint receives concurrent
    # requests: Python's import path is process-global, while the pipeline
    # itself remains safe to run in parallel after loading has finished.
    with _OFFICIAL_LOADER_IMPORT_LOCK:
        module_name = f"sdoc_official_loader_{abs(hash(str(loader_path.resolve())))}"
        spec = importlib.util.spec_from_file_location(module_name, loader_path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Could not create import specification for {loader_path}")
        module = importlib.util.module_from_spec(spec)
        original_path = list(sys.path)
        try:
            # Some challenge loaders import helper files that live beside loader.py.
            sys.path.insert(0, str(loader_path.parent))
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
        except Exception:
            sys.modules.pop(module_name, None)
            raise
        finally:
            sys.path[:] = original_path
        return module


def _find_sample_submission(source: Path) -> Path | None:
    candidate = source / "sample_submission.json"
    return candidate if candidate.is_file() else None
