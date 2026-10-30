import unittest

from bitcoinlab.position_manager import next_position_action


class PositionManagerTests(unittest.TestCase):
    def test_fresh_direction_opens_when_no_managed_position_exists(self):
        self.assertEqual(
            next_position_action({"action": "BUY", "blockers": []}, []),
            {
                "action": "OPEN",
                "side": "BUY",
                "reason": "fresh_central_decision_and_no_managed_position",
            },
        )

    def test_same_direction_position_is_kept_without_adding_another(self):
        result = next_position_action(
            {"action": "BUY", "blockers": []},
            [{"ticket": 12, "symbol": "BTCUSDm", "type": "BUY"}],
        )
        self.assertEqual(result["action"], "HOLD")
        self.assertIn(12, result["tickets"])

    def test_opposite_confirmed_decision_closes_one_ticket_first(self):
        result = next_position_action(
            {"action": "SELL", "blockers": []},
            [
                {"ticket": 20, "symbol": "BTCUSD", "type": "BUY"},
                {"ticket": 10, "symbol": "BTCUSD", "type": "BUY"},
            ],
        )
        self.assertEqual(result["action"], "CLOSE")
        self.assertEqual(result["ticket"], 10)

    def test_hold_never_closes_open_position(self):
        result = next_position_action(
            {"action": "HOLD", "blockers": ["insufficient_directional_confluence"]},
            [{"ticket": 12, "symbol": "BTCUSD", "type": "SELL"}],
        )
        self.assertEqual(result["action"], "HOLD")

    def test_blocked_direction_never_creates_order(self):
        result = next_position_action(
            {"action": "BUY", "blockers": ["spot_not_fresh"]}, []
        )
        self.assertEqual(result["action"], "HOLD")

    def test_non_bitcoin_positions_are_ignored(self):
        result = next_position_action(
            {"action": "BUY", "blockers": []},
            [{"ticket": 44, "symbol": "XAUUSD", "type": "SELL"}],
        )
        self.assertEqual(result["action"], "OPEN")


if __name__ == "__main__":
    unittest.main()
