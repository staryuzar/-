import unittest

from bitcoinlab.liquidations import (
    normalize_binance_force_order,
    normalize_bybit_liquidation,
    normalize_okx_liquidation,
    summarize_liquidations,
)


class LiquidationNormalizerTests(unittest.TestCase):
    def test_binance_maps_sell_liquidation_to_long_and_computes_filled_notional(self):
        event = normalize_binance_force_order({
            "e": "forceOrder", "E": 1_800_000_000_000,
            "o": {
                "s": "BTCUSDT", "S": "SELL", "X": "FILLED",
                "q": "0.20", "z": "0.12", "p": "67000",
                "ap": "67500", "T": 1_800_000_000_001,
            },
        })
        self.assertEqual(event["liquidated_side"], "LONG")
        self.assertEqual(event["raw_size"], 0.12)
        self.assertEqual(event["reference_price_kind"], "average_fill_price")
        self.assertAlmostEqual(event["notional_usd"], 8100.0)
        self.assertEqual(event["quantity_unit"], "BTC")

    def test_binance_buy_liquidation_maps_to_short(self):
        event = normalize_binance_force_order({
            "e": "forceOrder",
            "o": {
                "s": "BTCUSDT", "S": "BUY", "X": "FILLED",
                "z": "0.05", "ap": "68000", "T": 1_800_000_000_000,
            },
        })
        self.assertEqual(event["liquidated_side"], "SHORT")

    def test_binance_ignores_no_partial_or_open_order_snapshots(self):
        with self.assertRaisesRegex(ValueError, "not a completed fill"):
            normalize_binance_force_order({
                "e": "forceOrder",
                "o": {
                    "s": "BTCUSDT", "S": "SELL", "X": "NEW",
                    "z": "0", "ap": "0", "T": 1_800_000_000_000,
                },
            })

    def test_bybit_side_mapping_and_bankruptcy_price_are_preserved(self):
        events = normalize_bybit_liquidation({
            "topic": "allLiquidation.BTCUSDT", "ts": 1_800_000_000_000,
            "data": [
                {"T": 1_800_000_000_000, "s": "BTCUSDT", "S": "Buy", "v": "12000", "p": "67000"},
                {"T": 1_800_000_000_100, "s": "BTCUSDT", "S": "Sell", "v": "8000", "p": "68000"},
            ],
        })
        self.assertEqual([event["liquidated_side"] for event in events], ["LONG", "SHORT"])
        self.assertEqual(events[0]["reference_price_kind"], "bankruptcy_price")
        self.assertIsNone(events[0]["notional_usd"])
        self.assertEqual(events[0]["quantity_unit"], "venue_reported_contract_units")

    def test_okx_pos_side_maps_long_short_and_net_without_guessing_contract_usd(self):
        events = normalize_okx_liquidation({
            "arg": {"channel": "liquidation-orders", "instType": "SWAP"},
            "data": [{
                "instId": "BTC-USDT-SWAP",
                "details": [
                    {"side": "buy", "posSide": "short", "sz": "12", "bkPx": "67100", "ts": "1800000000000"},
                    {"side": "sell", "posSide": "net", "sz": "9", "bkPx": "67200", "ts": "1800000000100"},
                ],
            }],
        })
        self.assertEqual([event["liquidated_side"] for event in events], ["SHORT", "LONG"])
        self.assertEqual(events[0]["quantity_unit"], "contracts")
        self.assertIsNone(events[0]["notional_usd"])

    def test_okx_filters_non_btc_contracts(self):
        events = normalize_okx_liquidation({
            "arg": {"channel": "liquidation-orders", "instType": "SWAP"},
            "data": [{
                "instId": "ETH-USDT-SWAP",
                "details": [
                    {"side": "sell", "posSide": "long", "sz": "1", "bkPx": "2000", "ts": "1800000000000"},
                ],
            }],
        })
        self.assertEqual(events, [])

    def test_summary_never_combines_different_venue_units_into_one_total(self):
        binance = normalize_binance_force_order({
            "e": "forceOrder",
            "o": {
                "s": "BTCUSDT", "S": "SELL", "X": "FILLED",
                "z": "0.1", "ap": "67000", "T": 1_800_000_000_000,
            },
        })
        bybit = normalize_bybit_liquidation({
            "topic": "allLiquidation.BTCUSDT", "ts": 1_800_000_000_000,
            "data": [{"T": 1_800_000_000_000, "s": "BTCUSDT", "S": "Buy", "v": "100", "p": "67000"}],
        })[0]
        result = summarize_liquidations([binance, bybit])
        self.assertEqual(result["event_count"], 2)
        self.assertEqual(len(result["groups"]), 2)
        self.assertEqual(
            {row["quantity_unit"] for row in result["groups"]},
            {"BTC", "venue_reported_contract_units"},
        )
        bybit_group = next(row for row in result["groups"] if row["venue"] == "bybit_linear")
        self.assertIsNone(bybit_group["notional_usd"])

    def test_event_key_is_stable_for_duplicate_payload(self):
        message = {
            "e": "forceOrder", "o": {
                "s": "BTCUSDT", "S": "SELL", "X": "FILLED",
                "z": "0.1", "ap": "67000", "T": 1_800_000_000_000,
            },
        }
        one = normalize_binance_force_order(message)
        two = normalize_binance_force_order(message)
        self.assertEqual(one["event_key"], two["event_key"])


if __name__ == "__main__":
    unittest.main()
