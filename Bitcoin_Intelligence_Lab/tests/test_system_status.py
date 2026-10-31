import unittest

from bitcoinlab.system_status import build_system_readiness


class SystemReadinessTests(unittest.TestCase):
    def fresh_service(self):
        return {
            "status": "healthy",
            "freshness_status": "fresh",
            "age_seconds": 2,
            "last_success_utc": "2026-10-31T00:00:00+00:00",
        }

    def test_market_and_decision_can_be_ready_while_execution_is_not_running(self):
        result = build_system_readiness(
            snapshot={
                "status": "ok",
                "source_states": {
                    "spot": {"status": "fresh"},
                    "technical": {"status": "fresh"},
                    "orderflow": {"status": "fresh"},
                    "derivatives": {"status": "fresh"},
                },
                "market_stream": {"status": "ok", "venues": []},
                "data_health": {
                    "stream_feeds": [
                        {"name": "binance_spot", "feed_type": "orderbook", "status": "live"},
                        {"name": "bybit_linear", "feed_type": "orderbook", "status": "live"},
                        {"name": "bybit_linear_trades", "feed_type": "trades", "status": "live"},
                        {"name": "okx_swap_liquidations", "feed_type": "liquidations", "status": "connected_quiet_ok"},
                        {"name": "binance_usdm_trades", "feed_type": "trades", "status": "stale"},
                    ],
                },
                "decision": {
                    "action": "BUY", "score": 0.42, "blockers": [],
                    "active_domains": ["technical", "orderflow"],
                },
            },
            terminal={"status": "unavailable"},
            snapshot_service=self.fresh_service(),
            execution_loop={"status": "unavailable"},
        )
        self.assertEqual(result["status"], "analysis_ready")
        self.assertEqual(result["central_decision"]["status"], "direction_ready")
        self.assertEqual(result["market_data"]["status"], "live")
        self.assertEqual(result["market_data"]["live_orderbook_venues"], 2)
        self.assertEqual(result["market_data"]["live_trade_venues"], ["bybit_linear_trades"])
        self.assertIn("okx_swap_liquidations", result["market_data"]["connected_quiet_liquidation_feeds"])
        self.assertEqual(result["market_data"]["non_live_stream_feeds"][0]["name"], "binance_usdm_trades")
        self.assertFalse(result["execution_pipeline_ready"])
        self.assertFalse(result["new_entry_ready"])
        self.assertIn("execution_loop_unavailable", result["blockers"])

    def test_execution_pipeline_can_be_ready_while_central_decision_holds(self):
        result = build_system_readiness(
            snapshot={
                "status": "partial",
                "source_states": {
                    "spot": {"status": "fresh"},
                    "technical": {"status": "fresh"},
                    "orderflow": {"status": "fresh"},
                    "derivatives": {"status": "stale"},
                },
                "market_stream": {"status": "ok", "venues": []},
                "decision": {
                    "action": "HOLD", "score": 0.08,
                    "blockers": ["insufficient_directional_confluence"],
                    "active_domains": ["technical", "orderflow"],
                },
            },
            terminal={
                "status": "fresh", "headway_server_ok": True,
                "trading_ready": True, "symbol": "BTCUSDm",
                "account_server": "HeadwayMarkets-Demo", "age_seconds": 2,
                "risk_specs_ready": True,
            },
            snapshot_service=self.fresh_service(),
            execution_loop={"status": "fresh", "age_seconds": 5, "cycle_status": "no_command"},
            positions=[],
        )
        self.assertEqual(result["status"], "execution_ready")
        self.assertTrue(result["execution_pipeline_ready"])
        self.assertFalse(result["new_entry_ready"])
        self.assertEqual(result["central_decision"]["status"], "hold")

    def test_pending_broker_ack_blocks_new_entry_without_marking_components_offline(self):
        result = build_system_readiness(
            snapshot={
                "status": "ok",
                "source_states": {
                    "spot": {"status": "fresh"},
                    "technical": {"status": "fresh"},
                    "orderflow": {"status": "fresh"},
                    "derivatives": {"status": "fresh"},
                },
                "market_stream": {"status": "ok", "venues": []},
                "decision": {"action": "SELL", "score": -0.4, "blockers": []},
            },
            terminal={
                "status": "fresh", "headway_server_ok": True,
                "trading_ready": True, "symbol": "BTCUSD",
                "risk_specs_ready": True,
            },
            snapshot_service=self.fresh_service(),
            execution_loop={"status": "fresh", "age_seconds": 1},
            pending_command={
                "pending": True, "status": "pending",
                "command_id": "BTC-123", "ack_status": "PARTIAL_FILL_PENDING",
            },
        )
        self.assertTrue(result["execution_pipeline_ready"])
        self.assertFalse(result["new_entry_ready"])
        self.assertTrue(result["position_management"]["pending_command"])
        self.assertIn("broker_command_pending_acknowledgement", result["blockers"])

    def test_stale_core_domain_is_visible_and_never_counted_as_ready(self):
        result = build_system_readiness(
            snapshot={
                "status": "partial",
                "source_states": {
                    "spot": {"status": "fresh"},
                    "technical": {"status": "fresh"},
                    "orderflow": {"status": "stale"},
                    "derivatives": {"status": "fresh"},
                },
                "decision": {
                    "action": "HOLD", "score": None,
                    "blockers": ["insufficient_fresh_core_evidence_domains"],
                },
            },
            terminal={"status": "not_ready"},
            snapshot_service=self.fresh_service(),
            execution_loop={"status": "stale"},
        )
        self.assertIn("orderflow", result["market_data"]["core_missing_domains"])
        self.assertIn("orderflow_evidence_not_fresh", result["blockers"])
        self.assertFalse(result["new_entry_ready"])

    def test_stale_snapshot_service_blocks_execution_readiness(self):
        result = build_system_readiness(
            snapshot={
                "status": "ok",
                "source_states": {
                    "spot": {"status": "fresh"},
                    "technical": {"status": "fresh"},
                    "orderflow": {"status": "fresh"},
                    "derivatives": {"status": "fresh"},
                },
                "decision": {"action": "BUY", "score": 0.4, "blockers": []},
            },
            terminal={
                "status": "fresh", "headway_server_ok": True,
                "trading_ready": True, "symbol": "BTCUSD",
                "risk_specs_ready": True,
            },
            execution_loop={"status": "fresh"},
            snapshot_service={"status": "healthy", "freshness_status": "stale"},
        )
        self.assertFalse(result["execution_pipeline_ready"])
        self.assertFalse(result["new_entry_ready"])
        self.assertIn("snapshot_service_stale", result["blockers"])

    def test_missing_broker_risk_specs_blocks_new_entries_but_keeps_close_pipeline_ready(self):
        result = build_system_readiness(
            snapshot={
                "status": "ok",
                "source_states": {
                    "spot": {"status": "fresh"},
                    "technical": {"status": "fresh"},
                    "orderflow": {"status": "fresh"},
                    "derivatives": {"status": "fresh"},
                },
                "decision": {"action": "BUY", "score": 0.45, "blockers": []},
            },
            terminal={
                "status": "fresh",
                "headway_server_ok": True,
                "trading_ready": True,
                "symbol": "BTCUSD",
                "risk_specs_ready": False,
            },
            execution_loop={"status": "fresh"},
            snapshot_service=self.fresh_service(),
            positions=[{"ticket": 12345, "symbol": "BTCUSD", "type": "BUY"}],
        )
        self.assertTrue(result["execution_pipeline_ready"])
        self.assertFalse(result["new_entry_ready"])
        self.assertEqual(result["headway_mt5"]["status"], "ready")
        self.assertFalse(result["headway_mt5"]["risk_sizing_ready"])
        self.assertIn("mt5_broker_risk_specs_unavailable", result["blockers"])
        self.assertEqual(result["position_management"]["managed_btc_positions"], 1)

    def test_missing_snapshot_is_system_degraded(self):
        result = build_system_readiness(
            snapshot=None, terminal=None, execution_loop=None,
        )
        self.assertEqual(result["status"], "system_degraded")
        self.assertIn("market_snapshot_unavailable", result["blockers"])
        self.assertFalse(result["execution_pipeline_ready"])


if __name__ == "__main__":
    unittest.main()
