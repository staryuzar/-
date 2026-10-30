import unittest

from bitcoinlab.risk import calculate_position_size


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

    def test_risk_over_cap_is_rejected(self):
        with self.assertRaises(ValueError):
            self.base(risk_fraction=0.02)

    def test_bad_contract_specification_is_rejected(self):
        with self.assertRaises(ValueError):
            self.base(volume_step=0)


if __name__ == "__main__":
    unittest.main()
