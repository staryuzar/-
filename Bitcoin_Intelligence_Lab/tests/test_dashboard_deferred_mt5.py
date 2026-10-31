from pathlib import Path
import unittest


class DashboardMT5IntegrationContractTests(unittest.TestCase):
    def test_dashboard_reads_mt5_status_but_never_publishes_orders(self):
        app = (
            Path(__file__).resolve().parents[1] / "app.py"
        ).read_text(encoding="utf-8")
        allowed_read_only = (
            "default_common_files",
            "read_ea_status",
            "read_execution_loop_status",
            "read_positions",
            "current_ack",
        )
        for symbol in allowed_read_only:
            with self.subTest(symbol=symbol):
                self.assertIn(symbol, app)

        forbidden_execution = (
            "publish_decision_order",
            "publish_close_order",
            "execute_once(",
            "run_auto_management_cycle",
            "BTCIL_ENABLE_EXECUTION",
        )
        for symbol in forbidden_execution:
            with self.subTest(symbol=symbol):
                self.assertNotIn(symbol, app)

    def test_dashboard_explains_that_execution_is_separate_and_read_only(self):
        app = (
            Path(__file__).resolve().parents[1] / "app.py"
        ).read_text(encoding="utf-8")
        self.assertIn("اللوحة تقرأ حالة الطرفية والمراكز للعرض فقط", app)
        self.assertIn("عملية مستقلة", app)
        self.assertIn("لا تُرسل أوامر من إعادة تحميل Streamlit", app)


if __name__ == "__main__":
    unittest.main()
