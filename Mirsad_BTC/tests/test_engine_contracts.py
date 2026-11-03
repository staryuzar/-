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
    CHART_DECISION_WEIGHT,
    MARKET_CONFIRMATION_WEIGHT,
    DecisionEngine,
    _market_confirmation_score,
    _matching_positions,
    _price_to_tick,
    _weighted_direction_score,
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
    def test_chart_analysis_has_eighty_percent_of_directional_score(self) -> None:
        self.assertAlmostEqual(CHART_DECISION_WEIGHT, 0.80)
        self.assertAlmostEqual(MARKET_CONFIRMATION_WEIGHT, 0.20)
        self.assertAlmostEqual(_weighted_direction_score(0.8, -0.5), 0.54)

    def test_market_signal_cannot_override_a_neutral_or_weak_chart_analysis(self) -> None:
        score = _weighted_direction_score(0.1, 1.0)
        self.assertAlmostEqual(score, 0.28)
        self.assertLess(score, 0.40)

    def test_market_confirmation_score_uses_only_engine1_quote_update_pulse(self) -> None:
        market = {"market_context": {"microstructure": {
            "status": "READY", "quote_direction_balance": 0.65,
        }}}
        score, parts = _market_confirmation_score(0.0, market)
        self.assertAlmostEqual(score, 0.13, places=4)
        self.assertEqual(parts["quote_pulse_scope"], "bid/ask quote updates, not executed trades")

    def test_non_finite_directional_scores_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            _weighted_direction_score(float("nan"), 0.0)


class ChartDominantDecisionIntegrationTests(unittest.TestCase):
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

    def test_eighty_percent_chart_analyst_can_overrule_opposite_market_vote(self) -> None:
        result = DecisionEngine().analyze(
            self._market("down"),
            {"status": "READY", "decision_eligible": True, "visual_bias": "BULLISH",
             "analysis_score": 0.95, "analysis_confidence": 0.90, "image": "chart.png",
             "candle_history": make_engine2_candle_history("down")},
            {},
        )
        self.assertEqual(result["direction_inputs"], ["engine_1_market", "engine_2_chart", "engine_3_indicators"])
        self.assertEqual(result["calculation_inputs"], ["engine_3_indicators"])
        self.assertEqual(result["candidate_action"], "BUY")
        self.assertAlmostEqual(result["decision_weights"]["engine_2_chart"], 0.80)
        self.assertLess(result["decision_scores"]["market_score"], 0)

    def test_market_cannot_create_direction_when_chart_is_weak(self) -> None:
        result = DecisionEngine().analyze(
            self._market("up"),
            {"status": "READY", "decision_eligible": True, "visual_bias": "BULLISH",
             "analysis_score": 0.10, "analysis_confidence": 0.90, "image": "chart.png",
             "candle_history": make_engine2_candle_history("up")},
            {},
        )
        self.assertEqual(result["candidate_action"], "WAIT")
        self.assertLess(result["decision_scores"]["combined_score"], 0.40)

    def test_low_confidence_chart_never_creates_direction_even_with_extreme_market(self) -> None:
        result = DecisionEngine().analyze(
            self._market("up"),
            {"status": "READY", "decision_eligible": True, "visual_bias": "BULLISH",
             "analysis_score": 1.0, "analysis_confidence": 0.30, "image": "chart.png",
             "candle_history": make_engine2_candle_history("up")},
            {},
        )
        self.assertEqual(result["candidate_action"], "WAIT")
        self.assertEqual(result["chart_gate"], "INSUFFICIENT_ANALYSIS_CONFIDENCE")


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
        return {
            "status": "READY", "decision_eligible": True,
            "visual_bias": "BULLISH", "analysis_score": 0.95,
            "analysis_confidence": 0.90, "image": "contract-fixture.png",
            "candle_history": history,
        }

    def test_engine3_consumes_engine2_history_and_engine4_accepts_valid_contract(self) -> None:
        chart = self._chart()
        indicators = IndicatorsEngine().analyze(chart["candle_history"])
        self.assertEqual(indicators["engine"], "engine_3_indicators")
        self.assertEqual(indicators["source"], "engine_2_chart_candles")
        self.assertEqual(indicators["status"], "READY")

        result = DecisionEngine().analyze(self._market(), chart, {}, indicators)
        self.assertEqual(result["engine_3_indicator_status"], "READY")
        self.assertEqual(result["engine_inputs"]["indicators_from_engine_3"], "READY")
        self.assertEqual(result["candidate_action"], "BUY")
        self.assertFalse(result["command_ready"])

    def test_engine4_protective_stop_management_has_priority_over_visual_chart_gate(self) -> None:
        chart = self._chart()
        chart["status"] = "WAITING_FOR_IMAGE"
        chart["decision_eligible"] = False
        indicators = IndicatorsEngine().analyze(chart["candle_history"])
        now = int(time.time() * 1000)
        market = self._market()
        market["price"] = 200.05
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

    def test_engine4_rejects_missing_or_nonfinite_required_indicator_values(self) -> None:
        chart = self._chart()
        indicators = IndicatorsEngine().analyze(chart["candle_history"])
        indicators["values"]["atr14_5m"] = float("nan")

        result = DecisionEngine().analyze(self._market(), chart, {}, indicators)
        self.assertEqual(result["status"], "NOT_READY")
        self.assertEqual(result["action"], "WAIT")
        self.assertEqual(result["engine_3_indicator_status"], "INVALID_INDICATOR_PAYLOAD")


    def test_engine2_native_price_action_is_visible_but_never_becomes_an_unvalidated_vote(self) -> None:
        chart = self._chart()
        chart["decision_eligible"] = True
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
                "eligible_timeframes": ["1m", "5m", "15m", "1h"],
                "timeframe_alignment": "MIXED_TIMEFRAME_DIRECTIONS",
            },
            "decision_eligible": False,
        }
        without_context = DecisionEngine().analyze(self._market(), chart, {}, indicators)
        with_context = DecisionEngine().analyze(
            self._market(), chart, {}, indicators, engine2_price_action=price_action
        )

        self.assertEqual(with_context["action"], "WAIT")
        self.assertEqual(with_context["status"], "READY")
        self.assertEqual(
            with_context["engine_2_native_price_action_context"]["direction"],
            "MIXED_TIMEFRAME_DIRECTIONS",
        )
        self.assertEqual(
            with_context["engine_2_native_price_action_context"]["role"],
            "NON_DIRECTIONAL_SAFETY_GATE_ONLY",
        )
        self.assertEqual(without_context["candidate_action"], "BUY")
        self.assertEqual(with_context["candidate_action"], "WAIT")
        self.assertEqual(with_context["chart_gate"], "WAITING_FOR_ENGINE_2_PRICE_ACTION_CONFLUENCE")
        self.assertEqual(
            with_context["engine_2_native_price_action_context"]["gate"],
            "MIXED_OR_NO_CONFLUENCE",
        )
        self.assertEqual(with_context["decision_scores"], without_context["decision_scores"])

        aligned_price_action = {
            **price_action,
            "direction": "BULLISH",
            "summary": {
                **price_action["summary"],
                "timeframe_alignment": "BULLISH_STRUCTURE_CONFLUENCE",
            },
        }
        aligned = DecisionEngine().analyze(
            self._market(), chart, {}, indicators, engine2_price_action=aligned_price_action
        )
        self.assertEqual(aligned["candidate_action"], "BUY")
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
            self._market(), chart, {}, indicators, engine2_price_action=aligned_patterns
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
        chart = {"status": "READY", "decision_eligible": True,
                 "visual_bias": "NEUTRAL", "image": "unit.png",
                 "candle_history": make_engine2_candle_history("up", 80)}
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

    def test_command_is_not_replaced_while_previous_command_is_unsettled(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            engine = MT5BridgeEngine(common_files=temp)
            with patch.object(bridge_module, "ENABLE_ORDER_PUBLISH", True):
                first = engine.publish_decision(make_open_decision(), {"status": "CONNECTED"})
                self.assertEqual(first["status"], "PUBLISHED")

                second = make_open_decision("MIR-" + "c" * 24)
                blocked = engine.publish_decision(second, {"status": "CONNECTED"})
                self.assertEqual(blocked["status"], "PENDING_COMMAND_BLOCKED")

                command_path = Path(temp) / "MirsadBTC" / "command.json"
                command = json.loads(command_path.read_text(encoding="utf-8"))
                ack_path = Path(temp) / "MirsadBTC" / "ack.json"
                ack_path.write_text(json.dumps({
                    "schema": "MIR1",
                    "command_id": command["command_id"],
                    "state": "FILLED",
                }), encoding="utf-8")

                published = engine.publish_decision(second, {"status": "CONNECTED"})
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
