import csv
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from compare_tv26_csv import COMPONENTS, compare_files, read_csv
from split_tv26_alltf_export import split_file


TIMEFRAMES = {
    "M1": ("د1", 1),
    "M5": ("د5", 5),
    "M15": ("د15", 15),
    "M30": ("د30", 30),
    "H1": ("س1", 60),
}
PINE_FIELDS = (
    "packed", "total", "ma", "osc", "formula_total", "formula_ma",
    "formula_osc", "bar_open_time", "open", "high", "low", "close",
)
AUDIT_FIELDS = [
    "bar_open_time_server", "symbol", "broker_company", "broker_server",
    "timeframe", "component", "readiness", "vote", "value_a", "value_b",
    "value_c", "value_d", "value_e", "candle_open", "candle_high",
    "candle_low", "candle_close", "tick_volume",
]


def vote_vector(tf_index, bar_index):
    # Deterministic ternary votes; no warm-up/NA values in this integration fixture.
    return [((i + tf_index + bar_index) % 3) - 1 for i in range(len(COMPONENTS))]


def pack(votes):
    return sum((vote + 1) * (4 ** i) for i, vote in enumerate(votes))


def write_csv(path, fields, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


class TV26ParityPipelineEndToEndTests(unittest.TestCase):
    def make_fixtures(self, folder):
        start = datetime(2026, 9, 1, 0, 0, tzinfo=timezone.utc)
        alltf_fields = ["time"]
        for tf in TIMEFRAMES:
            alltf_fields.extend(f"TV26.{tf}.{field}" for field in PINE_FIELDS)
        alltf_rows, audit_rows = [], []

        # Two matched bars per timeframe, with MT5 server timestamps at UTC+3.
        for bar_index, minute_offset in enumerate((0, 60)):
            chart_time = start + timedelta(minutes=minute_offset)
            chart_row = {"time": str(int(chart_time.timestamp() * 1000))}
            for tf_index, (tf, (mt5_tf_label, _period)) in enumerate(TIMEFRAMES.items()):
                stamp = start + timedelta(minutes=minute_offset)
                epoch_ms = int(stamp.timestamp() * 1000)
                votes = vote_vector(tf_index, bar_index)
                packed = pack(votes)
                open_price = 2500.0 + 10 * tf_index + bar_index
                high_price, low_price, close_price = open_price + 1, open_price - 1, open_price + 0.25
                total, ma, osc = 0.1 + 0.01 * bar_index, 0.2, 0.0
                tv_values = {
                    "packed": str(packed), "total": str(total), "ma": str(ma), "osc": str(osc),
                    "formula_total": str(total), "formula_ma": str(ma), "formula_osc": str(osc),
                    "bar_open_time": str(epoch_ms), "open": str(open_price),
                    "high": str(high_price), "low": str(low_price), "close": str(close_price),
                }
                chart_row.update({f"TV26.{tf}.{key}": value for key, value in tv_values.items()})

                server_stamp = (stamp + timedelta(hours=3)).strftime("%Y.%m.%d %H:%M")
                common = {
                    "bar_open_time_server": server_stamp, "symbol": "XAUUSD",
                    "broker_company": "Fixture Broker", "broker_server": "Fixture Demo",
                    "timeframe": mt5_tf_label, "readiness": "OK", "value_a": str(total),
                    "value_b": str(ma), "value_c": str(osc), "value_d": "26",
                    "value_e": "15/15;11/11", "candle_open": str(open_price),
                    "candle_high": str(high_price), "candle_low": str(low_price),
                    "candle_close": str(close_price), "tick_volume": "100",
                }
                audit_rows.append({**common, "component": "SUMMARY", "vote": ""})
                for (name, arabic_label), vote in zip(COMPONENTS.items(), votes):
                    audit_rows.append({
                        **common, "component": arabic_label, "vote": str(vote),
                        "candle_open": "", "candle_high": "", "candle_low": "",
                        "candle_close": "", "tick_volume": "",
                    })
            alltf_rows.append(chart_row)

        alltf_path = folder / "TV26_AllTF.csv"
        audit_path = folder / "MT5_Audit.csv"
        write_csv(alltf_path, alltf_fields, alltf_rows)
        write_csv(audit_path, AUDIT_FIELDS, audit_rows)
        return alltf_path, audit_path

    def test_one_combined_export_passes_all_five_timeframes(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            alltf_path, audit_path = self.make_fixtures(folder)
            results = {}
            for tf in TIMEFRAMES:
                normalized = folder / f"{tf}.csv"
                split = split_file(alltf_path, tf, normalized)
                self.assertEqual(split["rows_written"], 2)
                self.assertEqual(split["rows_missing_pack"], 0)
                result, _, report = compare_files(
                    audit_path, normalized, tf, mt5_utc_offset_hours=3, min_bars=2
                )
                self.assertEqual(result["status"], "PASS", f"{tf}: {report}")
                self.assertEqual(result["matched_bars"], 2)
                self.assertEqual(result["component_votes_checked"], 52)
                self.assertEqual(result["component_vote_mismatches"], 0)
                results[tf] = result["status"]
            self.assertEqual(set(results), set(TIMEFRAMES))
            self.assertEqual(set(results.values()), {"PASS"})

    def test_one_corrupt_packed_vote_fails_the_target_timeframe(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            alltf_path, audit_path = self.make_fixtures(folder)
            headers, rows = read_csv(alltf_path)
            column = "TV26.M15.packed"
            original = int(rows[1][column])
            digit_index = list(COMPONENTS).index("RSI14")
            place = 4 ** digit_index
            digit = (original // place) % 4
            replacement = (digit + 1) % 3
            rows[1][column] = str(original + (replacement - digit) * place)
            write_csv(alltf_path, headers, rows)

            normalized = folder / "M15.csv"
            split_file(alltf_path, "M15", normalized)
            result, details, report = compare_files(
                audit_path, normalized, "M15", mt5_utc_offset_hours=3, min_bars=2
            )
            self.assertEqual(result["status"], "FAIL", report)
            self.assertEqual(result["component_vote_mismatches"], 1)
            mismatches = [d for d in details if d["check"] == "component_vote" and d["result"] == "FAIL"]
            self.assertEqual(len(mismatches), 1)
            self.assertEqual(mismatches[0]["component"], COMPONENTS["RSI14"])


if __name__ == "__main__":
    unittest.main()
