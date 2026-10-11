"""Tests for assignment, the status lifecycle and the work queue."""

import unittest

from campusflow.tickets import TicketStore, UnknownTicketError
from campusflow.workflow import (
    WorkflowError,
    assign_ticket,
    change_status,
    reopen_ticket,
    resolve_ticket,
    start_ticket,
    validate_staff_name,
    work_queue,
)


def make_store():
    """A store with three tickets in known states."""
    store = TicketStore()
    store.create_ticket("Campus Wi-Fi is down", "Network", "high", 15)   # T001 critical
    store.create_ticket("Projector flickers", "Hardware", "low", 2)     # T002 low
    store.create_ticket("Lab PCs cannot reach Git", "Software", "high", 4)  # T003 high
    return store


class AssignmentTests(unittest.TestCase):
    def test_assign_records_a_trimmed_name(self):
        store = make_store()
        ticket = assign_ticket(store, "T001", "  Ada Lovelace  ")
        self.assertEqual(ticket["assigned_to"], "Ada Lovelace")

    def test_assign_accepts_a_loosely_formatted_id(self):
        store = make_store()
        self.assertEqual(assign_ticket(store, "t2", "Grace Hopper")["id"], "T002")

    def test_assign_can_be_changed(self):
        store = make_store()
        assign_ticket(store, "T001", "Ada Lovelace")
        self.assertEqual(assign_ticket(store, "T001", "Alan Turing")["assigned_to"], "Alan Turing")

    def test_blank_staff_name_is_rejected_and_changes_nothing(self):
        store = make_store()
        for value in ("", "   ", "\t"):
            with self.subTest(value=value):
                with self.assertRaises(WorkflowError):
                    assign_ticket(store, "T001", value)
        self.assertIsNone(store.get("T001")["assigned_to"])

    def test_unknown_ticket_id_is_rejected(self):
        store = make_store()
        with self.assertRaises(UnknownTicketError):
            assign_ticket(store, "T999", "Ada Lovelace")

    def test_staff_name_is_not_validated_against_a_list(self):
        # Any non-empty human name is fine; this is not an account system.
        self.assertEqual(validate_staff_name("O'Brien, M."), "O'Brien, M.")


class LifecycleTests(unittest.TestCase):
    def test_unassigned_ticket_cannot_start(self):
        store = make_store()
        with self.assertRaises(WorkflowError) as ctx:
            start_ticket(store, "T001")
        self.assertIn("unassigned", str(ctx.exception).lower())
        self.assertEqual(store.get("T001")["status"], "open")  # unchanged

    def test_assigned_ticket_progresses_open_in_progress_resolved(self):
        store = make_store()
        assign_ticket(store, "T001", "Ada Lovelace")

        self.assertEqual(start_ticket(store, "T001")["status"], "in_progress")
        self.assertEqual(resolve_ticket(store, "T001")["status"], "resolved")

    def test_open_cannot_jump_straight_to_resolved(self):
        store = make_store()
        assign_ticket(store, "T001", "Ada Lovelace")
        with self.assertRaises(WorkflowError) as ctx:
            resolve_ticket(store, "T001")
        self.assertIn("Invalid transition", str(ctx.exception))
        self.assertEqual(store.get("T001")["status"], "open")

    def test_resolved_ticket_is_frozen_until_reopened(self):
        store = make_store()
        assign_ticket(store, "T001", "Ada Lovelace")
        start_ticket(store, "T001")
        resolve_ticket(store, "T001")

        with self.assertRaises(WorkflowError):
            start_ticket(store, "T001")
        with self.assertRaises(WorkflowError):
            resolve_ticket(store, "T001")
        with self.assertRaises(WorkflowError):
            assign_ticket(store, "T001", "Someone Else")

        self.assertEqual(store.get("T001")["status"], "resolved")
        self.assertEqual(store.get("T001")["assigned_to"], "Ada Lovelace")

    def test_reopening_sets_the_status_back_to_open(self):
        store = make_store()
        assign_ticket(store, "T001", "Ada Lovelace")
        start_ticket(store, "T001")
        resolve_ticket(store, "T001")

        self.assertEqual(reopen_ticket(store, "T001")["status"], "open")
        # A reopened ticket is workable again.
        self.assertEqual(start_ticket(store, "T001")["status"], "in_progress")

    def test_only_resolved_tickets_can_be_reopened(self):
        store = make_store()
        # T001 is in progress, so reopening it is not a legal move.
        assign_ticket(store, "T001", "Ada Lovelace")
        start_ticket(store, "T001")
        with self.assertRaises(WorkflowError) as ctx:
            reopen_ticket(store, "T001")
        self.assertIn("reopened", str(ctx.exception))
        self.assertIn("in_progress", str(ctx.exception))

        # T002 is open, so there is nothing to reopen.
        with self.assertRaises(WorkflowError) as ctx:
            reopen_ticket(store, "T002")
        self.assertIn("already open", str(ctx.exception))

        self.assertEqual(store.get("T001")["status"], "in_progress")
        self.assertEqual(store.get("T002")["status"], "open")

    def test_setting_the_current_status_again_is_rejected(self):
        store = make_store()
        with self.assertRaises(WorkflowError) as ctx:
            change_status(store, "T001", "open")
        self.assertIn("already open", str(ctx.exception))

    def test_unknown_status_is_rejected(self):
        store = make_store()
        for value in ("done", "closed", "", "in progress"):
            with self.subTest(value=value):
                with self.assertRaises(WorkflowError):
                    change_status(store, "T001", value)

    def test_unknown_ticket_id_is_rejected(self):
        store = make_store()
        with self.assertRaises(UnknownTicketError):
            start_ticket(store, "T042")

    def test_status_is_case_insensitive(self):
        store = make_store()
        assign_ticket(store, "T001", "Ada Lovelace")
        self.assertEqual(change_status(store, "T001", "IN_PROGRESS")["status"], "in_progress")


class WorkQueueTests(unittest.TestCase):
    def test_queue_is_ordered_by_priority(self):
        store = make_store()
        # T002 (low) is resolved, so it must disappear from the queue.
        assign_ticket(store, "T002", "Ada Lovelace")
        start_ticket(store, "T002")
        resolve_ticket(store, "T002")

        self.assertEqual([t["id"] for t in work_queue(store)], ["T001", "T003"])

    def test_queue_covers_every_priority_band(self):
        store = TicketStore()
        store.create_ticket("Critical", "Network", "high", 12)      # T001 critical
        store.create_ticket("High", "Network", "high", 2)           # T002 high
        store.create_ticket("Medium", "Network", "low", 4)          # T003 medium
        store.create_ticket("Low", "Network", "low", 1)             # T004 low

        self.assertEqual(
            [t["id"] for t in work_queue(store)], ["T001", "T002", "T003", "T004"]
        )

    def test_queue_excludes_resolved_tickets_only(self):
        store = make_store()
        assign_ticket(store, "T003", "Ada Lovelace")
        start_ticket(store, "T003")

        statuses = {t["id"]: t["status"] for t in work_queue(store)}
        self.assertEqual(statuses, {"T001": "open", "T003": "in_progress"})

    def test_queue_ties_break_on_the_earlier_numeric_id(self):
        # Same priority, and ids whose *string* order (T010 < T9) differs from
        # their numeric order (9 < 10). The queue must use the numbers.
        store = TicketStore(
            [
                {"id": "T010", "priority": "medium", "status": "open"},
                {"id": "T009", "priority": "medium", "status": "open"},
                {"id": "T002", "priority": "medium", "status": "open"},
            ]
        )
        self.assertEqual([t["id"] for t in work_queue(store)], ["T002", "T009", "T010"])

    def test_empty_queue_is_returned_for_a_fresh_store(self):
        self.assertEqual(work_queue(TicketStore()), [])

    def test_queue_does_not_disturb_the_store_order(self):
        store = make_store()
        work_queue(store)
        self.assertEqual([t["id"] for t in store.tickets], ["T001", "T002", "T003"])


if __name__ == "__main__":
    unittest.main()
