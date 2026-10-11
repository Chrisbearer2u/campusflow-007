"""Summary statistics for the ticket store.

Every counter is seeded at zero and no rate or percentage is computed, so an
empty store reports zeros and can never raise a ``ZeroDivisionError``.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List

from .tickets import PRIORITIES, STATUSES

#: Human-readable labels for canonical status values.
STATUS_LABELS = {
    "open": "open",
    "in_progress": "in_progress",
    "resolved": "resolved",
}


def status_counts(tickets: Iterable[Dict[str, Any]]) -> Dict[str, int]:
    """Count tickets per status; every known status is present, even at zero."""
    counts = {status: 0 for status in STATUSES}
    for ticket in tickets:
        status = ticket.get("status")
        if status in counts:
            counts[status] += 1
        else:  # unexpected values are counted, never silently dropped
            counts[status] = counts.get(status, 0) + 1
    return counts


def priority_counts(tickets: Iterable[Dict[str, Any]]) -> Dict[str, int]:
    """Count tickets per priority; every known priority is present, even at zero."""
    counts = {priority: 0 for priority in PRIORITIES}
    for ticket in tickets:
        priority = ticket.get("priority")
        if priority in counts:
            counts[priority] += 1
        else:
            counts[priority] = counts.get(priority, 0) + 1
    return counts


def summary(tickets: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """Return total, by-status and by-priority counts for ``tickets``."""
    materialised: List[Dict[str, Any]] = list(tickets)
    return {
        "total": len(materialised),
        "by_status": status_counts(materialised),
        "by_priority": priority_counts(materialised),
    }


def format_summary(report: Dict[str, Any]) -> str:
    """Render :func:`summary` output as plain text for the CLI."""
    lines = [
        "CampusFlow report",
        "=================",
        f"Total tickets: {report.get('total', 0)}",
        "",
        "By status:",
    ]
    by_status = report.get("by_status", {})
    for status in STATUSES:
        label = STATUS_LABELS.get(status, status)
        lines.append(f"  {label:<12} {by_status.get(status, 0)}")

    lines.append("")
    lines.append("By priority:")
    by_priority = report.get("by_priority", {})
    for priority in PRIORITIES:
        lines.append(f"  {priority:<12} {by_priority.get(priority, 0)}")

    if report.get("total", 0) == 0:
        lines.append("")
        lines.append("No tickets recorded yet.")

    return "\n".join(lines)


__all__ = ["STATUS_LABELS", "format_summary", "priority_counts", "status_counts", "summary"]
