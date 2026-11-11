from __future__ import annotations

from typing import Any, Mapping, Sequence


def next_position_action(
    decision: Mapping[str, Any],
    positions: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """
    Convert the central board decision into one position-management instruction.

    A HOLD decision never closes an existing position. An opposite confirmed
    decision closes one opposing EA-managed ticket at a time. A new position is
    opened only when no EA-managed BTC position remains.
    """
    side = str(decision.get("action", "HOLD")).upper()
    if side not in {"BUY", "SELL"} or decision.get("blockers"):
        return {
            "action": "HOLD",
            "reason": "central_decision_is_not_executable",
            "side": side,
        }

    btc_positions = [
        row for row in positions
        if "BTC" in str(row.get("symbol", "")).upper()
        and int(row.get("ticket", 0)) > 0
    ]
    opposing = sorted(
        (row for row in btc_positions if str(row.get("type", "")).upper() != side),
        key=lambda row: int(row["ticket"]),
    )
    if opposing:
        ticket = int(opposing[0]["ticket"])
        return {
            "action": "CLOSE",
            "ticket": ticket,
            "reason": f"confirmed_opposite_decision_{side.lower()}",
            "remaining_opposing": len(opposing),
        }

    if btc_positions:
        return {
            "action": "HOLD",
            "reason": "managed_position_already_aligned",
            "side": side,
            "tickets": [int(row["ticket"]) for row in btc_positions],
        }

    return {
        "action": "OPEN",
        "side": side,
        "reason": "fresh_central_decision_and_no_managed_position",
    }
