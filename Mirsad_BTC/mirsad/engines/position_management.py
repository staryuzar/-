from __future__ import annotations

import math
from typing import Any

BREAK_EVEN_TRIGGER_ATR = 1.5
TRAILING_ACTIVATION_ATR = 2.5
TRAILING_DISTANCE_ATR = 1.5
TRAILING_STEP_ATR = 0.25
PARTIAL_TAKE_PROFIT_TRIGGER_ATR = 1.5
PARTIAL_TAKE_PROFIT_FRACTION = 0.5


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


def plan_partial_take_profit(
    positions: list[dict[str, Any]],
    *,
    history: dict[str, Any],
    broker_symbol: str,
    bid: float,
    ask: float,
    atr: float,
    volume_min: float,
    volume_step: float,
    trigger_atr: float = PARTIAL_TAKE_PROFIT_TRIGGER_ATR,
    close_fraction: float = PARTIAL_TAKE_PROFIT_FRACTION,
) -> dict[str, Any]:
    """Plan one ledger-verified partial close; fail closed on any ambiguity."""
    def unavailable(reason: str) -> dict[str, Any]:
        return {"status": "NOT_REQUIRED", "reason": reason, "decision_eligible": False}

    if not isinstance(positions, list) or not positions:
        return unavailable("No Mirsad-owned open position is available.")
    if not isinstance(history, dict) or history.get("status") != "READY":
        return unavailable("A complete, current MT5 deal-history snapshot is required.")
    cycles = history.get("cycles")
    if not isinstance(cycles, dict):
        return unavailable("The position deal-cycle map is missing.")
    bid_v, ask_v = _finite_positive(bid), _finite_positive(ask)
    atr_v, min_v, step_v = (
        _finite_positive(atr), _finite_positive(volume_min), _finite_positive(volume_step)
    )
    try:
        trigger, fraction = float(trigger_atr), float(close_fraction)
    except (TypeError, ValueError, OverflowError):
        return unavailable("Partial-exit settings are invalid.")
    if (
        bid_v is None or ask_v is None or ask_v < bid_v
        or atr_v is None or min_v is None or step_v is None
        or not math.isfinite(trigger) or trigger <= 0
        or not math.isfinite(fraction) or not 0 < fraction < 1
        or not broker_symbol
    ):
        return unavailable("Valid broker prices, ATR and volume constraints are required.")

    candidates: list[dict[str, Any]] = []
    for pos in positions:
        if not isinstance(pos, dict) or str(pos.get("symbol", "")).upper() != broker_symbol.upper():
            continue
        side = str(pos.get("side", "")).upper()
        if side not in {"BUY", "SELL"}:
            continue
        try:
            ticket = int(pos.get("ticket", 0))
            position_id = str(int(pos.get("position_id", 0)))
            volume = float(pos.get("volume", 0))
            entry = float(pos.get("price_open", 0))
            target = float(pos.get("take_profit", 0))
        except (TypeError, ValueError, OverflowError):
            continue
        if (
            ticket <= 0 or int(position_id) <= 0
            or not all(math.isfinite(x) for x in (volume, entry, target))
            or volume <= 0 or entry <= 0 or target <= 0
        ):
            continue
        cycle = cycles.get(position_id)
        if not isinstance(cycle, dict) or (
            cycle.get("state") != "OPEN_FROM_CAPTURED_ENTRY"
            or cycle.get("history_starts_with_entry") is not True
        ):
            continue
        try:
            entry_count = int(cycle.get("entry_count", 0))
            exit_count = int(cycle.get("exit_count", 0))
            reversal_count = int(cycle.get("reversal_count", 0))
            ledger_remaining = float(cycle.get("remaining_signed_volume"))
            ledger_opened = float(cycle.get("opened_volume"))
        except (TypeError, ValueError, OverflowError):
            continue
        if entry_count != 1 or exit_count != 0 or reversal_count != 0:
            continue
        direction = "LONG" if side == "BUY" else "SHORT"
        signed_remaining = ledger_remaining if side == "BUY" else -ledger_remaining
        tolerance = max(1e-8, step_v * 0.51)
        if (
            cycle.get("direction") != direction
            or not math.isfinite(ledger_remaining) or not math.isfinite(ledger_opened)
            or abs(signed_remaining - volume) > tolerance
            or abs(ledger_opened - volume) > tolerance
        ):
            continue
        if side == "BUY":
            if target <= entry:
                continue
            favorable_move = bid_v - entry
        else:
            if target >= entry:
                continue
            favorable_move = entry - ask_v
        favorable_atr = favorable_move / atr_v
        if not math.isfinite(favorable_atr) or favorable_atr < trigger:
            continue
        close_volume = round(
            math.floor((volume * fraction + 1e-12) / step_v) * step_v, 8
        )
        remaining = round(volume - close_volume, 8)
        if (
            close_volume < min_v - 1e-9
            or remaining < min_v - 1e-9
            or close_volume > volume + 1e-9
        ):
            continue
        candidates.append({
            "ticket": ticket, "position_id": int(position_id), "symbol": broker_symbol,
            "side": side, "current_volume": volume, "close_volume": close_volume,
            "remaining_volume": remaining, "price_open": entry, "take_profit": target,
            "favorable_move_atr": round(favorable_atr, 4),
            "management_stage": "PARTIAL_TAKE_PROFIT", "decision_eligible": False,
        })
    if not candidates:
        return unavailable("No position qualifies for a first partial exit with reconciled deal history and live volume.")
    selected = sorted(candidates, key=lambda row: (-row["favorable_move_atr"], row["ticket"]))[0]
    return {
        **selected, "status": "READY", "action": "CLOSE",
        "reason": "Engine 4 proposes one 50% partial close after a 1.5 ATR favorable move; the remaining half retains its existing stop and take-profit.",
        "history_basis": "COMPLETE_MIR1_DEAL_CYCLE_WITH_ZERO_PRIOR_EXITS",
    }


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
