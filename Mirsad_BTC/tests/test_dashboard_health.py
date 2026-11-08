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
            "decision_eligible": True,
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
                "command_ready": False,
                "engine_2_native_price_action_context": {
                    "status": "READY", "direction": "BULLISH",
                    "decision_eligible": True, "gate": "BULLISH_CONFLUENCE",
                    "directional_frame_coverage": 0.80,
                },
                "risk_plan": {
                    "status": "READY", "volume": 0.1, "risk_cash": 5,
                    "estimated_stop_loss": 3.5, "estimated_commission": 1.5,
                    "estimated_loss": 5.0,
                },
            },
            "decision_calibration_persistence": {
                "status": "STORED", "profile_version": "v6.1", "sample_count": 7,
            },
            "decision_calibration_archive": {
                "status": "READY", "profile_version": "v6.1",
                "total_samples": 7, "current_profile_sample_count": 7,
                "current_profile_final_action_counts": {"BUY": 1, "SELL": 1, "WAIT": 5},
                "current_profile_candidate_action_counts": {"BUY": 1, "SELL": 1, "WAIT": 5},
                "current_profile_directional_sample_count": 2,
                "directional_samples_available": True,
                "validation_status": "UNVALIDATED",
                "note": "Directional samples exist; cost-adjusted chronological review remains pending.",
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

    def test_risk_panel_detail_includes_commission_in_total_loss(self) -> None:
        items = build_component_health(self.healthy_state())
        risk = next(item for item in items if item.get("component") == "حساب الدخول والوقف والهدف والحجم")
        self.assertIn("3.5", risk["detail"])
        self.assertIn("1.5", risk["detail"])
        self.assertIn("5.0", risk["detail"])

    def test_filled_modify_closed_later_by_mt5_deal_history_is_settled_healthily(self) -> None:
        state = self.healthy_state()
        state["bridge"]["position_reconciliation"] = {
            "status": "POSITION_CLOSED_AFTER_MODIFY",
            "command_id": "MIR-" + "e" * 24,
            "close_kind": "TAKE_PROFIT",
            "closed_volume": 0.03,
            "reason": "Complete MT5 deal history confirms full closure after the protective update.",
        }
        items = build_component_health(state)
        item = next(row for row in items if row["component"] == "\u0645\u0637\u0627\u0628\u0642\u0629 \u0625\u0642\u0631\u0627\u0631 ACK \u0645\u0639 \u0627\u0644\u0645\u0631\u0627\u0643\u0632 \u0627\u0644\u0641\u0639\u0644\u064a\u0629")
        self.assertEqual(item["health"], "HEALTHY")
        self.assertIn("TAKE_PROFIT", item["detail"])

    def test_healthy_native_telemetry_does_not_promote_safety_switches(self) -> None:
        items = build_component_health(self.healthy_state())
        by_name = {item["component"]: item for item in items}
        self.assertGreaterEqual(len(items), 20)
        self.assertEqual(by_name["نبض ودورة البرنامج الرئيسية"]["health"], "HEALTHY")
        self.assertEqual(by_name["سجل الشموع الأصلية متعددة الأطر"]["health"], "HEALTHY")
        self.assertEqual(by_name["تحليل القمم والقيعان وبنية السعر"]["health"], "HEALTHY")
        self.assertEqual(by_name["التوافق البنيوي وجودة الأدلة متعددة الأطر"]["health"], "HEALTHY")
        self.assertEqual(by_name["أهلية التصويت الاتجاهي والدخول"]["status"], "READY")
        self.assertEqual(by_name["أهلية التصويت الاتجاهي والدخول"]["health"], "HEALTHY")
        self.assertEqual(by_name["متابعة المراكز المفتوحة وحمايتها"]["status"], "NO_OPEN_POSITIONS")
        self.assertEqual(by_name["متابعة المراكز المفتوحة وحمايتها"]["health"], "HEALTHY")
        self.assertEqual(by_name["دفتر صفقات الوسيط المحفوظ"]["health"], "HEALTHY")
        self.assertEqual(by_name["دفتر صفقات الوسيط المحفوظ"]["status"], "READY")
        self.assertEqual(by_name["حفظ أدلة معايرة القرار"]["health"], "HEALTHY")
        self.assertEqual(by_name["حفظ أدلة معايرة القرار"]["status"], "STORED")
        self.assertEqual(by_name["تغطية عينات القرار الاتجاهية"]["status"], "DIRECTIONAL_SAMPLES_AVAILABLE")
        self.assertEqual(by_name["تغطية عينات القرار الاتجاهية"]["health"], "HEALTHY")
        self.assertIn("UNVALIDATED", by_name["تغطية عينات القرار الاتجاهية"]["detail"])
        self.assertEqual(by_name["حاجز حد الخسارة اليومية"]["health"], "SAFE_DISABLED")
        self.assertEqual(by_name["بوابة نشر أوامر MIR1"]["health"], "SAFE_DISABLED")
        self.assertFalse(any(any(token in item["component"] for token in ("صورة", "بصري", "OCR")) for item in items))
        self.assertIn("حفظ أدلة معايرة القرار", by_name)
        self.assertEqual(summarize_component_health(items)["attention"], 0)
        self.assertEqual(summarize_component_health(items)["safe_disabled"], 2)

    def test_directional_analysis_ready_but_not_eligible_is_waiting_not_attention(self) -> None:
        state = self.healthy_state()
        state["engine_2_price_action"]["decision_eligible"] = False
        state["decision"]["engine_2_native_price_action_context"] = {
            "status": "READY", "direction": "MIXED_TIMEFRAME_DIRECTIONS",
            "decision_eligible": False, "gate": "MIXED_OR_NO_CONFLUENCE",
            "directional_frame_coverage": 0.40,
        }
        item = next(x for x in build_component_health(state) if x["component"] == "أهلية التصويت الاتجاهي والدخول")
        self.assertEqual(item["status"], "WAITING_FOR_CONFLUENCE")
        self.assertEqual(item["health"], "WAITING")
        self.assertIn("MIXED_TIMEFRAME_DIRECTIONS", item["detail"])
        self.assertIn("MIXED_OR_NO_CONFLUENCE", item["detail"])

    def test_mixed_multi_timeframe_confluence_is_waiting_not_healthy(self) -> None:
        state = self.healthy_state()
        state["engine_2_price_action"]["summary"]["timeframe_alignment"] = "MIXED_TIMEFRAME_DIRECTIONS"
        state["engine_2_multi_timeframe_structure"]["alignment"] = "MIXED_TIMEFRAME_DIRECTIONS"
        state["decision"]["engine_2_native_price_action_context"] = {
            "status": "READY", "direction": "MIXED_TIMEFRAME_DIRECTIONS",
            "decision_eligible": False, "gate": "MIXED_OR_NO_CONFLUENCE",
            "directional_frame_coverage": 0.6667,
        }
        items = build_component_health(state)
        by_name = {item["component"]: item for item in items}
        confluence = by_name["التوافق البنيوي وجودة الأدلة متعددة الأطر"]
        eligibility = by_name["أهلية التصويت الاتجاهي والدخول"]
        self.assertEqual(confluence["status"], "WAITING_FOR_CONFLUENCE")
        self.assertEqual(confluence["health"], "WAITING")
        self.assertEqual(confluence["status_label"], "التحليل مكتمل؛ بانتظار توافق اتجاهي كافٍ")
        self.assertEqual(eligibility["health"], "WAITING")
        self.assertIn("MIXED_TIMEFRAME_DIRECTIONS", eligibility["detail"])

    def test_engine4_wait_state_explains_engine2_gates_in_arabic(self) -> None:
        state = self.healthy_state()
        state["decision"]["status"] = "WAITING_FOR_ENGINE_2"
        state["decision"]["engine_2_native_price_action_context"] = {
            "decision_eligible": False,
            "gate": "MIXED_OR_NO_CONFLUENCE",
            "timeframe_alignment": "MIXED_TIMEFRAME_DIRECTIONS",
            "latest_candle_pattern_alignment": "MIXED_CANDLE_PATTERN_EVIDENCE",
        }
        item = next(x for x in build_component_health(state) if x["component"] == "محرك القرار المركزي")
        self.assertEqual(item["health"], "WAITING")
        self.assertEqual(item["status_label"], "المحرك الرابع ينتظر توافق بنية السعر من المحرك الثاني")
        self.assertIn("لا يوجد توافق بنيوي كافٍ", item["detail"])
        self.assertIn("اتجاهات الأطر الزمنية متعارضة", item["detail"])
        self.assertIn("أدلة نماذج الشموع متعارضة", item["detail"])
        self.assertIn("لا يُرسل دخول جديد", item["detail"])

    def test_wait_only_calibration_archive_is_visible_as_waiting_not_validated(self) -> None:
        state = self.healthy_state()
        state["decision_calibration_archive"].update({
            "current_profile_final_action_counts": {"WAIT": 315},
            "current_profile_candidate_action_counts": {"WAIT": 315},
            "current_profile_sample_count": 315,
            "current_profile_directional_sample_count": 0,
            "directional_samples_available": False,
            "validation_status": "UNVALIDATED",
            "note": "WAIT observations verify storage continuity only.",
        })
        item = next(x for x in build_component_health(state) if x["component"] == "تغطية عينات القرار الاتجاهية")
        self.assertEqual(item["status"], "WAITING_FOR_DIRECTIONAL_SAMPLES")
        self.assertEqual(item["health"], "WAITING")
        self.assertIn("WAIT=315", item["detail"])
        self.assertIn("UNVALIDATED", item["detail"])

    def test_directional_calibration_samples_are_distinct_from_profit_validation(self) -> None:
        state = self.healthy_state()
        item = next(x for x in build_component_health(state) if x["component"] == "تغطية عينات القرار الاتجاهية")
        self.assertEqual(item["status"], "DIRECTIONAL_SAMPLES_AVAILABLE")
        self.assertEqual(item["health"], "HEALTHY")
        self.assertIn("الأداء لا يزال غير معتمد", item["status_label"])
        self.assertIn("UNVALIDATED", item["detail"])

    def test_active_high_impact_calendar_is_waiting_not_safe_disabled(self) -> None:
        state = self.healthy_state()
        state["market_intelligence"]["economic_calendar"]["high_impact_window_active"] = True
        state["market_intelligence"]["economic_calendar"]["active_high_impact_events"] = [
            {"name": "Michigan Consumer Sentiment Index", "minutes_to_event": 12}
        ]
        item = next(x for x in build_component_health(state) if x["component"] == "التقويم الاقتصادي العام المستقل")
        self.assertEqual(item["status"], "HIGH_IMPACT_EVENT_WINDOW")
        self.assertEqual(item["health"], "WAITING")
        summary = summarize_component_health(build_component_health(state))
        self.assertEqual(summary["safe_disabled"], 2)

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

    def test_runtime_cycle_error_is_not_hidden_by_a_fresh_error_heartbeat(self) -> None:
        state = self.healthy_state()
        state["overall_status"] = "ERROR"
        state["runtime_error"] = "sqlite3.OperationalError: database is locked"
        item = next(x for x in build_component_health(state) if x["component"] == "نبض ودورة البرنامج الرئيسية")
        self.assertEqual(item["status"], "ERROR")
        self.assertEqual(item["health"], "ATTENTION")
        self.assertIn("database is locked", item["detail"])

    def test_calibration_storage_failure_is_a_visible_health_item(self) -> None:
        state = self.healthy_state()
        state["decision_calibration_persistence"] = {
            "status": "ERROR",
            "profile_version": "v6.1",
            "reason": "disk is full",
        }
        item = next(x for x in build_component_health(state) if x["component"] == "حفظ أدلة معايرة القرار")
        self.assertEqual(item["status"], "ERROR")
        self.assertEqual(item["health"], "ATTENTION")
        self.assertIn("disk is full", item["detail"])

    def test_missing_telemetry_is_never_reported_as_healthy(self) -> None:
        self.assertEqual(build_component_health({}), [])
        state = {"heartbeat_at_ms": 0, "execution_controls": {"order_publish_enabled": False}}
        items = build_component_health(state)
        self.assertTrue(items)
        self.assertTrue(all(item["health"] in {"WAITING", "SAFE_DISABLED"} for item in items))
        self.assertFalse(any(item["health"] == "HEALTHY" for item in items))

    def test_every_dashboard_health_component_exposes_its_real_source(self) -> None:
        items = build_component_health(self.healthy_state())
        self.assertTrue(all(str(item.get("source", "")).strip() for item in items))
        by_name = {item["component"]: item for item in items}
        self.assertIn("observer/candles.json", by_name["سجل الشموع الأصلية متعددة الأطر"]["source"])
        self.assertIn("CopyBuffer", by_name["تغذية مؤشرات MT5 الأصلية وCopyBuffer"]["source"])
        self.assertIn("20%)", by_name["محرك القرار المركزي"]["source"])

    def test_not_required_risk_plan_is_healthy_when_no_entry_is_qualified(self) -> None:
        state = self.healthy_state()
        state["decision"]["risk_plan"] = {
            "status": "NOT_REQUIRED",
            "reason": "No qualified BUY/SELL signal exists.",
        }
        item = next(
            row for row in build_component_health(state)
            if row["component"] == "حساب الدخول والوقف والهدف والحجم"
        )
        self.assertEqual(item["status_label"], "غير مطلوب في هذه الدورة")
        self.assertEqual(item["health"], "HEALTHY")

    def test_deal_history_reconciled_unknown_close_is_healthy_but_ack_remains_distinct(self) -> None:
        state = self.healthy_state()
        state["bridge"]["position_reconciliation"] = {
            "status": "CONFIRMED_FROM_DEAL_HISTORY",
            "ack_state": "UNKNOWN",
            "confirmation_source": "FRESH_VALIDATED_MT5_DEAL_HISTORY_AND_LATER_POSITIONS",
            "reason": "Exact broker deal and later positions snapshot matched the close command.",
        }
        item = next(
            row for row in build_component_health(state)
            if row["component"] == "مطابقة إقرار ACK مع المراكز الفعلية"
        )
        self.assertEqual(item["status"], "CONFIRMED_FROM_DEAL_HISTORY")
        self.assertEqual(item["status_label"], "تم تأكيد التنفيذ من سجل صفقات MT5")
        self.assertEqual(item["health"], "HEALTHY")
        self.assertIn("Exact broker deal", item["detail"])

    def test_native_copybuffer_health_reports_counts_alignment_and_numeric_parity(self) -> None:
        state = self.healthy_state()
        timeframes = ("1m", "5m", "15m", "1h", "4h", "1d")
        state["mt5_native_indicators"]["ready_timeframe_count"] = 6
        state["mt5_native_indicators"]["bar_alignment_status"] = "MATCH"
        state["mt5_native_indicators"]["timeframes"] = {
            tf: {
                "status": "READY",
                "ready_indicator_count": 20,
                "values": {f"metric_{i}": {"status": "READY"} for i in range(20)},
                "missing_required_indicators": [],
            }
            for tf in timeframes
        }
        state["indicators"]["mt5_native_parity"] = {
            "status": "PASS",
            "timeframes": {
                tf: {
                    "metrics": {
                        f"metric_{i}": {"status": "PASS"} for i in range(20)
                    }
                }
                for tf in timeframes
            },
        }
        item = next(
            row for row in build_component_health(state)
            if row["component"] == "تغذية مؤشرات MT5 الأصلية وCopyBuffer"
        )
        self.assertIn("120/120", item["detail"])
        self.assertIn("6/6", item["detail"])
        self.assertIn("MATCH", item["detail"])
        self.assertIn("120/120 (PASS)", item["detail"])


if __name__ == "__main__":
    unittest.main()

