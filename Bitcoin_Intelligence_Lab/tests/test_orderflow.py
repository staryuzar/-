import unittest

from bitcoinlab.orderflow import order_book_metrics, orderflow_profile, trade_flow_metrics


class OrderFlowTests(unittest.TestCase):
    def test_book_imbalance_and_spread(self):
        result = order_book_metrics([[99, 5], [98, 2]], [[101, 1], [102, 1]])
        self.assertGreater(result["imbalance"], 0)
        self.assertAlmostEqual(result["spread_bps"], 200.0)

    def test_crossed_book_is_rejected(self):
        with self.assertRaises(ValueError):
            order_book_metrics([[101, 1]], [[100, 1]])

    def test_zero_depth_is_rejected(self):
        with self.assertRaises(ValueError):
            order_book_metrics([[99, 0]], [[101, 0]])

    def test_agg_trade_maker_flag_sets_aggressor_side(self):
        result = trade_flow_metrics([
            {"q": "2", "m": False},
            {"q": "1", "m": True},
        ])
        self.assertEqual(result["buy_volume"], 2.0)
        self.assertEqual(result["sell_volume"], 1.0)
        self.assertAlmostEqual(result["delta_ratio"], 1 / 3)

    def test_missing_maker_flag_is_rejected(self):
        with self.assertRaises(ValueError):
            trade_flow_metrics([{"q": "1"}])

    def test_profile_combines_book_and_trade_evidence(self):
        result = orderflow_profile({"imbalance": 0.5, "spread_bps": 2.0}, {"delta_ratio": 0.4})
        self.assertGreater(result["score"], 0)
        self.assertEqual(result["state"], "buy_pressure")


if __name__ == "__main__":
    unittest.main()
