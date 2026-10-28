"""Local audit ledger contracts. No prices or market simulations are created."""
import json, sqlite3, tempfile, unittest
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
from goldlab.audit_ledger import LocalAuditLedger, build_audit_payload

def metadata_only_report():
    return {
        "market_source": {"symbol":"XAUUSD","timeframe":"M1","bars_received":0},
        "market": {"quote_time_utc":None,"spread_points":None,"password":"test-sentinel"},
        "analysis": {"engine_version":"0.1.0","bar_time":None,"adx_profile":"official_help",
            "readiness":{"total_ready":0,"total_components":26,"complete":False},
            "ratings":{"overall":None,"overall_category_ar":"غير متاح"},
            "current_market_review":{"eligible":False,"status":"BLOCKED_DATA_QUALITY"},
            "components":[{"key":"RSI14","raw_values":{"value":None,"api_token":"test-sentinel"}}]},
        "scanner":{"trend":{"state":"unavailable"},"setups":[]},
        "advisor":{"status":"BLOCKED_DATA_QUALITY","title_ar":"بيانات غير كافية","api_key":"test-sentinel"},
        "api_key":"test-sentinel",
    }

class LocalAuditLedgerTests(unittest.TestCase):
    def test_append_read_hash_and_reopen(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/"nested"/"audit.sqlite3"
            saved=LocalAuditLedger(path).append_analysis(metadata_only_report())
            rows=LocalAuditLedger(path).list_recent(10)
            self.assertEqual(len(rows),1)
            self.assertEqual(rows[0]["event_id"],saved["event_id"])
            self.assertTrue(rows[0]["payload_integrity_ok"])
            self.assertEqual(rows[0]["symbol"],"XAUUSD")
            conn = sqlite3.connect(path)
            try:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0], 1)
            finally:
                conn.close()

    def test_sensitive_fields_are_redacted_recursively(self):
        text=json.dumps(build_audit_payload(metadata_only_report()),ensure_ascii=False).lower()
        for forbidden in ("test-sentinel","api_key","api_token","password"):
            self.assertNotIn(forbidden,text)

    def test_update_and_delete_are_blocked(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/"audit.sqlite3"
            ledger=LocalAuditLedger(path)
            ledger.append_analysis(metadata_only_report())
            conn=sqlite3.connect(path)
            try:
                with self.assertRaises(sqlite3.IntegrityError):
                    conn.execute("UPDATE audit_events SET symbol='OTHER'")
                conn.rollback()
                with self.assertRaises(sqlite3.IntegrityError):
                    conn.execute("DELETE FROM audit_events")
                conn.rollback()
            finally: conn.close()
            self.assertEqual(len(ledger.list_recent(10)),1)

    def test_limit_is_bounded(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):
                LocalAuditLedger(Path(folder)/"audit.sqlite3").list_recent(0)

if __name__ == "__main__": unittest.main()
