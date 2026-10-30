from __future__ import annotations

import math


def calculate_position_size(
    *, equity: float, risk_fraction: float, entry: float, stop: float,
    contract_size: float, volume_min: float, volume_step: float, volume_max: float,
    estimated_cost_per_lot: float = 0.0, max_risk_fraction: float = 0.01,
) -> dict:
    """Theoretical lot sizing using broker-supplied contract specs; never executes."""
    nums = (equity, risk_fraction, entry, stop, contract_size, volume_min, volume_step, volume_max, estimated_cost_per_lot)
    if any(not math.isfinite(float(x)) for x in nums):
        raise ValueError("Risk inputs must be finite.")
    if equity <= 0 or not 0 < risk_fraction <= max_risk_fraction:
        raise ValueError("Equity or risk fraction is outside the permitted range.")
    if entry <= 0 or stop <= 0 or entry == stop:
        raise ValueError("Entry and stop must be positive and distinct.")
    if contract_size <= 0 or volume_min <= 0 or volume_step <= 0 or volume_max < volume_min or estimated_cost_per_lot < 0:
        raise ValueError("Invalid broker contract specifications.")
    risk_budget = equity * risk_fraction
    loss_per_lot = abs(entry - stop) * contract_size + estimated_cost_per_lot
    raw_lots = risk_budget / loss_per_lot
    if raw_lots < volume_min:
        return {
            "status": "blocked_minimum_volume_exceeds_budget",
            "risk_budget": risk_budget, "loss_per_lot": loss_per_lot, "volume_lots": 0.0,
        }
    steps = math.floor((min(raw_lots, volume_max) - volume_min) / volume_step + 1e-12)
    lots = volume_min + max(0, steps) * volume_step
    lots = min(lots, volume_max)
    estimated_loss = lots * loss_per_lot
    if estimated_loss > risk_budget + 1e-8:
        return {
            "status": "blocked_rounding_exceeds_budget",
            "risk_budget": risk_budget, "loss_per_lot": loss_per_lot, "volume_lots": 0.0,
        }
    return {
        "status": "calculated", "risk_budget": risk_budget, "loss_per_lot": loss_per_lot,
        "volume_lots": round(lots, 8), "estimated_loss": estimated_loss,
        "risk_fraction": risk_fraction,
    }
