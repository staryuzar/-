import unittest
from unittest.mock import patch

from bitcoinlab.providers.bybit import fetch_derivatives_snapshot


def payload(result):
    return {"retCode": 0, "retMsg": "OK", "result": result}


class BybitProviderTests(unittest.TestCase):
    @patch("bitcoinlab.providers.bybit._request")
    def test_derivatives_snapshot_normalizes_oi_funding_and_taker_flow(self, request):
        request.side_effect = [
            payload({
                "list": [
                    {"timestamp": "1800000000000", "openInterest": "100"},
                    {"timestamp": "1800000300000", "openInterest": "102"},
                ]
            }),
            payload({
                "list": [{"fundingRate": "0.0001", "fundingRateTimestamp": "1800000000000"}]
            }),
            payload({
                "list": [
                    {"side": "Buy", "size": "2", "time": "1800000300000"},
                    {"side": "Sell", "size": "1", "time": "1800000299000"},
                ]
            }),
        ]
        result = fetch_derivatives_snapshot("BTCUSDT")
        self.assertEqual(result["venue"], "Bybit")
        self.assertAlmostEqual(result["open_interest_change_pct"], 2.0)
        self.assertAlmostEqual(result["taker_buy_sell_ratio"], 2.0)
        self.assertEqual(result["trades"][1]["m"], True)
        self.assertEqual(request.call_count, 3)

    @patch("bitcoinlab.providers.bybit._request")
    def test_nonzero_bybit_retcode_is_reported(self, request):
        request.return_value = {"retCode": 10001, "retMsg": "bad request"}
        with self.assertRaisesRegex(ValueError, "retCode=10001"):
            fetch_derivatives_snapshot("BTCUSDT")

    def test_non_bitcoin_symbol_is_rejected_before_request(self):
        with patch("bitcoinlab.providers.bybit._request") as request:
            with self.assertRaises(ValueError):
                fetch_derivatives_snapshot("ETHUSDT")
            request.assert_not_called()

    @patch("bitcoinlab.providers.bybit._request")
    def test_zero_side_volume_is_not_misreported_as_ratio(self, request):
        request.side_effect = [
            payload({"list": [
                {"timestamp": "1800000000000", "openInterest": "100"},
                {"timestamp": "1800000300000", "openInterest": "101"},
            ]}),
            payload({"list": []}),
            payload({"list": [
                {"side": "Buy", "size": "2", "time": "1800000300000"},
            ]}),
        ]
        with self.assertRaisesRegex(ValueError, "lacks both taker sides"):
            fetch_derivatives_snapshot("BTCUSDT")


if __name__ == "__main__":
    unittest.main()
