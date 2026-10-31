import unittest

from bitcoinlab.trade_flow import (
    normalize_binance_usdm_agg_trade,
    normalize_bybit_public_trades,
    normalize_okx_spot_trades,
)


class TradeStreamNormalizationTests(unittest.TestCase):
    def test_binance_usdm_agg_trade_uses_buyer_maker_for_aggressor(self):
        event = normalize_binance_usdm_agg_trade({
            "e": "aggTrade", "s": "BTCUSDT", "a": 5001,
            "p": "67000.0", "q": "0.05", "f": 101, "l": 103,
            "T": 1_800_000_000_000, "m": True,
        })
        self.assertEqual(event["aggressor_side"], "SELL")
        self.assertEqual(event["trade_count"], 3)
        self.assertEqual(event["market_type"], "linear_perpetual")
        self.assertEqual(event["quantity_unit"], "BTC")
        self.assertAlmostEqual(event["notional_usd"], 3350.0)

    def test_binance_rejects_wrong_symbol_and_bad_maker_flag(self):
        payload = {
            "e": "aggTrade", "s": "ETHUSDT", "a": 1,
            "p": "3000", "q": "1", "f": 1, "l": 1,
            "T": 1_800_000_000_000, "m": False,
        }
        with self.assertRaisesRegex(ValueError, "BTCUSDT"):
            normalize_binance_usdm_agg_trade(payload)
        payload["s"] = "BTCUSDT"
        payload["m"] = "false"
        with self.assertRaisesRegex(ValueError, "boolean"):
            normalize_binance_usdm_agg_trade(payload)

    def test_bybit_uses_taker_side_and_preserves_perpetual_type(self):
        events = normalize_bybit_public_trades({
            "topic": "publicTrade.BTCUSDT",
            "ts": 1_800_000_000_100,
            "data": [{
                "T": 1_800_000_000_000, "s": "BTCUSDT", "S": "Buy",
                "v": "0.02", "p": "67000", "i": "trade-abc",
            }],
        })
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["aggressor_side"], "BUY")
        self.assertEqual(events[0]["base_quantity"], 0.02)
        self.assertEqual(events[0]["market_type"], "linear_perpetual")

    def test_okx_spot_uses_base_quantity_and_count(self):
        events = normalize_okx_spot_trades({
            "arg": {"channel": "trades", "instId": "BTC-USDT"},
            "data": [{
                "instId": "BTC-USDT", "tradeId": "9876", "px": "67000",
                "sz": "0.03", "side": "sell", "ts": "1800000000000",
                "count": "4",
            }],
        })
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["market_type"], "spot")
        self.assertEqual(events[0]["aggressor_side"], "SELL")
        self.assertAlmostEqual(events[0]["base_quantity"], 0.03)
        self.assertEqual(events[0]["trade_count"], 4)

    def test_okx_rejects_swap_instrument_in_spot_normalizer(self):
        with self.assertRaisesRegex(ValueError, "BTC-USDT"):
            normalize_okx_spot_trades({
                "arg": {"channel": "trades", "instId": "BTC-USDT-SWAP"},
                "data": [],
            })


if __name__ == "__main__":
    unittest.main()
