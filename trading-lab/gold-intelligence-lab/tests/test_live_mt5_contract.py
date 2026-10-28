"""Read-only MT5 adapter contracts. No terminal connection or price fixtures are used."""
import ast
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))

from goldlab.live_mt5 import CLOSED_BAR_START_POSITION, MIN_HISTORY_BARS, TIMEFRAME_SECONDS, _validate_request


class LiveMT5ReadOnlyContractTests(unittest.TestCase):
    def test_supported_timeframes_are_explicit(self):
        self.assertEqual(set(TIMEFRAME_SECONDS), {"M1", "M5", "M15", "M30", "H1"})

    def test_adapter_reads_from_last_completed_bar(self):
        self.assertEqual(CLOSED_BAR_START_POSITION, 1)
        source = (ROOT / "python" / "goldlab" / "live_mt5.py").read_text(encoding="utf-8")
        self.assertIn("copy_rates_from_pos(", source)
        self.assertIn("symbol, mt5_tf, CLOSED_BAR_START_POSITION, bars_count", source)

    def test_request_validation_rejects_unsupported_timeframe_and_short_history(self):
        with self.assertRaises(ValueError):
            _validate_request("XAUUSD", "M2", MIN_HISTORY_BARS, 120)
        with self.assertRaises(ValueError):
            _validate_request("XAUUSD", "M1", MIN_HISTORY_BARS - 1, 120)

    def test_request_validation_normalizes_symbol_and_timeframe(self):
        self.assertEqual(_validate_request(" XAUUSD ", "m1", 260, 120), ("XAUUSD", "M1", 60))

    def test_blank_symbol_and_invalid_quote_age_are_rejected(self):
        with self.assertRaises(ValueError):
            _validate_request(" ", "M1", 260, 120)
        with self.assertRaises(ValueError):
            _validate_request("XAUUSD", "M1", 260, 0)

    def test_multi_timeframe_request_rejects_duplicates_and_unknown_frames(self):
        source = (ROOT / "python" / "goldlab" / "live_mt5.py").read_text(encoding="utf-8")
        self.assertIn("def analyze_live_mt5_multi(", source)
        self.assertIn("snapshot_captured_at_utc", source)
        self.assertIn("snapshot_time_consistent", source)
        self.assertIn("symbol_info_tick(clean_symbol)", source)
        self.assertIn("mt5.initialize(**args)", source)

    def test_multi_timeframe_analysis_uses_one_initialization_and_quote_call_site(self):
        source = (ROOT / "python" / "goldlab" / "live_mt5.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        function = next(node for node in tree.body
                        if isinstance(node, ast.FunctionDef) and node.name == "analyze_live_mt5_multi")
        calls = [
            node.func.attr for node in ast.walk(function)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        ]
        self.assertEqual(calls.count("initialize"), 1)
        self.assertEqual(calls.count("symbol_info_tick"), 1)
        self.assertEqual(calls.count("shutdown"), 1)
        self.assertGreaterEqual(calls.count("copy_rates_from_pos"), 1)

    def test_shared_snapshot_preserves_fail_closed_future_timestamp_guards(self):
        source = (ROOT / "python" / "goldlab" / "live_mt5.py").read_text(encoding="utf-8")
        self.assertIn("quote_age < -30", source)
        self.assertIn("bar_age < -30", source)
        self.assertIn("current-market review is blocked", source)

    def test_module_has_no_eager_terminal_import_or_order_write_calls(self):
        source = (ROOT / "python" / "goldlab" / "live_mt5.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported_roots = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_roots.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_roots.add(node.module.split(".")[0])
        self.assertNotIn("MetaTrader5", imported_roots)
        attrs = {node.attr.lower() for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
        self.assertTrue({"order_send", "order_check", "orders_send"}.isdisjoint(attrs))
        self.assertNotIn("TRADE_ACTION_DEAL", source)
        self.assertNotIn("TRADE_ACTION_PENDING", source)


if __name__ == "__main__":
    unittest.main()
