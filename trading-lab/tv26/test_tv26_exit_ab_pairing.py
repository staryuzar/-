#!/usr/bin/env python3
"""Deterministic tests for matching TV26 early-exit trigger and completion logs."""
import importlib.util
from pathlib import Path
import unittest

SCRIPT = Path(__file__).with_name("compare_tv26_exit_ab.py")
SPEC = importlib.util.spec_from_file_location("tv26_exit_ab", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class ExitEventPairingTests(unittest.TestCase):
    def test_exact_same_ticket_reason_and_bar_pairs(self):
        trigger = "TV26_EXIT_TRIGGER;reason=OPPOSITE_SUMMARY;bar=2026.09.01 12:05;side=POSITION_TYPE_BUY;ticket=12345"
        completed = "TV26_EXIT_COMPLETED;reason=OPPOSITE_SUMMARY;bar=2026.09.01 12:05;ticket=12345"
        self.assertEqual(MODULE.event_key(trigger), MODULE.event_key(completed))

    def test_same_ticket_but_different_bar_does_not_pair(self):
        trigger = "TV26_EXIT_TRIGGER;reason=OPPOSITE_SUMMARY;bar=2026.09.01 12:05;ticket=12345"
        completed = "TV26_EXIT_COMPLETED;reason=OPPOSITE_SUMMARY;bar=2026.09.01 12:06;ticket=12345"
        self.assertNotEqual(MODULE.event_key(trigger), MODULE.event_key(completed))

    def test_same_ticket_and_bar_but_different_reason_does_not_pair(self):
        trigger = "TV26_EXIT_TRIGGER;reason=REAL_M1_REVERSAL;bar=2026.09.01 12:05;ticket=12345"
        completed = "TV26_EXIT_COMPLETED;reason=OPPOSITE_SUMMARY;bar=2026.09.01 12:05;ticket=12345"
        self.assertNotEqual(MODULE.event_key(trigger), MODULE.event_key(completed))

    def test_missing_bar_or_ticket_is_not_pairable(self):
        self.assertIsNone(MODULE.event_key("TV26_EXIT_TRIGGER;reason=REAL_M1_REVERSAL;ticket=12345"))
        self.assertIsNone(MODULE.event_key("TV26_EXIT_COMPLETED;reason=REAL_M1_REVERSAL;bar=2026.09.01 12:05"))

    def test_repeated_trigger_cannot_borrow_later_close(self):
        first = "TV26_EXIT_TRIGGER;reason=OPPOSITE_SUMMARY;bar=2026.09.01 12:05;ticket=12345"
        second = "TV26_EXIT_TRIGGER;reason=OPPOSITE_SUMMARY;bar=2026.09.01 12:06;ticket=12345"
        close = "TV26_EXIT_COMPLETED;reason=OPPOSITE_SUMMARY;bar=2026.09.01 12:06;ticket=12345"
        close_key = MODULE.event_key(close)
        self.assertNotEqual(MODULE.event_key(first), close_key)
        self.assertEqual(MODULE.event_key(second), close_key)


if __name__ == "__main__":
    unittest.main(verbosity=2)
