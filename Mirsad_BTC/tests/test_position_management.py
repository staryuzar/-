from __future__ import annotations

import unittest

from mirsad.engines.position_management import plan_atr_stop_update


def position(
    *,
    side: str = "BUY",
    entry: float = 100.0,
    stop: float = 90.0,
    target: float = 130.0,
    ticket: int = 10,
    symbol: str = "BTC",
) -> dict:
    return {
        "ticket": ticket, "symbol": symbol, "side": side, "volume": 0.10,
        "price_open": entry, "stop_loss": stop, "take_profit": target,
    }


class ATRPositionManagementTests(unittest.TestCase):
    def plan(self, positions, *, bid=116.0, ask=116.1, atr=4.0, **overrides):
        args = {
            "broker_symbol": "BTC", "bid": bid, "ask": ask, "atr": atr,
            "tick_size": 0.1, "point": 0.1, "digits": 1,
            "stops_level_points": 0, "freeze_level_points": 0,
        }
        args.update(overrides)
        return plan_atr_stop_update(positions, **args)

    def test_long_position_moves_to_break_even_after_15_atr(self):
        result = self.plan([position()], bid=106.1, ask=106.2, atr=4.0)
        self.assertEqual(result["status"], "READY")
        self.assertEqual(result["action"], "MODIFY")
        self.assertEqual(result["management_stage"], "BREAK_EVEN")
        self.assertEqual(result["stop_loss"], 100.0)
        self.assertEqual(result["take_profit"], 130.0)
        self.assertEqual(result["ticket"], 10)

    def test_short_position_moves_to_break_even_after_15_atr(self):
        result = self.plan(
            [position(side="SELL", entry=100.0, stop=110.0, target=70.0)],
            bid=93.9, ask=94.0, atr=4.0,
        )
        self.assertEqual(result["status"], "READY")
        self.assertEqual(result["management_stage"], "BREAK_EVEN")
        self.assertEqual(result["stop_loss"], 100.0)
        self.assertEqual(result["take_profit"], 70.0)

    def test_long_position_uses_atr_trailing_after_25_atr(self):
        result = self.plan([position()], bid=112.1, ask=112.2, atr=4.0)
        self.assertEqual(result["status"], "READY")
        self.assertEqual(result["management_stage"], "ATR_TRAILING")
        self.assertAlmostEqual(result["stop_loss"], 106.0)
        self.assertGreater(result["stop_loss"], 100.0)

    def test_short_position_uses_atr_trailing_after_25_atr(self):
        result = self.plan(
            [position(side="SELL", entry=100.0, stop=110.0, target=70.0)],
            bid=87.9, ask=88.0, atr=4.0,
        )
        self.assertEqual(result["status"], "READY")
        self.assertEqual(result["management_stage"], "ATR_TRAILING")
        self.assertAlmostEqual(result["stop_loss"], 94.0)
        self.assertLess(result["stop_loss"], 100.0)

    def test_does_not_manage_before_break_even_threshold(self):
        result = self.plan([position()], bid=105.9, ask=106.0, atr=4.0)
        self.assertEqual(result["status"], "NOT_REQUIRED")

    def test_never_loosens_existing_long_stop(self):
        result = self.plan([position(stop=108.0)], bid=112.1, ask=112.2, atr=4.0)
        self.assertEqual(result["status"], "NOT_REQUIRED")

    def test_never_loosens_existing_short_stop(self):
        result = self.plan(
            [position(side="SELL", entry=100.0, stop=92.0, target=70.0)],
            bid=87.9, ask=88.0, atr=4.0,
        )
        self.assertEqual(result["status"], "NOT_REQUIRED")

    def test_respects_larger_of_stops_and_freeze_levels(self):
        result = self.plan(
            [position()], bid=106.1, ask=106.2, atr=4.0,
            point=0.1, stops_level_points=20, freeze_level_points=80,
        )
        self.assertEqual(result["status"], "NOT_REQUIRED")

    def test_skips_other_symbols_and_invalid_positions(self):
        result = self.plan([
            position(symbol="ETH"),
            {"ticket": 0, "symbol": "BTC", "side": "BUY"},
        ])
        self.assertEqual(result["status"], "NOT_REQUIRED")

    def test_requires_finite_fresh_price_inputs(self):
        result = self.plan([position()], bid=float("nan"))
        self.assertEqual(result["status"], "NOT_REQUIRED")


if __name__ == "__main__":
    unittest.main()
