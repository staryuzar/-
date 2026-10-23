import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from validate_tv26_mt5_audit import (
    ALL_COMPONENTS, MA_COMPONENTS, OSC_COMPONENTS, TIMEFRAMES, validate_rows
)


class TV26AuditIntegrityTests(unittest.TestCase):
    def make_rows(self):
        rows = []
        for index, tf in enumerate(TIMEFRAMES):
            stamp = f"2026.01.01 00:{index:02d}"
            # Non-uniform votes ensure arithmetic checks are not only a zero-score special case.
            votes = {name: ((i % 3) - 1) for i, name in enumerate(ALL_COMPONENTS)}
            ma = sum(votes[name] for name in MA_COMPONENTS) / 15.0
            osc = sum(votes[name] for name in OSC_COMPONENTS) / 11.0
            total = (ma + osc) / 2.0
            common = {
                "bar_open_time_server": stamp, "symbol": "XAUUSD",
                "broker_company": "Test Broker", "broker_server": "Demo",
                "timeframe": tf, "readiness": "OK",
                "candle_open": "2000.0", "candle_high": "2001.0",
                "candle_low": "1999.0", "candle_close": "2000.5",
                "tick_volume": "100",
            }
            rows.append({
                **common, "component": "SUMMARY", "vote": "",
                "value_a": str(total), "value_b": str(ma), "value_c": str(osc),
            })
            for name in ALL_COMPONENTS:
                rows.append({
                    **common, "component": name, "vote": str(votes[name]),
                    "value_a": "0", "value_b": "0", "value_c": "0",
                })
        return rows

    def minima(self):
        return {tf: 1 for tf in TIMEFRAMES}

    def test_valid_complete_audit_passes(self):
        result = validate_rows(self.make_rows(), self.minima(), "fixture.csv", "testhash")
        self.assertEqual(result["status"], "PASS", result["problems"])
        self.assertEqual(result["unique_candle_groups"], len(TIMEFRAMES))
        self.assertEqual(result["component_vote_rows_checked"], len(TIMEFRAMES) * 26)
        self.assertEqual(result["summary_aggregate_mismatches"], 0)
        self.assertEqual(result["ohlc_invalid_rows"], 0)

    def test_missing_component_fails(self):
        rows = self.make_rows()
        rows = [row for row in rows if not (
            row["timeframe"] == "د1" and row["component"] == ALL_COMPONENTS[0]
        )]
        result = validate_rows(rows, self.minima())
        self.assertEqual(result["status"], "FAIL")
        self.assertGreater(result["candle_bundle_errors"], 0)

    def test_bad_summary_arithmetic_fails(self):
        rows = self.make_rows()
        rows[0]["value_a"] = str(float(rows[0]["value_a"]) + 0.25)
        result = validate_rows(rows, self.minima())
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["summary_aggregate_mismatches"], 1)

    def test_invalid_vote_fails(self):
        rows = self.make_rows()
        first_component = next(row for row in rows if row["component"] == ALL_COMPONENTS[0])
        first_component["vote"] = "2"
        result = validate_rows(rows, self.minima())
        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(any(p["code"] == "INVALID_VOTE" for p in result["problems"]))


if __name__ == "__main__":
    unittest.main()
