from __future__ import annotations

import math


def calculate_position_size_from_tick_value(
    *,
    equity: float,
    risk_fraction: float,
    entry: float,
    stop: float,
    tick_size: float,
    tick_value_loss: float,
    volume_min: float,
    volume_step: float,
    volume_max: float,
    max_volume: float | None = None,
    estimated_cost_per_lot: float = 0.0,
    max_risk_fraction: float | None = None,
) -> dict:
    """Size volume using the connected broker's loss tick value in account currency.

    Unlike contract-size-only sizing, tick_value_loss incorporates the broker's
    symbol calculation and account-currency conversion. It is still an estimate:
    final execution and risk are rechecked by the EA with OrderCalcProfit.
    """
    values = (
        equity, risk_fraction, entry, stop, tick_size, tick_value_loss,
        volume_min, volume_step, volume_max, estimated_cost_per_lot,
    )
    if any(not math.isfinite(float(value)) for value in values):
        raise ValueError("Tick-value risk inputs must be finite.")
    if max_volume is not None and (
        not math.isfinite(float(max_volume)) or float(max_volume) <= 0
    ):
        raise ValueError("max_volume must be finite and positive.")
    if equity <= 0 or risk_fraction <= 0:
        raise ValueError("Equity and risk fraction must be positive.")
    if max_risk_fraction is not None and (
        not math.isfinite(max_risk_fraction)
        or max_risk_fraction <= 0
        or risk_fraction > max_risk_fraction
    ):
        raise ValueError("Risk fraction exceeds the optional configured cap.")
    if entry <= 0 or stop <= 0 or entry == stop:
        raise ValueError("Entry and stop must be positive and distinct.")
    if (
        tick_size <= 0 or tick_value_loss <= 0
        or volume_min <= 0 or volume_step <= 0 or volume_max < volume_min
        or estimated_cost_per_lot < 0
    ):
        raise ValueError("Invalid broker tick-value or volume specifications.")

    loss_per_lot = abs(entry - stop) / tick_size * tick_value_loss + estimated_cost_per_lot
    if not math.isfinite(loss_per_lot) or loss_per_lot <= 0:
        raise ValueError("Calculated loss per lot is invalid.")
    risk_budget = equity * risk_fraction
    raw_lots = risk_budget / loss_per_lot
    allowed_max = min(volume_max, max_volume) if max_volume is not None else volume_max
    if raw_lots < volume_min or allowed_max < volume_min:
        return {
            "status": "blocked_minimum_volume_exceeds_budget",
            "risk_budget": risk_budget,
            "loss_per_lot": loss_per_lot,
            "volume_lots": 0.0,
            "sizing_method": "broker_tick_value_loss",
        }
    candidate = min(raw_lots, allowed_max)
    steps = math.floor((candidate - volume_min) / volume_step + 1e-12)
    lots = min(volume_min + max(0, steps) * volume_step, allowed_max)
    estimated_loss = lots * loss_per_lot
    if estimated_loss > risk_budget + 1e-8:
        return {
            "status": "blocked_rounding_exceeds_budget",
            "risk_budget": risk_budget,
            "loss_per_lot": loss_per_lot,
            "volume_lots": 0.0,
            "sizing_method": "broker_tick_value_loss",
        }
    return {
        "status": "calculated",
        "risk_budget": risk_budget,
        "loss_per_lot": loss_per_lot,
        "volume_lots": round(lots, 8),
        "estimated_loss": estimated_loss,
        "risk_fraction": risk_fraction,
        "sizing_method": "broker_tick_value_loss",
        "volume_cap": allowed_max,
    }


def calculate_position_size(
    *, equity: float, risk_fraction: float, entry: float, stop: float,
    contract_size: float, volume_min: float, volume_step: float, volume_max: float,
    estimated_cost_per_lot: float = 0.0, max_risk_fraction: float | None = None,
) -> dict:
    """Theoretical lot sizing using broker-supplied contract specs; never executes."""
    nums = (equity, risk_fraction, entry, stop, contract_size, volume_min, volume_step, volume_max, estimated_cost_per_lot)
    if any(not math.isfinite(float(x)) for x in nums):
        raise ValueError("Risk inputs must be finite.")
    if equity <= 0 or not math.isfinite(risk_fraction) or risk_fraction <= 0:
        raise ValueError("Equity and risk fraction must be positive.")
    if max_risk_fraction is not None and (
        not math.isfinite(max_risk_fraction) or max_risk_fraction <= 0 or risk_fraction > max_risk_fraction
    ):
        raise ValueError("Risk fraction exceeds the optional configured cap.")
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
