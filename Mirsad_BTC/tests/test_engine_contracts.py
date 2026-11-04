from __future__ import annotations

import json
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from mirsad.engines.indicators import IndicatorsEngine
from mirsad.engines.decision import (
    ENGINE1_DECISION_WEIGHT,
    ENGINE2_DECISION_WEIGHT,
    ENGINE3_DECISION_WEIGHT,
    DecisionEngine,
    _market_intelligence_signal,
    _matching_positions,
    _price_to_tick,
    _weighted_three_engine_score,
    calculate_volume,
    _ema,
)
import mirsad.engines.mt5_bridge as bridge_module
from mirsad.engines.mt5_bridge import MT5BridgeEngine
from mirsad.storage import save_market_snapshot


def make_engine2_candle_history(direction: str = "up", count: int = 90) -> dict:
    now = int(time.time() * 1000)
    frames = {}
    for timeframe in ("1m", "5m", "15m", "1h", "4h", "1d"):
        candles = []
        for index in range(count):
            close = 100.0 + (index * 0.6 if direction == "up" else -index * 0.6)
            candles.append({
                "open_time_ms": now - (count - index) * 60_000,
                "open": close - 0.2 if direction == "up" else close + 0.2,
                "high": close + 1.0, "low": close - 1.0,
                "close": close, "volume": 2.0, "closed": True,
            })
        frames[timeframe] = candles
    return {
        "status": "READY",
        "source": "MT5_CHART_OBSERVER",
        "captured_at_ms": now,
        "candles_by_tf": frames,
    }


def make_engine2_price_action(direction: str = "BULLISH", score: float = 0.80) -> dict:
    alignment = "BULLISH_STRUCTURE_CONFLUENCE" if direction == "BULLISH" else "BEARISH_STRUCTURE_CONFLUENCE"
    return {
        "engine": "engine_2_native_price_action",
        "schema": "MIR-ENGINE2-PRICE-ACTION-1",
        "source": "MT5_COPYRATES_CLOSED_BARS",
        "status": "READY",
        "direction": direction,
        "structure_score": score if direction == "BULLISH" else -abs(score),
        "summary": {
            "eligible_timeframes": ["1m", "5m", "15m", "1h", "4h", "1d"],
            "timeframe_alignment": alignment,
            "timeframe_weight_coverage": 0.90,
            "directional_frame_coverage": 1.0,
            "directional_structure_agreement": 0.80,
            "directional_evidence_coverage": 1.0,
            "latest_candle_pattern_alignment": "NO_DIRECTIONAL_CANDLE_PATTERN",
        },
    }


def make_open_decision(command_id: str = "MIR-" + "a" * 24) -> dict:
    return {
        "status": "READY",
        "command_ready": True,
        "action": "BUY",
        "signal_id": command_id,
        "symbol": "BTC",
        "market_symbol": "BTCUSDT",
        "entry_reference": 100.0,
        "stop_loss": 95.0,
        "take_profit": 110.0,
        "risk_plan": {"status": "READY", "volume": 0.2},
    }


def make_close_decision(command_id: str = "MIR-" + "b" * 24) -> dict:
    return {
        "status": "READY",
        "command_ready": True,
        "action": "CLOSE",
        "signal_id": command_id,
        "symbol": "BTC",
        "market_symbol": "BTCUSDT",
        "position_ticket": 123456,
        "risk_plan": {
            "status": "READY",
            "volume": 0.1,
            "purpose": "close_existing_opposite_position",
        },
    }


def make_modify_decision(command_id: str = "MIR-" + "d" * 24) -> dict:
    return {
        "status": "READY", "command_ready": True, "action": "MODIFY",
        "signal_id": command_id, "symbol": "BTC", "market_symbol": "BTCUSDT",
        "position_ticket": 123456, "stop_loss": 101.0, "take_profit": 110.0,
        "risk_plan": {"status": "READY", "volume": 0.1, "purpose": "protective_stop_update"},
    }


class RiskSizingTests(unittest.TestCase):
    def test_volume_is_floored_to_allowed_step_from_minimum(self) -> None:
        # risk cash = 9.7; loss per lot = 10; raw volume = 0.97.
        result = calculate_volume(
            equity=9700,
            entry=100,
            stop_loss=90,
            tick_size=1,
            tick_value_loss=1,
            volume_min=0.1,
            volume_step=0.05,
            volume_max=2.0,
            risk_fraction=0.001,
        )
        self.assertEqual(result["status"], "READY")
        self.assertAlmostEqual(result["volume"], 0.95)
        self.assertLessEqual(result["estimated_loss"], result["risk_cash"])

    def test_volume_below_broker_minimum_is_blocked(self) -> None:
        result = calculate_volume(
            equity=100,
            entry=100,
            stop_loss=90,
            tick_size=1,
            tick_value_loss=1,
            volume_min=0.1,
            volume_step=0.1,
            volume_max=10,
            risk_fraction=0.001,
        )
        self.assertEqual(result["status"], "BLOCKED")

    def test_non_finite_specs_are_rejected(self) -> None:
        result = calculate_volume(
            equity=float("nan"),
            entry=100,
            stop_loss=90,
            tick_size=1,
            tick_value_loss=1,
            volume_min=0.1,
            volume_step=0.1,
            volume_max=10,
        )
        self.assertEqual(result["status"], "UNAVAILABLE")


class WeightedDecisionTests(unittest.TestCase):
    def test_engine_decision_weights_are_20_55_25_and_total_one_hundred_percent(self) -> None:
        self.assertAlmostEqual(ENGINE1_DECISION_WEIGHT, 0.20)
        self.assertAlmostEqual(ENGINE2_DECISION_WEIGHT, 0.55)
        self.assertAlmostEqual(ENGINE3_DECISION_WEIGHT, 0.25)
        self.assertAlmostEqual(
            ENGINE1_DECISION_WEIGHT + ENGINE2_DECISION_WEIGHT + ENGINE3_DECISION_WEIGHT,
            1.0,
        )

    def test_all_three_engines_are_combined_using_the_configured_baseline(self) -> None:
        score, weights = _weighted_three_engine_score(
            engine1_score=-0.50,
            engine2_score=0.80,
            engine3_score=-0.20,
            engine1_quality=1.0,
            engine2_quality=1.0,
            engine3_quality=1.0,
        )
        self.assertAlmostEqual(score, 0.29)
        self.assertAlmostEqual(weights["engine_1_market_intelligence"], 0.20)
        self.assertAlmostEqual(weights["engine_2_price_action"], 0.55)
        self.assertAlmostEqual(weights["engine_3_indicators"], 0.25)
        self.assertAlmostEqual(sum(weights.values()), 1.0)

    def test_missing_engine1_evidence_is_not_redistributed_to_engines2_and3(self) -> None:
        score, weights = _weighted_three_engine_score(
            engine1_score=None,
            engine2_score=0.80,
            engine3_score=-0.20,
            engine1_quality=0.0,
            engine2_quality=1.0,
            engine3_quality=1.0,
        )
        self.assertAlmostEqual(score, 0.39)
        self.assertEqual(weights["engine_1_market_intelligence"], 0.0)
        self.assertAlmostEqual(weights["engine_2_price_action"], 0.55)
        self.assertAlmostEqual(weights["engine_3_indicators"], 0.25)
        self.assertAlmostEqual(sum(weights.values()), 0.80)

    def test_low_quality_engine1_evidence_receives_less_than_its_baseline_weight(self) -> None:
        score, weights = _weighted_three_engine_score(
            engine1_score=0.90,
            engine2_score=0.50,
            engine3_score=0.10,
            engine1_quality=0.50,
            engine2_quality=1.0,
            engine3_quality=1.0,
        )
        self.assertAlmostEqual(weights["engine_1_market_intelligence"], 0.10)
        self.assertAlmostEqual(weights["engine_2_price_action"], 0.55)
        self.assertAlmostEqual(weights["engine_3_indicators"], 0.25)
        self.assertAlmostEqual(score, 0.90 * 0.10 + 0.50 * 0.55 + 0.10 * 0.25)
        self.assertAlmostEqual(sum(weights.values()), 0.90)

    def test_engine1_uses_only_its_standalone_report_and_never_quote_pulse(self) -> None:
        report = {
            "status": "READY", "directional_score": -0.40,
            "confidence": 0.80, "evidence_coverage": 0.80,
        }
        score, quality, parts = _market_intelligence_signal(report)
        self.assertAlmostEqual(score, -0.40)
        self.assertAlmostEqual(quality, 0.80)
        self.assertEqual(parts["source"], "ENGINE1_STANDALONE_REPORT")
        score, quality, parts = _market_intelligence_signal({
            "status": "LIVE",
            "market_context": {"microstructure": {"status": "READY", "quote_direction_balance": 0.95}},
        })
        self.assertIsNone(score)
        self.assertEqual(quality, 0.0)
        self.assertEqual(parts["source"], "UNAVAILABLE")

    def test_single_category_or_low_coverage_intelligence_is_excluded(self) -> None:
        score, quality, parts = _market_intelligence_signal({
            "status": "PARTIAL", "directional_score": 0.95,
            "confidence": 0.90, "evidence_coverage": 0.45,
        })
        self.assertIsNone(score)
        self.assertEqual(quality, 0.0)
        self.assertEqual(parts["source"], "UNAVAILABLE")

class ThreeEngineDecisionIntegrationTests(unittest.TestCase):
    def _market(self, direction: str) -> dict:
        now = int(time.time() * 1000)
        return {
            "status": "LIVE", "source": "MT5_TERMINAL", "venue_count": 1, "symbol": "BTCUSDT",
            "price": 100.0, "captured_at_ms": now, "primary_venue": "MT5 Broker",
            "feed_health": {"terminal_connected": True, "quote_fresh": True},
            "market_context": {"microstructure": {
                "status": "READY",
                "quote_direction_balance": 0.75 if direction == "up" else -0.75,
            }},
            "venues": {"MT5 Broker": {"status": "LIVE", "price": 100.0}},
        }

    def test_directional_candidate_is_rejected_without_native_engine2_price_action(self) -> None:
        result = DecisionEngine().analyze(
            self._market("down"),
            {"status": "READY", "candle_history": make_engine2_candle_history("down")},
            {},
            market_intelligence={
                "status": "READY", "direction": "BEARISH", "directional_score": -0.75,
                "confidence": 0.80, "evidence_coverage": 0.80,
            },
        )
        self.assertEqual(
            result["direction_inputs"],
            ["engine_1_market_intelligence", "engine_2_native_ohlc_price_action", "engine_3_indicators"],
        )
        self.assertEqual(
            result["calculation_inputs"],
            ["engine_1_market_intelligence", "engine_2_native_ohlc_price_action", "engine_3_indicators"],
        )
        self.assertEqual(result["candidate_action"], "WAIT")
        configured = result["decision_weights"]["configured"]
        self.assertEqual(configured, {
            "engine_1_market_intelligence": 0.20,
            "engine_2_price_action": 0.55,
            "engine_3_indicators": 0.25,
        })
        self.assertAlmostEqual(
            sum(result["decision_weights"][key] for key in configured),
            result["decision_scores"]["effective_weight_coverage"],
        )
        self.assertAlmostEqual(result["decision_scores"]["effective_weight_coverage"], 0.41)
        self.assertAlmostEqual(result["decision_scores"]["market_score"], -0.75)
        self.assertIsNone(result["decision_scores"]["engine_2_score"])
        self.assertEqual(result["engine_2_score_source"], "NATIVE_OHLC_NOT_PROVIDED")
        self.assertEqual(result["chart_gate"], "WAITING_FOR_ENGINE_2_NATIVE_OHLC")
        self.assertNotIn("re-normalizes", result["reason"].lower())
        self.assertIn("without redistributing missing weight", result["reason"].lower())

    def test_high_impact_macro_window_pauses_new_entries_but_not_position_close(self) -> None:
        now = int(time.time() * 1000)
        market = self._market("up")
        market["market_intelligence"] = {
            "status": "READY",
            "directional_score": 0.5,
            "confidence": 0.9,
            "economic_calendar": {
                "status": "READY",
                "high_impact_window_active": True,
                "active_high_impact_events": [{"name": "US CPI", "minutes_to_event": 5}],
            },
        }
        chart = {"status": "READY", "candle_history": make_engine2_candle_history("up")}
        indicators = {
            "status": "READY", "engine": "engine_3_indicators",
            "source": "engine_2_chart_candles",
            "trend_score": 0.70,
            "signal_score": 0.62,
            "signal_quality": 1.0,
            "signal_timeframe_weight_coverage": 1.0,
            "last_closed_candle_time_ms": now - 60_000,
            "values": {
                "ema20_1m": 101.0, "ema50_1m": 100.0, "rsi14_1m": 60.0,
                "atr14_1m": 2.0, "atr14_5m": 2.0,
            },
        }
        bridge = {
            "status": "CONNECTED", "symbol": "BTCUSDT", "market_symbol": "BTCUSDT",
            "magic_number": 12345, "quote_age_seconds": 0.1,
            "quote": {"bid": 100.0, "ask": 100.02, "tick_age_seconds": 0.1},
            "account": {"equity": 10_000.0},
            "symbol_spec": {
                "tick_size": 0.01, "tick_value_loss": 1.0,
                "volume_min": 0.01, "volume_step": 0.01, "volume_max": 10.0,
                "point": 0.01, "digits": 2, "stops_level_points": 0,
            },
            "positions": [],
        }
        paused = DecisionEngine().analyze(
            market, chart, bridge, indicators,
            engine2_price_action=make_engine2_price_action(),
            market_intelligence=market["market_intelligence"],
        )
        self.assertEqual(paused["candidate_action"], "BUY")
        self.assertEqual(paused["action"], "WAIT")
        self.assertTrue(paused["macro_event_gate"]["new_entries_paused"])
        self.assertEqual(paused["macro_event_gate"]["status"], "ACTIVE")
        self.assertEqual(paused["macro_event_gate"]["calendar_status"], "READY")
        self.assertFalse(paused["command_ready"])

        # A missing/unavailable calendar is not equivalent to a verified
        # calendar with no high-impact event. New exposure must fail closed.
        unavailable_calendar = {
            **market["market_intelligence"],
            "economic_calendar": {"status": "NOT_AVAILABLE", "events": []},
        }
        unavailable = DecisionEngine().analyze(
            market, chart, bridge, indicators,
            engine2_price_action=make_engine2_price_action(),
            market_intelligence=unavailable_calendar,
        )
        self.assertEqual(unavailable["candidate_action"], "BUY")
        self.assertEqual(unavailable["action"], "WAIT")
        self.assertEqual(unavailable["macro_event_gate"]["status"], "UNKNOWN")
        self.assertFalse(unavailable["macro_event_gate"]["calendar_verified"])
        self.assertTrue(unavailable["macro_event_gate"]["new_entries_paused"])
        self.assertFalse(unavailable["command_ready"])
        self.assertIn("calendar", unavailable["open_block_reason"].lower())

        bridge_with_short = {
            **bridge,
            "positions": [{
                "ticket": 778899, "symbol": "BTCUSDT", "type": 1,
                "magic": 12345, "volume": 0.05,
            }],
        }
        close = DecisionEngine().analyze(
            market, chart, bridge_with_short, indicators,
            engine2_price_action=make_engine2_price_action(),
            market_intelligence=market["market_intelligence"],
        )
        self.assertEqual(close["action"], "CLOSE")
        self.assertEqual(close["position_ticket"], 778899)
        self.assertTrue(close["macro_event_gate"]["new_entries_paused"])

        # Missing calendar data must not obstruct an existing protective close.
        close_unavailable_calendar = DecisionEngine().analyze(
            market, chart, bridge_with_short, indicators,
            engine2_price_action=make_engine2_price_action(),
            market_intelligence=unavailable_calendar,
        )
        self.assertEqual(close_unavailable_calendar["action"], "CLOSE")
        self.assertEqual(close_unavailable_calendar["position_ticket"], 778899)
        self.assertTrue(close_unavailable_calendar["command_ready"])
        self.assertEqual(close_unavailable_calendar["macro_event_gate"]["status"], "UNKNOWN")

    def test_market_cannot_create_direction_without_engine2_price_action(self) -> None:
        result = DecisionEngine().analyze(
            self._market("up"),
            {"status": "READY", "candle_history": make_engine2_candle_history("up")},
            {},
        )
        self.assertEqual(result["candidate_action"], "WAIT")
        self.assertIsNone(result["decision_scores"]["engine_2_score"])
        self.assertEqual(result["chart_gate"], "WAITING_FOR_ENGINE_2_NATIVE_OHLC")

    def test_missing_engine2_vote_never_creates_direction_even_with_extreme_market(self) -> None:
        result = DecisionEngine().analyze(
            self._market("up"),
            {"status": "READY", "candle_history": make_engine2_candle_history("up")},
            {},
        )
        self.assertEqual(result["candidate_action"], "WAIT")
        self.assertEqual(result["chart_gate"], "WAITING_FOR_ENGINE_2_NATIVE_OHLC")
        self.assertIsNone(result["decision_scores"]["engine_2_score"])
        self.assertIsNone(result["decision_scores"]["combined_score"])


class Engine2Engine3Engine4ContractTests(unittest.TestCase):
    def _market(self) -> dict:
        now = int(time.time() * 1000)
        return {
            "status": "LIVE", "source": "MT5_TERMINAL", "venue_count": 1,
            "symbol": "BTCUSDT", "price": 100.0, "captured_at_ms": now,
            "primary_venue": "MT5 Broker",
            "feed_health": {"terminal_connected": True, "quote_fresh": True},
        }

    def _chart(self) -> dict:
        history = make_engine2_candle_history("up", 90)
        return {"status": "READY", "candle_history": history}

    def test_engine3_consumes_engine2_history_and_engine4_accepts_valid_contract(self) -> None:
        chart = self._chart()
        indicators = IndicatorsEngine().analyze(chart["candle_history"])
        self.assertEqual(indicators["engine"], "engine_3_indicators")
        self.assertEqual(indicators["source"], "engine_2_chart_candles")
        self.assertEqual(indicators["status"], "READY")

        result = DecisionEngine().analyze(
            self._market(), chart, {}, indicators,
            engine2_price_action=make_engine2_price_action(),
        )
        self.assertEqual(result["engine_3_indicator_status"], "READY")
        self.assertEqual(result["engine_inputs"]["indicators_from_engine_3"], "READY")
        self.assertEqual(result["candidate_action"], "BUY")
        self.assertFalse(result["command_ready"])


    def test_engine4_requires_live_native_indicator_parity_before_using_engine3_vote(self) -> None:
        chart = self._chart()
        indicators = IndicatorsEngine().analyze(chart["candle_history"])
        indicators["mt5_native"] = {"status": "READY"}
        indicators["mt5_native_parity"] = {
            "status": "FAIL", "passed_metrics": 119, "total_metrics": 120,
            "failures": ["5m: rsi14 mismatch"],
        }

        blocked = DecisionEngine().analyze(
            self._market(), chart, {}, indicators,
            engine2_price_action=make_engine2_price_action(),
            require_mt5_native_parity=True,
        )
        self.assertEqual(blocked["status"], "WAITING_FOR_ENGINE_3_PARITY")
        self.assertEqual(blocked["action"], "WAIT")
        self.assertFalse(blocked["command_ready"])
        self.assertEqual(blocked["engine_3_native_parity_status"], "FAIL")

        indicators["mt5_native_parity"] = {
            "status": "PASS", "passed_metrics": 120, "total_metrics": 120, "failures": []
        }
        accepted = DecisionEngine().analyze(
            self._market(), chart, {}, indicators,
            engine2_price_action=make_engine2_price_action(),
            require_mt5_native_parity=True,
        )
        self.assertEqual(accepted["candidate_action"], "BUY")
        self.assertEqual(accepted["status"], "READY")

    def test_engine4_uses_grouped_indicator_signal_instead_of_ema_trend_score(self) -> None:
        chart = self._chart()
        indicators = IndicatorsEngine().analyze(chart["candle_history"])
        indicators["trend_score"] = -0.80
        indicators["signal_score"] = 0.23
        indicators["signal_quality"] = 0.80
        result = DecisionEngine().analyze(
            self._market(), chart, {}, indicators,
            engine2_price_action=make_engine2_price_action(),
        )
        self.assertAlmostEqual(result["decision_scores"]["engine_3_indicators"], 0.23)
        self.assertAlmostEqual(result["decision_scores"]["engine_3_ema_trend_score"], -0.80)
        self.assertAlmostEqual(result["decision_scores"]["engine_3_quality"], 0.80)

    def test_engine4_reduces_engine3_weight_when_higher_timeframe_coverage_is_missing(self) -> None:
        chart = self._chart()
        indicators = IndicatorsEngine().analyze(chart["candle_history"])
        indicators["signal_quality"] = 1.0
        indicators["signal_timeframe_weight_coverage"] = 0.60
        result = DecisionEngine().analyze(
            self._market(), chart, {}, indicators,
            engine2_price_action=make_engine2_price_action(),
        )
        self.assertAlmostEqual(result["decision_scores"]["engine_3_core_quality"], 1.0)
        self.assertAlmostEqual(result["decision_scores"]["engine_3_timeframe_weight_coverage"], 0.60)
        self.assertAlmostEqual(result["decision_scores"]["engine_3_quality"], 0.60)
        self.assertAlmostEqual(
            result["decision_weights"]["engine_3_indicators"],
            0.25 * 0.60,
        )

    def test_engine4_rejects_missing_or_low_quality_composite_indicator_signal(self) -> None:
        chart = self._chart()
        indicators = IndicatorsEngine().analyze(chart["candle_history"])
        del indicators["signal_score"]
        missing = DecisionEngine().analyze(self._market(), chart, {}, indicators)
        self.assertEqual(missing["status"], "NOT_READY")
        self.assertEqual(missing["engine_3_indicator_status"], "INVALID_INDICATOR_PAYLOAD")
        indicators = IndicatorsEngine().analyze(chart["candle_history"])
        indicators["signal_quality"] = 0.59
        weak = DecisionEngine().analyze(self._market(), chart, {}, indicators)
        self.assertEqual(weak["status"], "NOT_READY")
        self.assertEqual(weak["engine_3_indicator_status"], "INVALID_INDICATOR_PAYLOAD")

    def _daily_risk_bridge(self, *, locked: bool, positions: list[dict] | None = None) -> dict:
        now = int(time.time() * 1000)
        return {
            "status": "CONNECTED", "symbol": "BTC", "market_symbol": "BTCUSDT",
            "magic_number": 26110201, "quote_age_seconds": 1.0,
            "quote": {"bid": 99.9, "ask": 100.0, "time_ms": now, "tick_age_seconds": 1.0},
            "account": {"equity": 1000.0},
            "symbol_spec": {
                "tick_size": 0.1, "tick_value_loss": 1.0, "point": 0.1,
                "digits": 1, "volume_min": 0.01, "volume_step": 0.01,
                "volume_max": 10.0, "stops_level_points": 0, "freeze_level_points": 0,
            },
            "positions": positions or [],
            "daily_risk_required": True,
            "daily_risk": {
                "status": "READY", "locked": locked,
                "new_entries_blocked": locked,
                "max_daily_loss_fraction": 0.02,
                "daily_loss_fraction": 0.021 if locked else 0.005,
                "day_utc": "2026-11-03",
            },
        }

    def test_engine4_ready_decision_is_published_through_engine5_mir1(self) -> None:
        chart = self._chart()
        indicators = IndicatorsEngine().analyze(chart["candle_history"])
        bridge = self._daily_risk_bridge(locked=False)
        bridge.update({
            "terminal_connected": True,
            "execution_enabled": True,
            "execution_input_enabled": True,
            "trade_permissions_available": True,
        })
        intelligence = {
            "status": "PARTIAL",
            "economic_calendar": {
                "status": "EMPTY",
                "high_impact_window_active": False,
                "events": [],
            },
        }

        decision = DecisionEngine().analyze(
            self._market(),
            chart,
            bridge,
            indicators,
            engine2_price_action=make_engine2_price_action(),
            market_intelligence=intelligence,
        )
        self.assertEqual(decision["action"], "BUY")
        self.assertTrue(decision["command_ready"])
        self.assertEqual(decision["risk_plan"]["status"], "READY")

        with tempfile.TemporaryDirectory() as temp:
            engine = MT5BridgeEngine(common_files=temp)
            with patch.object(bridge_module, "ENABLE_ORDER_PUBLISH", True):
                published = engine.publish_decision(decision, bridge)

            self.assertEqual(published["status"], "PUBLISHED")
            command_path = Path(temp) / "MirsadBTC" / "command.json"
            self.assertTrue(command_path.is_file())
            envelope = json.loads(command_path.read_text(encoding="utf-8"))
            self.assertEqual(envelope["command_id"], decision["signal_id"])
            self.assertEqual(envelope["action"], "BUY")
            self.assertEqual(envelope["symbol"], "BTC")
            self.assertEqual(envelope["market_symbol"], "BTCUSDT")
            self.assertEqual(envelope["volume"], decision["risk_plan"]["volume"])
            self.assertEqual(envelope["stop_loss"], decision["stop_loss"])
            self.assertEqual(envelope["take_profit"], decision["take_profit"])
            self.assertEqual(envelope["magic_number"], 26110201)

    def test_full_engine1_to_engine5_open_ack_position_reconciliation(self) -> None:
        """Exercise a complete simulated E1/E2/E3 -> E4 -> E5 command/ACK/reconciliation cycle."""
        chart = self._chart()
        indicators = IndicatorsEngine().analyze(chart["candle_history"])
        indicators["mt5_native"] = {"status": "READY"}
        indicators["mt5_native_parity"] = {
            "status": "PASS",
            "passed_metrics": 120,
            "total_metrics": 120,
            "failures": [],
        }
        bridge = self._daily_risk_bridge(locked=False)
        bridge.update({
            "terminal_connected": True,
            "execution_enabled": True,
            "execution_input_enabled": True,
            "trade_permissions_available": True,
        })
        intelligence = {
            "status": "PARTIAL",
            "economic_calendar": {
                "status": "EMPTY",
                "high_impact_window_active": False,
                "events": [],
            },
        }

        decision = DecisionEngine().analyze(
            self._market(),
            chart,
            bridge,
            indicators,
            engine2_price_action=make_engine2_price_action(),
            market_intelligence=intelligence,
            require_mt5_native_parity=True,
        )
        self.assertEqual(decision["status"], "READY")
        self.assertEqual(decision["action"], "BUY")
        self.assertTrue(decision["command_ready"])
        self.assertEqual(decision["risk_plan"]["status"], "READY")
        self.assertAlmostEqual(
            sum(decision["decision_weights"]["configured"].values()), 1.0
        )

        with tempfile.TemporaryDirectory() as temp:
            engine = MT5BridgeEngine(common_files=temp)
            with patch.object(bridge_module, "ENABLE_ORDER_PUBLISH", True):
                published = engine.publish_decision(decision, bridge)
            self.assertEqual(published["status"], "PUBLISHED")

            root = Path(temp) / "MirsadBTC"
            command_path = root / "command.json"
            self.assertTrue(command_path.is_file())
            command = json.loads(command_path.read_text(encoding="utf-8"))
            self.assertEqual(command["schema"], "MIR1")
            self.assertEqual(command["command_id"], decision["signal_id"])
            self.assertEqual(command["action"], "BUY")
            self.assertEqual(command["magic_number"], bridge["magic_number"])
            self.assertEqual(command["position_snapshot_before"], [])

            # Simulate the EA ACK and a later MT5 positions heartbeat. No broker
            # connection or order is made; only the exact MIR1 filesystem contract
            # consumed by Engine 5 is exercised in this temporary directory.
            ack_at_ms = int(time.time() * 1000)
            heartbeat_at_ms = ack_at_ms + 1000
            position = {
                "ticket": 987654,
                "position_id": 987654,
                "symbol": command["symbol"],
                "type": 0,
                "magic": command["magic_number"],
                "volume": command["volume"],
                "price_open": command["entry_reference"],
                "stop_loss": command["stop_loss"],
                "take_profit": command["take_profit"],
                "profit": 0.0,
            }
            ack = {
                "schema": "MIR1",
                "command_id": command["command_id"],
                "state": "FILLED",
                "ack_at_ms": ack_at_ms,
                "filled_volume": command["volume"],
                "position_ticket": position["ticket"],
                "message": "SIMULATED_ACCEPTANCE_ONLY",
            }
            status = {
                "schema": "MIR1",
                "terminal_connected": True,
                "execution_enabled": True,
                "execution_input_enabled": True,
                "trade_permissions_available": True,
                "heartbeat_at_ms": heartbeat_at_ms,
                "symbol": command["symbol"],
                "market_symbol": command["market_symbol"],
                "magic_number": command["magic_number"],
                "account": {"equity": bridge["account"]["equity"], "currency": "USD"},
                "quote": {
                    "time_ms": heartbeat_at_ms,
                    "bid": command["entry_reference"] - 0.1,
                    "ask": command["entry_reference"],
                    "tick_age_seconds": 1.0,
                },
                "symbol_spec": bridge["symbol_spec"],
                "positions": [position],
            }
            (root / "ack.json").write_text(json.dumps(ack), encoding="utf-8")
            (root / "positions.json").write_text(json.dumps([position]), encoding="utf-8")
            (root / "status.json").write_text(json.dumps(status), encoding="utf-8")

            with patch(
                "mirsad.engines.mt5_bridge.time.time",
                return_value=heartbeat_at_ms / 1000.0,
            ):
                inspected = engine.inspect()

            self.assertEqual(inspected["status"], "CONNECTED")
            self.assertTrue(inspected["positions_snapshot_valid"])
            self.assertTrue(inspected["positions_file_valid"])
            self.assertEqual(inspected["last_order_ack"]["state"], "FILLED")
            self.assertEqual(
                inspected["position_reconciliation"]["status"], "CONFIRMED"
            )
            self.assertEqual(
                inspected["position_reconciliation"]["observed_volume_delta"],
                command["volume"],
            )

    def test_full_engine1_to_engine5_sell_and_mixed_wait_no_publish(self) -> None:
        """Verify bearish end-to-end publishing and mixed-structure fail-closed behavior."""
        chart = {
            "status": "READY",
            "candle_history": make_engine2_candle_history("down", 90),
        }
        indicators = IndicatorsEngine().analyze(chart["candle_history"])
        indicators["mt5_native"] = {"status": "READY"}
        indicators["mt5_native_parity"] = {
            "status": "PASS",
            "passed_metrics": 120,
            "total_metrics": 120,
            "failures": [],
        }
        bridge = self._daily_risk_bridge(locked=False)
        bridge.update({
            "terminal_connected": True,
            "execution_enabled": True,
            "execution_input_enabled": True,
            "trade_permissions_available": True,
        })
        intelligence = {
            "status": "PARTIAL",
            "direction": "BEARISH",
            "directional_score": -0.90,
            "confidence": 0.95,
            "evidence_coverage": 0.95,
            "economic_calendar": {
                "status": "EMPTY",
                "high_impact_window_active": False,
                "events": [],
            },
        }

        decision = DecisionEngine().analyze(
            self._market(),
            chart,
            bridge,
            indicators,
            engine2_price_action=make_engine2_price_action(
                direction="BEARISH", score=-0.80
            ),
            market_intelligence=intelligence,
            require_mt5_native_parity=True,
        )
        self.assertEqual(decision["status"], "READY")
        self.assertEqual(decision["candidate_action"], "SELL")
        self.assertEqual(decision["action"], "SELL")
        self.assertTrue(decision["command_ready"])
        self.assertLess(
            decision["take_profit"],
            decision["entry_reference"],
        )
        self.assertLess(
            decision["entry_reference"],
            decision["stop_loss"],
        )
        self.assertEqual(decision["risk_plan"]["status"], "READY")

        with tempfile.TemporaryDirectory() as temp:
            engine = MT5BridgeEngine(common_files=temp)
            with patch.object(bridge_module, "ENABLE_ORDER_PUBLISH", True):
                published = engine.publish_decision(decision, bridge)
            self.assertEqual(published["status"], "PUBLISHED")
            command = json.loads(
                (Path(temp) / "MirsadBTC" / "command.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(command["schema"], "MIR1")
            self.assertEqual(command["action"], "SELL")
            self.assertEqual(command["command_id"], decision["signal_id"])
            self.assertEqual(command["magic_number"], bridge["magic_number"])

        mixed_price_action = {
            "engine": "engine_2_native_price_action",
            "source": "MT5_COPYRATES_CLOSED_BARS",
            "status": "READY",
            "direction": "MIXED_TIMEFRAME_DIRECTIONS",
            "structure_score": -0.08,
            "summary": {
                "eligible_timeframes": ["1m", "5m", "15m", "1h", "4h", "1d"],
                "timeframe_alignment": "MIXED_TIMEFRAME_DIRECTIONS",
                "timeframe_weight_coverage": 1.0,
                "directional_frame_coverage": 0.50,
                "directional_structure_agreement": 0.6667,
                "directional_evidence_coverage": 0.95,
                "latest_candle_pattern_alignment": "NO_DIRECTIONAL_CANDLE_PATTERN",
            },
        }
        wait = DecisionEngine().analyze(
            self._market(),
            chart,
            bridge,
            indicators,
            engine2_price_action=mixed_price_action,
            market_intelligence=intelligence,
            require_mt5_native_parity=True,
        )
        self.assertEqual(wait["action"], "WAIT")
        self.assertEqual(wait["candidate_action"], "WAIT")
        self.assertFalse(wait["command_ready"])
        self.assertEqual(wait["status"], "WAITING_FOR_ENGINE_2")

        with tempfile.TemporaryDirectory() as temp:
            engine = MT5BridgeEngine(common_files=temp)
            with patch.object(bridge_module, "ENABLE_ORDER_PUBLISH", True):
                rejected = engine.publish_decision(wait, bridge)
            self.assertEqual(rejected["status"], "REJECTED")
            self.assertFalse(
                (Path(temp) / "MirsadBTC" / "command.json").exists()
            )

    def test_market_snapshot_time_does_not_change_order_signal_identity(self) -> None:
        intelligence = {
            "status": "PARTIAL",
            "economic_calendar": {"status": "EMPTY", "high_impact_window_active": False, "events": []},
        }
        engine2_data = self._chart()
        indicators = IndicatorsEngine().analyze(engine2_data["candle_history"])
        price_action = make_engine2_price_action()
        market_a = self._market()
        market_b = {**market_a, "captured_at_ms": market_a["captured_at_ms"] + 5000}
        open_a = DecisionEngine().analyze(
            market_a, engine2_data, self._daily_risk_bridge(locked=False),
            indicators, engine2_price_action=price_action, market_intelligence=intelligence,
        )
        open_b = DecisionEngine().analyze(
            market_b, engine2_data, self._daily_risk_bridge(locked=False),
            indicators, engine2_price_action=price_action, market_intelligence=intelligence,
        )
        self.assertEqual(open_a["candidate_action"], "BUY")
        self.assertEqual(open_a["action"], "BUY")
        self.assertEqual(open_a["signal_id"], open_b["signal_id"])
        opposite_position = [{
            "ticket": 7654321, "symbol": "BTC", "type": 1,
            "magic": 26110201, "volume": 0.1,
        }]
        close_a = DecisionEngine().analyze(
            market_a, engine2_data,
            self._daily_risk_bridge(locked=False, positions=opposite_position),
            indicators, engine2_price_action=price_action, market_intelligence=intelligence,
        )
        close_b = DecisionEngine().analyze(
            market_b, engine2_data,
            self._daily_risk_bridge(locked=False, positions=opposite_position),
            indicators, engine2_price_action=price_action, market_intelligence=intelligence,
        )
        self.assertEqual(close_a["action"], "CLOSE")
        self.assertEqual(close_a["position_ticket"], 7654321)
        self.assertEqual(close_a["signal_id"], close_b["signal_id"])

    def test_daily_loss_lock_blocks_new_buy_or_sell_entry(self) -> None:
        chart = self._chart()
        indicators = IndicatorsEngine().analyze(chart["candle_history"])
        result = DecisionEngine().analyze(
            self._market(), chart, self._daily_risk_bridge(locked=True), indicators,
            engine2_price_action=make_engine2_price_action(),
            market_intelligence={
                "status": "PARTIAL",
                "economic_calendar": {
                    "status": "EMPTY",
                    "high_impact_window_active": False,
                    "events": [],
                },
            },
        )
        self.assertEqual(result["candidate_action"], "BUY")
        self.assertEqual(result["action"], "WAIT")
        self.assertFalse(result["command_ready"])
        self.assertEqual(result["risk_plan"]["status"], "BLOCKED")
        self.assertIn("Daily loss cap", result["open_block_reason"])
        self.assertTrue(result["daily_risk_gate"]["new_entry_blocked"])

    def test_disabled_daily_loss_guard_does_not_block_entry_when_other_gates_pass(self) -> None:
        chart = self._chart()
        indicators = IndicatorsEngine().analyze(chart["candle_history"])
        bridge = self._daily_risk_bridge(locked=False)
        bridge["daily_risk"] = {
            "status": "READY",
            "mode": "DISABLED_FOR_DEVELOPMENT",
            "enabled": False,
            "locked": False,
            "new_entries_blocked": False,
            "max_daily_loss_fraction": None,
            "daily_loss_fraction": None,
        }

        # A valid EMPTY calendar means the provider responded successfully
        # and confirmed there are no current high-impact events.
        verified_empty_calendar = {
            "status": "PARTIAL",
            "economic_calendar": {
                "status": "EMPTY",
                "high_impact_window_active": False,
                "events": [],
            },
        }
        result = DecisionEngine().analyze(
            self._market(), chart, bridge, indicators,
            engine2_price_action=make_engine2_price_action(),
            market_intelligence=verified_empty_calendar,
        )

        self.assertEqual(result["macro_event_gate"]["status"], "CLEAR")
        self.assertTrue(result["macro_event_gate"]["calendar_verified"])
        self.assertFalse(result["macro_event_gate"]["new_entries_paused"])
        self.assertEqual(result["candidate_action"], "BUY")
        self.assertEqual(result["action"], "BUY")
        self.assertTrue(result["command_ready"])
        self.assertEqual(result["daily_risk_gate"]["status"], "READY")
        self.assertFalse(result["daily_risk_gate"]["new_entry_blocked"])

    def test_daily_loss_lock_does_not_block_opposite_position_close(self) -> None:
        chart = self._chart()
        indicators = IndicatorsEngine().analyze(chart["candle_history"])
        bridge = self._daily_risk_bridge(
            locked=True,
            positions=[{
                "ticket": 345678, "symbol": "BTC", "type": 1,
                "magic": 26110201, "volume": 0.1,
            }],
        )
        result = DecisionEngine().analyze(
            self._market(), chart, bridge, indicators,
            engine2_price_action=make_engine2_price_action(),
        )
        self.assertEqual(result["action"], "CLOSE")
        self.assertTrue(result["command_ready"])
        self.assertEqual(result["position_ticket"], 345678)
        self.assertTrue(result["daily_risk_gate"]["new_entry_blocked"])

    def test_required_but_missing_daily_risk_baseline_fails_closed_for_entry(self) -> None:
        chart = self._chart()
        indicators = IndicatorsEngine().analyze(chart["candle_history"])
        bridge = self._daily_risk_bridge(locked=False)
        bridge["daily_risk"] = {"status": "ACCOUNT_EQUITY_UNAVAILABLE", "locked": True}
        result = DecisionEngine().analyze(
            self._market(), chart, bridge, indicators,
            engine2_price_action=make_engine2_price_action(),
        )
        self.assertEqual(result["candidate_action"], "BUY")
        self.assertEqual(result["action"], "WAIT")
        self.assertFalse(result["command_ready"])
        self.assertEqual(result["daily_risk_gate"]["status"], "ACCOUNT_EQUITY_UNAVAILABLE")

    def test_engine4_partial_take_profit_requires_complete_history_and_precedes_stop_update(self) -> None:
        chart = self._chart()
        indicators = IndicatorsEngine().analyze(chart["candle_history"])
        atr5 = float(indicators["values"]["atr14_5m"])
        market = self._market()
        bid = 100.0 + 1.8 * atr5
        bridge = self._daily_risk_bridge(
            locked=False,
            positions=[{
                "ticket": 123456, "position_id": 501, "symbol": "BTC", "type": 0,
                "magic": 26110201, "volume": 0.10, "price_open": 100.0,
                "stop_loss": 90.0, "take_profit": 130.0,
            }],
        )
        bridge["quote"] = {
            "bid": bid, "ask": bid + 0.1,
            "time_ms": int(time.time() * 1000), "tick_age_seconds": 1.0,
        }
        bridge["position_management_history"] = {
            "status": "READY",
            "cycles": {"501": {
                "state": "OPEN_FROM_CAPTURED_ENTRY", "direction": "LONG",
                "entry_count": 1, "exit_count": 0, "reversal_count": 0,
                "history_starts_with_entry": True,
                "opened_volume": 0.10, "remaining_signed_volume": 0.10,
            }},
        }

        result = DecisionEngine().analyze(market, chart, bridge, indicators)

        self.assertEqual(result["action"], "CLOSE")
        self.assertTrue(result["command_ready"])
        self.assertEqual(result["position_ticket"], 123456)
        self.assertEqual(result["risk_plan"]["purpose"], "one_time_partial_take_profit")
        self.assertAlmostEqual(result["risk_plan"]["volume"], 0.05)
        self.assertEqual(result["position_management"]["stage"], "PARTIAL_TAKE_PROFIT")
        self.assertTrue(result["position_management"]["history_verified"])

        # Once any exit is recorded, that position is never offered another
        # partial take-profit; its remaining exposure returns to stop management.
        bridge["positions"][0]["volume"] = 0.05
        bridge["position_management_history"]["cycles"]["501"].update({
            "exit_count": 1, "opened_volume": 0.10, "remaining_signed_volume": 0.05,
        })
        repeated = DecisionEngine().analyze(market, chart, bridge, indicators)
        self.assertNotEqual(repeated["action"], "CLOSE")
        self.assertFalse(
            repeated.get("position_management", {}).get("stage") == "PARTIAL_TAKE_PROFIT"
        )

    def test_engine4_protective_stop_management_precedes_directional_entry_gates(self) -> None:
        chart = self._chart()
        chart["status"] = "NOT_READY"
        indicators = IndicatorsEngine().analyze(chart["candle_history"])
        now = int(time.time() * 1000)
        market = self._market()
        market["status"] = "STALE"
        market["venue_count"] = 0
        market["primary_venue"] = None
        market["price"] = None
        bridge = {
            "status": "CONNECTED", "symbol": "BTC", "market_symbol": "BTCUSDT",
            "magic_number": 26110201, "quote_age_seconds": 1.0,
            "quote": {"bid": 200.0, "ask": 200.1, "time_ms": now, "tick_age_seconds": 1.0},
            "account": {"equity": 1000.0},
            "symbol_spec": {"tick_size": 0.1, "point": 0.1, "digits": 1,
                            "stops_level_points": 0, "freeze_level_points": 0},
            "positions": [{
                "ticket": 123456, "symbol": "BTC", "type": 0, "magic": 26110201,
                "volume": 0.1, "price_open": 100.0, "stop_loss": 90.0, "take_profit": 220.0,
            }],
        }
        result = DecisionEngine().analyze(market, chart, bridge, indicators)
        self.assertEqual(result["action"], "MODIFY")
        self.assertTrue(result["command_ready"])
        self.assertEqual(result["position_ticket"], 123456)
        self.assertEqual(result["position_management"]["action"], "MODIFY")
        self.assertEqual(result["chart_gate"], "POSITION_MANAGEMENT_PRIORITY")
        self.assertEqual(result["engine_inputs"]["engine_5_execution_quote_feed"], "STALE")
        self.assertFalse(result["engine_inputs"]["engine_1_intelligence_required_for_protective_management"])
        self.assertFalse(result["management_plan"]["decision_eligible"])
        self.assertGreater(result["stop_loss"], 100.0)

    def test_engine4_rejects_ready_indicator_payload_with_wrong_provenance(self) -> None:
        chart = self._chart()
        indicators = IndicatorsEngine().analyze(chart["candle_history"])
        indicators["source"] = "external_unverified_candles"

        result = DecisionEngine().analyze(self._market(), chart, {}, indicators)
        self.assertEqual(result["status"], "NOT_READY")
        self.assertEqual(result["action"], "WAIT")
        self.assertEqual(result["engine_3_indicator_status"], "INVALID_PROVENANCE")

    def test_native_ohlc_price_action_contributes_its_engine2_vote(self) -> None:
        market = self._market()
        chart = self._chart()
        indicators = IndicatorsEngine().analyze(chart["candle_history"])
        price_action = {
            "engine": "engine_2_native_price_action",
            "source": "MT5_COPYRATES_CLOSED_BARS",
            "status": "READY",
            "direction": "BULLISH",
            "structure_score": 0.80,
            "summary": {
                "eligible_timeframes": ["1m", "5m", "15m", "1h", "4h"],
                "timeframe_alignment": "BULLISH_STRUCTURE_CONFLUENCE",
                "timeframe_weight_coverage": 0.90,
                "directional_frame_coverage": 0.80,
                "directional_structure_agreement": 0.80,
                "latest_candle_pattern_alignment": "NO_DIRECTIONAL_CANDLE_PATTERN",
            },
        }

        result = DecisionEngine().analyze(
            market, chart, {}, indicators, engine2_price_action=price_action
        )
        self.assertEqual(result["candidate_action"], "BUY")
        self.assertEqual(result["status"], "READY")
        self.assertEqual(result["engine_2_score_source"], "NATIVE_MT5_OHLC_ONLY")
        self.assertAlmostEqual(result["decision_scores"]["engine_2_score"], 0.80)
        self.assertEqual(result["chart_gate"], "20_55_25_NATIVE_OHLC_CONFIRMED")

    def test_waiting_score_diagnostic_uses_current_20_55_25_weight_profile(self) -> None:
        market = self._market()
        chart = self._chart()
        indicators = IndicatorsEngine().analyze(chart["candle_history"])
        price_action = make_engine2_price_action("BULLISH", score=0.30)
        intelligence = {
            "status": "READY",
            "direction": "BEARISH",
            "directional_score": -1.0,
            "confidence": 1.0,
            "evidence_coverage": 1.0,
        }

        result = DecisionEngine().analyze(
            market, chart, {}, indicators,
            engine2_price_action=price_action,
            market_intelligence=intelligence,
        )

        self.assertEqual(result["candidate_action"], "WAIT")
        self.assertEqual(
            result["chart_gate"],
            "20_55_25_SCORE_BELOW_THRESHOLD_OR_CONFLICT",
        )

    def test_engine4_rejects_missing_or_nonfinite_required_indicator_values(self) -> None:
        chart = self._chart()
        indicators = IndicatorsEngine().analyze(chart["candle_history"])
        indicators["values"]["atr14_5m"] = float("nan")

        result = DecisionEngine().analyze(self._market(), chart, {}, indicators)
        self.assertEqual(result["status"], "NOT_READY")
        self.assertEqual(result["action"], "WAIT")
        self.assertEqual(result["engine_3_indicator_status"], "INVALID_INDICATOR_PAYLOAD")


    def test_engine4_reduces_engine2_quality_when_supporting_evidence_is_absent(self) -> None:
        chart = self._chart()
        indicators = IndicatorsEngine().analyze(chart["candle_history"])
        price_action = make_engine2_price_action()
        price_action["summary"]["directional_evidence_coverage"] = 0.70
        result = DecisionEngine().analyze(
            self._market(), chart, {}, indicators,
            engine2_price_action=price_action,
        )
        self.assertAlmostEqual(result["decision_scores"]["engine_2_evidence_coverage"], 0.70)
        self.assertAlmostEqual(result["decision_scores"]["engine_2_quality"], 0.70)

    def test_engine4_requires_sufficient_directional_frame_coverage(self) -> None:
        chart = self._chart()
        indicators = IndicatorsEngine().analyze(chart["candle_history"])
        price_action = make_engine2_price_action()
        price_action["summary"]["directional_structure_agreement"] = 1.0
        price_action["summary"]["directional_frame_coverage"] = 0.50

        blocked = DecisionEngine().analyze(
            self._market(), chart, {}, indicators,
            engine2_price_action=price_action,
        )
        context = blocked["engine_2_native_price_action_context"]
        self.assertFalse(context["decision_eligible"])
        self.assertEqual(context["gate"], "INSUFFICIENT_DIRECTIONAL_FRAME_COVERAGE")
        self.assertEqual(blocked["candidate_action"], "WAIT")
        self.assertEqual(
            blocked["decision_scores"]["engine_2_directional_frame_coverage"],
            0.50,
        )

        price_action["summary"]["directional_frame_coverage"] = 0.6667
        accepted = DecisionEngine().analyze(
            self._market(), chart, {}, indicators,
            engine2_price_action=price_action,
        )
        self.assertTrue(accepted["engine_2_native_price_action_context"]["decision_eligible"])
        self.assertAlmostEqual(accepted["decision_scores"]["engine_2_quality"], 0.6667, places=4)

    def test_engine4_blocks_engine2_direction_below_core_evidence_coverage(self) -> None:
        chart = self._chart()
        indicators = IndicatorsEngine().analyze(chart["candle_history"])
        price_action = make_engine2_price_action()
        price_action["summary"]["directional_evidence_coverage"] = 0.69
        result = DecisionEngine().analyze(
            self._market(), chart, {}, indicators,
            engine2_price_action=price_action,
        )
        self.assertFalse(result["engine_2_native_price_action_context"]["decision_eligible"])
        self.assertEqual(result["engine_2_native_price_action_context"]["gate"],
                         "INSUFFICIENT_STRUCTURE_EVIDENCE_QUALITY")
        self.assertEqual(result["candidate_action"], "WAIT")
        self.assertIsNone(result["decision_scores"]["combined_score"])

    def test_engine2_native_price_action_is_primary_only_after_multitimeframe_confluence(self) -> None:
        chart = self._chart()
        chart["status"] = "READY"
        indicators = IndicatorsEngine().analyze(chart["candle_history"])
        price_action = {
            "engine": "engine_2_native_price_action",
            "source": "MT5_COPYRATES_CLOSED_BARS",
            "status": "READY",
            "direction": "MIXED_TIMEFRAME_DIRECTIONS",
            "structure_score": 0.25,
            "as_of_utc_ms": int(time.time() * 1000),
            "summary": {
                "eligible_timeframes": ["1m", "5m", "15m", "1h", "4h"],
                "timeframe_alignment": "MIXED_TIMEFRAME_DIRECTIONS",
                "timeframe_weight_coverage": 0.90,
                "directional_frame_coverage": 0.80,
                "directional_structure_agreement": 0.80,
                "latest_candle_pattern_alignment": "NO_DIRECTIONAL_CANDLE_PATTERN",
            },
            "decision_eligible": False,
        }
        without_context = DecisionEngine().analyze(self._market(), chart, {}, indicators)
        with_context = DecisionEngine().analyze(
            self._market(), chart, {}, indicators, engine2_price_action=price_action
        )

        self.assertEqual(with_context["action"], "WAIT")
        self.assertEqual(with_context["status"], "WAITING_FOR_ENGINE_2")
        self.assertEqual(
            with_context["engine_2_native_price_action_context"]["direction"],
            "MIXED_TIMEFRAME_DIRECTIONS",
        )
        self.assertEqual(
            with_context["engine_2_native_price_action_context"]["role"],
            "PRIMARY_ENGINE_2_NATIVE_OHLC_DIRECTIONAL_VOTE",
        )
        self.assertEqual(without_context["candidate_action"], "WAIT")
        self.assertIsNone(without_context["decision_scores"]["engine_2_score"])
        self.assertEqual(with_context["candidate_action"], "WAIT")
        self.assertIsNone(with_context["decision_scores"]["combined_score"])
        self.assertEqual(with_context["chart_gate"], "WAITING_FOR_ENGINE_2_PRICE_ACTION_CONFLUENCE")
        self.assertEqual(
            with_context["engine_2_native_price_action_context"]["gate"],
            "MIXED_OR_NO_CONFLUENCE",
        )
        self.assertEqual(
            without_context["engine_2_native_price_action_context"]["gate"],
            "NATIVE_OHLC_NOT_PROVIDED",
        )

        aligned_price_action = {
            **price_action,
            "direction": "BULLISH",
            "summary": {
                **price_action["summary"],
                "timeframe_alignment": "BULLISH_STRUCTURE_CONFLUENCE",
                "directional_structure_agreement": 0.80,
                "timeframe_weight_coverage": 0.90,
            },
        }
        # A valid price-action confluence is necessary but still not enough
        # by itself: the composite must cross the fixed-share 20/55/25 gate.
        aligned_indicators = {
            **indicators,
            "signal_score": 0.80,
            "signal_quality": 1.0,
            "signal_timeframe_weight_coverage": 1.0,
        }
        aligned_intelligence = {
            "status": "READY",
            "direction": "BULLISH",
            "directional_score": 0.60,
            "confidence": 1.0,
            "evidence_coverage": 1.0,
        }
        aligned = DecisionEngine().analyze(
            self._market(), chart, {}, aligned_indicators,
            engine2_price_action=aligned_price_action,
            market_intelligence=aligned_intelligence,
        )
        self.assertEqual(aligned["candidate_action"], "BUY")
        self.assertAlmostEqual(aligned["decision_scores"]["combined_score"], 0.43)
        self.assertEqual(aligned["engine_2_score_source"], "NATIVE_MT5_OHLC_ONLY")
        self.assertAlmostEqual(aligned["decision_scores"]["engine_2_score"], 0.25)
        self.assertEqual(
            aligned["engine_2_native_price_action_context"]["gate"],
            "BULLISH_CONFLUENCE",
        )

        aligned_patterns = {
            **aligned_price_action,
            "summary": {
                **aligned_price_action["summary"],
                "latest_candle_pattern_alignment": "BULLISH_CANDLE_PATTERN_EVIDENCE",
                "bullish_pattern_timeframes": ["5m", "15m"],
            },
        }
        aligned_pattern_result = DecisionEngine().analyze(
            self._market(), chart, {}, aligned_indicators,
            engine2_price_action=aligned_patterns,
            market_intelligence=aligned_intelligence,
        )
        self.assertEqual(aligned_pattern_result["candidate_action"], "BUY")
        self.assertEqual(
            aligned_pattern_result["engine_2_native_price_action_context"]["gate"],
            "BULLISH_CONFLUENCE",
        )

        conflicting_patterns = {
            **aligned_price_action,
            "summary": {
                **aligned_price_action["summary"],
                "latest_candle_pattern_alignment": "BEARISH_CANDLE_PATTERN_EVIDENCE",
                "bearish_pattern_timeframes": ["5m", "15m"],
            },
        }
        pattern_veto = DecisionEngine().analyze(
            self._market(), chart, {}, indicators, engine2_price_action=conflicting_patterns
        )
        self.assertEqual(pattern_veto["candidate_action"], "WAIT")
        self.assertEqual(
            pattern_veto["engine_2_native_price_action_context"]["gate"],
            "CANDLE_PATTERN_DIRECTION_CONFLICT",
        )
        self.assertEqual(pattern_veto["chart_gate"], "WAITING_FOR_ENGINE_2_CANDLE_PATTERN_CONFLUENCE")
        self.assertEqual(
            pattern_veto["engine_2_native_price_action_context"]["latest_candle_pattern_alignment"],
            "BEARISH_CANDLE_PATTERN_EVIDENCE",
        )

        mixed_patterns = {
            **aligned_price_action,
            "summary": {
                **aligned_price_action["summary"],
                "latest_candle_pattern_alignment": "MIXED_CANDLE_PATTERN_EVIDENCE",
            },
        }
        mixed_pattern_veto = DecisionEngine().analyze(
            self._market(), chart, {}, indicators, engine2_price_action=mixed_patterns
        )
        self.assertEqual(mixed_pattern_veto["candidate_action"], "WAIT")
        self.assertEqual(
            mixed_pattern_veto["engine_2_native_price_action_context"]["gate"],
            "MIXED_CANDLE_PATTERN_EVIDENCE",
        )
        self.assertEqual(mixed_pattern_veto["chart_gate"], "WAITING_FOR_ENGINE_2_CANDLE_PATTERN_CONFLUENCE")


    def test_engine4_waits_when_live_like_engine2_structure_has_no_timeframe_confluence(self) -> None:
        chart = self._chart()
        indicators = IndicatorsEngine().analyze(chart["candle_history"])
        indicators["trend_score"] = -0.60
        indicators["signal_score"] = -0.341163
        indicators["signal_quality"] = 1.0
        price_action = {
            "engine": "engine_2_native_price_action",
            "source": "MT5_COPYRATES_CLOSED_BARS",
            "status": "READY",
            "direction": "BULLISH",
            "structure_score": 0.3077,
            "summary": {
                "eligible_timeframes": ["5m", "15m", "1h", "4h"],
                "timeframe_alignment": "NO_CLEAR_STRUCTURE_CONFLUENCE",
                "timeframe_weight_coverage": 0.6842,
                "directional_frame_coverage": 1.0,
                "directional_structure_agreement": 1.0,
                "latest_candle_pattern_alignment": "NO_LATEST_DIRECTIONAL_CANDLE_PATTERN",
            },
            "decision_eligible": False,
        }

        result = DecisionEngine().analyze(
            self._market(), chart, {}, indicators, engine2_price_action=price_action
        )

        self.assertEqual(result["candidate_action"], "WAIT")
        self.assertEqual(result["action"], "WAIT")
        self.assertEqual(result["engine_2_native_price_action_context"]["gate"], "MIXED_OR_NO_CONFLUENCE")
        self.assertEqual(result["chart_gate"], "WAITING_FOR_ENGINE_2_PRICE_ACTION_CONFLUENCE")
        self.assertIsNone(result["decision_scores"]["combined_score"])
        self.assertAlmostEqual(result["decision_scores"]["engine_3_indicators"], -0.3412, places=4)
        self.assertFalse(result["command_ready"])



class DecisionBoundaryTests(unittest.TestCase):
    def test_one_verified_mt5_source_passes_market_quorum_but_still_needs_engine3_history(self) -> None:
        result = DecisionEngine().analyze(
            {
                "status": "LIVE", "source": "MT5_TERMINAL", "venue_count": 1,
                "primary_venue": "MT5 Broker",
                "feed_health": {"terminal_connected": True, "quote_fresh": True},
                "venues": {"MT5 Broker": {"status": "LIVE"}},
            },
            {},
            {},
        )
        self.assertEqual(result["action"], "WAIT")
        self.assertEqual(result["status"], "NOT_READY")
        self.assertIn("Engine 2", result["reason"])

    def test_one_public_venue_without_mt5_identity_is_still_blocked(self) -> None:
        result = DecisionEngine().analyze(
            {"status": "LIVE", "venue_count": 1, "primary_venue": "Public Venue"},
            {},
            {},
        )
        self.assertEqual(result["action"], "WAIT")
        self.assertEqual(result["status"], "NOT_READY")
        self.assertIn("at least two independent public venues", result["reason"])

    def test_price_rounding_respects_broker_tick(self) -> None:
        self.assertAlmostEqual(_price_to_tick(100.03, 0.05, 2, "UP"), 100.05)
        self.assertAlmostEqual(_price_to_tick(100.03, 0.05, 2, "DOWN"), 100.00)

    def test_mt5_price_divergence_is_exposed_and_rejected(self) -> None:
        now = int(time.time() * 1000)
        candles = []
        for i in range(80):
            close = 70.0 + 0.2 * i
            candles.append({
                "open_time_ms": now - (80 - i) * 60_000,
                "open": close - 0.1, "high": close + 0.2,
                "low": close - 0.2, "close": close,
                "volume": 1.0, "closed": True,
            })
        frames = {tf: candles for tf in ("1m", "5m", "15m", "1h", "4h", "1d")}
        market = {
            "status": "LIVE", "venue_count": 2, "symbol": "BTCUSDT",
            "price": 100.0, "captured_at_ms": now, "primary_venue": "OKX Spot",
            "venues": {
                "OKX Spot": {"status": "LIVE", "candles_by_tf": frames, "orderflow": None},
                "Bybit Spot": {"status": "LIVE", "orderflow": {
                    "unit": "BTC", "taker_buy_quantity": 1.0,
                    "taker_sell_quantity": 1.0, "trade_count": 2}},
            },
        }
        bridge = {
            "status": "CONNECTED", "symbol": "BTC", "market_symbol": "BTCUSDT",
            "magic_number": 26110201, "positions": [],
            "quote": {"bid": 150.0, "ask": 150.1, "time_ms": now, "tick_age_seconds": 1},
            "quote_age_seconds": 1,
            "account": {"equity": 1000.0},
            "symbol_spec": {
                "tick_size": 0.01, "point": 0.01, "digits": 2,
                "tick_value_loss": 1.0, "volume_min": 0.01,
                "volume_step": 0.01, "volume_max": 10.0, "stops_level_points": 0,
            },
        }
        chart = {"status": "READY", "candle_history": make_engine2_candle_history("up", 80)}
        result = DecisionEngine().analyze(market, chart, bridge)
        self.assertGreater(result["broker_market_price_divergence_pct"], 1.0)
        self.assertIsNone(result["broker_quote"])

    def test_position_manager_only_sees_mirsad_magic(self) -> None:
        bridge = {
            "magic_number": 26110201,
            "positions": [
                {"ticket": 1, "symbol": "BTC", "type": 0, "magic": 26110201, "volume": 0.1},
                {"ticket": 2, "symbol": "BTC", "type": 1, "magic": 888, "volume": 0.2},
                {"ticket": 3, "symbol": "ETH", "type": 0, "magic": 26110201, "volume": 0.3},
            ],
        }
        positions = _matching_positions(bridge, "BTC")
        self.assertEqual([p["ticket"] for p in positions], [1])


class StorageTests(unittest.TestCase):
    def test_market_snapshot_stores_summary_not_duplicate_candle_trade_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            db = Path(temp) / "storage.sqlite3"
            now = int(time.time() * 1000)
            candle = {
                "open_time_ms": now, "open": 100.0, "high": 101.0,
                "low": 99.0, "close": 100.5, "volume": 3.0, "closed": True,
            }
            snapshot = {
                "captured_at_ms": now, "symbol": "BTCUSDT",
                "price": 100.0, "primary_venue": "OKX Spot",
                "venue_count": 1, "status": "PARTIAL",
                "venues": {
                    "OKX Spot": {
                        "status": "LIVE", "bid": 99.9, "ask": 100.1,
                        "latency_ms": 10.0,
                        "candles_by_tf": {"1m": [candle]},
                        "orderbook": {"bids": [[99.9, 2.0]], "asks": [[100.1, 3.0]], "imbalance": -0.2},
                        "trades": [{"id": "1", "time_ms": now, "price": 100.0, "quantity": 0.1, "taker_side": "BUY"}],
                    }
                },
            }
            save_market_snapshot(snapshot, db_path=db)
            conn = sqlite3.connect(db)
            try:
                payload_text = conn.execute("SELECT payload_json FROM market_snapshots").fetchone()[0]
                payload = json.loads(payload_text)
                candles = conn.execute("SELECT COUNT(*) FROM candles").fetchone()[0]
                books = conn.execute("SELECT COUNT(*) FROM orderbook_snapshots").fetchone()[0]
                trades = conn.execute("SELECT COUNT(*) FROM public_trades").fetchone()[0]
            finally:
                conn.close()
            self.assertNotIn("candles_by_tf", payload["venues"]["OKX Spot"])
            self.assertNotIn("orderbook", payload["venues"]["OKX Spot"])
            self.assertNotIn("trades", payload["venues"]["OKX Spot"])
            self.assertEqual((candles, books, trades), (1, 1, 1))


class BridgeProtocolTests(unittest.TestCase):
    def test_malformed_heartbeat_is_reported_stale_without_crashing_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "MirsadBTC"
            root.mkdir()
            (root / "status.json").write_text(json.dumps({
                "schema": "MIR1",
                "terminal_connected": True,
                "heartbeat_at_ms": "not-a-timestamp",
                "quote": None,
                "account": [],
                "symbol_spec": "invalid",
                "positions": {},
            }), encoding="utf-8")
            bridge = MT5BridgeEngine(common_files=temp).inspect()
            self.assertEqual(bridge["status"], "STALE")
            self.assertIsNone(bridge["heartbeat_age_seconds"])
            self.assertEqual(bridge["quote"], {})
            self.assertEqual(bridge["account"], {})
            self.assertEqual(bridge["symbol_spec"], {})
            self.assertEqual(bridge["positions"], [])

    def test_inspect_surfaces_ea_execution_current_command_and_event_log(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "MirsadBTC"
            root.mkdir()
            now = int(time.time() * 1000)
            (root / "status.json").write_text(json.dumps({
                "schema": "MIR1",
                "terminal_connected": True,
                "execution_enabled": False,
                "execution_input_enabled": False,
                "trade_permissions_available": True,
                "heartbeat_at_ms": now,
                "symbol": "BTC",
                "market_symbol": "BTCUSDT",
                "account": {"equity": 1000.0},
                "symbol_spec": {"tick_size": 0.1},
                "positions": [],
            }), encoding="utf-8")
            command = {"schema": "MIR1", "command_id": "MIR-" + "a" * 24, "action": "BUY"}
            ack = {"schema": "MIR1", "command_id": command["command_id"], "state": "REJECTED"}
            (root / "command.json").write_text(json.dumps(command), encoding="utf-8")
            (root / "ack.json").write_text(json.dumps(ack), encoding="utf-8")
            (root / "positions.json").write_text("[]", encoding="utf-8")
            (root / "events.jsonl").write_text(
                json.dumps({"time_ms": now, "event": "COMMAND_REJECTED", "command_id": command["command_id"]}) + "\n",
                encoding="utf-8",
            )

            bridge = MT5BridgeEngine(common_files=temp).inspect()

            self.assertEqual(bridge["status"], "CONNECTED")
            self.assertIs(bridge["terminal_connected"], True)
            self.assertIs(bridge["execution_enabled"], False)
            self.assertIs(bridge["execution_input_enabled"], False)
            self.assertIs(bridge["trade_permissions_available"], True)
            self.assertEqual(bridge["current_command"]["command_id"], command["command_id"])
            self.assertEqual(bridge["last_order_ack"]["state"], "REJECTED")
            self.assertTrue(bridge["positions_file_valid"])
            self.assertEqual(bridge["event_log"][0]["event"], "COMMAND_REJECTED")
            self.assertTrue(bridge["common_files_files"]["events.jsonl"])

    def test_fresh_heartbeat_with_malformed_positions_is_stale(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "MirsadBTC"
            root.mkdir()
            (root / "status.json").write_text(json.dumps({
                "schema": "MIR1",
                "terminal_connected": True,
                "heartbeat_at_ms": int(time.time() * 1000),
                "symbol": "BTC",
                "market_symbol": "BTCUSDT",
                "magic_number": 26110201,
                "positions": [{
                    "ticket": 123,
                    "position_id": 456,
                    "symbol": "BTC",
                    "type": 0,
                    "magic": 26110201,
                    "volume": "0.1",
                    "price_open": "60000",
                    "stop_loss": "59000",
                    "take_profit": "62000",
                    "profit": "0",
                }, {"ticket": "invalid"}],
            }), encoding="utf-8")

            bridge = MT5BridgeEngine(common_files=temp).inspect()

            self.assertEqual(bridge["status"], "STALE")
            self.assertFalse(bridge["positions_snapshot_valid"])
            self.assertEqual(bridge["positions"], [])
            self.assertIn("missing required", bridge["positions_snapshot_reason"])
            self.assertIn("missing required", bridge["message"])

    def test_fresh_heartbeat_requires_a_positions_array(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "MirsadBTC"
            root.mkdir()
            (root / "status.json").write_text(json.dumps({
                "schema": "MIR1",
                "terminal_connected": True,
                "heartbeat_at_ms": int(time.time() * 1000),
                "symbol": "BTC",
                "market_symbol": "BTCUSDT",
                "magic_number": 26110201,
            }), encoding="utf-8")

            bridge = MT5BridgeEngine(common_files=temp).inspect()

            self.assertEqual(bridge["status"], "STALE")
            self.assertFalse(bridge["positions_snapshot_valid"])
            self.assertEqual(bridge["positions"], [])
            self.assertIn("must be a JSON array", bridge["message"])

    def test_future_heartbeat_is_not_treated_as_connected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "MirsadBTC"
            root.mkdir()
            (root / "status.json").write_text(json.dumps({
                "schema": "MIR1",
                "terminal_connected": True,
                "heartbeat_at_ms": int(time.time() * 1000) + 60_000,
            }), encoding="utf-8")
            bridge = MT5BridgeEngine(common_files=temp).inspect()
            self.assertEqual(bridge["status"], "STALE")
            self.assertLess(bridge["heartbeat_age_seconds"], 0)

    def test_open_and_close_envelopes_validate(self) -> None:
        open_envelope = MT5BridgeEngine._validate_decision(make_open_decision())
        close_envelope = MT5BridgeEngine._validate_decision(make_close_decision())
        self.assertEqual(open_envelope["action"], "BUY")
        self.assertEqual(open_envelope["schema"], "MIR1")
        self.assertEqual(close_envelope["action"], "CLOSE")
        self.assertEqual(close_envelope["position_ticket"], 123456)
        modify_envelope = MT5BridgeEngine._validate_decision(make_modify_decision())
        self.assertEqual(modify_envelope["action"], "MODIFY")
        self.assertEqual(modify_envelope["position_ticket"], 123456)
        self.assertEqual(modify_envelope["stop_loss"], 101.0)
        self.assertEqual(modify_envelope["take_profit"], 110.0)

    def test_modify_requires_ticket_and_valid_protective_prices(self) -> None:
        decision = make_modify_decision()
        decision["position_ticket"] = 0
        with self.assertRaises(ValueError):
            MT5BridgeEngine._validate_decision(decision)
        decision = make_modify_decision()
        decision["stop_loss"] = 0
        with self.assertRaises(ValueError):
            MT5BridgeEngine._validate_decision(decision)
        decision = make_modify_decision()
        decision["take_profit"] = -1
        with self.assertRaises(ValueError):
            MT5BridgeEngine._validate_decision(decision)

    def test_close_without_ticket_is_rejected(self) -> None:
        decision = make_close_decision()
        decision["position_ticket"] = 0
        with self.assertRaises(ValueError):
            MT5BridgeEngine._validate_decision(decision)

    def test_same_command_id_with_unknown_ack_is_never_published_again_after_restart(self) -> None:
        state = {
            "status": "CONNECTED",
            "terminal_connected": True,
            "execution_enabled": True,
            "execution_input_enabled": True,
            "trade_permissions_available": True,
        }
        with tempfile.TemporaryDirectory() as temp:
            first_engine = MT5BridgeEngine(common_files=temp)
            with patch.object(bridge_module, "ENABLE_ORDER_PUBLISH", True):
                published = first_engine.publish_decision(make_open_decision(), state)
            self.assertEqual(published["status"], "PUBLISHED")
            root = Path(temp) / "MirsadBTC"
            command_path = root / "command.json"
            original_bytes = command_path.read_bytes()
            command = json.loads(original_bytes)
            (root / "ack.json").write_text(json.dumps({
                "schema": "MIR1",
                "command_id": command["command_id"],
                "state": "UNKNOWN",
            }), encoding="utf-8")

            restarted_engine = MT5BridgeEngine(common_files=temp)
            with patch.object(bridge_module, "ENABLE_ORDER_PUBLISH", True):
                duplicate = restarted_engine.publish_decision(make_open_decision(), state)

            self.assertEqual(duplicate["status"], "ALREADY_ACKNOWLEDGED")
            self.assertEqual(command_path.read_bytes(), original_bytes)

    def test_command_is_not_replaced_while_previous_command_is_unsettled(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            engine = MT5BridgeEngine(common_files=temp)
            with patch.object(bridge_module, "ENABLE_ORDER_PUBLISH", True):
                first = engine.publish_decision(make_open_decision(), {"status": "CONNECTED", "terminal_connected": True, "execution_enabled": True, "execution_input_enabled": True, "trade_permissions_available": True})
                self.assertEqual(first["status"], "PUBLISHED")

                # Recreate the bridge object to simulate a Python process restart.
                engine = MT5BridgeEngine(common_files=temp)
                second = make_open_decision("MIR-" + "c" * 24)
                blocked = engine.publish_decision(second, {"status": "CONNECTED", "terminal_connected": True, "execution_enabled": True, "execution_input_enabled": True, "trade_permissions_available": True})
                self.assertEqual(blocked["status"], "PENDING_COMMAND_BLOCKED")

                command_path = Path(temp) / "MirsadBTC" / "command.json"
                command = json.loads(command_path.read_text(encoding="utf-8"))
                ack_path = Path(temp) / "MirsadBTC" / "ack.json"
                ack_path.write_text(json.dumps({
                    "schema": "MIR1",
                    "command_id": command["command_id"],
                    "state": "FILLED",
                }), encoding="utf-8")

                unconfirmed = engine.publish_decision(second, {"status": "CONNECTED", "terminal_connected": True, "execution_enabled": True, "execution_input_enabled": True, "trade_permissions_available": True})
                self.assertEqual(unconfirmed["status"], "PENDING_COMMAND_BLOCKED")
                published = engine.publish_decision(second, {
                    "status": "CONNECTED",
                    "terminal_connected": True,
                    "execution_enabled": True,
                    "execution_input_enabled": True,
                    "trade_permissions_available": True,
                    "position_reconciliation": {
                        "status": "CONFIRMED",
                        "command_id": command["command_id"],
                    },
                })
                self.assertEqual(published["status"], "PUBLISHED")
                replacement = json.loads(command_path.read_text(encoding="utf-8"))
                self.assertEqual(replacement["command_id"], second["signal_id"])

    def test_command_publish_disabled_switch_writes_no_mir1_command(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            engine = MT5BridgeEngine(common_files=temp)
            with patch.object(bridge_module, "ENABLE_ORDER_PUBLISH", False):
                result = engine.publish_decision(
                    make_open_decision(), {"status": "CONNECTED"}
                )
            self.assertEqual(result["status"], "PUBLISH_DISABLED")
            self.assertFalse((Path(temp) / "MirsadBTC" / "command.json").exists())

    def test_publish_requires_explicit_ea_execution_telemetry(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            engine = MT5BridgeEngine(common_files=temp)
            base = {"status": "CONNECTED", "terminal_connected": True}
            with patch.object(bridge_module, "ENABLE_ORDER_PUBLISH", True):
                disabled = engine.publish_decision(make_open_decision(), {**base, "execution_enabled": False})
                unknown = engine.publish_decision(make_open_decision(), base)
            self.assertEqual(disabled["status"], "EXECUTION_DISABLED")
            self.assertEqual(unknown["status"], "EXECUTION_STATE_UNKNOWN")
            self.assertFalse((Path(temp) / "MirsadBTC" / "command.json").exists())

    def test_publish_requires_explicit_execution_input_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            engine = MT5BridgeEngine(common_files=temp)
            state = {
                "status": "CONNECTED",
                "terminal_connected": True,
                "execution_enabled": True,
                "execution_input_enabled": False,
                "trade_permissions_available": True,
            }
            with patch.object(bridge_module, "ENABLE_ORDER_PUBLISH", True):
                result = engine.publish_decision(make_open_decision(), state)
            self.assertEqual(result["status"], "EXECUTION_INPUT_DISABLED")
            self.assertFalse((Path(temp) / "MirsadBTC" / "command.json").exists())

    def test_publish_requires_explicit_mt5_trading_permissions(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            engine = MT5BridgeEngine(common_files=temp)
            state = {
                "status": "CONNECTED",
                "terminal_connected": True,
                "execution_enabled": True,
                "execution_input_enabled": True,
                "trade_permissions_available": False,
            }
            with patch.object(bridge_module, "ENABLE_ORDER_PUBLISH", True):
                result = engine.publish_decision(make_open_decision(), state)
            self.assertEqual(result["status"], "TRADE_PERMISSIONS_UNAVAILABLE")
            self.assertFalse((Path(temp) / "MirsadBTC" / "command.json").exists())

    def test_publish_requires_terminal_connected_flag(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            engine = MT5BridgeEngine(common_files=temp)
            with patch.object(bridge_module, "ENABLE_ORDER_PUBLISH", True):
                result = engine.publish_decision(
                    make_open_decision(),
                    {"status": "CONNECTED", "execution_enabled": True},
                )
            self.assertEqual(result["status"], "TERMINAL_NOT_CONNECTED")
            self.assertFalse((Path(temp) / "MirsadBTC" / "command.json").exists())



    def test_filled_open_ack_requires_a_later_matching_position_snapshot(self) -> None:
        now = int(time.time() * 1000)
        command = {
            "command_id": "MIR-" + "a" * 24, "action": "BUY", "symbol": "BTC",
            "magic_number": 26110201, "volume": 0.2, "volume_step": 0.01,
            "position_snapshot_before": [],
        }
        ack = {
            "command_id": command["command_id"], "state": "FILLED",
            "filled_volume": 0.2, "ack_at_ms": now - 100,
        }
        stale = MT5BridgeEngine._reconcile_ack_with_positions(
            ack, command,
            [{"ticket": 11, "symbol": "BTC", "type": 0, "magic": 26110201, "volume": 0.2}],
            now - 200,
        )
        same_second = MT5BridgeEngine._reconcile_ack_with_positions(
            ack, command,
            [{"ticket": 11, "symbol": "BTC", "type": 0, "magic": 26110201, "volume": 0.2}],
            now - 100,
        )
        self.assertEqual(stale["status"], "AWAITING_POST_ACK_TELEMETRY")
        self.assertEqual(same_second["status"], "AWAITING_POST_ACK_TELEMETRY")
        confirmed = MT5BridgeEngine._reconcile_ack_with_positions(
            ack, command,
            [{"ticket": 11, "symbol": "BTC", "type": 0, "magic": 26110201, "volume": 0.2}],
            now,
        )
        self.assertEqual(confirmed["status"], "CONFIRMED")
        self.assertEqual(confirmed["observed_volume_delta"], 0.2)

    def test_filled_close_ack_is_matched_to_the_target_ticket_volume_reduction(self) -> None:
        now = int(time.time() * 1000)
        before = {
            "ticket": 123456, "symbol": "BTC", "type": 1, "magic": 26110201,
            "volume": 0.2, "stop_loss": 110.0, "take_profit": 80.0,
        }
        command = {
            "command_id": "MIR-" + "b" * 24, "action": "CLOSE", "symbol": "BTC",
            "magic_number": 26110201, "position_ticket": 123456, "volume": 0.1,
            "volume_step": 0.01, "position_snapshot_before": [before],
        }
        ack = {
            "command_id": command["command_id"], "state": "FILLED",
            "filled_volume": 0.1, "ack_at_ms": now - 50,
        }
        result = MT5BridgeEngine._reconcile_ack_with_positions(
            ack, command,
            [{**before, "volume": 0.1}],
            now,
        )
        self.assertEqual(result["status"], "CONFIRMED")
        self.assertEqual(result["observed_reduction"], 0.1)

    def test_filled_modify_ack_requires_the_requested_stop_and_unchanged_target(self) -> None:
        now = int(time.time() * 1000)
        before = {
            "ticket": 123456, "symbol": "BTC", "type": 0, "magic": 26110201,
            "volume": 0.1, "stop_loss": 90.0, "take_profit": 130.0,
        }
        command = {
            "command_id": "MIR-" + "c" * 24, "action": "MODIFY", "symbol": "BTC",
            "magic_number": 26110201, "position_ticket": 123456, "volume": 0.1,
            "stop_loss": 100.0, "take_profit": 130.0, "tick_size": 0.1,
            "position_snapshot_before": [before],
        }
        ack = {
            "command_id": command["command_id"], "state": "FILLED",
            "filled_volume": 0.0, "ack_at_ms": now - 50,
        }
        not_applied = MT5BridgeEngine._reconcile_ack_with_positions(
            ack, command, [{**before, "stop_loss": 95.0}], now
        )
        self.assertEqual(not_applied["status"], "AWAITING_POSITION_UPDATE")
        applied = MT5BridgeEngine._reconcile_ack_with_positions(
            ack, command, [{**before, "stop_loss": 100.0}], now
        )
        self.assertEqual(applied["status"], "CONFIRMED")

    def test_partial_and_unknown_ack_states_never_count_as_reconciled(self) -> None:
        command = {
            "command_id": "MIR-" + "d" * 24, "action": "BUY", "symbol": "BTC",
            "magic_number": 26110201, "volume": 0.2, "position_snapshot_before": [],
        }
        for state in ("SUBMITTED", "PARTIAL", "UNKNOWN"):
            with self.subTest(state=state):
                result = MT5BridgeEngine._reconcile_ack_with_positions(
                    {"command_id": command["command_id"], "state": state},
                    command, [], int(time.time() * 1000),
                )
                self.assertEqual(result["status"], "ACK_PENDING")

    def test_partial_open_ack_reconciles_the_actual_filled_volume(self) -> None:
        now = int(time.time() * 1000)
        command = {
            "command_id": "MIR-" + "e" * 24, "action": "BUY", "symbol": "BTC",
            "magic_number": 26110201, "volume": 0.2, "volume_step": 0.01,
            "position_snapshot_before": [],
        }
        ack = {
            "command_id": command["command_id"], "state": "PARTIAL",
            "filled_volume": 0.08, "ack_at_ms": now - 1500,
        }
        result = MT5BridgeEngine._reconcile_ack_with_positions(
            ack,
            command,
            [{"ticket": 22, "symbol": "BTC", "type": 0, "magic": 26110201, "volume": 0.08}],
            now,
        )
        self.assertEqual(result["status"], "CONFIRMED_PARTIAL")
        self.assertEqual(result["expected_volume"], 0.08)
        self.assertEqual(result["observed_volume_delta"], 0.08)

    def test_partial_close_ack_reconciles_the_actual_position_reduction(self) -> None:
        now = int(time.time() * 1000)
        before = {
            "ticket": 654321, "symbol": "BTC", "type": 0, "magic": 26110201,
            "volume": 0.2, "stop_loss": 90.0, "take_profit": 130.0,
        }
        command = {
            "command_id": "MIR-" + "f" * 24, "action": "CLOSE", "symbol": "BTC",
            "magic_number": 26110201, "position_ticket": 654321, "volume": 0.1,
            "volume_step": 0.01, "position_snapshot_before": [before],
        }
        ack = {
            "command_id": command["command_id"], "state": "PARTIAL",
            "filled_volume": 0.05, "ack_at_ms": now - 1500,
        }
        result = MT5BridgeEngine._reconcile_ack_with_positions(
            ack, command, [{**before, "volume": 0.15}], now
        )
        self.assertEqual(result["status"], "CONFIRMED_PARTIAL")
        self.assertEqual(result["expected_reduction"], 0.05)
        self.assertEqual(result["observed_reduction"], 0.05)

    def test_new_command_can_follow_a_reconciled_partial_fill(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            engine = MT5BridgeEngine(common_files=temp)
            previous_id = "MIR-" + "1" * 24
            root = Path(temp) / "MirsadBTC"
            root.mkdir()
            previous = {
                "schema": "MIR1", "command_id": previous_id, "action": "BUY",
                "symbol": "BTC", "market_symbol": "BTCUSDT", "volume": 0.2,
            }
            (root / "command.json").write_text(json.dumps(previous), encoding="utf-8")
            (root / "ack.json").write_text(json.dumps({
                "schema": "MIR1", "command_id": previous_id, "state": "PARTIAL",
                "filled_volume": 0.08,
            }), encoding="utf-8")
            decision = make_open_decision("MIR-" + "2" * 24)
            bridge_state = {
                "status": "CONNECTED", "terminal_connected": True,
                "execution_enabled": True, "execution_input_enabled": True,
                "trade_permissions_available": True, "magic_number": 26110201,
                "symbol_spec": {"tick_size": 0.01, "volume_step": 0.01},
                "positions": [],
                "position_reconciliation": {
                    "status": "CONFIRMED_PARTIAL", "command_id": previous_id,
                },
            }
            with patch.object(bridge_module, "ENABLE_ORDER_PUBLISH", True):
                result = engine.publish_decision(decision, bridge_state)
            self.assertEqual(result["status"], "PUBLISHED")
            current = json.loads((root / "command.json").read_text(encoding="utf-8"))
            self.assertEqual(current["command_id"], decision["signal_id"])

    def test_bridge_reads_live_magic_and_position_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "MirsadBTC"
            root.mkdir()
            payload = {
                "schema": "MIR1",
                "terminal_connected": True,
                "heartbeat_at_ms": int(time.time() * 1000),
                "magic_number": 26110201,
                "symbol": "BTC",
                "market_symbol": "BTCUSDT",
                "quote": {"bid": 99999.0, "ask": 100000.0, "time_ms": int(time.time() * 1000),
                          "tick_age_seconds": 1},
                "symbol_spec": {"tick_size": 0.01},
                "positions": [],
            }
            (root / "status.json").write_text(json.dumps(payload), encoding="utf-8")
            bridge = MT5BridgeEngine(common_files=temp).inspect()
            self.assertEqual(bridge["status"], "CONNECTED")
            self.assertEqual(bridge["magic_number"], 26110201)
            self.assertEqual(bridge["symbol"], "BTC")


if __name__ == "__main__":
    unittest.main()
