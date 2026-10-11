"""CampusFlow - command-line helpdesk for Learn2Earn campus staff.

Run it with::

    python main.py                 # uses data/tickets.json
    python main.py path/to.json    # uses an alternative store

The CLI is a thin skin over the package: it validates nothing itself, it just
prompts, calls into ``campusflow.*`` and reports whatever error comes back.
Every successful change is saved immediately, so an unexpected exit costs at
most the command in flight.
"""

from __future__ import annotations

import sys
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from campusflow import reports, storage
from campusflow.tickets import TicketStore, UnknownTicketError, ValidationError
from campusflow.workflow import WorkflowError, assign_ticket, change_status, work_queue

#: ``(key, menu label, handler method name or None for Exit)``.
OPTIONS: Tuple[Tuple[str, str, Optional[str]], ...] = (
    ("1", "Create a ticket", "_create_ticket"),
    ("2", "List all tickets", "_list_tickets"),
    ("3", "View one ticket in full", "_view_ticket"),
    ("4", "Assign a ticket to a staff member", "_assign_ticket"),
    ("5", "Update a ticket's status", "_update_status"),
    ("6", "Show the work queue (unresolved, most urgent first)", "_show_work_queue"),
    ("7", "Show reports", "_show_reports"),
    ("8", "Save now", "_save_now"),
    ("9", "Exit", None),
)

EXIT_KEY = "9"

BANNER = """\
=========================================
 CampusFlow - Learn2Earn campus helpdesk
=========================================
Record Wi-Fi outages, faulty laptops, broken dev environments and
platform access problems, and track them to resolution."""

#: Longest ticket title shown in the list table before it is elided.
TITLE_WIDTH = 44


def _menu_text() -> str:
    lines = ["", "Menu", "----"]
    lines.extend(f"  {key}. {label}" for key, label, _ in OPTIONS)
    return "\n".join(lines)


def _render_table(headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
    """Return a left-aligned fixed-width table as text."""
    cells = [[str(cell) for cell in row] for row in rows]
    widths = [len(header) for header in headers]
    for row in cells:
        for index, cell in enumerate(row):
            if index < len(widths):
                widths[index] = max(widths[index], len(cell))

    def render(line: Sequence[str]) -> str:
        return "  ".join(
            cell.ljust(widths[index]) for index, cell in enumerate(line)
        ).rstrip()

    output = [render(list(headers)), render(["-" * width for width in widths])]
    output.extend(render(row) for row in cells)
    return "\n".join(output)


def _elide(text: str, width: int = TITLE_WIDTH) -> str:
    return text if len(text) <= width else text[: width - 1] + "…"


class HelpdeskApp:
    """The interactive menu loop.

    The input function and output sink are injectable so the loop can be driven
    without a real terminal.
    """

    def __init__(
        self,
        store: TicketStore,
        path: Optional[str] = None,
        input_fn: Callable[[str], str] = input,
        out: Callable[[str], None] = print,
    ) -> None:
        self.store = store
        self.path = path
        self._input = input_fn
        self.out = out

    # -- plumbing -----------------------------------------------------------
    def _ask(self, prompt: str) -> str:
        return self._input(f"{prompt} ").strip()

    def _emit(self, text: str = "") -> None:
        self.out(text)

    def _persist(self, quiet: bool = False) -> None:
        """Write the store to disk; called after every successful change."""
        saved_to = storage.save_tickets(self.store.tickets, self.path)
        if not quiet:
            self._emit(f"Saved {len(self.store)} ticket(s) to {saved_to}")

    def _show_ticket(self, ticket: Dict[str, Any]) -> None:
        labels = {
            "id": "ID",
            "title": "Title",
            "category": "Category",
            "urgency": "Urgency",
            "affected_users": "Affected users",
            "priority": "Priority",
            "status": "Status",
            "assigned_to": "Assigned to",
        }
        self._emit("")
        for field, label in labels.items():
            value = ticket.get(field)
            if value is None:
                value = "(unassigned)" if field == "assigned_to" else "-"
            self._emit(f"  {label + ':':<16}{value}")

    # -- F1 create ----------------------------------------------------------
    def _create_ticket(self) -> None:
        self._emit("")
        self._emit("New ticket (press Ctrl+C to cancel)")
        title = self._ask("Title:")
        category = self._ask("Category (Network/Hardware/Software/Other):")
        urgency = self._ask("Urgency (low/medium/high):")
        affected = self._ask("Affected users:")
        ticket = self.store.create_ticket(title, category, urgency, affected)
        self._persist()
        self._emit(
            f"Created {ticket['id']} [{ticket['priority']}] "
            f"{ticket['title']} - status {ticket['status']}, unassigned."
        )

    # -- F2 list / view -----------------------------------------------------
    def _list_tickets(self) -> None:
        tickets = self.store.tickets
        self._emit("")
        if not tickets:
            self._emit("No tickets recorded yet. Use option 1 to create one.")
            return
        rows = [
            (
                t["id"],
                t["priority"],
                t["status"],
                t["category"],
                t["urgency"],
                t["affected_users"],
                t["assigned_to"] or "-",
                _elide(t["title"]),
            )
            for t in tickets
        ]
        headers = (
            "ID",
            "Priority",
            "Status",
            "Category",
            "Urgency",
            "Users",
            "Assigned to",
            "Title",
        )
        self._emit(_render_table(headers, rows))
        self._emit(f"\n{len(tickets)} ticket(s).")

    def _view_ticket(self) -> None:
        self._emit("")
        ticket = self.store.get(self._ask("Ticket id to view:"))
        self._show_ticket(ticket)
        self._emit("")

    # -- F3 assign ----------------------------------------------------------
    def _assign_ticket(self) -> None:
        self._emit("")
        ticket = self.store.get(self._ask("Ticket id to assign:"))
        self._emit(f"{ticket['id']} - {ticket['title']}")
        name = self._ask("Assign to (staff name):")
        assign_ticket(self.store, ticket["id"], name)
        self._persist()
        self._emit(f"{ticket['id']} is now assigned to {ticket['assigned_to']}.")

    # -- F4 workflow --------------------------------------------------------
    def _update_status(self) -> None:
        self._emit("")
        ticket = self.store.get(self._ask("Ticket id:"))
        self._emit(f"{ticket['id']} is currently {ticket['status']}.")
        self._emit("  1. Start work   (open -> in_progress)")
        self._emit("  2. Resolve      (in_progress -> resolved)")
        self._emit("  3. Reopen       (resolved -> open)")
        choice = self._ask("Choose 1, 2 or 3:")
        targets = {"1": "in_progress", "2": "resolved", "3": "open"}
        target = targets.get(choice)
        if target is None:
            raise WorkflowError(
                f"Unrecognised option {choice!r}; choose 1, 2 or 3."
            )
        change_status(self.store, ticket["id"], target)
        self._persist()
        self._emit(f"{ticket['id']} is now {ticket['status']}.")

    # -- F5 work queue ------------------------------------------------------
    def _show_work_queue(self) -> None:
        queue = work_queue(self.store)
        self._emit("")
        if not queue:
            self._emit("Nothing outstanding - the work queue is empty.")
            return
        rows = [
            (
                t["id"],
                t["priority"],
                t["status"],
                t["urgency"],
                t["affected_users"],
                t["assigned_to"] or "(unassigned)",
                _elide(t["title"]),
            )
            for t in queue
        ]
        headers = ("ID", "Priority", "Status", "Urgency", "Users", "Assigned to", "Title")
        self._emit("Work queue (unresolved tickets, most urgent first)")
        self._emit(_render_table(headers, rows))
        self._emit(f"\n{len(queue)} unresolved ticket(s).")

    # -- F6 reports ---------------------------------------------------------
    def _show_reports(self) -> None:
        self._emit("")
        self._emit(reports.format_summary(reports.summary(self.store.tickets)))

    # -- F7 persistence -----------------------------------------------------
    def _save_now(self) -> None:
        self._emit("")
        self._persist()

    # -- the loop -----------------------------------------------------------
    def _dispatch(self, key: str) -> bool:
        """Run the handler for ``key``; return True when the app should exit."""
        handlers = {option_key: method for option_key, _, method in OPTIONS}
        if key not in handlers:
            self._emit(f"Unrecognised option {key!r}. Enter a number from the menu.")
            return False
        method_name = handlers[key]
        if method_name is None:
            return True
        getattr(self, method_name)()
        return False

    def run(self) -> int:
        """Show the menu until the user exits. Returns a process exit code."""
        self._emit(BANNER)
        while True:
            self._emit(_menu_text())
            try:
                key = self._ask("Choose an option:")
            except (EOFError, KeyboardInterrupt):
                # Input stream closed or the user pressed Ctrl+C at the prompt.
                self._emit("")
                self._emit("Input closed - saving and exiting.")
                try:
                    self._persist(quiet=True)
                except storage.StorageError as exc:
                    self._emit(f"Warning: could not save on exit: {exc}")
                return 0

            try:
                if self._dispatch(key):
                    self._emit("")
                    self._emit("Goodbye.")
                    return 0
            except EOFError:
                # stdin ran out part-way through a command (piped input). Exit
                # cleanly rather than dumping a traceback at the user.
                self._emit("")
                self._emit("Input closed - saving and exiting.")
                try:
                    self._persist(quiet=True)
                except storage.StorageError as exc:
                    self._emit(f"Warning: could not save on exit: {exc}")
                return 0
            except UnknownTicketError as exc:
                self._emit(f"Error: {exc}")
            except (ValidationError, WorkflowError, storage.StorageError) as exc:
                self._emit(f"Error: {exc}")
            except KeyboardInterrupt:
                self._emit("")
                self._emit("Cancelled; nothing was changed.")


def main(argv: Optional[List[str]] = None) -> int:
    """Load the store and run the CLI. Returns a process exit code."""
    args = list(sys.argv[1:] if argv is None else argv)
    data_path = args[0] if args else None

    try:
        records = storage.load_tickets(data_path)
    except storage.StorageError as exc:
        # Refuse to start rather than risk overwriting a file we cannot read.
        print(f"Could not load tickets: {exc}", file=sys.stderr)
        print(
            "CampusFlow has not started, so the existing file is untouched.",
            file=sys.stderr,
        )
        return 1

    store = TicketStore(records)
    app = HelpdeskApp(store, path=data_path)
    return app.run()


if __name__ == "__main__":
    raise SystemExit(main())
