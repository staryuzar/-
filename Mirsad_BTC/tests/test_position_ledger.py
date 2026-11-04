from __future__ import annotations

import unittest

from mirsad.engines.position_ledger import aggregate_position_cycles


def deal(
    ticket: str,
    position_id: str,
    time_ms: int,
    deal_type: int,
    entry: int,
    volume: float,
    *,
    profit: float = 0.0,
    commission: float = 0.0,
    swap: float = 0.0,
    fee: float = 0.0,
) -> dict:
    return {
        "deal_ticket": ticket,
        "position_id": position_id,
        "time_server_ms": time_ms,
        "deal_type": deal_type,
        "deal_entry": entry,
        "volume": volume,
        "price": 65000.0,
        "profit": profit,
        "commission": commission,
        "swap": swap,
        "fee": fee,
        "net_cashflow": profit + commission + swap + fee,
        "currency": "USD",
    }


class PositionLedgerTests(unittest.TestCase):
    def test_closed_long_cycle_sums_realized_profit_and_all_charges(self) -> None:
        rows = [
            deal("1", "501", 1000, 0, 0, 0.02, commission=-0.10),
            deal("2", "501", 2000, 1, 1, 0.02, profit=8.0, commission=-0.10, swap=-0.02, fee=-0.01),
        ]
        result = aggregate_position_cycles(rows)
        self.assertEqual(len(result), 1)
        cycle = result[0]
        self.assertEqual(cycle["state"], "CLOSED")
        self.assertEqual(cycle["direction"], "FLAT")
        self.assertEqual(cycle["remaining_signed_volume"], 0.0)
        self.assertEqual(cycle["deal_count"], 2)
        self.assertAlmostEqual(cycle["realized_deal_profit"], 8.0)
        self.assertAlmostEqual(cycle["net_deal_cashflow"], 7.77)
        self.assertEqual(cycle["currency"], "USD")

    def test_partial_exit_is_reported_as_open_without_fabricating_floating_pnl(self) -> None:
        rows = [
            deal("1", "502", 1000, 0, 0, 0.05, commission=-0.10),
            deal("2", "502", 2000, 1, 1, 0.02, profit=3.0, commission=-0.05),
        ]
        cycle = aggregate_position_cycles(rows)[0]
        self.assertEqual(cycle["state"], "OPEN_FROM_CAPTURED_ENTRY")
        self.assertEqual(cycle["direction"], "LONG")
        self.assertAlmostEqual(cycle["remaining_signed_volume"], 0.03)
        self.assertAlmostEqual(cycle["realized_deal_profit"], 3.0)
        self.assertAlmostEqual(cycle["net_deal_cashflow"], 2.85)

    def test_closed_short_cycle_uses_signed_deal_volume(self) -> None:
        rows = [
            deal("1", "503", 1000, 1, 0, 0.03),
            deal("2", "503", 2000, 0, 1, 0.03, profit=2.5),
        ]
        cycle = aggregate_position_cycles(rows)[0]
        self.assertEqual(cycle["state"], "CLOSED")
        self.assertEqual(cycle["direction"], "FLAT")
        self.assertEqual(cycle["remaining_signed_volume"], 0.0)

    def test_history_without_initial_entry_is_never_claimed_as_complete(self) -> None:
        rows = [deal("2", "504", 2000, 1, 1, 0.02, profit=1.0)]
        cycle = aggregate_position_cycles(rows)[0]
        self.assertEqual(cycle["state"], "INCOMPLETE_HISTORY")
        self.assertFalse(cycle["history_starts_with_entry"])

    def test_invalid_and_non_position_deals_are_ignored(self) -> None:
        rows = [
            deal("1", "0", 1000, 0, 0, 0.02),
            deal("2", "505", 0, 0, 0, 0.02),
            deal("3", "506", 1000, 2, 0, 0.02),
            deal("4", "507", 1000, 0, 0, -0.01),
        ]
        self.assertEqual(aggregate_position_cycles(rows), [])


if __name__ == "__main__":
    unittest.main()
