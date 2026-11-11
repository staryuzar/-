import unittest

from bitcoinlab.scenarios import build_trade_levels


class ScenarioTests(unittest.TestCase):
    def test_buy_levels_are_atr_derived(self):
        result = build_trade_levels(side="BUY", entry=70000, atr_value=100, atr_stop_multiple=1.2, reward_risk=1.8)
        self.assertEqual(result["stop_loss"], 69880)
        self.assertEqual(result["take_profit"], 70216)

    def test_sell_levels_are_mirrored(self):
        result = build_trade_levels(side="SELL", entry=70000, atr_value=100)
        self.assertGreater(result["stop_loss"], 70000)
        self.assertLess(result["take_profit"], 70000)

    def test_broker_minimum_distance_is_respected(self):
        result = build_trade_levels(side="BUY", entry=70000, atr_value=10, broker_min_stop_distance=50)
        self.assertEqual(result["stop_distance"], 50)

    def test_invalid_atr_is_rejected(self):
        with self.assertRaises(ValueError):
            build_trade_levels(side="BUY", entry=70000, atr_value=0)

    def test_direction_is_required(self):
        with self.assertRaises(ValueError):
            build_trade_levels(side="HOLD", entry=70000, atr_value=100)


if __name__ == "__main__":
    unittest.main()
