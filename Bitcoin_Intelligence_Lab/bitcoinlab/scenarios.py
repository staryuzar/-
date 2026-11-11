from __future__ import annotations

import math


def build_trade_levels(
    *, side: str, entry: float, atr_value: float,
    atr_stop_multiple: float = 1.2, reward_risk: float = 1.8,
    broker_min_stop_distance: float = 0.0,
) -> dict:
    """Build transparent ATR-derived SL/TP levels around a live broker quote."""
    side = side.upper()
    if side not in {"BUY", "SELL"}:
        raise ValueError("side must be BUY or SELL")
    values = (entry, atr_value, atr_stop_multiple, reward_risk, broker_min_stop_distance)
    if any(not math.isfinite(float(value)) for value in values):
        raise ValueError("Scenario inputs must be finite.")
    if entry <= 0 or atr_value <= 0 or atr_stop_multiple <= 0 or reward_risk <= 0 or broker_min_stop_distance < 0:
        raise ValueError("Scenario price and distance inputs must be positive.")
    stop_distance = max(atr_value * atr_stop_multiple, broker_min_stop_distance)
    target_distance = stop_distance * reward_risk
    if side == "BUY":
        stop_loss, take_profit = entry - stop_distance, entry + target_distance
    else:
        stop_loss, take_profit = entry + stop_distance, entry - target_distance
    if stop_loss <= 0 or take_profit <= 0:
        raise ValueError("Calculated stop/target is outside valid positive price range.")
    return {
        "status": "ready", "side": side, "entry_reference": entry,
        "atr": atr_value, "atr_stop_multiple": atr_stop_multiple,
        "stop_distance": stop_distance, "reward_risk": reward_risk,
        "stop_loss": stop_loss, "take_profit": take_profit,
        "method": "ATR-based initial protection from the latest closed candle and live broker quote.",
    }
