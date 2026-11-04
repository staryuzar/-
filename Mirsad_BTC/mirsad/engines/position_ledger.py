from __future__ import annotations

import math
from collections import defaultdict
from typing import Any


def aggregate_position_cycles(deals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Aggregate raw MT5 deals by POSITION_ID without inventing floating PnL.

    A cycle is considered complete only when its first observed trade deal is
    an IN entry and its signed net volume returns to zero. Otherwise it is
    explicitly marked INCOMPLETE or OPEN_FROM_CAPTURED_ENTRY.
    """
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in deals:
        if not isinstance(row, dict):
            continue
        try:
            position_id = str(int(row.get("position_id", 0)))
            deal_type = int(row.get("deal_type", row.get("type", -1)))
            entry = int(row.get("deal_entry", row.get("entry", -1)))
            stamp = int(row.get("time_server_ms", 0))
            volume = float(row.get("volume", 0.0))
            cashflow = float(row.get("net_cashflow", 0.0))
            profit = float(row.get("profit", 0.0))
            commission = float(row.get("commission", 0.0))
            swap = float(row.get("swap", 0.0))
            fee = float(row.get("fee", 0.0))
        except (TypeError, ValueError, OverflowError):
            continue
        values = (volume, cashflow, profit, commission, swap, fee)
        if (
            int(position_id) <= 0 or stamp <= 0
            or deal_type not in (0, 1) or entry not in (0, 1, 2, 3)
            or any(not math.isfinite(value) for value in values)
            or volume < 0
        ):
            continue
        grouped[position_id].append({
            **row,
            "position_id": position_id,
            "deal_type": deal_type,
            "deal_entry": entry,
            "time_server_ms": stamp,
            "volume": volume,
            "net_cashflow": cashflow,
            "profit": profit,
            "commission": commission,
            "swap": swap,
            "fee": fee,
        })

    cycles: list[dict[str, Any]] = []
    for position_id, rows in grouped.items():
        rows.sort(key=lambda item: (item["time_server_ms"], str(item.get("deal_ticket", ""))))
        first_trade = rows[0]
        signed_volume = sum(
            row["volume"] if row["deal_type"] == 0 else -row["volume"]
            for row in rows
        )
        first_is_entry = first_trade["deal_entry"] == 0
        if not first_is_entry:
            state = "INCOMPLETE_HISTORY"
        elif abs(signed_volume) <= 1e-8:
            state = "CLOSED"
        else:
            state = "OPEN_FROM_CAPTURED_ENTRY"
        currency_values = {
            str(row.get("currency", "")).strip()
            for row in rows if str(row.get("currency", "")).strip()
        }
        currencies = sorted(currency_values)
        cycles.append({
            "position_id": position_id,
            "state": state,
            "direction": "LONG" if signed_volume > 1e-8 else "SHORT" if signed_volume < -1e-8 else "FLAT",
            "remaining_signed_volume": round(signed_volume, 8),
            "opened_volume": round(sum(row["volume"] for row in rows if row["deal_entry"] == 0), 8),
            "closed_deal_volume": round(sum(row["volume"] for row in rows if row["deal_entry"] in (1, 3)), 8),
            "reversal_deal_volume": round(sum(row["volume"] for row in rows if row["deal_entry"] == 2), 8),
            "deal_count": len(rows),
            "entry_count": sum(1 for row in rows if row["deal_entry"] == 0),
            "exit_count": sum(1 for row in rows if row["deal_entry"] in (1, 3)),
            "reversal_count": sum(1 for row in rows if row["deal_entry"] == 2),
            "first_time_server_ms": first_trade["time_server_ms"],
            "last_time_server_ms": rows[-1]["time_server_ms"],
            "realized_deal_profit": round(sum(row["profit"] for row in rows), 8),
            "commission": round(sum(row["commission"] for row in rows), 8),
            "swap": round(sum(row["swap"] for row in rows), 8),
            "fee": round(sum(row["fee"] for row in rows), 8),
            "net_deal_cashflow": round(sum(row["net_cashflow"] for row in rows), 8),
            "currency": currencies[0] if len(currencies) == 1 else "MIXED" if currencies else "UNKNOWN",
            "history_starts_with_entry": first_is_entry,
        })
    return sorted(cycles, key=lambda row: (row["last_time_server_ms"], row["position_id"]), reverse=True)


def build_position_management_history(
    deals: list[dict[str, Any]] | None,
    positions: list[dict[str, Any]] | None,
    *,
    expected_magic: int,
    history_status: str,
    truncated: bool,
    queried_at_utc_ms: int,
    now_ms: int,
    max_age_ms: int = 120_000,
) -> dict[str, Any]:
    """Return only complete, recent deal cycles for active Mirsad-owned positions."""
    try:
        magic, query_at, now = int(expected_magic), int(queried_at_utc_ms), int(now_ms)
        age = now - query_at
    except (TypeError, ValueError, OverflowError):
        magic = query_at = now = age = 0
    if (
        magic <= 0 or history_status != "READY" or truncated is not False
        or not isinstance(deals, list) or query_at <= 0
        or age < 0 or age > max_age_ms
    ):
        return {"status": "UNAVAILABLE", "reason": "Recent complete non-truncated MIR1 deal history is required.", "cycles": {}}

    active_ids: set[str] = set()
    for pos in positions if isinstance(positions, list) else []:
        if not isinstance(pos, dict):
            continue
        try:
            if int(pos.get("magic", -1)) != magic:
                continue
            position_id = str(int(pos.get("position_id", 0)))
        except (TypeError, ValueError, OverflowError):
            continue
        if int(position_id) > 0:
            active_ids.add(position_id)
    if not active_ids:
        return {"status": "READY", "reason": "No active Mirsad positions require partial management.", "cycles": {}, "queried_at_utc_ms": query_at, "history_age_ms": age}

    by_id = {
        str(row["position_id"]): row
        for row in aggregate_position_cycles(deals)
        if isinstance(row, dict) and row.get("position_id") is not None
    }
    missing = sorted(active_ids - set(by_id))
    selected = {key: by_id[key] for key in sorted(active_ids & set(by_id))}
    incomplete = sorted(key for key, row in selected.items() if row.get("state") != "OPEN_FROM_CAPTURED_ENTRY")
    if missing or incomplete:
        return {
            "status": "INCOMPLETE", "reason": "At least one active Mirsad position has no complete opening deal cycle.",
            "cycles": selected, "missing_position_ids": missing, "incomplete_position_ids": incomplete,
            "queried_at_utc_ms": query_at, "history_age_ms": age,
        }
    return {
        "status": "READY", "reason": "Every active Mirsad position is matched to a complete current deal cycle.",
        "cycles": selected, "queried_at_utc_ms": query_at, "history_age_ms": age,
    }


__all__ = ["aggregate_position_cycles", "build_position_management_history"]
