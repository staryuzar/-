from __future__ import annotations

import time
import unittest

from mirsad.health import build_component_health, summarize_component_health


class ComponentHealthTests(unittest.TestCase):
    def healthy_state(self) -> dict:
        now = int(time.time() * 1000)
        price_action = {
            "status": "READY",
            "direction": "BULLISH",
            "structure_score": 0.82,
            "summary": {
                "eligible_timeframes": ["1m", "5m", "15m", "1h", "4h"],
                "timeframe_alignment": "BULLISH_STRUCTURE_CONFLUENCE",
                "directional_structure_agreement": 1.0,
                "timeframe_weight_coverage": 0.95,
                "directional_evidence_weights": {
                    "confirmed_swing_structure": 0.70,
                    "latest_confirmed_bos_choch": 0.15,
                    "latest_candle_pattern": 0.10,
                    "latest_liquidity_sweep": 0.05,
                },
            },
            "multi_timeframe_structure": {
                "status": "READY",
                "alignment": "BULLISH_STRUCTURE_CONFLUENCE",
            },
        }
        return {
            "heartbeat_at_ms": now,
            "market_age_seconds": 1.2,
            "market": {
                "status": "LIVE", "price": 90000, "primary_venue": "MT5 Broker",
                "venues": {"MT5 Broker": {
                    "microstructure": {"status": "READY", "tick_rate_per_minute": 120, "current_spread_pct": 0.02},
                    "economic_calendar_status": "AVAILABLE",
                }},
            },
            "engine_2_candles": {
                "status": "READY",
                "timeframes": {"1m": 100, "5m": 100, "15m": 100, "1h": 100, "4h": 100, "1d": 100},
                "closed_candles": {"1m": 99, "5m": 99, "15m": 99, "1h": 99, "4h": 99, "1d": 99},
            },
            "engine_2_price_action": price_action,
            "engine_2_multi_timeframe_structure": price_action["multi_timeframe_structure"],
            "market_intelligence": {
                "status": "READY", "direction": "NEUTRAL", "directional_score": 0.0,
                "evidence_coverage": 0.8,
                "news": {"status": "READY", "count": 4, "sources": {"source_a": "READY"}},
                "fear_greed": {"status": "READY", "value": 50, "classification": "Neutral"},
                "derivatives": {"status": "READY", "venue_count": 3, "score": 0.0},
                "economic_calendar": {"status": "READY", "sources": {"public": "READY"}, "active_high_impact_events": []},
            },
            "indicators": {
                "status": "READY", "source": "engine_2_chart_candles",
                "values": {"ema20_1m": 90000, "rsi14_1m": 58, "atr14_5m": 120},
            },
            "mt5_native_indicators": {"status": "READY", "ready_indicator_count": 6, "missing_required_indicators": []},
            "decision": {
                "status": "READY", "action": "WAIT", "candidate_action": "WAIT",
                "command_ready": False, "risk_plan": {"status": "READY", "volume": 0.1, "risk_cash": 5},
            },
            "daily_risk": {"status": "READY", "enabled": False, "mode": "DISABLED_FOR_DEVELOPMENT"},
            "bridge": {
                "status": "CONNECTED", "heartbeat_age_seconds": 1.0,
                "symbol": "BTC", "market_symbol": "BTCUSDT", "positions": [],
                "position_reconciliation": {"status": "NO_PENDING_COMMAND", "reason": "No pending command."},
                "deal_history": {"status": "READY", "deal_count": 3, "truncated": False},
                "deal_ledger_persistence": {"status": "READY", "received": 3, "stored": 3, "currency": "USD"},
            },
            "command_publish": {"status": "NOT_READY"},
            "execution_controls": {"order_publish_enabled": False},
        }

    def test_healthy_native_telemetry_does_not_promote_safety_switches(self) -> None:
        items = build_component_health(self.healthy_state())
        by_name = {item["component"]: item for item in items}
        self.assertGreaterEqual(len(items), 20)
        self.assertEqual(by_name["نبض ودورة البرنامج الرئيسية"]["health"], "HEALTHY")
        self.assertEqual(by_name["سجل الشموع الأصلية متعددة الأطر"]["health"], "HEALTHY")
        self.assertEqual(by_name["تحليل القمم والقيعان وبنية السعر"]["health"], "HEALTHY")
        self.assertEqual(by_name["التوافق البنيوي وجودة الأدلة متعددة الأطر"]["health"], "HEALTHY")
        self.assertEqual(by_name["متابعة المراكز المفتوحة وحمايتها"]["status"], "NO_OPEN_POSITIONS")
        self.assertEqual(by_name["متابعة المراكز المفتوحة وحمايتها"]["health"], "HEALTHY")
        self.assertEqual(by_name["دفتر صفقات الوسيط المحفوظ"]["health"], "HEALTHY")
        self.assertEqual(by_name["دفتر صفقات الوسيط المحفوظ"]["status"], "READY")
        self.assertEqual(by_name["حاجز حد الخسارة اليومية"]["health"], "SAFE_DISABLED")
        self.assertEqual(by_name["بوابة نشر أوامر MIR1"]["health"], "SAFE_DISABLED")
        self.assertFalse(any(any(token in item["component"] for token in ("صورة", "بصري", "معايرة", "OCR")) for item in items))
        self.assertEqual(summarize_component_health(items)["attention"], 0)
        self.assertEqual(summarize_component_health(items)["safe_disabled"], 2)

    def test_stale_market_is_attention_without_any_chart_image_state(self) -> None:
        state = self.healthy_state()
        state["market"]["status"] = "STALE"
        by_name = {item["component"]: item for item in build_component_health(state)}
        self.assertEqual(by_name["تغذية السوق وسعر MT5"]["health"], "ATTENTION")
        self.assertEqual(by_name["تحليل القمم والقيعان وبنية السعر"]["health"], "HEALTHY")

    def test_price_action_quality_failure_is_reported_not_hidden(self) -> None:
        state = self.healthy_state()
        state["engine_2_price_action"]["status"] = "PARTIAL"
        state["engine_2_price_action"]["direction"] = "INSUFFICIENT_CONTEXT"
        state["engine_2_price_action"]["reason"] = "Required higher timeframes are incomplete."
        item = next(x for x in build_component_health(state) if x["component"] == "تحليل القمم والقيعان وبنية السعر")
        self.assertEqual(item["status"], "PARTIAL")
        self.assertEqual(item["health"], "WAITING")
        self.assertIn("INSUFFICIENT_CONTEXT", item["detail"])

    def test_missing_native_ohlc_data_is_never_reported_as_healthy(self) -> None:
        state = self.healthy_state()
        state["engine_2_candles"]["status"] = "NOT_READY"
        state["engine_2_price_action"]["status"] = "NOT_READY"
        by_name = {item["component"]: item for item in build_component_health(state)}
        self.assertEqual(by_name["سجل الشموع الأصلية متعددة الأطر"]["health"], "WAITING")
        self.assertEqual(by_name["تحليل القمم والقيعان وبنية السعر"]["health"], "WAITING")

    def test_invalid_broker_deal_ledger_is_an_attention_item(self) -> None:
        state = self.healthy_state()
        state["bridge"]["deal_history"] = {"status": "INVALID", "reason": "Deal magic number does not match."}
        item = next(x for x in build_component_health(state) if x["component"] == "دفتر صفقات الوسيط المحفوظ")
        self.assertEqual(item["status"], "INVALID")
        self.assertEqual(item["health"], "ATTENTION")

    def test_missing_telemetry_is_never_reported_as_healthy(self) -> None:
        self.assertEqual(build_component_health({}), [])
        state = {"heartbeat_at_ms": 0, "execution_controls": {"order_publish_enabled": False}}
        items = build_component_health(state)
        self.assertTrue(items)
        self.assertTrue(all(item["health"] in {"WAITING", "SAFE_DISABLED"} for item in items))
        self.assertFalse(any(item["health"] == "HEALTHY" for item in items))


if __name__ == "__main__":
    unittest.main()
