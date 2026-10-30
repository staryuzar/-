import unittest

from bitcoinlab.derivatives import derivatives_profile


class DerivativesTests(unittest.TestCase):
    def test_taker_buy_pressure_is_bullish_when_not_crowded(self):
        result = derivatives_profile(
            funding_rate=0.0001, open_interest_change_pct=3.0,
            taker_buy_sell_ratio=1.2, global_long_short_ratio=1.1,
        )
        self.assertEqual(result["state"], "bullish")
        self.assertEqual(result["open_interest_interpretation"], "rising")

    def test_extreme_positive_funding_is_crowding_penalty_not_sell_vote(self):
        result = derivatives_profile(
            funding_rate=0.001, open_interest_change_pct=4.0,
            taker_buy_sell_ratio=1.0,
        )
        self.assertEqual(result["crowding"], "long_crowded")
        self.assertLess(result["score"], 0)

    def test_oi_alone_does_not_create_direction(self):
        result = derivatives_profile(
            funding_rate=0.0, open_interest_change_pct=12.0,
            taker_buy_sell_ratio=1.0,
        )
        self.assertAlmostEqual(result["score"], 0.0)

    def test_negative_funding_flags_short_crowding(self):
        result = derivatives_profile(
            funding_rate=-0.001, open_interest_change_pct=-2.0,
            taker_buy_sell_ratio=1.0,
        )
        self.assertEqual(result["crowding"], "short_crowded")
        self.assertGreater(result["score"], 0)

    def test_missing_taker_ratio_is_incomplete(self):
        self.assertEqual(derivatives_profile(
            funding_rate=0.0, open_interest_change_pct=None, taker_buy_sell_ratio=None,
        )["status"], "incomplete")

    def test_nonfinite_input_is_rejected(self):
        with self.assertRaises(ValueError):
            derivatives_profile(funding_rate=float("nan"), open_interest_change_pct=None, taker_buy_sell_ratio=1.0)


if __name__ == "__main__":
    unittest.main()
