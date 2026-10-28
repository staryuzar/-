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
            "advisor.py", "economic_calendar.py", "cot_data.py", "audit_ledger.py", "multi_timeframe.py", "market_time.py",
        )
        for filename in required:
            with self.subTest(filename=filename):
                self.assertTrue((PYTHON / filename).is_file(), filename)

    def test_dashboard_wires_data_sources_analysis_and_audit(self):
        app = (PROGRAM / "app.py").read_text(encoding="utf-8")
        for marker in (
            "analyze_live_mt5", "fetch_bls_calendar", "fetch_cftc_gold_cot",
            "LocalAuditLedger", "summarize_timeframe_consensus", "streamlit", "قراءة السوق وتحليل الأطر الزمنية", "تحليل الأطر الزمنية الخمسة معًا",
            "تحديث تقويم إصدارات BLS", "تحديث مراكز الذهب COT", "حفظ لقطة التحليل محليًا", "منطقة توقيت خادم MT5", "server_timezone=server_timezone",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, app)

    def test_dashboard_uses_one_shared_snapshot_for_selected_timeframes(self):
        app = (PROGRAM / "app.py").read_text(encoding="utf-8")
        live = (PROGRAM / "python" / "goldlab" / "live_mt5.py").read_text(encoding="utf-8")
        self.assertIn("analyze_live_mt5_multi", app)
        self.assertIn("goldlab_snapshot_id", app)
        self.assertIn("snapshot_time_consistent", live)
        self.assertIn("snapshot_captured_at_utc", live)

    def test_live_adapter_has_explicit_broker_timezone_conversion(self):
        live = (PROGRAM / "python" / "goldlab" / "live_mt5.py").read_text(encoding="utf-8")
        time_module = (PROGRAM / "python" / "goldlab" / "market_time.py").read_text(encoding="utf-8")
        self.assertIn("server_timestamp_to_utc", live)
        self.assertIn("server_timestamp_sequence_to_utc", live)
        self.assertIn("DEFAULT_SERVER_TIMEZONE", live)
        self.assertIn("Europe/Athens", time_module)
        self.assertIn("server_utc_offset_seconds", live)

    def test_dashboard_uses_current_streamlit_width_argument(self):
        app = (PROGRAM / "app.py").read_text(encoding="utf-8")
        self.assertNotIn("use_container_width=", app)
        self.assertIn('width="stretch"', app)

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
        ignore_path = PROGRAM / ".gitignore"
        if not ignore_path.exists():
            self.skipTest("This check requires the project-local .gitignore.")
        ignore = ignore_path.read_text(encoding="utf-8")
        self.assertIn("data/", ignore)
        self.assertIn(".venv/", ignore)
        self.assertIn("*.sqlite3", ignore)

    def test_legacy_order_probe_and_simulator_are_quarantined(self):
        repo_root = next(
            (parent for parent in PROGRAM.parents if (parent / ".github" / "retired-disabled" / "README_AR.md").is_file()),
            None,
        )
        if repo_root is None:
            self.skipTest("Standalone program package does not include repository governance files.")
        self.assertFalse((repo_root / ".github" / "scripts" / "gold_lab_live_demo_probe.py").exists())
        self.assertTrue((repo_root / ".github" / "retired-disabled" / "gold_lab_live_demo_probe.py.DISABLED.txt").exists())
        self.assertFalse((repo_root / ".github" / "scripts" / "gold_lab_strategy_test.ps1").exists())
        self.assertTrue((repo_root / ".github" / "retired-disabled" / "gold_lab_strategy_test.ps1.DISABLED.txt").exists())


if __name__ == "__main__":
    unittest.main()
