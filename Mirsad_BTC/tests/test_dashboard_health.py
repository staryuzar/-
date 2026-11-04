from __future__ import annotations

import time
import unittest

from mirsad.health import build_component_health, summarize_component_health


class ComponentHealthTests(unittest.TestCase):
    def healthy_state(self) -> dict:
        now = int(time.time() * 1000)
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
            "chart_observer": {
                "status": "READY_FOR_ENGINE_2_VALIDATION", "capture_id": "capture-1",
                "image_sha256": "abc123", "age_seconds": 1.0, "bar_count": 80,
                "chart": {"symbol": "BTC", "timeframe": "1m"},
            },
            "chart": {
                "status": "READY", "decision_eligible": True, "detected_bar_count": 80,
                "calibration": {"source": "reference_multi_candle_ohlc"},
                "observer_capture": {"capture_id": "capture-1", "image_sha256": "abc123"},
                "reference_multi_calibration": {"status": "READY"},
                "reference_axis_validation": {"status": "READY"},
                "native_ohlc_analysis": {"status": "READY"},
                "reference_patterns": {"status": "READY", "pattern_definition_count": 65, "event_count": 4},
            },
            "engine_2_candles": {"status": "READY", "timeframes": {"1m": 100, "5m": 100, "15m": 100}},
            "engine_2_price_action": {"status": "READY", "direction": "BULLISH", "summary": {"eligible_timeframes": ["1m", "5m"]}},
            "engine_2_multi_timeframe_structure": {"status": "READY", "eligible_timeframes": ["1m", "5m"], "alignment": "BULLISH"},
            "indicators": {"status": "READY", "source": "engine_2_chart_candles", "values": {"ema20_1m": 90000, "rsi14_1m": 58, "atr14_5m": 120}},
            "mt5_native_indicators": {"status": "READY", "ready_indicator_count": 6, "missing_required_indicators": []},
            "decision": {"status": "READY", "action": "WAIT", "candidate_action": "WAIT", "command_ready": False, "risk_plan": {"status": "READY", "volume": 0.1, "risk_cash": 5}},
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

    def test_healthy_telemetry_does_not_promote_safety_switches(self) -> None:
        items = build_component_health(self.healthy_state())
        by_name = {item["component"]: item for item in items}
        self.assertGreaterEqual(len(items), 20)
        self.assertEqual(by_name["نبض ودورة البرنامج الرئيسية"]["health"], "HEALTHY")
        self.assertEqual(by_name["تطابق هوية الصورة مع بيانات التحليل"]["status"], "VERIFIED")
        self.assertEqual(by_name["متابعة المراكز المفتوحة وحمايتها"]["status"], "NO_OPEN_POSITIONS")
        self.assertEqual(by_name["متابعة المراكز المفتوحة وحمايتها"]["health"], "HEALTHY")
        self.assertEqual(by_name["دفتر صفقات الوسيط المحفوظ"]["health"], "HEALTHY")
        self.assertEqual(by_name["دفتر صفقات الوسيط المحفوظ"]["status"], "READY")
        self.assertEqual(by_name["حاجز حد الخسارة اليومية"]["health"], "SAFE_DISABLED")
        self.assertEqual(by_name["بوابة نشر أوامر MIR1"]["health"], "SAFE_DISABLED")
        self.assertEqual(summarize_component_health(items)["attention"], 0)
        self.assertEqual(summarize_component_health(items)["safe_disabled"], 2)

    def test_stale_market_and_capture_hash_mismatch_are_attention(self) -> None:
        state = self.healthy_state()
        state["market"]["status"] = "STALE"
        state["chart"]["observer_capture"]["image_sha256"] = "different"
        by_name = {item["component"]: item for item in build_component_health(state)}
        self.assertEqual(by_name["تغذية السوق وسعر MT5"]["health"], "ATTENTION")
        self.assertEqual(by_name["تطابق هوية الصورة مع بيانات التحليل"]["status"], "HASH_MISMATCH")

    def test_observer_capture_gate_failures_are_attention_not_waiting(self) -> None:
        state = self.healthy_state()
        state["chart"]["status"] = "OBSERVER_INBOX_VALIDATION_BLOCKED"
        state["chart"]["decision_eligible"] = False
        item = next(x for x in build_component_health(state) if x["component"] == "تحليل الصورة وأهلية المعايرة")
        self.assertEqual(item["health"], "ATTENTION")

    def test_missing_optional_image_capture_does_not_degrade_native_engine2_health(self) -> None:
        state = self.healthy_state()
        state["chart_observer"] = {"status": "OPTIONAL_DISABLED"}
        state["chart"] = {
            "status": "NATIVE_OHLC_ONLY",
            "decision_eligible": False,
            "visual_analysis": "OPTIONAL_DISABLED",
        }

        items = build_component_health(state)
        by_name = {item["component"]: item for item in items}

        optional_components = (
            "استقبال صور الشارت الاختياري من خبير MT5",
            "تطابق هوية الصورة مع بيانات التحليل",
            "تحليل الصورة وأهلية المعايرة",
            "معايرة محور السعر والهندسة",
            "مطابقة OHLC مع شموع MT5 الأصلية",
            "مرجع الأنماط الحسابي TA-Lib",
        )
        for component in optional_components:
            self.assertEqual(by_name[component]["status"], "OPTIONAL_DISABLED")
            self.assertEqual(by_name[component]["health"], "SAFE_DISABLED")

        self.assertEqual(by_name["سجل الشموع الأصلية متعددة الأطر"]["health"], "HEALTHY")
        self.assertEqual(by_name["تحليل القمم والقيعان وبنية السعر"]["health"], "HEALTHY")
        self.assertEqual(by_name["تحليل الصورة وأهلية المعايرة"]["health"], "SAFE_DISABLED")
        self.assertEqual(summarize_component_health(items)["attention"], 0)

    def test_invalid_broker_deal_ledger_is_an_attention_item(self) -> None:
        state = self.healthy_state()
        state["bridge"]["deal_history"] = {
            "status": "INVALID",
            "reason": "Deal magic number does not match.",
        }
        item = next(
            x for x in build_component_health(state)
            if x["component"] == "دفتر صفقات الوسيط المحفوظ"
        )
        self.assertEqual(item["status"], "INVALID")
        self.assertEqual(item["health"], "ATTENTION")

    def test_missing_telemetry_is_never_reported_as_healthy(self) -> None:
        self.assertEqual(build_component_health({}), [])
        state = {"heartbeat_at_ms": 0, "execution_controls": {"order_publish_enabled": False}}
        items = build_component_health(state)
        self.assertTrue(items)
        self.assertTrue(all(item["health"] in {"WAITING", "SAFE_DISABLED"} for item in items))
        self.assertFalse(any(item["health"] == "HEALTHY" for item in items))

    def test_capture_id_mismatch_is_not_hidden_by_visual_ready_status(self) -> None:
        state = self.healthy_state()
        state["chart"]["observer_capture"]["capture_id"] = "capture-other"
        item = next(x for x in build_component_health(state) if x["component"] == "تطابق هوية الصورة مع بيانات التحليل")
        self.assertEqual(item["status"], "IDENTITY_MISMATCH")
        self.assertEqual(item["health"], "ATTENTION")


if __name__ == "__main__":
    unittest.main()
