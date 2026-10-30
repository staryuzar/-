import unittest
from unittest.mock import patch

from bitcoinlab.providers.binance import fetch_spot_klines, normalize_derivatives
from bitcoinlab.providers.cftc import CFTC_TFF_CODES, parse_tff_csv
from bitcoinlab.providers.coinmetrics import fetch_community_metrics
from bitcoinlab.providers.deribit import fetch_dvol_history
from bitcoinlab.providers.http import ProviderError, get_json


def tff_row(code, name="BITCOIN - CHICAGO MERCANTILE EXCHANGE"):
    fields = [""] * 87
    fields[0] = name
    fields[2] = "10/13/2026"
    fields[3] = code
    fields[7] = "20000"
    fields[8], fields[9] = "1000", "900"
    fields[11], fields[12] = "500", "400"
    fields[14], fields[15] = "7000", "6500"
    return ",".join(fields)


class ProviderTests(unittest.TestCase):
    def test_binance_kline_adapter_excludes_open_candle(self):
        closed = [1000, "100", "102", "99", "101", "10", 1999]
        open_row = [2000, "101", "103", "100", "102", "11", 2999]
        with patch("bitcoinlab.providers.binance.get_json", return_value=[closed, open_row]):
            bars = fetch_spot_klines("BTCUSDT", "1m", 60, now_ms=2500)
        self.assertEqual(len(bars), 1)
        self.assertTrue(bars[0].is_closed)
        self.assertEqual(bars[0].close, 101.0)

    def test_cftc_tff_parser_uses_financial_futures_field_positions(self):
        rows = parse_tff_csv(tff_row("133741") + "\n" + tff_row("133742", "MICRO BITCOIN - CME"))
        self.assertEqual(len(rows), 2)
        btc = next(row for row in rows if row["contract_code"] == "133741")
        self.assertEqual(btc["leveraged_money_net"], 500)
        self.assertEqual(btc["asset_manager_net"], 100)
        self.assertEqual(btc["dealer_net"], 100)
        self.assertEqual(CFTC_TFF_CODES["133742"], "BTC_MICRO")

    def test_cftc_ignores_unrelated_products(self):
        self.assertEqual(parse_tff_csv(tff_row("088691")), [])

    def test_coinmetrics_adapter_restricts_metric_allowlist(self):
        with self.assertRaises(ValueError):
            fetch_community_metrics(("SecretMetric",))

    def test_coinmetrics_payload_is_checked(self):
        payload = {"data": [{"asset": "btc", "time": "2026-10-30T00:00:00Z", "AdrActCnt": "500000"}]}
        with patch("bitcoinlab.providers.coinmetrics.get_json", return_value=payload):
            result = fetch_community_metrics()
        self.assertEqual(result["data"][0]["asset"], "btc")

    def test_deribit_requires_jsonrpc_result(self):
        with patch("bitcoinlab.providers.deribit.get_json", return_value={"result": {"data": [[1, 2, 3, 4, 5]]}}):
            result = fetch_dvol_history(start_timestamp_ms=1000, end_timestamp_ms=2000)
        self.assertEqual(result["status"], "ok")

    def test_derivatives_normalizer(self):
        result = normalize_derivatives(
            [{"fundingRate": "0.0001"}],
            {"openInterest": "100", "time": 1700000000000},
            [{"buySellRatio": "1.2"}],
            prior_open_interest=95,
        )
        self.assertAlmostEqual(result["open_interest_change_pct"], (100 - 95) / 95 * 100)
        self.assertAlmostEqual(result["taker_buy_sell_ratio"], 1.2)

    def test_http_client_rejects_non_https(self):
        with self.assertRaises(ValueError):
            get_json("http://example.com")


if __name__ == "__main__":
    unittest.main()
