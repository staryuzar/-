from __future__ import annotations

import math
from typing import Any

BREAK_EVEN_TRIGGER_ATR = 1.5
TRAILING_ACTIVATION_ATR = 2.5
TRAILING_DISTANCE_ATR = 1.5
TRAILING_STEP_ATR = 0.25


def _finite_positive(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def _tick_price(value: float, tick_size: float, digits: int, side: str) -> float:
    units = value / tick_size
    if side == "BUY":
        # Round a long protective stop down: never make it closer to market
        # than the unrounded plan.
        ticks = math.floor(units + 1e-10)
    else:
        # Round a short protective stop up for the symmetric reason.
        ticks = math.ceil(units - 1e-10)
    return round(ticks * tick_size, max(0, min(10, int(digits))))


def plan_atr_stop_update(
    positions: list[dict[str, Any]],
    *,
    broker_symbol: str,
    bid: float,
    ask: float,
    atr: float,
    tick_size: float,
    point: float,
    digits: int,
    stops_level_points: int = 0,
    freeze_level_points: int = 0,
) -> dict[str, Any]:
    """Plan one tighten-only break-even/ATR-trailing SL update.

    The function is intentionally stateless and emits at most one position
    modification per runtime cycle. It never loosens an existing stop, changes
    take-profit, closes volume, or authorizes execution.
    """
    def unavailable(reason: str) -> dict[str, Any]:
        return {"status": "NOT_REQUIRED", "reason": reason, "decision_eligible": False}

    if not isinstance(positions, list) or not positions:
        return unavailable("No Mirsad-owned open position is available for management.")
    bid_value = _finite_positive(bid)
    ask_value = _finite_positive(ask)
    atr_value = _finite_positive(atr)
    tick_value = _finite_positive(tick_size)
    point_value = _finite_positive(point)
    if (
        bid_value is None or ask_value is None or ask_value < bid_value
        or atr_value is None or tick_value is None or point_value is None
    ):
        return unavailable("Fresh bid/ask, positive ATR, tick size and point are required.")
    if not broker_symbol:
        return unavailable("Broker symbol is missing.")

    try:
        minimum_gap = (
            max(0, int(stops_level_points), int(freeze_level_points)) * point_value
            + tick_value
        )
        precision = max(0, min(10, int(digits)))
    except (TypeError, ValueError, OverflowError):
        return unavailable("Broker stop/freeze levels or price precision are invalid.")
    if not math.isfinite(minimum_gap):
        return unavailable("Broker minimum stop distance is non-finite.")

    candidates: list[dict[str, Any]] = []
    for position in positions:
        if not isinstance(position, dict):
            continue
        if str(position.get("symbol", "")).upper() != broker_symbol.upper():
            continue
        side = str(position.get("side", "")).upper()
        if side not in {"BUY", "SELL"}:
            continue
        entry = _finite_positive(position.get("price_open"))
        volume = _finite_positive(position.get("volume"))
        try:
            ticket = int(position.get("ticket", 0))
            current_sl = float(position.get("stop_loss", 0) or 0)
            current_tp = float(position.get("take_profit", 0) or 0)
        except (TypeError, ValueError, OverflowError):
            continue
        if (
            ticket <= 0 or entry is None or volume is None
            or not math.isfinite(current_sl) or current_sl < 0
            or not math.isfinite(current_tp) or current_tp < 0
        ):
            continue

        market_price = bid_value if side == "BUY" else ask_value
        favorable_move = market_price - entry if side == "BUY" else entry - market_price
        if not math.isfinite(favorable_move) or favorable_move < BREAK_EVEN_TRIGGER_ATR * atr_value:
            continue

        stage = "BREAK_EVEN"
        if favorable_move >= TRAILING_ACTIVATION_ATR * atr_value:
            stage = "ATR_TRAILING"
            raw_stop = (
                max(entry, bid_value - TRAILING_DISTANCE_ATR * atr_value)
                if side == "BUY"
                else min(entry, ask_value + TRAILING_DISTANCE_ATR * atr_value)
            )
        else:
            raw_stop = entry

        desired_sl = _tick_price(raw_stop, tick_value, precision, side)
        step = max(tick_value, atr_value * TRAILING_STEP_ATR)
        if side == "BUY":
            if current_sl > 0 and desired_sl <= current_sl + step:
                continue
            if desired_sl >= bid_value or bid_value - desired_sl < minimum_gap:
                continue
        else:
            if current_sl > 0 and desired_sl >= current_sl - step:
                continue
            if desired_sl <= ask_value or desired_sl - ask_value < minimum_gap:
                continue

        candidates.append({
            "ticket": ticket,
            "symbol": broker_symbol,
            "side": side,
            "volume": volume,
            "price_open": entry,
            "current_stop_loss": current_sl,
            "stop_loss": desired_sl,
            "take_profit": current_tp,
            "management_stage": stage,
            "favorable_move_atr": round(favorable_move / atr_value, 4),
            "minimum_stop_distance": round(minimum_gap, precision),
            "decision_eligible": False,
        })

    if not candidates:
        return unavailable(
            "No position has crossed the management threshold with a broker-valid, tighten-only stop improvement."
        )

    # Prefer the strongest favorable move; break ties by ticket for deterministic output.
    selected = sorted(
        candidates,
        key=lambda item: (-item["favorable_move_atr"], item["ticket"]),
    )[0]
    return {
        **selected,
        "status": "READY",
        "action": "MODIFY",
        "reason": (
            "Engine 4 proposes a broker-validated, tighten-only protective-stop update. "
            "The existing take-profit and position volume remain unchanged."
        ),
        "break_even_basis": "ENTRY_PRICE_BEFORE_COMMISSION_AND_SWAP",
    }


__all__ = [
    "BREAK_EVEN_TRIGGER_ATR",
    "TRAILING_ACTIVATION_ATR",
    "TRAILING_DISTANCE_ATR",
    "TRAILING_STEP_ATR",
    "plan_atr_stop_update",
]
