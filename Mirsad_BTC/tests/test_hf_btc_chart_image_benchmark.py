from __future__ import annotations

import unittest

from scripts.run_hf_btc_chart_image_benchmark import (
    extracted_bar_direction,
    future_close_direction,
    parse_reference_candle,
)


class HFBtcChartImageBenchmarkTests(unittest.TestCase):
    def test_parse_reference_candle_direction_and_close(self) -> None:
        parsed = parse_reference_candle(
            "Candle: bullish, Price change: 0.54%, Open: 97368.62, "
            "High: 97898.81, Low: 97339.16, Close: 97898.80"
        )
        self.assertEqual(parsed["direction"], "BULLISH")
        self.assertAlmostEqual(parsed["close"], 97898.80)
        self.assertTrue(parsed["ohlc_valid"])
        self.assertEqual(parsed["ohlc"], {
            "open": 97368.62,
            "high": 97898.81,
            "low": 97339.16,
            "close": 97898.80,
        })

    def test_parse_reference_candle_handles_bearish_and_missing_fields(self) -> None:
        self.assertEqual(
            parse_reference_candle("Candle: bearish")["direction"],
            "BEARISH",
        )
        missing = parse_reference_candle("no reference candle")
        self.assertIsNone(missing["close"])
        self.assertFalse(missing["ohlc_valid"])
        self.assertIsNone(missing["ohlc"])

    def test_parse_reference_candle_rejects_inconsistent_ohlc(self) -> None:
        parsed = parse_reference_candle(
            "Candle: bullish, Open: 100, High: 99, Low: 90, Close: 105"
        )
        self.assertFalse(parsed["ohlc_valid"])
        self.assertIsNone(parsed["ohlc"])

    def test_future_close_direction_uses_next_close_only(self) -> None:
        self.assertEqual(future_close_direction(100.0, 101.0), "BULLISH")
        self.assertEqual(future_close_direction(100.0, 99.0), "BEARISH")
        self.assertEqual(future_close_direction(100.0, 100.0), "FLAT")
        self.assertIsNone(future_close_direction(None, 100.0))

    def test_extracted_bar_direction_uses_palette_evidence(self) -> None:
        self.assertEqual(extracted_bar_direction({"colour": "GREEN"}), "BULLISH")
        self.assertEqual(extracted_bar_direction({"colour": "RED"}), "BEARISH")
        self.assertIsNone(extracted_bar_direction({}))


if __name__ == "__main__":
    unittest.main()
