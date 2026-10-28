"""Contract tests for the analysis-only TV26 engine.

These tests verify API/schema and policy boundaries only. They do not run a
market simulation, create synthetic market prices, or assess profitability.
"""
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))

import pandas as pd
from goldlab.technical_rating import (
    COMPONENTS,
    MA_COMPONENTS,
    OSCILLATOR_COMPONENTS,
    DataQualityError,
    TechnicalRatingError,
    analyze_ohlcv,
    rating_category,
)

class TV26EngineContractTests(unittest.TestCase):
    def test_inventory_is_26_components_split_15_and_11(self):
        self.assertEqual(len(COMPONENTS), 26)
        self.assertEqual(len({item.key for item in COMPONENTS}), 26)
        self.assertEqual(len(MA_COMPONENTS), 15)
        self.assertEqual(len(OSCILLATOR_COMPONENTS), 11)

    def test_published_rating_category_boundaries(self):
        self.assertEqual(rating_category(-0.500001), "بيع قوي")
        self.assertEqual(rating_category(-0.5), "بيع")
        self.assertEqual(rating_category(-0.1), "حياد")
        self.assertEqual(rating_category(0.1), "حياد")
        self.assertEqual(rating_category(0.100001), "شراء")
        self.assertEqual(rating_category(0.5), "شراء")
        self.assertEqual(rating_category(0.500001), "شراء قوي")
        self.assertEqual(rating_category(None), "غير متاح")

    def test_empty_market_input_is_rejected_not_filled(self):
        empty = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        with self.assertRaises(DataQualityError):
            analyze_ohlcv(empty, "M1")

    def test_missing_volume_is_rejected(self):
        empty = pd.DataFrame(columns=["open", "high", "low", "close"])
        with self.assertRaises(DataQualityError):
            analyze_ohlcv(empty, "M1")

    def test_unknown_timeframe_is_rejected(self):
        empty = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        with self.assertRaises(TechnicalRatingError):
            analyze_ohlcv(empty, "M2")

    def test_adx_disagreement_is_an_explicit_profile_not_a_hidden_choice(self):
        with self.assertRaises(TechnicalRatingError):
            analyze_ohlcv(pd.DataFrame(columns=["open", "high", "low", "close", "volume"]), "M1", adx_profile="guess")

    def test_module_has_no_execution_or_network_dependencies(self):
        source = (ROOT / "python" / "goldlab" / "technical_rating.py").read_text(encoding="utf-8")
        for forbidden in ("MetaTrader5", "order_send(", "OrderSend(", "requests.", "urllib.request", "websocket"):
            self.assertNotIn(forbidden, source)

if __name__ == "__main__":
    unittest.main()
