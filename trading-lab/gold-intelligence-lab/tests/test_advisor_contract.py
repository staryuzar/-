"""Adviser policy/contract tests; no price series or trade simulation."""
import ast
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))

from goldlab.advisor import build_advisory


class AdviserContractTests(unittest.TestCase):
    def test_missing_fresh_market_gate_blocks_advice(self):
        report = build_advisory({}, {})
        self.assertEqual(report["status"], "BLOCKED_DATA_QUALITY")
        self.assertFalse(report["trade_execution_enabled"])
        self.assertIsNone(report["entry_price"])
        self.assertIsNone(report["probability"])

    def test_adviser_source_has_no_order_execution_calls(self):
        source = (ROOT / "python" / "goldlab" / "advisor.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        attrs = {node.attr.lower() for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
        self.assertTrue({"order_send", "order_check", "orders_send", "position_close"}.isdisjoint(attrs))
        self.assertNotIn("TRADE_ACTION_DEAL", source)


if __name__ == "__main__":
    unittest.main()
