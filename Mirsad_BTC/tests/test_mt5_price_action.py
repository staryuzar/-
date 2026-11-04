from __future__ import annotations

import unittest

from mirsad.engines.mt5_price_action import (
    DIRECTIONAL_EVIDENCE_WEIGHTS,
    _directional_evidence_score,
    analyze_mt5_native_price_action,
    _summarize_latest_pattern_alignment,
)


DURATIONS = {
    "1m": 60_000,
    "5m": 300_000,
    "15m": 900_000,
    "1h": 3_600_000,
    "4h": 14_400_000,
    "1d": 86_400_000,
}
WAVE = (0, 10, 20, 10, 0, -10, -20, -10)


def make_history(
    *,
    count: int = 121,
    directions: dict[str, str] | None = None,
    as_of_ms: int = 1_800_000_000_000,
    forming_spike: bool = False,
) -> dict:
    directions = directions or {name: "up" for name in DURATIONS}
    frames = {}
    for timeframe, duration in DURATIONS.items():
        direction = directions.get(timeframe, "up")
        drift = 1.25 if direction == "up" else -1.25 if direction == "down" else 0.0
        bars = []
        first_open = as_of_ms - int((count - 0.5) * duration)
        for index in range(count):
            close = 50_000.0 + index * drift + WAVE[index % len(WAVE)]
            open_price = close - (2.0 if direction == "up" else -2.0 if direction == "down" else 0.0)
            high = max(open_price, close) + 3.0
            low = min(open_price, close) - 3.0
            volume = 100.0 + (index % 9)
            if forming_spike and index == count - 1:
                open_price, close, high, low, volume = 20_000.0, 150_000.0, 200_000.0, 1_000.0, 1_000_000.0
            bars.append({
                "open_time_ms": first_open + index * duration,
                "open": open_price,
                "high": high,
                "low": low,
                "close": close,
                "volume": volume,
                "closed": index < count - 1,
            })
        frames[timeframe] = bars
    return {
        "status": "READY",
        "source": "MT5_CHART_OBSERVER",
        "symbol": "BTCUSDT",
        "broker_symbol": "BTC",
        "account_server": "Headway-Demo",
        "captured_at_ms": as_of_ms,
        "candles_by_tf": frames,
    }


class DirectionalEvidenceScoringTests(unittest.TestCase):
    def test_swing_structure_is_primary_and_stands_alone_when_other_evidence_is_absent(self) -> None:
        score, evidence = _directional_evidence_score(
            {"swing": {"direction": "BULLISH"}},
            {"latest_pattern_bias": "NONE"},
        )
        self.assertAlmostEqual(score, 1.0)
        self.assertEqual(evidence["evidence_count"], 1)
        self.assertEqual(evidence["applied_weights"], {"confirmed_swing_structure": 1.0})
        self.assertAlmostEqual(evidence["evidence_coverage"], 0.65)

    def test_candles_bos_choch_and_liquidity_sweeps_contribute_to_engine2_score(self) -> None:
        score, evidence = _directional_evidence_score(
            {
                "swing": {"direction": "BULLISH"},
                "bos_choch_events": [
                    {"event": "BOS_BEARISH", "confirmation_time_utc_ms": 10},
                    {"event": "BOS_BULLISH", "confirmation_time_utc_ms": 20},
                ],
                "liquidity_sweeps": [
                    {"event": "HIGH_LIQUIDITY_SWEEP", "confirmation_time_utc_ms": 15},
                    {"event": "LOW_LIQUIDITY_SWEEP", "confirmation_time_utc_ms": 25},
                ],
            },
            {"latest_pattern_bias": "BULLISH"},
        )
        self.assertAlmostEqual(score, 1.0)
        self.assertEqual(evidence["evidence_count"], 4)
        self.assertEqual(evidence["applied_weights"], DIRECTIONAL_EVIDENCE_WEIGHTS)

    def test_opposing_confirmed_structure_event_reduces_directional_score(self) -> None:
        score, evidence = _directional_evidence_score(
            {
                "swing": {"direction": "BULLISH"},
                "bos_choch_events": [
                    {"event": "BOS_BEARISH", "confirmation_time_utc_ms": 10},
                ],
            },
            {"latest_pattern_bias": "NONE"},
        )
        self.assertAlmostEqual(score, (0.65 - 0.20) / 0.85)
        self.assertEqual(evidence["component_scores"]["latest_confirmed_bos_choch"], -1.0)

    def test_missing_directional_evidence_is_renormalized_not_counted_as_bearish(self) -> None:
        score, evidence = _directional_evidence_score(
            {"swing": {"direction": "BULLISH"}},
            {"latest_pattern_bias": "MIXED"},
        )
        self.assertAlmostEqual(score, 1.0)
        self.assertEqual(evidence["applied_weights"], {"confirmed_swing_structure": 1.0})


class LatestCandlePatternAlignmentTests(unittest.TestCase):
    def test_mixed_patterns_within_one_timeframe_are_not_misclassified_as_no_pattern(self) -> None:
        alignment, bullish, bearish, mixed = _summarize_latest_pattern_alignment({
            "1m": "MIXED",
            "5m": "NONE",
        })
        self.assertEqual(alignment, "MIXED_CANDLE_PATTERN_EVIDENCE")
        self.assertEqual(bullish, [])
        self.assertEqual(bearish, [])
        self.assertEqual(mixed, ["1m"])

    def test_opposing_timeframe_patterns_are_mixed(self) -> None:
        alignment, bullish, bearish, mixed = _summarize_latest_pattern_alignment({
            "1m": "BULLISH",
            "5m": "BEARISH",
            "15m": "NONE",
        })
        self.assertEqual(alignment, "MIXED_CANDLE_PATTERN_EVIDENCE")
        self.assertEqual(bullish, ["1m"])
        self.assertEqual(bearish, ["5m"])
        self.assertEqual(mixed, [])


class MT5NativePriceActionTests(unittest.TestCase):
    def test_higher_highs_and_higher_lows_produce_bullish_structure(self) -> None:
        result = analyze_mt5_native_price_action(make_history())
        self.assertEqual(result["status"], "READY")
        self.assertEqual(result["direction"], "BULLISH")
        self.assertEqual(result["summary"]["higher_timeframe_direction"], "BULLISH")
        self.assertEqual(set(result["summary"]["eligible_timeframes"]), set(DURATIONS))
        for timeframe in DURATIONS:
            structure = result["timeframes"][timeframe]["structure"]["swing"]
            self.assertGreaterEqual(len(structure["swing_highs"]), 2)
            self.assertGreaterEqual(len(structure["swing_lows"]), 2)
            self.assertTrue(structure["higher_highs"])
            self.assertTrue(structure["higher_lows"])

    def test_lower_highs_and_lower_lows_produce_bearish_structure(self) -> None:
        directions = {name: "down" for name in DURATIONS}
        result = analyze_mt5_native_price_action(make_history(directions=directions))
        self.assertEqual(result["status"], "READY")
        self.assertEqual(result["direction"], "BEARISH")
        self.assertEqual(result["summary"]["higher_timeframe_direction"], "BEARISH")

    def test_conflicting_timeframes_are_reported_as_mixed(self) -> None:
        directions = {
            "1m": "down", "5m": "down", "15m": "down",
            "1h": "up", "4h": "up", "1d": "up",
        }
        result = analyze_mt5_native_price_action(make_history(directions=directions))
        self.assertEqual(result["status"], "READY")
        self.assertEqual(result["direction"], "MIXED_TIMEFRAME_DIRECTIONS")
        self.assertEqual(result["summary"]["short_term_direction"], "BEARISH")
        self.assertEqual(result["summary"]["higher_timeframe_direction"], "BULLISH")

    def test_directional_frame_coverage_counts_mixed_eligible_timeframes(self) -> None:
        directions = {
            "1m": "down", "5m": "up", "15m": "up",
            "1h": "flat", "4h": "flat", "1d": "down",
        }
        result = analyze_mt5_native_price_action(make_history(directions=directions))
        summary = result["summary"]
        self.assertEqual(result["status"], "READY")
        self.assertEqual(result["direction"], "MIXED_TIMEFRAME_DIRECTIONS")
        self.assertEqual(summary["directional_frame_count"], 4)
        self.assertAlmostEqual(summary["directional_frame_coverage"], 4 / 6)
        self.assertEqual(summary["mixed_or_unconfirmed_frame_count"], 2)
        self.assertAlmostEqual(summary["mixed_or_unconfirmed_frame_coverage"], 2 / 6)
        self.assertAlmostEqual(summary["directional_structure_agreement"], 0.5)

    def test_forming_candle_spike_does_not_change_price_action_result(self) -> None:
        normal = analyze_mt5_native_price_action(make_history())
        spike = analyze_mt5_native_price_action(make_history(forming_spike=True))
        self.assertEqual(normal["direction"], spike["direction"])
        self.assertEqual(normal["structure_score"], spike["structure_score"])
        for timeframe in DURATIONS:
            self.assertEqual(
                normal["timeframes"][timeframe]["structure"],
                spike["timeframes"][timeframe]["structure"],
            )
            self.assertEqual(
                normal["timeframes"][timeframe]["candle_analysis"],
                spike["timeframes"][timeframe]["candle_analysis"],
            )
            self.assertEqual(
                spike["timeframes"][timeframe]["forming_candle"]["state"],
                "FORMING_NOT_USED_FOR_DIRECTION",
            )

    def test_swings_are_only_published_after_right_side_confirmation(self) -> None:
        result = analyze_mt5_native_price_action(make_history())
        pivots = (
            result["timeframes"]["1h"]["structure"]["swing"]["swing_highs"]
            + result["timeframes"]["1h"]["structure"]["swing"]["swing_lows"]
        )
        self.assertTrue(pivots)
        for pivot in pivots:
            self.assertTrue(pivot["confirmed"])
            self.assertLessEqual(
                pivot["confirmation_time_utc_ms"],
                result["timeframes"]["1h"]["last_closed_bar_open_time_ms"],
            )

    def test_insufficient_higher_timeframes_blocks_final_direction(self) -> None:
        history = make_history()
        for timeframe in ("4h", "1d"):
            history["candles_by_tf"][timeframe] = history["candles_by_tf"][timeframe][-18:]
            for bar in history["candles_by_tf"][timeframe][:-1]:
                bar["closed"] = True
            history["candles_by_tf"][timeframe][-1]["closed"] = False
        result = analyze_mt5_native_price_action(history)
        self.assertEqual(result["status"], "PARTIAL")
        self.assertEqual(result["direction"], "INSUFFICIENT_CONTEXT")

    def test_large_historical_gap_excludes_old_prefix_and_keeps_recent_contiguous_segment(self) -> None:
        history = make_history()
        bars = history["candles_by_tf"]["1h"]
        split = len(bars) // 2
        for bar in bars[:split]:
            bar["open_time_ms"] -= 10 * DURATIONS["1h"]
        result = analyze_mt5_native_price_action(history)
        report = result["timeframes"]["1h"]
        self.assertEqual(report["status"], "READY")
        self.assertEqual(report["data_quality"]["gap_count"], 1)
        self.assertEqual(report["data_quality"]["source_closed_bars"], 120)
        self.assertEqual(report["data_quality"]["closed_bars"], 60)
        self.assertEqual(report["data_quality"]["excluded_closed_bars_before_latest_gap"], 60)
        self.assertIn("1h", result["summary"]["eligible_timeframes"])
        self.assertIn("1h", result["historical_gap_timeframes"])

    def test_single_historical_missing_candle_does_not_discard_recent_contiguous_segment(self) -> None:
        history = make_history()
        bars = history["candles_by_tf"]["1h"]
        bars[60:] = bars[61:]
        result = analyze_mt5_native_price_action(history)
        report = result["timeframes"]["1h"]
        self.assertEqual(report["status"], "READY")
        self.assertEqual(report["data_quality"]["gap_count"], 1)
        self.assertEqual(report["data_quality"]["closed_bars"], 59)
        self.assertIn("1h", result["summary"]["eligible_timeframes"])

    def test_recent_gap_with_too_short_contiguous_suffix_blocks_timeframe(self) -> None:
        history = make_history()
        bars = history["candles_by_tf"]["1h"]
        bars[100:-1] = bars[101:-1]
        result = analyze_mt5_native_price_action(history)
        report = result["timeframes"]["1h"]
        self.assertEqual(report["status"], "PARTIAL")
        self.assertEqual(report["data_quality"]["gap_count"], 1)
        self.assertLess(report["data_quality"]["closed_bars"], 24)
        self.assertNotIn("1h", result["summary"]["eligible_timeframes"])

    def test_forming_candle_must_immediately_follow_latest_closed_candle(self) -> None:
        history = make_history()
        bars = history["candles_by_tf"]["15m"]
        bars[-1]["open_time_ms"] += DURATIONS["15m"]
        result = analyze_mt5_native_price_action(history)
        self.assertEqual(result["timeframes"]["15m"]["status"], "INVALID_SEQUENCE")
        self.assertNotIn("15m", result["summary"]["eligible_timeframes"])

    def test_stale_timeframe_is_not_used_for_consensus(self) -> None:
        history = make_history()
        history["candles_by_tf"]["1h"] = [
            {**bar, "open_time_ms": bar["open_time_ms"] - 10 * DURATIONS["1h"]}
            for bar in history["candles_by_tf"]["1h"]
        ]
        result = analyze_mt5_native_price_action(history)
        self.assertEqual(result["timeframes"]["1h"]["status"], "STALE")
        self.assertNotIn("1h", result["summary"]["eligible_timeframes"])

    def test_timeframe_needs_confirmed_swing_evidence_before_eligibility(self) -> None:
        history = make_history()
        for bars in history["candles_by_tf"].values():
            for index, bar in enumerate(bars[:-1]):
                price = 50_000.0 + index * 4.0
                bar.update({
                    "open": price + 1.0,
                    "high": price + 3.0,
                    "low": price,
                    "close": price + 2.0,
                    "closed": True,
                })
            bars[-1]["closed"] = False

        result = analyze_mt5_native_price_action(history)
        self.assertEqual(result["status"], "PARTIAL")
        self.assertEqual(result["direction"], "INSUFFICIENT_CONTEXT")
        self.assertEqual(result["summary"]["eligible_timeframes"], [])
        for report in result["timeframes"].values():
            self.assertEqual(report["data_quality"]["status"], "READY")
            self.assertEqual(report["structure"]["status"], "PARTIAL")
            self.assertEqual(report["status"], "PARTIAL")
            self.assertEqual(
                report["readiness"]["confirmed_swing_structure"], "PARTIAL"
            )

    def test_invalid_ohlc_fails_closed(self) -> None:
        history = make_history()
        history["candles_by_tf"]["15m"][10]["high"] = 1.0
        result = analyze_mt5_native_price_action(history)
        self.assertEqual(result["status"], "PARTIAL")
        self.assertEqual(result["timeframes"]["15m"]["status"], "INVALID")
        self.assertEqual(result["timeframes"]["15m"]["direction"], "MIXED_OR_UNKNOWN")

    def test_candle_patterns_are_reported_with_timestamps_and_context(self) -> None:
        history = make_history()
        result = analyze_mt5_native_price_action(history)
        report = result["timeframes"]["1m"]["candle_analysis"]
        self.assertIn("latest_closed_candle", report)
        self.assertIn("latest_candle_patterns", report)
        for pattern in report["recent_patterns"]:
            self.assertIn("start_time_utc_ms", pattern)
            self.assertIn("end_time_utc_ms", pattern)
            self.assertEqual(pattern["interpretation"], "RULE_MATCH_NOT_PROBABILITY")

    def test_live_price_action_cli_uses_only_native_engine2_candle_history(self) -> None:
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        from scripts.analyze_mt5_native_price_action import build_report

        candles = make_history()
        with tempfile.TemporaryDirectory() as directory:
            with patch(
                "scripts.analyze_mt5_native_price_action.MT5ChartCandleHistory.collect",
                return_value=candles,
            ) as candle_collect:
                report = build_report(
                    Path(directory),
                    market_symbol="BTCUSDT",
                    broker_symbol="BTC",
                    expected_server="Headway-Demo",
                )

        candle_collect.assert_called_once_with()
        self.assertEqual(report["status"], "READY")
        self.assertEqual(report["candle_feed_status"], "READY")
        self.assertFalse(report["engine5_quote_consumed_by_engine2"])
        self.assertFalse(report["decision_eligible"])

    def test_live_price_action_cli_rejects_native_candle_identity_mismatch(self) -> None:
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        from scripts.analyze_mt5_native_price_action import build_report

        candles = make_history()
        candles["broker_symbol"] = "OTHER"
        with tempfile.TemporaryDirectory() as directory:
            with patch(
                "scripts.analyze_mt5_native_price_action.MT5ChartCandleHistory.collect",
                return_value=candles,
            ):
                report = build_report(
                    Path(directory),
                    market_symbol="BTCUSDT",
                    broker_symbol="BTC",
                    expected_server="Headway-Demo",
                )

        self.assertEqual(report["status"], "FAILED")
        self.assertIn("candle broker symbol identity mismatch.", report["failures"])
        self.assertFalse(report["decision_eligible"])


    def test_engine2_does_not_calculate_or_depend_on_technical_indicators(self) -> None:
        import inspect
        from mirsad.engines import mt5_price_action

        signature = inspect.signature(mt5_price_action.analyze_mt5_native_price_action)
        self.assertEqual(list(signature.parameters), ["candle_history"])
        result = analyze_mt5_native_price_action(make_history())
        self.assertFalse(result["safety"]["calculates_indicators"])
        for frame in result["timeframes"].values():
            self.assertNotIn("indicators", frame)

    def test_missing_candle_source_blocks_analysis(self) -> None:
        result = analyze_mt5_native_price_action({"status": "OFFLINE"})
        self.assertEqual(result["status"], "NOT_READY")
        self.assertEqual(result["direction"], "UNKNOWN")
        self.assertFalse(result["decision_eligible"])


if __name__ == "__main__":
    unittest.main()
