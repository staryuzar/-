import csv
import math
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from validate_tv26_ichimoku_alignment import (
    ICHIMOKU_LABEL, TF_LABELS, expected_ichimoku, validate_files
)

AUDIT_FIELDS = [
    "bar_open_time_server", "symbol", "broker_company", "broker_server",
    "timeframe", "component", "readiness", "vote", "value_a", "value_b",
    "value_c", "value_d", "value_e", "candle_open", "candle_high",
    "candle_low", "candle_close", "tick_volume",
]
HISTORY_FIELDS = [
    "timeframe", "bar_open_time_server", "symbol", "broker_company",
    "broker_server", "candle_open", "candle_high", "candle_low",
    "candle_close", "tick_volume",
]
STEPS = {"M1": 1, "M5": 5, "M15": 15, "M30": 30, "H1": 60}


def write_csv(path, fields, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def make_bars(start, count, step_minutes, tf_index):
    bars = []
    for i in range(count):
        close = 2000.0 + tf_index * 7.0 + 0.027 * i + 1.2 * math.sin(i / 5.0)
        open_price = close + 0.12 * math.sin(i / 2.3)
        high = max(open_price, close) + 0.35 + 0.02 * math.cos(i / 4.0)
        low = min(open_price, close) - 0.31 - 0.03 * math.sin(i / 6.0)
        stamp = (start + timedelta(minutes=step_minutes * i)).strftime("%Y.%m.%d %H:%M")
        bars.append({
            "time": stamp, "open": open_price, "high": high, "low": low,
            "close": close, "volume": int(100 + (i * 7) % 29),
        })
    return bars


class TV26IchimokuRawAlignmentTests(unittest.TestCase):
    def make_fixtures(self, folder: Path, corrupt: bool = False):
        history_rows, audit_rows = [], []
        start = datetime(2026, 1, 1, 0, 0)
        for tf_index, (tf, label) in enumerate(TF_LABELS.items()):
            all_bars = make_bars(start, 160, STEPS[tf], tf_index)
            audit_start = 120
            for bar in all_bars[:audit_start]:
                history_rows.append({
                    "timeframe": label, "bar_open_time_server": bar["time"],
                    "symbol": "XAUUSD", "broker_company": "Fixture Broker",
                    "broker_server": "Fixture Demo", "candle_open": bar["open"],
                    "candle_high": bar["high"], "candle_low": bar["low"],
                    "candle_close": bar["close"], "tick_volume": bar["volume"],
                })
            expected = expected_ichimoku(all_bars)
            for i in range(audit_start, len(all_bars)):
                bar = all_bars[i]
                stamp = bar["time"]
                common = {
                    "bar_open_time_server": stamp, "symbol": "XAUUSD",
                    "broker_company": "Fixture Broker", "broker_server": "Fixture Demo",
                    "timeframe": label, "readiness": "OK", "vote": "",
                    "value_a": "", "value_b": "", "value_c": "", "value_d": "", "value_e": "",
                    "candle_open": str(bar["open"]), "candle_high": str(bar["high"]),
                    "candle_low": str(bar["low"]), "candle_close": str(bar["close"]),
                    "tick_volume": str(bar["volume"]),
                }
                audit_rows.append({**common, "component": "SUMMARY"})
                calc = expected.iloc[i]
                values = {
                    "value_a": float(calc["tenkan_sen"]),
                    "value_b": float(calc["kijun_sen"]),
                    "value_c": float(calc["senkou_span_a_shift26"]),
                    "value_d": float(calc["senkou_span_b_shift26"]),
                    "value_e": float(calc["close"]),
                }
                if corrupt and tf == "M15" and i == audit_start + 3:
                    values["value_c"] += 0.01
                audit_rows.append({**common, "component": ICHIMOKU_LABEL, **{k: str(v) for k, v in values.items()},
                                   "candle_open": "", "candle_high": "", "candle_low": "", "candle_close": "", "tick_volume": ""})

        history_path = folder / "history.csv"
        audit_path = folder / "audit.csv"
        write_csv(history_path, HISTORY_FIELDS, history_rows)
        write_csv(audit_path, AUDIT_FIELDS, audit_rows)
        return audit_path, history_path

    def test_all_five_timeframes_pass_when_raw_values_align(self):
        with tempfile.TemporaryDirectory() as temp:
            audit, history = self.make_fixtures(Path(temp))
            result, details, report = validate_files(audit, history, tolerance=1e-6, min_bars=10)
            self.assertEqual(result["status"], "PASS", report)
            self.assertEqual(result["total_ichimoku_bars"], 5 * 40)
            self.assertEqual(result["total_raw_values_checked"], 5 * 40 * 5)
            self.assertEqual(result["total_mismatches"], 0)
            self.assertEqual(result["total_missing_values"], 0)

    def test_wrong_cloud_shift_is_detected_and_located(self):
        with tempfile.TemporaryDirectory() as temp:
            audit, history = self.make_fixtures(Path(temp), corrupt=True)
            result, details, report = validate_files(audit, history, tolerance=1e-6, min_bars=10)
            self.assertEqual(result["status"], "FAIL", report)
            self.assertEqual(result["total_mismatches"], 1)
            mismatches = [row for row in details if row["result"] == "FAIL"]
            self.assertEqual(len(mismatches), 1)
            self.assertEqual(mismatches[0]["timeframe"], "M15")
            self.assertEqual(mismatches[0]["field"], "value_c")


if __name__ == "__main__":
    unittest.main()
