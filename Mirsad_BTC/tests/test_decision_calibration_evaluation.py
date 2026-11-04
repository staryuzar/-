from __future__ import annotations
import sqlite3,tempfile,unittest
from pathlib import Path
from scripts.evaluate_decision_calibration import (
 SplitWindow,evaluate_database,forward_markout_bps,parse_horizons,validate_split_windows
)

class DecisionCalibrationEvaluationTests(unittest.TestCase):
 def test_horizons_are_sorted_unique_positive(self):
  self.assertEqual(parse_horizons("5,1,3"),(1,3,5))
  with self.assertRaisesRegex(ValueError,"unique"): parse_horizons("1,3,1")
  with self.assertRaisesRegex(ValueError,"positive"): parse_horizons("1,0,5")

 def test_chronological_splits_enforce_embargo(self):
  windows=[SplitWindow("train",60_000,4_000_000),SplitWindow("validation",4_030_000,8_000_000),
           SplitWindow("test",8_030_000,12_000_000)]
  with self.assertRaisesRegex(ValueError,"begin at least"):
   validate_split_windows(windows,max_horizon=20,embargo_bars=20)

 def test_forward_markout_uses_next_open_and_deducts_round_trip_cost(self):
  candles={120_000:{"open":100.0,"high":101.0,"low":99.0,"close":101.0},
           180_000:{"open":101.0,"high":103.0,"low":100.0,"close":102.0}}
  result=forward_markout_bps(signal_bar_time_ms=60_000,action="BUY",candles_by_open_ms=candles,
    horizon=2,fee_bps_per_side=2.0,slippage_bps_per_side=1.0,spread_pct=0.02)
  self.assertAlmostEqual(result["gross_bps"],200.0)
  self.assertAlmostEqual(result["cost_bps"],8.0)
  self.assertAlmostEqual(result["net_bps"],192.0)

 def test_sell_is_directional_and_wait_is_not_a_trade(self):
  candles={120_000:{"open":100.0,"high":101.0,"low":98.0,"close":99.0}}
  sell=forward_markout_bps(signal_bar_time_ms=60_000,action="SELL",candles_by_open_ms=candles,
    horizon=1,fee_bps_per_side=0.0,slippage_bps_per_side=0.0,spread_pct=0.0)
  self.assertGreater(sell["gross_bps"],0.0)
  self.assertIsNone(forward_markout_bps(signal_bar_time_ms=60_000,action="WAIT",
    candles_by_open_ms=candles,horizon=1,fee_bps_per_side=0.0,
    slippage_bps_per_side=0.0,spread_pct=0.0))

 def test_evaluator_keeps_train_validation_test_separate_and_unvalidated(self):
  with tempfile.TemporaryDirectory() as directory:
   db=Path(directory)/"calibration.sqlite3"
   with sqlite3.connect(db) as conn:
    conn.executescript("""
      CREATE TABLE decision_calibration_samples(sample_key TEXT,signal_bar_time_ms INTEGER,
        symbol TEXT,profile_version TEXT,final_action TEXT,broker_spread_pct REAL);
      CREATE TABLE decision_calibration_candles(symbol TEXT,timeframe TEXT,open_time_ms INTEGER,
        open REAL,high REAL,low REAL,close REAL,volume REAL);
    """)
    conn.executemany("INSERT INTO decision_calibration_samples VALUES(?,?,?,?,?,?)",[
      ("tr",120_000,"BTCUSDT","v1","BUY",0.01),
      ("va",1_200_000,"BTCUSDT","v1","SELL",0.01),
      ("te",2_200_000,"BTCUSDT","v1","WAIT",0.01)])
    bars=[("BTCUSDT","1m",t,100.0,101.0,99.0,100.5,10.0)
          for t in range(60_000,3_000_001,60_000)]
    conn.executemany("INSERT INTO decision_calibration_candles VALUES(?,?,?,?,?,?,?,?)",bars)
   windows=[SplitWindow("train",60_000,900_000),SplitWindow("validation",1_080_000,1_920_000),
            SplitWindow("test",2_100_000,2_940_000)]
   result=evaluate_database(db,windows=windows,horizons=(1,),embargo_bars=1,
     fee_bps_per_side=1.0,slippage_bps_per_side=0.5)
   self.assertEqual(result["status"],"UNVALIDATED")
   self.assertTrue(result["costs_applied"])
   self.assertEqual(result["splits"]["train"]["directional_signals"],1)
   self.assertEqual(result["splits"]["validation"]["directional_signals"],1)
   self.assertEqual(result["splits"]["test"]["wait_signals"],1)
   self.assertEqual(result["splits"]["test"]["directional_signals"],0)

if __name__=="__main__":
 unittest.main()
