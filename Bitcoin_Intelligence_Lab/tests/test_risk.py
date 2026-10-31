import unittest

from bitcoinlab.risk import calculate_position_size, calculate_position_size_from_tick_value


class RiskTests(unittest.TestCase):
    def base(self, **kwargs):
        data = dict(
            equity=10_000, risk_fraction=0.005, entry=70_000, stop=69_000,
            contract_size=1, volume_min=0.001, volume_step=0.001,
            volume_max=10, estimated_cost_per_lot=0,
        )
        data.update(kwargs)
        return calculate_position_size(**data)

    def test_size_is_rounded_down_to_step_and_within_budget(self):
        result = self.base()
        self.assertEqual(result["status"], "calculated")
        self.assertLessEqual(result["estimated_loss"], result["risk_budget"])
        self.assertAlmostEqual(result["volume_lots"], 0.05)

    def test_minimum_lot_above_budget_is_blocked(self):
        result = self.base(
            equity=1000, entry=100, stop=90,
            volume_min=1, volume_step=1, volume_max=100,
        )
        self.assertEqual(result["status"], "blocked_minimum_volume_exceeds_budget")
        self.assertEqual(result["volume_lots"], 0.0)

    def test_cost_is_included(self):
        result = self.base(estimated_cost_per_lot=50)
        self.assertLess(result["volume_lots"], 0.05)

    def test_default_risk_fraction_has_no_arbitrary_cap_but_optional_cap_can_be_set(self):
        result = self.base(risk_fraction=0.02)
        self.assertEqual(result["status"], "calculated")
        with self.assertRaises(ValueError):
            calculate_position_size(
                equity=10_000, risk_fraction=0.02, entry=70_000, stop=69_000,
                contract_size=1, volume_min=0.001, volume_step=0.001,
                volume_max=10, max_risk_fraction=0.01,
            )

    def test_tick_value_sizing_uses_account_currency_and_broker_volume_step(self):
        result = calculate_position_size_from_tick_value(
            equity=10_000,
            risk_fraction=0.0025,
            entry=70_000,
            stop=69_000,
            tick_size=0.01,
            tick_value_loss=0.01,
            volume_min=0.01,
            volume_step=0.01,
            volume_max=100,
            max_volume=0.10,
            max_risk_fraction=0.005,
        )
        self.assertEqual(result["status"], "calculated")
        self.assertEqual(result["sizing_method"], "broker_tick_value_loss")
        self.assertAlmostEqual(result["risk_budget"], 25)
        self.assertAlmostEqual(result["loss_per_lot"], 1000)
        self.assertEqual(result["volume_lots"], 0.02)
        self.assertLessEqual(result["estimated_loss"], result["risk_budget"])

    def test_tick_value_sizing_blocks_when_minimum_lot_exceeds_risk_budget(self):
        result = calculate_position_size_from_tick_value(
            equity=100,
            risk_fraction=0.0025,
            entry=70_000,
            stop=69_000,
            tick_size=0.01,
            tick_value_loss=0.01,
            volume_min=0.01,
            volume_step=0.01,
            volume_max=100,
        )
        self.assertEqual(result["status"], "blocked_minimum_volume_exceeds_budget")
        self.assertEqual(result["volume_lots"], 0.0)

    def test_tick_value_sizing_rejects_missing_or_invalid_broker_specs(self):
        with self.assertRaises(ValueError):
            calculate_position_size_from_tick_value(
                equity=10_000, risk_fraction=0.0025, entry=70_000, stop=69_000,
                tick_size=0, tick_value_loss=0.01, volume_min=0.01,
                volume_step=0.01, volume_max=100,
            )

    def test_bad_contract_specification_is_rejected(self):
        with self.assertRaises(ValueError):
            self.base(volume_step=0)


if __name__ == "__main__":
    unittest.main()
