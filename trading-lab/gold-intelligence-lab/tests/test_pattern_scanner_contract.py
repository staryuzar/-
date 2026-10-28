"""Scanner contract checks without synthetic price series or trade simulation."""
import ast
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))

import pandas as pd
from goldlab.pattern_scanner import scan_market_structure
from goldlab.technical_rating import DataQualityError, TechnicalRatingError


class PatternScannerContractTests(unittest.TestCase):
    def test_scanner_rejects_unsupported_timeframe_and_empty_input(self):
        empty = pd.DataFrame(columns=["open", "high", "low", "close"])
        with self.assertRaises(TechnicalRatingError):
            scan_market_structure(empty, "M2")
        with self.assertRaises(DataQualityError):
            scan_market_structure(empty, "M1")

    def test_scanner_rejects_invalid_parameters(self):
        empty = pd.DataFrame(columns=["open", "high", "low", "close"])
        with self.assertRaises(ValueError):
            scan_market_structure(empty, "M1", lookback=10)
        with self.assertRaises(ValueError):
            scan_market_structure(empty, "M1", swing_left=0)

    def test_scanner_source_is_analysis_only(self):
        source = (ROOT / "python" / "goldlab" / "pattern_scanner.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        attributes = {node.attr.lower() for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
        self.assertTrue({"order_send", "order_check", "orders_send"}.isdisjoint(attributes))
        for forbidden in ("TRADE_ACTION_DEAL", "TRADE_ACTION_PENDING", "MetaTrader5"):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
