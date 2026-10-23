import csv
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from compare_tv26_csv import COMPONENTS, compare_files, parse_time


class TV26ParityComparatorTests(unittest.TestCase):
    def test_mt5_server_offset_and_tv_epoch_align(self):
        # 03:00 at UTC+3 is 00:00 UTC.
        mt5_time = parse_time("2026.01.01 03:00", 3)
        tv_time = parse_time(str(int(datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)))
        self.assertEqual(mt5_time, tv_time)

    def make_fixtures(self, folder: Path, mismatch: bool = False, formula_mismatch: bool = False):
        mt5_path = folder / "mt5.csv"
        tv_path = folder / "tv.csv"
        mt_headers = [
            "bar_open_time_server", "symbol", "broker_company", "broker_server",
            "timeframe", "component", "readiness", "vote", "value_a", "value_b",
            "value_c", "value_d", "value_e", "candle_open", "candle_high",
            "candle_low", "candle_close", "tick_volume",
        ]
        tv_headers = [
            "time", "TV26.total", "TV26.ma", "TV26.osc", "TV26.formula_total",
            "TV26.formula_ma", "TV26.formula_osc", "TV26.bar_open_time",
            "TV26.open", "TV26.high", "TV26.low", "TV26.close", "TV26.volume",
        ] + ["TV26." + key for key in COMPONENTS]
        rows_mt, rows_tv = [], []
        for minute in range(2):
            time_mt = f"2026.01.01 03:0{minute}"
            epoch_ms = int(datetime(2026, 1, 1, 0, minute, tzinfo=timezone.utc).timestamp() * 1000)
            open_price = 2000.0 + minute
            prices = {
                "candle_open": open_price,
                "candle_high": open_price + 1,
                "candle_low": open_price - 1,
                "candle_close": open_price + 0.25,
            }
            rows_mt.append({
                "bar_open_time_server": time_mt, "symbol": "XAUUSD",
                "broker_company": "TestBroker", "broker_server": "Demo",
                "timeframe": "د1", "component": "SUMMARY", "readiness": "OK",
                "vote": "", "value_a": "1", "value_b": "1", "value_c": "1",
                "value_d": "26", "value_e": "15/15;11/11",
                **{k: str(v) for k, v in prices.items()}, "tick_volume": "100",
            })
            for tv_key, arabic_name in COMPONENTS.items():
                vote = -1 if mismatch and minute == 1 and tv_key == "RSI14" else 1
                rows_mt.append({
                    "bar_open_time_server": time_mt, "symbol": "XAUUSD",
                    "broker_company": "TestBroker", "broker_server": "Demo",
                    "timeframe": "د1", "component": arabic_name, "readiness": "OK",
                    "vote": str(vote), "value_a": "0", "value_b": "0",
                    "value_c": "0", "value_d": "0", "value_e": "0",
                    "candle_open": "", "candle_high": "", "candle_low": "",
                    "candle_close": "", "tick_volume": "",
                })
            tv_row = {
                "time": time_mt, "TV26.total": "1", "TV26.ma": "1",
                "TV26.osc": "1",
                "TV26.formula_total": "0.5" if formula_mismatch and minute == 1 else "1",
                "TV26.formula_ma": "1", "TV26.formula_osc": "1",
                "TV26.bar_open_time": str(epoch_ms),
                "TV26.open": str(open_price), "TV26.high": str(open_price + 1),
                "TV26.low": str(open_price - 1), "TV26.close": str(open_price + 0.25),
                "TV26.volume": "100",
            }
            tv_row.update({"TV26." + key: str(
                1
            ) for key in COMPONENTS})
            rows_tv.append(tv_row)
        for path, headers, rows in ((mt5_path, mt_headers, rows_mt), (tv_path, tv_headers, rows_tv)):
            with path.open("w", encoding="utf-8", newline="") as file:
                writer = csv.DictWriter(file, fieldnames=headers)
                writer.writeheader()
                writer.writerows(rows)
        return mt5_path, tv_path

    def test_clean_fixture_passes_all_gates(self):
        with tempfile.TemporaryDirectory() as temp:
            mt5, tv = self.make_fixtures(Path(temp))
            result, details, report = compare_files(mt5, tv, "M1", 3, min_bars=2)
            self.assertEqual(result["status"], "PASS", report)
            self.assertEqual(result["matched_bars"], 2)
            self.assertEqual(result["component_votes_checked"], 52)
            self.assertEqual(result["component_vote_mismatches"], 0)
            self.assertEqual(result["price_mismatches"], 0)
            self.assertEqual(result["summary_mismatches"], 0)
            self.assertEqual(result["formula_calibration_values_checked"], 6)
            self.assertEqual(result["formula_calibration_mismatches"], 0)
            self.assertEqual(len(details), 2 * (4 + 3 + 3 + 26))

    def test_single_component_mismatch_fails_and_is_located(self):
        with tempfile.TemporaryDirectory() as temp:
            mt5, tv = self.make_fixtures(Path(temp), mismatch=True)
            result, details, report = compare_files(mt5, tv, "M1", 3, min_bars=2)
            self.assertEqual(result["status"], "FAIL")
            self.assertEqual(result["component_vote_mismatches"], 1)
            failed = [d for d in details if d["result"] == "FAIL"]
            self.assertEqual(len(failed), 1)
            self.assertEqual(failed[0]["component"], COMPONENTS["RSI14"])
            self.assertIn("all_26_component_votes_match", result["pass_requirements"])

    def test_formula_aggregate_mismatch_against_official_library_fails(self):
        with tempfile.TemporaryDirectory() as temp:
            mt5, tv = self.make_fixtures(Path(temp), formula_mismatch=True)
            result, details, report = compare_files(mt5, tv, "M1", 3, min_bars=2)
            self.assertEqual(result["status"], "FAIL", report)
            self.assertEqual(result["formula_calibration_mismatches"], 1)
            failed = [d for d in details if d["result"] == "FAIL"]
            self.assertEqual(len(failed), 1)
            self.assertEqual(failed[0]["check"], "official_library_calibration")
            self.assertIn("pine_component_aggregates_match_official_library", result["pass_requirements"])

    def test_wrong_time_offset_never_claims_parity(self):
        with tempfile.TemporaryDirectory() as temp:
            mt5, tv = self.make_fixtures(Path(temp))
            result, _, _ = compare_files(mt5, tv, "M1", 0, min_bars=1)
            self.assertEqual(result["status"], "FAIL")
            self.assertEqual(result["matched_bars"], 0)

    def test_rejects_unsupported_timeframe(self):
        with tempfile.TemporaryDirectory() as temp:
            mt5, tv = self.make_fixtures(Path(temp))
            with self.assertRaises(ValueError):
                compare_files(mt5, tv, "M2", 3, min_bars=1)


if __name__ == "__main__":
    unittest.main()
