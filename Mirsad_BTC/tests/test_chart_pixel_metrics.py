from __future__ import annotations

import unittest

from mirsad.engines.chart_pixel_metrics import analyze_pixel_visual_evidence


def _trend_bars(direction: str, count: int = 30) -> list[dict]:
    bars = []
    for index in range(count):
        if direction == "BULLISH":
            body_top = 180 - index * 3
            colour = "GREEN"
            body_bottom = body_top + 8
        else:
            body_top = 90 + index * 3
            colour = "RED"
            body_bottom = body_top + 8
        bars.append({
            "x_px": 10 + index * 12,
            "colour": colour,
            "high_y_px": body_top - 2,
            "body_top_y_px": body_top,
            "body_bottom_y_px": body_bottom,
            "low_y_px": body_bottom + 2,
            "body_ratio": 0.67,
        })
    return bars


class PixelVisualEvidenceTests(unittest.TestCase):
    def test_scale_free_pixel_trend_detects_bullish_sequence(self) -> None:
        result = analyze_pixel_visual_evidence(_trend_bars("BULLISH"))
        self.assertEqual(result["status"], "READY")
        self.assertEqual(result["direction"], "BULLISH")
        self.assertGreater(result["score"], 0.0)
        self.assertFalse(result["decision_eligible"])
        self.assertEqual(result["windows"]["6"]["direction"], "BULLISH")
        self.assertEqual(result["windows"]["12"]["direction"], "BULLISH")
        self.assertEqual(result["windows"]["30"]["direction"], "BULLISH")

    def test_scale_free_pixel_trend_detects_bearish_sequence(self) -> None:
        result = analyze_pixel_visual_evidence(_trend_bars("BEARISH"))
        self.assertEqual(result["status"], "READY")
        self.assertEqual(result["direction"], "BEARISH")
        self.assertLess(result["score"], 0.0)
        self.assertFalse(result["decision_eligible"])

    def test_bars_without_separated_bodies_are_excluded(self) -> None:
        bars = _trend_bars("BULLISH")
        for bar in bars:
            bar["body_ratio"] = 1.0
        result = analyze_pixel_visual_evidence(bars)
        self.assertEqual(result["status"], "INSUFFICIENT")
        self.assertEqual(result["direction"], "NEUTRAL")
        self.assertEqual(result["windows"]["30"]["usable_bars"], 0)
        self.assertFalse(result["decision_eligible"])

    def test_pixel_trend_does_not_require_absolute_price_fields(self) -> None:
        bars = _trend_bars("BULLISH")
        self.assertTrue(all("open" not in bar and "close" not in bar for bar in bars))
        result = analyze_pixel_visual_evidence(bars)
        self.assertEqual(result["direction"], "BULLISH")
        self.assertIn("scale_free_pixel_close_trend", result["method"])


if __name__ == "__main__":
    unittest.main()
