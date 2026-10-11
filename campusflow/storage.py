"""JSON persistence for the ticket store.

Two guarantees drive this module:

* **A read never writes.** A missing file is a fresh empty store; a malformed
  file raises :class:`StorageError` and is left byte-for-byte untouched, so a
  typo in the JSON can never destroy the tickets inside it.
* **A write is atomic.** Tickets are serialised to a temporary file in the same
  directory, flushed to disk, then moved over the target with ``os.replace``.
  A crash mid-save leaves either the old file or the new one, never a
  half-written mixture.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Union

from .tickets import (
    CATEGORIES,
    PRIORITIES,
    STATUSES,
    TICKET_FIELDS,
    URGENCIES,
    ValidationError,
    normalize_ticket_id,
)

#: Default store location: ``<project root>/data/tickets.json``.
#: Resolved from this file's path (not the process CWD) so the CLI behaves the
#: same however it is launched.
DEFAULT_DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "tickets.json"


class StorageError(Exception):
    """Raised when tickets cannot be read or written safely."""


def resolve_path(path: Optional[Union[str, Path]] = None) -> Path:
    """Return the store path, falling back to :data:`DEFAULT_DATA_PATH`."""
    return Path(path) if path is not None else DEFAULT_DATA_PATH


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------
def _validate_record(record: Any, position: int, target: Path) -> Dict[str, Any]:
    """Return a clean copy of one stored record, or raise :class:`StorageError`.

    Validating on load means a hand-edited or truncated file is reported once,
    with the offending position, instead of surfacing later as a ``KeyError``
    somewhere in the workflow.
    """
    where = f"{target}: ticket #{position}"
    if not isinstance(record, dict):
        raise StorageError(f"{where} is not a JSON object (found {type(record).__name__}).")

    missing = [field for field in TICKET_FIELDS if field not in record]
    if missing:
        raise StorageError(f"{where} is missing required field(s): {', '.join(missing)}.")

    try:
        ticket_id = normalize_ticket_id(record["id"])
    except ValidationError as exc:
        raise StorageError(f"{where} has an invalid id: {exc}") from exc
    if record["id"] != ticket_id:
        raise StorageError(
            f"{where} has a non-canonical id {record['id']!r}; expected {ticket_id!r}."
        )

    title = record["title"]
    if not isinstance(title, str) or not title.strip():
        raise StorageError(f"{where} has a blank or non-text title ({title!r}).")

    for field, allowed in (
        ("category", CATEGORIES),
        ("urgency", URGENCIES),
        ("priority", PRIORITIES),
        ("status", STATUSES),
    ):
        if record[field] not in allowed:
            raise StorageError(
                f"{where} has an invalid {field} {record[field]!r}; "
                f"expected one of: {', '.join(allowed)}."
            )

    affected = record["affected_users"]
    if isinstance(affected, bool) or not isinstance(affected, int) or affected <= 0:
        raise StorageError(f"{where} has an invalid affected_users value ({affected!r}).")

    assigned = record["assigned_to"]
    if assigned is not None and (not isinstance(assigned, str) or not assigned.strip()):
        raise StorageError(f"{where} has an invalid assigned_to value ({assigned!r}).")

    return {field: record[field] for field in TICKET_FIELDS}


def load_tickets(path: Optional[Union[str, Path]] = None) -> List[Dict[str, Any]]:
    """Load tickets from ``path``.

    * file missing or blank -> ``[]`` (a fresh, empty store)
    * unreadable / malformed -> :class:`StorageError`, file left untouched
    """
    target = resolve_path(path)

    if not target.exists():
        return []

    try:
        raw = target.read_text(encoding="utf-8")
    except OSError as exc:
        raise StorageError(f"Could not read tickets from {target}: {exc}") from exc
    except UnicodeDecodeError as exc:
        raise StorageError(
            f"{target} is not valid UTF-8 text ({exc}); the file was left untouched."
        ) from exc

    if not raw.strip():
        # An empty file carries no tickets, so starting fresh loses nothing.
        return []

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise StorageError(
            f"{target} is not valid JSON (line {exc.lineno}, column {exc.colno}: "
            f"{exc.msg}). The file was left untouched - fix it, or rename it to "
            f"start with an empty store."
        ) from exc

    if not isinstance(payload, list):
        raise StorageError(
            f"{target} must contain a JSON list of tickets, "
            f"found {type(payload).__name__}. The file was left untouched."
        )

    return [
        _validate_record(record, position, target)
        for position, record in enumerate(payload, start=1)
    ]


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------
def save_tickets(
    tickets: Iterable[Dict[str, Any]],
    path: Optional[Union[str, Path]] = None,
) -> Path:
    """Write ``tickets`` to ``path`` atomically and return the path written.

    The temp file is created in the destination directory so ``os.replace`` is a
    same-filesystem rename, which is atomic on Windows and POSIX alike.
    """
    target = resolve_path(path)
    payload = list(tickets)

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise StorageError(f"Could not create {target.parent}: {exc}") from exc

    text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"

    tmp_path: Optional[Path] = None
    try:
        fd, tmp_name = tempfile.mkstemp(
            dir=str(target.parent), prefix=f"{target.name}.", suffix=".tmp"
        )
        tmp_path = Path(tmp_name)
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())  # durable before the rename
        os.replace(tmp_path, target)
        tmp_path = None  # renamed away; nothing to clean up
    except OSError as exc:
        raise StorageError(f"Could not save tickets to {target}: {exc}") from exc
    finally:
        if tmp_path is not None and tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:  # pragma: no cover - best-effort cleanup only
                pass

    return target


__all__ = ["DEFAULT_DATA_PATH", "StorageError", "load_tickets", "resolve_path", "save_tickets"]
