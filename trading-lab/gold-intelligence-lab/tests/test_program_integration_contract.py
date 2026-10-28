"""End-to-end program wiring contracts without market fixtures or trade simulation."""
import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROGRAM = ROOT
PYTHON = PROGRAM / "python" / "goldlab"


class ProgramIntegrationContracts(unittest.TestCase):
    def test_all_major_modules_are_present(self):
        required = (
            "technical_rating.py", "live_mt5.py", "pattern_scanner.py",
            "advisor.py", "economic_calendar.py", "cot_data.py", "audit_ledger.py",
        )
        for filename in required:
            with self.subTest(filename=filename):
                self.assertTrue((PYTHON / filename).is_file(), filename)

    def test_dashboard_wires_data_sources_analysis_and_audit(self):
        app = (PROGRAM / "app.py").read_text(encoding="utf-8")
        for marker in (
            "analyze_live_mt5", "fetch_bls_calendar", "fetch_cftc_gold_cot",
            "LocalAuditLedger", "streamlit", "قراءة السوق وتحليل المؤشرات",
            "تحديث تقويم إصدارات BLS", "تحديث مراكز الذهب COT", "حفظ لقطة التحليل محليًا",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, app)

    def test_runtime_manifest_contains_ui_mt5_and_windows_timezone_data(self):
        ui = (PROGRAM / "python" / "requirements-ui.txt").read_text(encoding="utf-8")
        analysis = (PROGRAM / "python" / "requirements-analysis.txt").read_text(encoding="utf-8")
        for marker in ("requirements-analysis.txt", "MetaTrader5", "streamlit"):
            with self.subTest(marker=marker):
                self.assertIn(marker, ui)
        self.assertIn("tzdata", analysis)

    def test_analysis_and_data_modules_have_no_order_execution_api(self):
        forbidden = {"order_send", "order_check", "orders_send", "position_close", "ordersend"}
        for path in sorted(PYTHON.glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            attributes = {node.attr.casefold() for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
            with self.subTest(module=path.name):
                self.assertTrue(forbidden.isdisjoint(attributes), (path.name, forbidden.intersection(attributes)))
                source = path.read_text(encoding="utf-8")
                self.assertNotIn("TRADE_ACTION_DEAL", source)
                self.assertNotIn("TRADE_ACTION_PENDING", source)

    def test_local_database_path_and_virtualenv_are_ignored(self):
        ignore = (PROGRAM.parents[1] / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("trading-lab/gold-intelligence-lab/data/", ignore)
        self.assertIn(".venv/", ignore)

    def test_legacy_order_probe_and_simulator_are_quarantined(self):
        repo_root = PROGRAM.parents[1]
        self.assertFalse((repo_root / ".github" / "scripts" / "gold_lab_live_demo_probe.py").exists())
        self.assertTrue((repo_root / ".github" / "retired-disabled" / "gold_lab_live_demo_probe.py.DISABLED.txt").exists())
        self.assertFalse((repo_root / ".github" / "scripts" / "gold_lab_strategy_test.ps1").exists())
        self.assertTrue((repo_root / ".github" / "retired-disabled" / "gold_lab_strategy_test.ps1.DISABLED.txt").exists())


if __name__ == "__main__":
    unittest.main()
