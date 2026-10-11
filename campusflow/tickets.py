"""Ticket model, input validation and priority calculation.

Everything that turns untrusted user input into a stored ticket lives here.
The two rules the rest of the app depends on:

* validation always happens *before* any state changes, so a rejected input
  can never leave a half-written ticket or a consumed ticket id behind;
* ticket ids are generated from the highest number already in the store, so
  ids stay unique and sequential across restarts.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional

#: Canonical category names, as stored (input is accepted case-insensitively).
CATEGORIES = ("Network", "Hardware", "Software", "Other")

#: Canonical urgency values, lowest first.
URGENCIES = ("low", "medium", "high")

#: Canonical status values.
STATUSES = ("open", "in_progress", "resolved")

#: Canonical priority values, highest first.
PRIORITIES = ("critical", "high", "medium", "low")

#: Sort order used by the work queue: lower rank == more urgent.
PRIORITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}

#: Status a brand new ticket starts in.
DEFAULT_STATUS = "open"

#: The fields every ticket carries, in the order they are displayed.
TICKET_FIELDS = (
    "id",
    "title",
    "category",
    "urgency",
    "affected_users",
    "priority",
    "status",
    "assigned_to",
)

#: A ticket id looks like ``T001``: a T followed by one or more digits.
_TICKET_ID_RE = re.compile(r"^T(\d+)$")

#: Whole-number text, optionally signed (``2.5`` and ``2e3`` deliberately fail).
_INTEGER_RE = re.compile(r"^[+-]?\d+$")


class ValidationError(ValueError):
    """Raised when user-supplied ticket data fails validation."""


class UnknownTicketError(KeyError):
    """Raised when a ticket id does not exist in the store."""


def _reject(raw: Any, expected: str, field: str) -> "ValidationError":
    """Build a consistent 'wrong type' error for ``field``."""
    return ValidationError(
        f"{field} must be {expected}, got {type(raw).__name__} ({raw!r})."
    )


# ---------------------------------------------------------------------------
# Field-level validation
# ---------------------------------------------------------------------------
def validate_title(raw: Any) -> str:
    """Return the trimmed title, or raise if it is blank / not text."""
    if not isinstance(raw, str):
        raise _reject(raw, "text", "Title")
    title = raw.strip()
    if not title:
        raise ValidationError("Title must not be blank.")
    return title


def normalize_category(raw: Any) -> str:
    """Accept ``network``/``NETWORK``/`` Network `` and return ``Network``."""
    if not isinstance(raw, str):
        raise _reject(raw, "text", "Category")
    cleaned = raw.strip().lower()
    for category in CATEGORIES:
        if category.lower() == cleaned:
            return category
    raise ValidationError(
        f"Unknown category {raw.strip()!r}. Choose one of: {', '.join(CATEGORIES)}."
    )


def normalize_urgency(raw: Any) -> str:
    """Accept ``HIGH``/`` High `` and return ``high``."""
    if not isinstance(raw, str):
        raise _reject(raw, "text", "Urgency")
    cleaned = raw.strip().lower()
    if cleaned not in URGENCIES:
        raise ValidationError(
            f"Unknown urgency {raw.strip()!r}. Choose one of: {', '.join(URGENCIES)}."
        )
    return cleaned


def normalize_status(raw: Any) -> str:
    """Accept ``In_Progress``/`` RESOLVED `` and return a canonical status."""
    if not isinstance(raw, str):
        raise _reject(raw, "text", "Status")
    cleaned = raw.strip().lower()
    if cleaned not in STATUSES:
        raise ValidationError(
            f"Unknown status {raw.strip()!r}. Choose one of: {', '.join(STATUSES)}."
        )
    return cleaned


def parse_affected_users(raw: Any) -> int:
    """Return a positive ``int`` for ``raw``.

    Accepts ``int`` and integer-looking ``str``. Rejects ``bool`` (a subclass of
    ``int``), floats such as ``2.5`` and ``2.0``, zero, negatives and free text.
    """
    if isinstance(raw, bool):
        # Checked first: True/False are ints as far as isinstance() is concerned.
        raise ValidationError(
            f"Affected users must be a whole number, got the boolean {raw!r}."
        )
    if isinstance(raw, int):
        value = raw
    elif isinstance(raw, float):
        raise ValidationError(
            f"Affected users must be a whole number, got the decimal {raw!r}."
        )
    elif isinstance(raw, str):
        text = raw.strip()
        if not _INTEGER_RE.match(text):
            raise ValidationError(
                f"Affected users must be a whole number, got {raw.strip()!r}."
            )
        value = int(text)
    else:
        raise _reject(raw, "a whole number", "Affected users")

    if value <= 0:
        raise ValidationError(
            f"Affected users must be greater than zero, got {value}."
        )
    return value


# ---------------------------------------------------------------------------
# Priority
# ---------------------------------------------------------------------------
def compute_priority(urgency: Any, affected_users: Any) -> str:
    """Return the priority for a ticket, applying the rules *in order*.

    1. high urgency **and** >= 10 users  -> critical
    2. high urgency **or**  >= 10 users  -> high
    3. medium urgency **or** >= 3 users  -> medium
    4. otherwise                        -> low

    Inputs are validated here too, so a bad call fails loudly instead of
    silently producing a wrong priority.
    """
    urgency = normalize_urgency(urgency)
    affected_users = parse_affected_users(affected_users)

    if urgency == "high" and affected_users >= 10:
        return "critical"
    if urgency == "high" or affected_users >= 10:
        return "high"
    if urgency == "medium" or affected_users >= 3:
        return "medium"
    return "low"


# ---------------------------------------------------------------------------
# Ticket ids
# ---------------------------------------------------------------------------
def parse_ticket_number(ticket_id: Any) -> int:
    """Return the numeric part of ``T001`` as ``1``.

    Comparing these numbers (not the raw strings) is what breaks work-queue
    ties correctly, including across differing widths such as ``T9``/``T10``.
    """
    match = _TICKET_ID_RE.match(str(ticket_id).strip().upper())
    if not match:
        raise ValidationError(
            f"Malformed ticket id {ticket_id!r}; expected a value like T001."
        )
    return int(match.group(1))


def format_ticket_id(number: int) -> str:
    """Render ticket number ``7`` as ``T007``."""
    if isinstance(number, bool) or not isinstance(number, int) or number <= 0:
        raise ValidationError(f"Ticket numbers must be positive integers, got {number!r}.")
    return f"T{number:03d}"


def normalize_ticket_id(raw: Any) -> str:
    """Return the canonical id for user input such as ``t7`` -> ``T007``."""
    return format_ticket_id(parse_ticket_number(raw))


# ---------------------------------------------------------------------------
# The store
# ---------------------------------------------------------------------------
class TicketStore:
    """An in-memory collection of tickets, keyed by ticket id.

    The store holds no file handle of its own: ``storage`` loads records in and
    ``storage.save_tickets`` writes them out, which keeps persistence testable
    and the store free of global state.
    """

    def __init__(self, records: Optional[Iterable[Dict[str, Any]]] = None) -> None:
        self._tickets: Dict[str, Dict[str, Any]] = {}
        for record in records or []:
            ticket = dict(record)
            ticket_id = normalize_ticket_id(ticket.get("id", ""))
            ticket["id"] = ticket_id
            ticket.setdefault("status", DEFAULT_STATUS)
            ticket.setdefault("assigned_to", None)
            if ticket_id in self._tickets:
                raise ValidationError(f"Duplicate ticket id {ticket_id} in the loaded data.")
            self._tickets[ticket_id] = ticket
        self._next_number = self._compute_next_number()

    # -- reading ------------------------------------------------------------
    @property
    def tickets(self) -> List[Dict[str, Any]]:
        """Every ticket, ordered by ticket number."""
        return [self._tickets[ticket_id] for ticket_id in self._sorted_ids()]

    def _sorted_ids(self) -> List[str]:
        return sorted(self._tickets, key=parse_ticket_number)

    def __len__(self) -> int:
        return len(self._tickets)

    def __iter__(self):
        return iter(self.tickets)

    def __contains__(self, ticket_id: Any) -> bool:
        try:
            return normalize_ticket_id(ticket_id) in self._tickets
        except ValidationError:
            return False

    def get(self, ticket_id: Any) -> Dict[str, Any]:
        """Return the ticket for ``ticket_id``.

        Raises :class:`UnknownTicketError` for ids that are unknown *or*
        malformed, so the CLI can report one clear message either way.
        """
        try:
            key = normalize_ticket_id(ticket_id)
        except ValidationError as exc:
            raise UnknownTicketError(f"Unknown ticket id {str(ticket_id).strip()!r}.") from exc
        try:
            return self._tickets[key]
        except KeyError as exc:
            raise UnknownTicketError(f"Unknown ticket id {key}.") from exc

    # -- writing ------------------------------------------------------------
    def _compute_next_number(self) -> int:
        """One past the highest ticket number seen, so ids never repeat.

        Deriving this from the data (rather than storing a counter) is what
        keeps ids unique after a reload, even if a ticket was removed by hand.
        """
        highest = 0
        for ticket_id in self._tickets:
            highest = max(highest, parse_ticket_number(ticket_id))
        return highest + 1

    def create_ticket(
        self,
        title: Any,
        category: Any,
        urgency: Any,
        affected_users: Any,
    ) -> Dict[str, Any]:
        """Validate ``title``/``category``/``urgency``/``affected_users``, then store.

        All validation runs before the store is touched, so an invalid input
        returns a clear error and leaves the stored data exactly as it was.
        """
        clean_title = validate_title(title)
        clean_category = normalize_category(category)
        clean_urgency = normalize_urgency(urgency)
        clean_users = parse_affected_users(affected_users)
        priority = compute_priority(clean_urgency, clean_users)

        ticket_id = format_ticket_id(self._next_number)
        ticket: Dict[str, Any] = {
            "id": ticket_id,
            "title": clean_title,
            "category": clean_category,
            "urgency": clean_urgency,
            "affected_users": clean_users,
            "priority": priority,
            "status": DEFAULT_STATUS,
            "assigned_to": None,
        }
        self._tickets[ticket_id] = ticket
        self._next_number += 1
        return ticket
