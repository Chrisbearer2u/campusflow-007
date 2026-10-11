"""Tests for JSON persistence: round trips, missing files, corruption, atomicity."""

import json
import tempfile
import unittest
from pathlib import Path

from campusflow import storage
from campusflow.storage import StorageError, load_tickets, save_tickets
from campusflow.tickets import TicketStore
from campusflow.workflow import assign_ticket, start_ticket


def record(ticket_id, **overrides):
    """A complete, valid stored ticket, with fields overridable per test."""
    ticket = {
        "id": ticket_id,
        "title": f"Ticket {ticket_id}",
        "category": "Network",
        "urgency": "low",
        "affected_users": 1,
        "priority": "low",
        "status": "open",
        "assigned_to": None,
    }
    ticket.update(overrides)
    return ticket


class TempStoreTestCase(unittest.TestCase):
    """Gives every test its own directory, so nothing touches real data."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.directory = Path(self._tmp.name)
        self.path = self.directory / "data" / "tickets.json"


class LoadTests(TempStoreTestCase):
    def test_missing_file_starts_an_empty_store(self):
        self.assertEqual(load_tickets(self.path), [])
        self.assertFalse(self.path.exists())  # reading never creates the file

    def test_blank_file_starts_an_empty_store(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text("\n   \n", encoding="utf-8")
        self.assertEqual(load_tickets(self.path), [])

    def test_corrupt_json_raises_without_touching_the_file(self):
        self.path.parent.mkdir(parents=True)
        corrupt = '{"id": "T001", "title": "unterminated'
        self.path.write_text(corrupt, encoding="utf-8")

        with self.assertRaises(StorageError) as ctx:
            load_tickets(self.path)

        message = str(ctx.exception)
        self.assertIn("not valid JSON", message)
        self.assertIn(str(self.path), message)
        # The bad file is exactly as it was - nothing was overwritten or erased.
        self.assertEqual(self.path.read_text(encoding="utf-8"), corrupt)

    def test_non_list_json_is_rejected(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text('{"tickets": []}', encoding="utf-8")
        with self.assertRaises(StorageError) as ctx:
            load_tickets(self.path)
        self.assertIn("list", str(ctx.exception))

    def test_record_missing_a_field_is_rejected(self):
        self.path.parent.mkdir(parents=True)
        broken = record("T001")
        del broken["priority"]
        self.path.write_text(json.dumps([broken]), encoding="utf-8")

        with self.assertRaises(StorageError) as ctx:
            load_tickets(self.path)
        self.assertIn("priority", str(ctx.exception))

    def test_record_with_a_bad_value_is_rejected(self):
        cases = (
            {"affected_users": 0},
            {"affected_users": 2.5},
            {"status": "closed"},
            {"priority": "urgent"},
            {"category": "Power"},
            {"urgency": "critical"},
            {"title": "   "},
            {"assigned_to": ""},
        )
        for overrides in cases:
            with self.subTest(overrides=overrides):
                self.path.parent.mkdir(parents=True, exist_ok=True)
                payload = [record("T001", **overrides)]
                self.path.write_text(json.dumps(payload), encoding="utf-8")
                with self.assertRaises(StorageError):
                    load_tickets(self.path)

    def test_non_canonical_id_is_rejected(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text(json.dumps([record("T1")]), encoding="utf-8")
        with self.assertRaises(StorageError) as ctx:
            load_tickets(self.path)
        self.assertIn("non-canonical", str(ctx.exception))

    def test_extra_fields_are_dropped_on_load(self):
        self.path.parent.mkdir(parents=True)
        payload = [record("T001", notes="scratch field", reporter="ops")]
        self.path.write_text(json.dumps(payload), encoding="utf-8")

        loaded = load_tickets(self.path)
        self.assertEqual(list(loaded[0]), list(storage.TICKET_FIELDS))


class SaveTests(TempStoreTestCase):
    def test_save_and_reload_preserves_every_ticket(self):
        store = TicketStore()
        store.create_ticket("Campus Wi-Fi is down", "Network", "high", 15)
        store.create_ticket("Laptop won't boot", "Hardware", "medium", 2)

        save_tickets(store.tickets, self.path)
        reloaded = load_tickets(self.path)

        self.assertEqual(reloaded, store.tickets)
        self.assertEqual(
            reloaded[0],
            {
                "id": "T001",
                "title": "Campus Wi-Fi is down",
                "category": "Network",
                "urgency": "high",
                "affected_users": 15,
                "priority": "critical",
                "status": "open",
                "assigned_to": None,
            },
        )

    def test_save_creates_the_data_directory(self):
        self.assertFalse(self.path.parent.exists())
        save_tickets([record("T001")], self.path)
        self.assertTrue(self.path.is_file())

    def test_saved_file_is_readable_json(self):
        save_tickets([record("T001")], self.path)
        with self.path.open(encoding="utf-8") as handle:
            self.assertEqual(json.load(handle), [record("T001")])

    def test_save_leaves_no_temporary_files_behind(self):
        save_tickets([record("T001")], self.path)
        save_tickets([record("T001"), record("T002")], self.path)

        leftovers = [p.name for p in self.path.parent.iterdir() if p.name != self.path.name]
        self.assertEqual(leftovers, [], f"temporary files left behind: {leftovers}")

    def test_save_overwrites_cleanly_rather_than_appending(self):
        save_tickets([record("T001"), record("T002")], self.path)
        save_tickets([record("T001")], self.path)
        self.assertEqual([t["id"] for t in load_tickets(self.path)], ["T001"])

    def test_saving_an_empty_store_writes_an_empty_list(self):
        save_tickets([], self.path)
        self.assertEqual(load_tickets(self.path), [])

    def test_unicode_survives_a_round_trip(self):
        store = TicketStore()
        store.create_ticket("Café till Wi-Fi — intermittent", "Network", "low", 1)
        save_tickets(store.tickets, self.path)
        self.assertEqual(load_tickets(self.path)[0]["title"], "Café till Wi-Fi — intermittent")


class PersistenceAcrossRestartTests(TempStoreTestCase):
    """The checks that matter when the process stops and starts again."""

    def test_reload_preserves_status_assignment_and_priority(self):
        store = TicketStore()
        store.create_ticket("Campus Wi-Fi is down", "Network", "high", 15)
        store.create_ticket("Broken dev env", "Software", "medium", 4)
        save_tickets(store.tickets, self.path)

        # Simulate a restart: fresh store built from what is on disk.
        restarted = TicketStore(load_tickets(self.path))
        assign_ticket(restarted, "T001", "Ada Lovelace")
        start_ticket(restarted, "T001")
        save_tickets(restarted.tickets, self.path)

        final = TicketStore(load_tickets(self.path))
        self.assertEqual(final.get("T001")["status"], "in_progress")
        self.assertEqual(final.get("T001")["assigned_to"], "Ada Lovelace")
        self.assertEqual(final.get("T001")["priority"], "critical")
        self.assertEqual(len(final), 2)

    def test_creating_a_ticket_after_reload_does_not_duplicate_ids(self):
        store = TicketStore()
        store.create_ticket("First", "Network", "high", 15)
        store.create_ticket("Second", "Hardware", "low", 1)
        save_tickets(store.tickets, self.path)

        restarted = TicketStore(load_tickets(self.path))
        created = restarted.create_ticket("Third", "Other", "low", 2)
        save_tickets(restarted.tickets, self.path)

        final = load_tickets(self.path)
        ids = [t["id"] for t in final]
        self.assertEqual(created["id"], "T003")
        self.assertEqual(ids, ["T001", "T002", "T003"])
        self.assertEqual(len(set(ids)), len(ids), "ticket ids must stay unique")

    def test_blank_path_falls_back_to_the_default_location(self):
        # Guards the "no argument means data/tickets.json" contract.
        self.assertEqual(storage.resolve_path(None), storage.DEFAULT_DATA_PATH)
        self.assertEqual(storage.DEFAULT_DATA_PATH.name, "tickets.json")
        self.assertEqual(storage.DEFAULT_DATA_PATH.parent.name, "data")


if __name__ == "__main__":
    unittest.main()
