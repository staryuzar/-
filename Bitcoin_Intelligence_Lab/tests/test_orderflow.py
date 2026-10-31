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

    def test_profile_scores_executed_trade_delta_and_keeps_depth_as_context(self):
        result = orderflow_profile({"imbalance": 0.5, "spread_bps": 2.0}, {"delta_ratio": 0.4, "trade_count": 80})
        self.assertAlmostEqual(result["score"], 0.4)
        self.assertAlmostEqual(result["book_imbalance_context"], 0.5)
        self.assertEqual(result["directional_basis"], "executed_aggressor_trade_delta_only")
        self.assertEqual(result["state"], "buy_pressure")

    def test_cross_venue_book_depth_does_not_change_orderflow_vote(self):
        flow = {"delta_ratio": -0.35, "trade_count": 120}
        buy_book = orderflow_profile({"imbalance": 0.8, "spread_bps": 1.0}, flow)
        sell_book = orderflow_profile({"imbalance": -0.9, "spread_bps": 3.0}, flow)
        self.assertEqual(buy_book["score"], sell_book["score"])
        self.assertAlmostEqual(buy_book["score"], -0.35)

    def test_orderflow_can_score_from_trades_without_rest_depth(self):
        result = orderflow_profile(None, {"delta_ratio": 0.25, "trade_count": 40})
        self.assertEqual(result["status"], "ok")
        self.assertAlmostEqual(result["score"], 0.25)
        self.assertIsNone(result["book_imbalance_context"])


if __name__ == "__main__":
    unittest.main()
