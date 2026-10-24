import csv
import math
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from reference_tv26_formulas import KEY_TO_LABEL, TF_LABEL, compute_votes, rma, run_audit, MA_KEYS, OSC_KEYS, sign_price_level

AUDIT_FIELDS = ["bar_open_time_server", "symbol", "broker_company", "broker_server", "timeframe",
                "component", "readiness", "vote", "value_a", "value_b", "value_c", "value_d", "value_e",
                "candle_open", "candle_high", "candle_low", "candle_close", "tick_volume"]
HISTORY_FIELDS = ["timeframe", "bar_open_time_server", "symbol", "broker_company", "broker_server",
                  "candle_open", "candle_high", "candle_low", "candle_close", "tick_volume"]


def save_csv(path: Path, fields, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def generated_ohlc(start: datetime, count: int, step: int):
    result = []
    for i in range(count):
        close = 2000.0 + 0.035 * i + 1.8 * math.sin(i / 8.0) + 0.4 * math.cos(i / 3.3)
        open_price = close + 0.15 * math.sin(i / 2.7)
        high = max(open_price, close) + 0.35 + 0.08 * math.sin(i / 6.0)
        low = min(open_price, close) - 0.31 - 0.06 * math.cos(i / 4.1)
        stamp = (start + timedelta(minutes=step * i)).strftime("%Y.%m.%d %H:%M")
        result.append({"time": stamp, "open": open_price, "high": high, "low": low,
                       "close": close, "volume": float(100 + (i * 7) % 23)})
    return result


class TV26FormulaReferenceTests(unittest.TestCase):
    def test_price_ma_comparison_suppresses_float_noise(self):
        close = pd.Series([4399.14, 4400.00])
        almost_equal = pd.Series([4399.139999999999, 4399.99])
        votes = sign_price_level(close, almost_equal)
        self.assertEqual(votes.iloc[0], 0.0)
        self.assertEqual(votes.iloc[1], 1.0)

    def test_wilder_rma_uses_sma_seed_then_recursive_smoothing(self):
        result = rma(pd.Series([1.0, 2.0, 3.0, 4.0, 5.0]), 3)
        self.assertTrue(math.isnan(result.iloc[0]))
        self.assertTrue(math.isnan(result.iloc[1]))
        self.assertAlmostEqual(result.iloc[2], 2.0)
        self.assertAlmostEqual(result.iloc[3], 8.0 / 3.0)
        self.assertAlmostEqual(result.iloc[4], 31.0 / 9.0)

    def fixture(self, folder: Path, corrupt_vote=False):
        history_rows, audit_rows = [], []
        step_by_tf = {"M1": 1, "M5": 5, "M15": 15, "M30": 30, "H1": 60}
        start = datetime(2026, 1, 1, 0, 0)
        for tf, label in TF_LABEL.items():
            step = step_by_tf[tf]
            source = generated_ohlc(start, 300, step)
            last = generated_ohlc(start, 301, step)[-1]
            for bar in source:
                history_rows.append({"timeframe": label, "bar_open_time_server": bar["time"],
                                     "symbol": "XAUUSD", "broker_company": "Fixture Broker",
                                     "broker_server": "Fixture Demo", "candle_open": bar["open"],
                                     "candle_high": bar["high"], "candle_low": bar["low"],
                                     "candle_close": bar["close"], "tick_volume": int(bar["volume"])})
            votes = compute_votes(pd.DataFrame(source + [last]))
            component_votes = {}
            for key in KEY_TO_LABEL:
                value = votes[key].iloc[-1]
                if not math.isfinite(float(value)):
                    raise AssertionError(f"Fixture warmup did not initialize {key} in {tf}")
                component_votes[key] = int(value)
            common = {"bar_open_time_server": last["time"], "symbol": "XAUUSD",
                      "broker_company": "Fixture Broker", "broker_server": "Fixture Demo",
                      "timeframe": label, "readiness": "OK", "value_a": "0", "value_b": "0",
                      "value_c": "0", "value_d": "26", "value_e": "15/15;11/11",
                      "candle_open": str(last["open"]), "candle_high": str(last["high"]),
                      "candle_low": str(last["low"]), "candle_close": str(last["close"]),
                      "tick_volume": str(int(last["volume"]))}
            audit_rows.append({**common, "component": "SUMMARY", "vote": ""})
            for key, label_name in KEY_TO_LABEL.items():
                vote = component_votes[key]
                if corrupt_vote and tf == "M1" and key == "RSI14":
                    vote = 1 if vote != 1 else -1
                audit_rows.append({**common, "component": label_name, "vote": str(vote),
                                   "candle_open": "", "candle_high": "", "candle_low": "",
                                   "candle_close": "", "tick_volume": ""})
        history_path = folder / "history.csv"
        audit_path = folder / "audit.csv"
        save_csv(history_path, HISTORY_FIELDS, history_rows)
        save_csv(audit_path, AUDIT_FIELDS, audit_rows)
        return audit_path, history_path

    def test_dmi_and_ultimate_oscillator_preserve_pine_first_bar_na(self):
        # Published Pine expressions depend on previous-bar values for TR and DM.
        # Those inputs are unavailable on bar 0; both votes should first be ready on bar 28.
        frame = pd.DataFrame(generated_ohlc(datetime(2026, 1, 1), 400, 1))
        votes = compute_votes(frame)
        self.assertEqual(votes["ADX"].first_valid_index(), 28)
        self.assertEqual(votes["UltimateOscillator"].first_valid_index(), 28)

    def test_formula_engine_exposes_exactly_26_component_votes(self):
        votes = compute_votes(pd.DataFrame(generated_ohlc(datetime(2026, 1, 1), 400, 1)))
        self.assertEqual(set(votes), set(KEY_TO_LABEL))
        self.assertEqual(len(MA_KEYS), 15)
        self.assertEqual(len(OSC_KEYS), 11)
        for series in votes.values():
            valid = series.dropna()
            self.assertTrue(len(valid) > 0)
            self.assertTrue(set(valid.astype(int).unique()).issubset({-1, 0, 1}))

    def test_multiframe_audit_passes_when_votes_agree(self):
        with tempfile.TemporaryDirectory() as tmp:
            audit, history = self.fixture(Path(tmp))
            result, detail, report = run_audit(audit, history, {tf: 1 for tf in TF_LABEL})
            self.assertEqual(result["status"], "PASS", report)
            self.assertEqual(result["total_formula_votes_checked"], 5 * 26)
            self.assertEqual(result["total_vote_mismatches"], 0)
            self.assertEqual(result["total_missing_or_invalid"], 0)

    def test_single_bad_vote_fails_the_formula_audit(self):
        with tempfile.TemporaryDirectory() as tmp:
            audit, history = self.fixture(Path(tmp), corrupt_vote=True)
            result, detail, report = run_audit(audit, history, {tf: 1 for tf in TF_LABEL})
            self.assertEqual(result["status"], "FAIL")
            self.assertEqual(result["total_vote_mismatches"], 1)
            failures = [row for row in detail if row["state"] == "MISMATCH"]
            self.assertEqual(len(failures), 1)
            self.assertEqual(failures[0]["component"], "RSI14")


if __name__ == "__main__":
    unittest.main()
