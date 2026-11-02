from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from mirsad.engines.chart_ocr import (
    detect_chart_header_metadata,
    parse_chart_header_text,
)


class ChartHeaderOCRTests(unittest.TestCase):
    def test_extracts_symbol_exchange_and_intraday_timeframe(self) -> None:
        result = parse_chart_header_text(
            ["BTC/USDT", "1h", "BINANCE"],
            [0.99, 0.98, 0.97],
            expected_symbol="BTCUSDT",
        )
        self.assertEqual(result["status"], "SUGGESTIONS_FOUND")
        self.assertEqual(result["symbol_suggestion"], "BTCUSDT")
        self.assertEqual(result["timeframe_suggestion"], "1h")
        self.assertEqual(result["exchange_suggestion"], "BINANCE")
        self.assertTrue(result["expected_symbol_match"])
        self.assertIn("METADATA_SUGGESTIONS_ONLY", result["interpretation"])

    def test_monthly_and_minute_timeframes_are_not_conflated(self) -> None:
        monthly = parse_chart_header_text(
            ["BTCUSDT", "1M", "COINBASE"], expected_symbol="BTCUSDT"
        )
        minute = parse_chart_header_text(
            ["BTCUSDT", "1m", "BINANCE"], expected_symbol="BTCUSDT"
        )
        self.assertEqual(monthly["timeframe_suggestion"], "1M")
        self.assertEqual(minute["timeframe_suggestion"], "1m")
        self.assertNotEqual(
            monthly["timeframe_suggestion"],
            minute["timeframe_suggestion"],
        )

    def test_supports_multiple_intraday_units(self) -> None:
        cases = {
            "15m": "15m",
            "4h": "4h",
            "1D": "1d",
            "1W": "1w",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                result = parse_chart_header_text([f"BTCUSDT · {raw} · BINANCE"])
                self.assertEqual(result["timeframe_suggestion"], expected)

    def test_market_cap_suffix_is_not_mistaken_for_monthly_timeframe(self) -> None:
        result = parse_chart_header_text(["BTCUSDT", "Market Cap", "500M"])
        self.assertIsNone(result["timeframe_suggestion"])

    def test_decimal_price_suffix_is_not_mistaken_for_timeframe(self) -> None:
        result = parse_chart_header_text(["BTCUSDT", "69.5M", "BINANCE"])
        self.assertIsNone(result["timeframe_suggestion"])

    def test_expected_symbol_match_requires_exact_detected_symbol(self) -> None:
        result = parse_chart_header_text(
            ["ETHBTCUSDT", "1h", "BINANCE"],
            expected_symbol="BTCUSDT",
        )
        self.assertFalse(result["expected_symbol_match"])

    def test_price_number_alone_is_not_mistaken_for_timeframe(self) -> None:
        result = parse_chart_header_text(["BTCUSDT", "69,500.25", "BINANCE"])
        self.assertIsNone(result["timeframe_suggestion"])
        self.assertEqual(result["symbol_suggestion"], "BTCUSDT")
        self.assertEqual(result["exchange_suggestion"], "BINANCE")

    def test_expected_symbol_mismatch_is_reported_not_overridden(self) -> None:
        result = parse_chart_header_text(
            ["ETH/USDT", "5m", "OKX"],
            expected_symbol="BTCUSDT",
        )
        self.assertEqual(result["symbol_suggestion"], "ETHUSDT")
        self.assertFalse(result["expected_symbol_match"])
        self.assertEqual(result["timeframe_suggestion"], "5m")

    def test_unrelated_text_does_not_generate_fake_metadata(self) -> None:
        result = parse_chart_header_text(
            ["Volume", "RSI 14", "MACD", "69000"]
        )
        self.assertEqual(result["status"], "NO_METADATA")
        self.assertIsNone(result["symbol_suggestion"])
        self.assertIsNone(result["timeframe_suggestion"])
        self.assertIsNone(result["exchange_suggestion"])

    def test_image_detector_reads_only_the_top_header_strip(self) -> None:
        image = np.zeros((200, 400, 3), dtype=np.uint8)

        def fake_ocr(crop):
            self.assertEqual(crop.shape, (44, 400, 3))
            return SimpleNamespace(
                txts=["BTC/USDT", "1h", "BINANCE"],
                scores=[0.99, 0.98, 0.97],
            )

        with patch("mirsad.engines.chart_ocr._get_ocr_engine", return_value=fake_ocr):
            result = detect_chart_header_metadata(
                image, expected_symbol="BTCUSDT"
            )

        self.assertEqual(result["status"], "SUGGESTIONS_FOUND")
        self.assertEqual(result["crop_height_px"], 44)
        self.assertEqual(result["symbol_suggestion"], "BTCUSDT")
        self.assertEqual(result["timeframe_suggestion"], "1h")
        self.assertEqual(result["exchange_suggestion"], "BINANCE")
        self.assertTrue(result["expected_symbol_match"])

    def test_invalid_header_crop_fraction_is_rejected_without_ocr(self) -> None:
        image = np.zeros((200, 400, 3), dtype=np.uint8)
        with patch("mirsad.engines.chart_ocr._get_ocr_engine") as engine:
            result = detect_chart_header_metadata(
                image, header_height_fraction=0.95
            )
        engine.assert_not_called()
        self.assertEqual(result["status"], "INVALID_HEADER_REGION")

    def test_header_metadata_never_claims_price_calibration_or_decision(self) -> None:
        result = parse_chart_header_text(
            ["BTCUSDT", "1h", "BINANCE"]
        )
        self.assertEqual(
            result["interpretation"],
            "METADATA_SUGGESTIONS_ONLY_NOT_USED_FOR_PRICE_CALIBRATION_OR_DECISION",
        )


if __name__ == "__main__":
    unittest.main()
