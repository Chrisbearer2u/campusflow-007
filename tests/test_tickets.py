"""Tests for the ticket model: validation, priority rules and id generation."""

import unittest

from campusflow.tickets import (
    CATEGORIES,
    PRIORITIES,
    TicketStore,
    UnknownTicketError,
    ValidationError,
    compute_priority,
    format_ticket_id,
    normalize_category,
    normalize_ticket_id,
    normalize_urgency,
    parse_affected_users,
    parse_ticket_number,
    validate_title,
)


class PriorityRuleTests(unittest.TestCase):
    """The four documented rules, in order, plus their boundaries."""

    def test_high_urgency_and_twelve_users_is_critical(self):
        self.assertEqual(compute_priority("high", 12), "critical")

    def test_high_urgency_and_two_users_is_high(self):
        self.assertEqual(compute_priority("high", 2), "high")

    def test_low_urgency_and_four_users_is_medium(self):
        self.assertEqual(compute_priority("low", 4), "medium")

    def test_low_urgency_and_one_user_is_low(self):
        self.assertEqual(compute_priority("low", 1), "low")

    def test_boundary_ten_users_with_high_urgency_is_critical(self):
        # >= 10, not > 10: exactly ten must already be critical.
        self.assertEqual(compute_priority("high", 10), "critical")

    def test_boundary_ten_users_with_low_urgency_is_high(self):
        # Rule 2 catches the user count alone, whatever the urgency.
        self.assertEqual(compute_priority("low", 10), "high")

    def test_boundary_ten_users_with_medium_urgency_is_high(self):
        self.assertEqual(compute_priority("medium", 10), "high")

    def test_boundary_three_users_with_medium_urgency_is_medium(self):
        self.assertEqual(compute_priority("medium", 3), "medium")

    def test_boundary_two_users_with_medium_urgency_is_medium(self):
        # Medium urgency alone satisfies rule 3, even below the user threshold.
        self.assertEqual(compute_priority("medium", 2), "medium")

    def test_rule_order_high_urgency_beats_user_count(self):
        # Both rules could fire; the earlier one (critical) must win.
        self.assertEqual(compute_priority("high", 500), "critical")

    def test_priority_is_always_a_known_value(self):
        for urgency in ("low", "medium", "high"):
            for users in (1, 2, 3, 9, 10, 11, 99):
                with self.subTest(urgency=urgency, users=users):
                    self.assertIn(compute_priority(urgency, users), PRIORITIES)

    def test_priority_accepts_uppercase_urgency(self):
        self.assertEqual(compute_priority("HIGH", 12), "critical")

    def test_priority_rejects_unknown_urgency(self):
        with self.assertRaises(ValidationError):
            compute_priority("urgent", 5)

    def test_priority_rejects_zero_users(self):
        with self.assertRaises(ValidationError):
            compute_priority("low", 0)


class AffectedUsersTests(unittest.TestCase):
    """Affected users must be a positive whole number, and nothing else."""

    def test_accepts_positive_integer(self):
        self.assertEqual(parse_affected_users(15), 15)

    def test_accepts_integer_text_with_padding(self):
        self.assertEqual(parse_affected_users("  12  "), 12)

    def test_rejects_zero(self):
        with self.assertRaises(ValidationError):
            parse_affected_users(0)

    def test_rejects_negative(self):
        with self.assertRaises(ValidationError):
            parse_affected_users(-3)

    def test_rejects_decimal(self):
        with self.assertRaises(ValidationError):
            parse_affected_users(2.5)

    def test_rejects_whole_float(self):
        # 2.0 is still a decimal as far as the spec is concerned.
        with self.assertRaises(ValidationError):
            parse_affected_users(2.0)

    def test_rejects_text(self):
        with self.assertRaises(ValidationError):
            parse_affected_users("lots")

    def test_rejects_booleans(self):
        for value in (True, False):
            with self.subTest(value=value):
                with self.assertRaises(ValidationError):
                    parse_affected_users(value)

    def test_rejects_other_junk(self):
        for value in ("", " ", "2.5", "1e3", "3 users", None, [], {}):
            with self.subTest(value=value):
                with self.assertRaises(ValidationError):
                    parse_affected_users(value)

    def test_error_message_names_the_problem(self):
        with self.assertRaises(ValidationError) as ctx:
            parse_affected_users("0")
        self.assertIn("greater than zero", str(ctx.exception))


class TitleAndVocabularyTests(unittest.TestCase):
    def test_title_is_stripped(self):
        self.assertEqual(validate_title("  Wi-Fi down  "), "Wi-Fi down")

    def test_blank_title_rejected(self):
        for value in ("", "   ", "\t\n"):
            with self.subTest(value=value):
                with self.assertRaises(ValidationError):
                    validate_title(value)

    def test_non_text_title_rejected(self):
        with self.assertRaises(ValidationError):
            validate_title(None)

    def test_category_is_normalised_case_insensitively(self):
        for raw, expected in (
            ("network", "Network"),
            ("NETWORK", "Network"),
            ("  Hardware ", "Hardware"),
            ("software", "Software"),
            ("other", "Other"),
        ):
            with self.subTest(raw=raw):
                self.assertEqual(normalize_category(raw), expected)

    def test_unknown_category_rejected(self):
        with self.assertRaises(ValidationError) as ctx:
            normalize_category("Power")
        self.assertIn("Unknown category", str(ctx.exception))

    def test_urgency_is_normalised_to_lowercase(self):
        for raw, expected in (("HIGH", "high"), (" Medium ", "medium"), ("low", "low")):
            with self.subTest(raw=raw):
                self.assertEqual(normalize_urgency(raw), expected)

    def test_invalid_urgency_rejected(self):
        with self.assertRaises(ValidationError):
            normalize_urgency("critical")

    def test_category_list_is_the_documented_one(self):
        self.assertEqual(CATEGORIES, ("Network", "Hardware", "Software", "Other"))


class TicketIdTests(unittest.TestCase):
    def test_format_pads_to_three_digits(self):
        self.assertEqual(format_ticket_id(1), "T001")
        self.assertEqual(format_ticket_id(42), "T042")
        self.assertEqual(format_ticket_id(1234), "T1234")

    def test_normalize_accepts_loose_input(self):
        self.assertEqual(normalize_ticket_id("t7"), "T007")
        self.assertEqual(normalize_ticket_id(" T007 "), "T007")

    def test_parse_rejects_malformed_ids(self):
        for value in ("", "001", "T", "T00A", None, "T-1"):
            with self.subTest(value=value):
                with self.assertRaises(ValidationError):
                    parse_ticket_number(value)

    def test_numeric_parse_ignores_padding(self):
        self.assertEqual(parse_ticket_number("T010"), parse_ticket_number("T10"))


class TicketStoreTests(unittest.TestCase):
    def test_create_assigns_sequential_ids(self):
        store = TicketStore()
        first = store.create_ticket("Wi-Fi down", "network", "high", 15)
        second = store.create_ticket("Laptop dead", "hardware", "low", 1)
        self.assertEqual([first["id"], second["id"]], ["T001", "T002"])

    def test_new_ticket_defaults(self):
        store = TicketStore()
        ticket = store.create_ticket("Campus Wi-Fi is down", "Network", "high", 15)
        self.assertEqual(
            ticket,
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

    def test_create_normalises_input(self):
        store = TicketStore()
        ticket = store.create_ticket("  VPN broken ", "SOFTWARE", "HIGH", "12")
        self.assertEqual(ticket["title"], "VPN broken")
        self.assertEqual(ticket["category"], "Software")
        self.assertEqual(ticket["urgency"], "high")
        self.assertEqual(ticket["affected_users"], 12)

    def test_invalid_input_leaves_the_store_untouched(self):
        store = TicketStore()
        store.create_ticket("Wi-Fi down", "Network", "high", 15)

        for args in (
            ("   ", "Network", "high", 1),
            ("Blank users", "Network", "high", 0),
            ("Bad category", "Power", "high", 1),
            ("Bad urgency", "Network", "urgent", 1),
            ("Bad users", "Network", "high", "many"),
        ):
            with self.subTest(args=args):
                with self.assertRaises(ValidationError):
                    store.create_ticket(*args)

        self.assertEqual(len(store), 1)  # nothing was added
        # ...and no id was consumed: the next ticket is still T002.
        self.assertEqual(store.create_ticket("Printer jam", "Hardware", "low", 2)["id"], "T002")

    def test_ids_continue_after_a_reload(self):
        records = [
            {"id": "T001", "title": "One", "category": "Network", "urgency": "low",
             "affected_users": 1, "priority": "low", "status": "open", "assigned_to": None},
            {"id": "T002", "title": "Two", "category": "Network", "urgency": "low",
             "affected_users": 1, "priority": "low", "status": "open", "assigned_to": None},
        ]
        store = TicketStore(records)
        self.assertEqual(store.create_ticket("Three", "Other", "low", 1)["id"], "T003")

    def test_ids_do_not_reuse_gaps_after_reload(self):
        # Highest id wins, so a deleted ticket can never have its id reused.
        records = [{"id": "T001", "status": "open"}, {"id": "T007", "status": "resolved"}]
        store = TicketStore(records)
        self.assertEqual(store.create_ticket("Next", "Other", "low", 1)["id"], "T008")

    def test_duplicate_ids_in_loaded_data_are_rejected(self):
        records = [{"id": "T001"}, {"id": "T001"}]
        with self.assertRaises(ValidationError):
            TicketStore(records)

    def test_get_normalises_the_id(self):
        store = TicketStore()
        created = store.create_ticket("Wi-Fi down", "Network", "high", 15)
        self.assertIs(store.get("t1"), created)
        self.assertIs(store.get(" T001 "), created)

    def test_get_unknown_id_raises(self):
        store = TicketStore()
        for value in ("T999", "T001", "nonsense", ""):
            with self.subTest(value=value):
                with self.assertRaises(UnknownTicketError):
                    store.get(value)

    def test_tickets_are_ordered_by_number(self):
        records = [{"id": "T010", "status": "open"}, {"id": "T002", "status": "open"}]
        store = TicketStore(records)
        self.assertEqual([t["id"] for t in store.tickets], ["T002", "T010"])

    def test_contains_handles_bad_input(self):
        store = TicketStore()
        store.create_ticket("Wi-Fi down", "Network", "high", 15)
        self.assertIn("T001", store)
        self.assertIn("t1", store)
        self.assertNotIn("T002", store)
        self.assertNotIn("nonsense", store)


if __name__ == "__main__":
    unittest.main()
