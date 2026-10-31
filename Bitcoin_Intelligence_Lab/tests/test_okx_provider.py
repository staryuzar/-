import unittest
from unittest.mock import patch

from bitcoinlab.providers.okx import SWAP_SYMBOL, fetch_derivatives_snapshot


NOW = 1_800_000_000_000


def payload(rows):
    return {"code": "0", "msg": "", "data": rows}


class OKXDerivativesProviderTests(unittest.TestCase):
    @patch("bitcoinlab.providers.okx.get_json")
    def test_reuses_cross_venue_context_and_scores_recent_taker_trade_sample(self, get_json):
        get_json.return_value = payload([
            {"instId": SWAP_SYMBOL, "side": "buy", "sz": "2", "ts": str(NOW)},
            {"instId": SWAP_SYMBOL, "side": "sell", "sz": "1", "ts": str(NOW - 1000)},
            {"instId": SWAP_SYMBOL, "side": "buy", "sz": "0.5", "ts": str(NOW - 2000)},
        ])
        context = {
            "venues": [{
                "venue": "okx_swap", "status": "ok",
                "funding_rate_per_settlement": 0.0002,
                "funding_interval_minutes": 480,
                "open_interest_btc": 123.4,
                "open_interest_native": 12340,
                "open_interest_quote_value": 8_000_000,
                "observed_at_ms": NOW - 3000,
            }]
        }
        result = fetch_derivatives_snapshot("BTCUSDT", cross_venue_context=context)
        self.assertEqual(result["venue"], "OKX")
        self.assertEqual(result["symbol"], SWAP_SYMBOL)
        self.assertAlmostEqual(result["taker_buy_sell_ratio"], 2.5)
        self.assertEqual(result["trade_count"], 3)
        self.assertEqual(result["taker_buy_volume_contracts"], 2.5)
        self.assertEqual(result["taker_sell_volume_contracts"], 1.0)
        self.assertAlmostEqual(result["funding_rate"], 0.0002)
        self.assertEqual(result["open_interest_btc"], 123.4)
        self.assertEqual(result["open_interest_native_unit"], "contracts")
        self.assertIsNone(result["open_interest_change_pct"])
        self.assertEqual(get_json.call_count, 1)

    @patch("bitcoinlab.providers.okx.get_json")
    def test_fetches_settled_funding_and_oi_when_context_is_missing(self, get_json):
        get_json.side_effect = [
            payload([{
                "instId": SWAP_SYMBOL,
                "fundingRate": "0.0003",
                "settFundingRate": "0.0002",
                "settState": "settled",
                "fundingTime": str(NOW - 480 * 60_000),
                "nextFundingTime": str(NOW),
                "ts": str(NOW - 1000),
            }]),
            payload([{
                "instId": SWAP_SYMBOL, "oi": "15000",
                "oiCcy": "150", "oiUsd": "10000000", "ts": str(NOW - 2000),
            }]),
            payload([
                {"instId": SWAP_SYMBOL, "side": "buy", "sz": "3", "ts": str(NOW)},
                {"instId": SWAP_SYMBOL, "side": "sell", "sz": "2", "ts": str(NOW - 500)},
            ]),
        ]
        result = fetch_derivatives_snapshot("BTCUSDT")
        self.assertAlmostEqual(result["funding_rate"], 0.0002)
        self.assertEqual(result["funding_rate_kind"], "settled")
        self.assertAlmostEqual(result["funding_interval_minutes"], 480)
        self.assertEqual(result["open_interest_btc"], 150.0)
        self.assertEqual(result["open_interest_native"], 15000.0)
        self.assertEqual(result["open_interest_quote_value"], 10_000_000.0)
        self.assertAlmostEqual(result["taker_buy_sell_ratio"], 1.5)
        self.assertEqual(get_json.call_count, 3)

    @patch("bitcoinlab.providers.okx.get_json")
    def test_current_period_funding_estimate_is_labelled_not_misrepresented_as_settled(self, get_json):
        get_json.side_effect = [
            payload([{
                "fundingRate": "0.0004", "settFundingRate": "",
                "settState": "processing", "fundingTime": str(NOW),
                "nextFundingTime": str(NOW + 240 * 60_000), "ts": str(NOW),
            }]),
            payload([{"oi": "100", "oiCcy": "1", "oiUsd": "70000", "ts": str(NOW)}]),
            payload([
                {"side": "buy", "sz": "1", "ts": str(NOW)},
                {"side": "sell", "sz": "1", "ts": str(NOW - 100)},
            ]),
        ]
        result = fetch_derivatives_snapshot("BTCUSDT")
        self.assertEqual(result["funding_rate_kind"], "current_period_estimate")
        self.assertAlmostEqual(result["funding_rate"], 0.0004)
        self.assertIn("okx_funding_rate_is_current_period_estimate_not_settled", result["warnings"])

    @patch("bitcoinlab.providers.okx.get_json")
    def test_one_sided_trade_sample_is_not_promoted_to_a_taker_ratio(self, get_json):
        get_json.return_value = payload([
            {"side": "buy", "sz": "1", "ts": str(NOW)},
            {"side": "buy", "sz": "2", "ts": str(NOW - 100)},
        ])
        with self.assertRaisesRegex(ValueError, "both taker sides"):
            fetch_derivatives_snapshot(
                "BTCUSDT",
                cross_venue_context={"venues": []},
            )

    @patch("bitcoinlab.providers.okx.get_json")
    def test_non_bitcoin_symbol_is_rejected_without_network_requests(self, get_json):
        with self.assertRaises(ValueError):
            fetch_derivatives_snapshot("ETHUSDT")
        get_json.assert_not_called()

    @patch("bitcoinlab.providers.okx.get_json")
    def test_nonzero_okx_api_code_is_reported(self, get_json):
        get_json.side_effect = [
            payload([{
                "fundingRate": "0.0001", "settFundingRate": "0.0001",
                "settState": "settled", "fundingTime": str(NOW - 480 * 60_000),
                "nextFundingTime": str(NOW), "ts": str(NOW - 1000),
            }]),
            payload([{
                "oi": "100", "oiCcy": "1", "oiUsd": "70000", "ts": str(NOW),
            }]),
            {"code": "50011", "msg": "rate limit", "data": []},
        ]
        with self.assertRaisesRegex(ValueError, "OKX perpetual trades response failed"):
            fetch_derivatives_snapshot(
                "BTCUSDT",
                cross_venue_context={"venues": []},
            )


if __name__ == "__main__":
    unittest.main()
