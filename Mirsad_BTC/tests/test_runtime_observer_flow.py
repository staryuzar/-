from __future__ import annotations

import time
import unittest
from unittest.mock import Mock, patch

import mirsad.runtime as runtime


def make_engine2_multiframe_history(as_of_ms: int) -> dict:
    durations = {
        "1m": 60_000, "5m": 300_000, "15m": 900_000,
        "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000,
    }
    frames = {}
    for timeframe, duration in durations.items():
        candles = []
        for index in range(90):
            wave = (0, 20, 40, 20, 0, -20, -40, -20)[index % 8]
            close = 90_000.0 + index * 5.0 + wave
            candles.append({
                "open_time_ms": as_of_ms - (89 - index) * duration,
                "open": close - 2.0, "high": close + 5.0,
                "low": close - 5.0, "close": close,
                "volume": 10.0, "closed": index < 89,
            })
        frames[timeframe] = candles
    return {
        "engine": "engine_2_chart_candles",
        "source": "MT5_CHART_OBSERVER",
        "status": "READY",
        "captured_at_ms": as_of_ms,
        "candles_by_tf": frames,
        "timeframes": {key: len(rows) for key, rows in frames.items()},
    }

class RuntimeObserverFlowTests(unittest.TestCase):
    def test_explicitly_disabled_daily_loss_cap_is_ready_for_configured_runtime(self) -> None:
        disabled = {
            "status": "READY", "mode": "DISABLED_FOR_DEVELOPMENT",
            "enabled": False, "locked": False, "new_entries_blocked": False,
        }
        self.assertTrue(runtime._daily_risk_guard_ready(disabled))
        inconsistent = {**disabled, "locked": True}
        self.assertFalse(runtime._daily_risk_guard_ready(inconsistent))
        blocked = {**disabled, "new_entries_blocked": True}
        self.assertFalse(runtime._daily_risk_guard_ready(blocked))

    def test_daily_loss_guard_requires_a_valid_enabled_persistent_baseline(self) -> None:
        ready = {
            "status": "READY", "mode": "ENABLED", "enabled": True,
            "starting_equity": 1000.0, "baseline_at_ms": 1_800_000_000_000,
            "max_daily_loss_fraction": 0.02, "locked": False,
        }
        locked = {**ready, "locked": True}
        no_baseline = {**ready, "baseline_at_ms": 0}
        self.assertTrue(runtime._daily_risk_guard_ready(ready))
        self.assertTrue(runtime._daily_risk_guard_ready(locked))
        self.assertFalse(runtime._daily_risk_guard_ready(no_baseline))
    def test_engine2_multi_timeframe_structure_uses_only_native_engine2_history(self) -> None:
        now_ms = int(time.time() * 1000)
        history = make_engine2_multiframe_history(now_ms)
        result = runtime._analyze_engine2_multi_timeframe_structure(history)
        self.assertEqual(result["status"], "READY")
        self.assertEqual(result["source"], "MT5_CHART_OBSERVER")
        self.assertEqual(result["ownership"], "engine_2_native_candles_only")
        self.assertEqual(result["as_of_ms"], now_ms)
        self.assertEqual(set(result["available_timeframes"]), set(history["candles_by_tf"]))
        self.assertGreaterEqual(len(result["eligible_timeframes"]), 2)
        for frame in result["timeframe_reports"].values():
            self.assertLessEqual(frame["last_close_time_ms"], now_ms)

    def test_engine2_multi_timeframe_structure_refuses_unvalidated_history(self) -> None:
        result = runtime._analyze_engine2_multi_timeframe_structure({"status": "STALE"})
        self.assertEqual(result["status"], "NOT_READY")
        self.assertEqual(result["source"], "MT5_CHART_OBSERVER")
        self.assertEqual(result["available_timeframes"], [])
    def test_collect_once_uses_native_ohlc_and_never_calls_image_pipeline(self) -> None:
        bars = []
        for index in range(30):
            base = 90_000.0 + index
            bars.append({
                "time_server_ms": 1_700_000_000_000 + index * 60_000,
                "open": base, "high": base + 20, "low": base - 20,
                "close": base + 5, "is_closed": index < 29,
            })


        now_ms = int(time.time() * 1000)
        market = {
            "symbol": "BTCUSDT",
            "price": 90_100.0,
            "captured_at_ms": now_ms,
            "status": "LIVE",
            "source": "MT5_TERMINAL",
            "venue_count": 1,
            "primary_venue": "MT5 Broker",
            "feed_health": {"terminal_connected": True, "quote_fresh": True},
            "market_context": {"microstructure": {"status": "NOT_AVAILABLE"}},
            "venues": {
                "MT5 Broker": {"status": "LIVE", "price": 90_100.0},
            },
        }
        deal_history_payload = {
            "schema": "MIR1-DEALS-1",
            "status": "READY",
            "queried_at_utc_ms": now_ms,
            "window_start_server_ms": now_ms - 90 * 86400 * 1000,
            "window_end_server_ms": now_ms,
            "server_utc_offset_seconds_at_query": 0,
            "history_total_selected": 1,
            "history_start_index": 0,
            "returned_count": 1,
            "truncated": False,
            "symbol": "BTC",
            "magic": 26110201,
            "currency": "USD",
            "time_basis": "MT5_SERVER_TIME",
            "deals": [{
                "deal_ticket": "10001", "order_ticket": "20001",
                "position_id": "30001", "magic": 26110201,
                "symbol": "BTC", "type": 0, "entry": 0, "reason": 3,
                "time_server_ms": now_ms - 1000, "volume": 0.01,
                "price": 65000.0, "profit": 0.0, "commission": -0.25,
                "swap": 0.0, "fee": 0.0, "net_cashflow": -0.25,
                "currency": "USD", "comment": "MIR-test",
            }],
        }
        deal_persistence_result = {
            "status": "READY", "received": 1, "stored": 1,
            "queried_at_utc_ms": now_ms, "magic": 26110201, "symbol": "BTC",
            "currency": "USD", "truncated": False,
        }
        bridge_snapshot = {
            "engine": "engine_5_communication_bridge",
            "status": "CONNECTED",
            "terminal_connected": True,
            "execution_enabled": True,
            "execution_input_enabled": True,
            "trade_permissions_available": True,
            "symbol": "BTC",
            "market_symbol": "BTCUSDT",
            "magic_number": 26110201,
            "account": {"server": "Headway-Demo", "currency": "USD"},
            "deal_history": deal_history_payload,
        }

        market_engine = Mock()
        market_engine.collect.return_value = market
        bridge_engine = Mock()
        bridge_engine.inspect.return_value = bridge_snapshot
        bridge_engine.publish_decision = Mock()
        candle_history = {
            "engine": "engine_2_chart_candles",
            "source": "MT5_CHART_OBSERVER",
            "status": "READY",
            "candles_by_tf": {"1m": bars},
            "timeframes": {"1m": len(bars)},
            "closed_candles": {"1m": len(bars) - 1},
        }
        candle_history_engine = Mock()
        candle_history_engine.collect.return_value = candle_history
        indicators_engine = Mock()
        indicators_engine.analyze.return_value = {"status": "READY"}
        decision_engine = Mock()
        decision_engine.analyze.return_value = {
            "status": "READY",
            "action": "WAIT",
            "command_ready": False,
        }

        intelligence_engine = Mock()
        intelligence_engine.collect.return_value = {
            "engine": "engine_1_market_intelligence", "status": "READY",
            "direction": "NEUTRAL", "directional_score": 0.0,
            "confidence": 0.8, "evidence_coverage": 0.8,
            "economic_calendar": {"status": "EMPTY", "high_impact_window_active": False, "events": []},
        }

        with (
            patch.object(runtime, "MT5MarketDataEngine", return_value=market_engine),
            patch.object(runtime, "MarketIntelligenceEngine", return_value=intelligence_engine),
            patch.object(runtime, "MT5ChartCandleHistory", return_value=candle_history_engine),
            patch.object(runtime, "MT5BridgeEngine", return_value=bridge_engine),
            patch.object(runtime, "IndicatorsEngine", return_value=indicators_engine),
            patch.object(runtime, "DecisionEngine", return_value=decision_engine),
            patch.object(runtime, "save_market_snapshot"),
            patch.object(runtime, "save_market_intelligence_snapshot"),
            patch.object(runtime, "save_mt5_deal_history", return_value=deal_persistence_result) as persist_deals,
            patch.object(runtime, "write_json_atomic"),
        ):
            report = runtime.collect_once()

        self.assertEqual(report["chart"]["source"], "NATIVE_MT5_OHLC")
        self.assertEqual(report["chart"]["status"], "NATIVE_OHLC_ONLY")
        self.assertFalse(report["chart"]["decision_eligible"])
        self.assertEqual(report["chart_observer"]["status"], "OPTIONAL_DISABLED")
        decision_engine.analyze.assert_called_once()
        passed_chart = decision_engine.analyze.call_args.args[1]
        self.assertEqual(passed_chart["source"], "NATIVE_MT5_OHLC")
        self.assertFalse(passed_chart["decision_eligible"])
        self.assertEqual(report["market_intelligence"]["status"], "READY")
        self.assertTrue(report["readiness"]["engine_1_market_intelligence"])
        intelligence_engine.collect.assert_called_once_with()
        self.assertIs(
            decision_engine.analyze.call_args.kwargs["market_intelligence"],
            report["market_intelligence"],
        )
        self.assertEqual(report["decision"]["action"], "WAIT")
        self.assertEqual(report["command_publish"]["status"], "NOT_READY")
        self.assertTrue(report["execution_controls"]["terminal_connected"])
        self.assertIs(report["execution_controls"]["expert_execution_enabled"], True)
        self.assertTrue(report["execution_controls"]["order_publish_enabled"])
    self.assertTrue(report["execution_controls"]["order_execution_ready"])
        self.assertTrue(report["readiness"]["engine_5_command_execution_gate"])
        self.assertEqual(report["overall_status"], "PARTIAL_OR_WAITING")
        self.assertEqual(report["execution_controls"]["expert_execution_telemetry"], "REPORTED_ENABLED")
        market_engine.collect.assert_called_once_with(bridge=bridge_snapshot)
        candle_history_engine.collect.assert_called_once_with(
            bridge=bridge_snapshot
        )
        indicators_engine.analyze.assert_called_once_with(candle_history)
        self.assertEqual(report["engine_2_candles"]["status"], "READY")
        self.assertNotIn("engine_2_visual_chart", report["readiness"])
        self.assertTrue(report["readiness"]["engine_2_candles"])
        self.assertEqual(report["engine_2_multi_timeframe_structure"]["source"], "NATIVE_MT5_OHLC")
        self.assertEqual(report["chart"]["engine_2_multi_timeframe_structure"]["source"], "NATIVE_MT5_OHLC")
        persist_deals.assert_called_once_with(deal_history_payload)
        self.assertEqual(report["mt5_deal_ledger"], deal_persistence_result)
        self.assertEqual(report["bridge"]["deal_history"]["deal_count"], 1)
        self.assertNotIn("deals", report["bridge"]["deal_history"])
        self.assertEqual(report["bridge"]["deal_ledger_persistence"]["status"], "READY")
        bridge_engine.publish_decision.assert_not_called()


if __name__ == "__main__":
    unittest.main()
