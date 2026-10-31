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

    def test_dashboard_exposes_five_domain_vote_and_normalized_weights(self):
        self.assertIn("خريطة تصويت المجالات الخمسة", self.dashboard)
        self.assertIn("الوزن الفعلي بعد التطبيع", self.dashboard)
        for domain in ('"technical"', '"orderflow"', '"derivatives"', '"market_structure"', '"cross_venue"'):
            self.assertIn(domain, self.dashboard)


if __name__ == "__main__":
    unittest.main()
