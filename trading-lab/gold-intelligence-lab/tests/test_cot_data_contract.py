"""CFTC COT data-format contracts; no price series or trading simulation."""
import unittest
from datetime import datetime, timezone
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
from goldlab.cot_data import API_URL, SOURCE_URL, COTDataError, parse_cftc_cot_rows

ROWS = [
 {"report_date_as_yyyy_mm_dd":"2026-10-20T00:00:00.000","market_and_exchange_names":"GOLD - COMMODITY EXCHANGE INC.","cftc_contract_market_code":"088691","open_interest_all":"10000","m_money_positions_long_all":"1500","m_money_positions_short_all":"900","m_money_positions_spread":"100"},
 {"report_date_as_yyyy_mm_dd":"2026-10-13T00:00:00.000","market_and_exchange_names":"GOLD - COMMODITY EXCHANGE INC.","cftc_contract_market_code":"088691","open_interest_all":"9800","m_money_positions_long_all":"1400","m_money_positions_short_all":"900","m_money_positions_spread":"90"},
]
class CFTCOTContracts(unittest.TestCase):
 def test_net_position_and_weekly_change(self):
  r=parse_cftc_cot_rows(ROWS,fetched_at_utc=datetime(2026,10,28,tzinfo=timezone.utc)); x=r["rows"][0]
  self.assertEqual(r["latest_report_date"],"2026-10-20")
  self.assertEqual(x["managed_money_net"],600)
  self.assertEqual(x["net_change_vs_previous_report"],100)
  self.assertAlmostEqual(x["managed_money_net_pct_open_interest"],6.0)
  self.assertEqual(r["scope"],"futures_only")
 def test_missing_positions_are_not_filled_with_zero(self):
  row=dict(ROWS[0]); row["m_money_positions_long_all"]=None
  self.assertIsNone(parse_cftc_cot_rows([row])["rows"][0]["managed_money_net"])
 def test_wrong_contract_and_duplicate_report_date_are_rejected(self):
  row=dict(ROWS[0]); row["cftc_contract_market_code"]="123456"
  with self.assertRaises(COTDataError): parse_cftc_cot_rows([row])
  with self.assertRaises(COTDataError): parse_cftc_cot_rows([ROWS[0],ROWS[0]])
 def test_missing_required_field_is_rejected(self):
  row=dict(ROWS[0]); row.pop("m_money_positions_long_all")
  with self.assertRaises(COTDataError): parse_cftc_cot_rows([row])
 def test_invalid_payload_or_empty_rows_are_rejected(self):
  with self.assertRaises(COTDataError): parse_cftc_cot_rows({"error":"fixture"})
  with self.assertRaises(COTDataError): parse_cftc_cot_rows([])
 def test_fixed_public_source_has_no_api_key_or_token_field(self):
  self.assertEqual(API_URL,"https://publicreporting.cftc.gov/resource/72hh-3qpy.json")
  self.assertIn("72hh-3qpy",SOURCE_URL)
  s=(ROOT/"python"/"goldlab"/"cot_data.py").read_text(encoding="utf-8")
  self.assertIn("User-Agent",s); self.assertNotIn("api_key",s.lower()); self.assertNotIn("Authorization",s)
if __name__=="__main__": unittest.main()
