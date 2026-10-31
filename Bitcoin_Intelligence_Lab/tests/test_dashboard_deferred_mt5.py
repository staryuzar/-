from pathlib import Path
import unittest


class DashboardMT5DeferralTests(unittest.TestCase):
    def test_dashboard_has_no_mt5_bridge_or_order_automation_calls(self):
        app = (
            Path(__file__).resolve().parents[1] / "app.py"
        ).read_text(encoding="utf-8")
        forbidden = (
            "run_auto_management_cycle",
            "publish_decision_order",
            "publish_close_order",
            "default_common_files",
            "read_ea_status",
            "read_positions",
            "current_ack",
        )
        for symbol in forbidden:
            with self.subTest(symbol=symbol):
                self.assertNotIn(symbol, app)

    def test_dashboard_explains_that_mt5_is_deferred(self):
        app = (
            Path(__file__).resolve().parents[1] / "app.py"
        ).read_text(encoding="utf-8")
        self.assertIn("ربط الخبير بمنصة MT5 مؤجل عمداً", app)
        self.assertIn("لا يوجد اتصال أو إرسال أوامر", app)


if __name__ == "__main__":
    unittest.main()
