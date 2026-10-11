"""Assignment, status transitions and the work queue.

The lifecycle is deliberately small and strictly enforced::

    open --(start)--> in_progress --(resolve)--> resolved
      ^                                            |
      +---------------(reopen)---------------------+

Anything else is rejected with an explanatory message. A resolved ticket is
frozen until it is explicitly reopened.
"""

from __future__ import annotations

from typing import Any, Dict, List

from .tickets import (
    PRIORITY_RANK,
    STATUSES,
    TicketStore,
    UnknownTicketError,
    ValidationError,
    normalize_status,
    parse_ticket_number,
)

#: The only forward transitions the workflow permits.
ALLOWED_TRANSITIONS = (("open", "in_progress"), ("in_progress", "resolved"))

#: Statuses that still need work, i.e. what the work queue shows.
UNRESOLVED_STATUSES = ("open", "in_progress")

#: Rank used for tickets whose stored priority is unrecognised, so a hand-edited
#: file can never make the queue sort crash.
_UNKNOWN_PRIORITY_RANK = len(PRIORITY_RANK)


class WorkflowError(Exception):
    """Raised when an assignment or a status change is not allowed."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _describe_allowed() -> str:
    return " and ".join(f"{old} -> {new}" for old, new in ALLOWED_TRANSITIONS)


def validate_staff_name(raw: Any) -> str:
    """Return a trimmed staff name, or raise if it is blank."""
    if not isinstance(raw, str):
        raise WorkflowError(f"Staff name must be text, got {type(raw).__name__}.")
    name = raw.strip()
    if not name:
        raise WorkflowError("Staff name must not be blank.")
    return name


def _reject_if_resolved(ticket: Dict[str, Any], action: str) -> None:
    """A resolved ticket may not be modified until it is reopened."""
    if ticket.get("status") == "resolved":
        raise WorkflowError(
            f"Ticket {ticket['id']} is resolved and cannot be {action}. "
            f"Reopen it first."
        )


# ---------------------------------------------------------------------------
# Assignment
# ---------------------------------------------------------------------------
def assign_ticket(store: TicketStore, ticket_id: Any, staff_name: Any) -> Dict[str, Any]:
    """Assign a ticket to a named staff member.

    Rejects unknown ticket ids, blank names, and any change to a resolved
    ticket (which must be reopened first).
    """
    ticket = store.get(ticket_id)  # raises UnknownTicketError for bad/unknown ids
    name = validate_staff_name(staff_name)
    _reject_if_resolved(ticket, "reassigned")
    ticket["assigned_to"] = name
    return ticket


# ---------------------------------------------------------------------------
# Status transitions
# ---------------------------------------------------------------------------
def _check_transition(ticket: Dict[str, Any], target: str) -> None:
    """Raise :class:`WorkflowError` unless ``ticket`` may move to ``target``."""
    current = ticket.get("status")
    ticket_id = ticket["id"]

    if current == target:
        raise WorkflowError(f"Ticket {ticket_id} is already {target}.")

    if target == "in_progress":
        if current != "open":
            raise WorkflowError(
                f"Invalid transition for ticket {ticket_id}: {current} -> {target}. "
                f"Allowed: {_describe_allowed()}."
            )
        if not ticket.get("assigned_to"):
            raise WorkflowError(
                f"Ticket {ticket_id} is unassigned; assign it to a staff member "
                f"before starting work."
            )
    elif target == "resolved":
        if current != "in_progress":
            raise WorkflowError(
                f"Invalid transition for ticket {ticket_id}: {current} -> {target}. "
                f"Allowed: {_describe_allowed()}."
            )
    elif target == "open":  # reopening
        if current != "resolved":
            raise WorkflowError(
                f"Only a resolved ticket can be reopened, but {ticket_id} is {current}."
            )
    else:  # pragma: no cover - normalize_status() rejects anything else first
        raise WorkflowError(f"Unknown status {target!r}.")


def change_status(store: TicketStore, ticket_id: Any, new_status: Any) -> Dict[str, Any]:
    """Move a ticket to ``new_status``, enforcing the lifecycle rules."""
    ticket = store.get(ticket_id)
    try:
        target = normalize_status(new_status)
    except ValidationError as exc:
        raise WorkflowError(
            f"Unknown status {str(new_status).strip()!r}. "
            f"Choose one of: {', '.join(STATUSES)}."
        ) from exc

    _check_transition(ticket, target)
    ticket["status"] = target
    return ticket


def start_ticket(store: TicketStore, ticket_id: Any) -> Dict[str, Any]:
    """open -> in_progress."""
    return change_status(store, ticket_id, "in_progress")


def resolve_ticket(store: TicketStore, ticket_id: Any) -> Dict[str, Any]:
    """in_progress -> resolved."""
    return change_status(store, ticket_id, "resolved")


def reopen_ticket(store: TicketStore, ticket_id: Any) -> Dict[str, Any]:
    """resolved -> open."""
    return change_status(store, ticket_id, "open")


# ---------------------------------------------------------------------------
# Work queue
# ---------------------------------------------------------------------------
def work_queue(store: TicketStore) -> List[Dict[str, Any]]:
    """Unresolved tickets, most urgent first.

    Ordered by priority (critical -> high -> medium -> low) and, for equal
    priorities, by the earlier *numeric* ticket id (T002 before T010).
    """
    unresolved = [t for t in store if t.get("status") in UNRESOLVED_STATUSES]
    return sorted(
        unresolved,
        key=lambda t: (
            PRIORITY_RANK.get(t.get("priority"), _UNKNOWN_PRIORITY_RANK),
            parse_ticket_number(t["id"]),
        ),
    )


__all__ = [
    "ALLOWED_TRANSITIONS",
    "UNRESOLVED_STATUSES",
    "WorkflowError",
    "assign_ticket",
    "change_status",
    "start_ticket",
    "resolve_ticket",
    "reopen_ticket",
    "validate_staff_name",
    "work_queue",
]
