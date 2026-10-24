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
    def test_window_range_extracts_the_exact_inclusive_test_dates(self):
        summary = "Range 2026-09-07 to 2026-09-09 inclusive; MT5 Tester ToDate=2026.09.10"
        self.assertEqual(MODULE.window_range(summary), "2026-09-07 to 2026-09-09")

    def test_window_range_is_explicit_when_report_format_is_unknown(self):
        self.assertEqual(MODULE.window_range("No date metadata"), "window unknown")

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

    def test_summary_exit_passes_only_for_exact_paired_opposite_summary(self):
        trigger = "TV26_EXIT_TRIGGER;reason=OPPOSITE_SUMMARY;bar=2026.09.01 12:05;side=POSITION_TYPE_BUY;ticket=12345"
        completed = "TV26_EXIT_COMPLETED;reason=OPPOSITE_SUMMARY;bar=2026.09.01 12:05;ticket=12345"
        result = MODULE.classify_exit_events([trigger], [completed], [])
        self.assertTrue(result["valid_summary_only"])
        self.assertEqual(result["summary_paired"], 1)
        self.assertEqual(result["other_triggers"], [])

    def test_m1_price_reversal_cannot_pass_summary_only_diagnostic(self):
        trigger = "TV26_EXIT_TRIGGER;reason=REAL_M1_REVERSAL;bar=2026.09.01 12:05;side=POSITION_TYPE_BUY;ticket=12345"
        completed = "TV26_EXIT_COMPLETED;reason=REAL_M1_REVERSAL;bar=2026.09.01 12:05;ticket=12345"
        result = MODULE.classify_exit_events([trigger], [completed], [])
        self.assertFalse(result["valid_summary_only"])
        self.assertEqual(result["summary_triggers"], [])
        self.assertEqual(result["other_triggers"], [trigger])

    def test_summary_exit_without_exact_same_bar_close_does_not_pass(self):
        trigger = "TV26_EXIT_TRIGGER;reason=OPPOSITE_SUMMARY;bar=2026.09.01 12:05;side=POSITION_TYPE_BUY;ticket=12345"
        completed = "TV26_EXIT_COMPLETED;reason=OPPOSITE_SUMMARY;bar=2026.09.01 12:06;ticket=12345"
        result = MODULE.classify_exit_events([trigger], [completed], [])
        self.assertFalse(result["valid_summary_only"])
        self.assertEqual(result["summary_paired"], 0)

    def test_summary_exit_with_failed_close_does_not_pass(self):
        trigger = "TV26_EXIT_TRIGGER;reason=OPPOSITE_SUMMARY;bar=2026.09.01 12:05;side=POSITION_TYPE_BUY;ticket=12345"
        completed = "TV26_EXIT_COMPLETED;reason=OPPOSITE_SUMMARY;bar=2026.09.01 12:05;ticket=12345"
        failed = "TV26_EXIT_FAILED;reason=OPPOSITE_SUMMARY;bar=2026.09.01 12:05;ticket=12345"
        result = MODULE.classify_exit_events([trigger], [completed], [failed])
        self.assertFalse(result["valid_summary_only"])

    def test_zero_summary_triggers_is_not_a_pass(self):
        result = MODULE.classify_exit_events([], [], [])
        self.assertFalse(result["valid_summary_only"])
        self.assertEqual(result["summary_triggers"], [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
