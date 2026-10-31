import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from bitcoinlab.providers import binance
from bitcoinlab.providers.cftc import parse_tff_csv


class BinanceTakerRatioAdapterTests(unittest.TestCase):
    @patch("bitcoinlab.providers.binance.get_json")
    def test_public_endpoint_and_query(self, get_json):
        get_json.return_value = [{"buySellRatio": "1.5", "timestamp": 1800000000000}]
        rows = binance.fetch_taker_ratio("btcusdt", "5m", 3)
        url = get_json.call_args.args[0]
        self.assertIn("/futures/data/takerlongshortRatio", url)
        query = parse_qs(urlparse(url).query)
        self.assertEqual(query["symbol"], ["BTCUSDT"])
        self.assertEqual(query["period"], ["5m"])
        self.assertEqual(query["limit"], ["3"])
        self.assertEqual(len(rows), 1)

    def test_invalid_period_rejected(self):
        with self.assertRaises(ValueError):
            binance.fetch_taker_ratio("BTCUSDT", "2m", 3)

    @patch("bitcoinlab.providers.binance.get_json")
    def test_invalid_payload_rejected(self, get_json):
        get_json.return_value = [{"buySellRatio": "0", "timestamp": 1800000000000}]
        with self.assertRaises(ValueError):
            binance.fetch_taker_ratio()
        get_json.return_value = [{"buySellRatio": "1.2"}]
        with self.assertRaises(ValueError):
            binance.fetch_taker_ratio()


class CFTCTFFParserRepairTests(unittest.TestCase):
    def test_dash_optional_field_keeps_valid_row(self):
        fields = ["BITCOIN - CME", "", "10/27/2026", "133741", "", "", "",
                  "1000", "300", "200", "0", "250", "100", "0", "-", ""]
        rows = parse_tff_csv(",".join(fields))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["report_date"], "2026-10-27")
        self.assertEqual(rows[0]["dealer_net"], 100)
        self.assertEqual(rows[0]["asset_manager_net"], 150)
        self.assertIsNone(rows[0]["leveraged_money_net"])

    def test_iso_date_accepted(self):
        fields = ["BITCOIN - CME", "", "2026-10-27", "133742", "", "", "",
                  "500", "50", "40", "0", "20", "10", "0", "5", "2"]
        rows = parse_tff_csv(",".join(fields))
        self.assertEqual(rows[0]["asset"], "BTC_MICRO")
        self.assertEqual(rows[0]["leveraged_money_net"], 3)


if __name__ == "__main__":
    unittest.main()
