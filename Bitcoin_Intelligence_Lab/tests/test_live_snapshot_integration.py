from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class LiveSnapshotIntegrationContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snapshot = (ROOT / "bitcoinlab" / "live_snapshot.py").read_text(encoding="utf-8")
        cls.dashboard = (ROOT / "app.py").read_text(encoding="utf-8")

    def test_cross_venue_derivatives_context_is_reapplied_after_bybit_fallback(self):
        fallback = self.snapshot.index('if deriv_engine.get("status") != "ok":')
        attach = self.snapshot.index("deriv_engine = attach_cross_venue_context")
        timeframe_build = self.snapshot.index("timeframe_inputs =")
        self.assertLess(fallback, attach)
        self.assertLess(attach, timeframe_build)

    def test_recent_trade_flow_is_not_gated_by_rest_depth_availability(self):
        self.assertIn("if trades:", self.snapshot)
        self.assertIn("flow_engine = orderflow_profile(book_metrics, flow_metrics)", self.snapshot)
        self.assertNotIn("if depth and trades:", self.snapshot)
        self.assertIn('"minimum_fresh_frames": MINIMUM_FRESH_TIMEFRAMES', self.snapshot)

    def test_dashboard_live_snapshot_uses_configurable_collector_database_path(self):
        self.assertIn('os.environ.get("BTCIL_MARKET_DB", "data/market_stream.sqlite")', self.snapshot)
        for reader in (
            "read_market_stream_dashboard",
            "read_liquidation_heatmap",
            "read_trade_analytics",
            "read_depth_liquidity_context",
        ):
            start = self.snapshot.index(f"{reader}(")
            end = self.snapshot.index(")", start)
            self.assertIn("market_db_path", self.snapshot[start:end])

    def test_okx_perpetual_derivatives_fallback_runs_after_binance_and_bybit(self):
        bybit_fallback = self.snapshot.index('if deriv_engine.get("status") != "ok":')
        okx_fallback = self.snapshot.index("fetch_okx_derivatives_snapshot(")
        attach_context = self.snapshot.index("deriv_engine = attach_cross_venue_context")
        self.assertLess(bybit_fallback, okx_fallback)
        self.assertLess(okx_fallback, attach_context)
        self.assertIn('errors["derivatives_okx"]', self.snapshot)
        self.assertIn('"venue": "OKX"', self.snapshot)

    def test_dashboard_exposes_five_domain_vote_and_normalized_weights(self):
        self.assertIn("خريطة تصويت المجالات الخمسة", self.dashboard)
        self.assertIn("الوزن الفعلي بعد التطبيع", self.dashboard)
        for domain in ('"technical"', '"orderflow"', '"derivatives"', '"market_structure"', '"cross_venue"'):
            self.assertIn(domain, self.dashboard)


if __name__ == "__main__":
    unittest.main()
