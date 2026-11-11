from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Mapping


def _number(value: object, field: str, *, allow_zero: bool = False) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{field} must be numeric.") from exc
    if not math.isfinite(result) or result < 0 or (result == 0 and not allow_zero):
        raise ValueError(f"{field} must be finite and positive.")
    return result


def _timestamp(value: object, field: str) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{field} must be a positive millisecond timestamp.") from exc
    if result <= 0:
        raise ValueError(f"{field} must be a positive millisecond timestamp.")
    return result


def _event_key(event: Mapping[str, Any]) -> str:
    stable = {
        key: event.get(key)
        for key in (
            "venue", "symbol", "market_type", "event_time_ms", "liquidated_side",
            "order_side", "raw_size", "quantity_unit", "reference_price",
            "reference_price_kind", "notional_usd",
        )
    }
    raw = json.dumps(stable, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def normalize_binance_force_order(message: Mapping[str, Any]) -> dict[str, Any]:
    """
    Normalize a Binance USDⓈ-M forceOrder event.

    z is cumulative executed quantity and ap is average fill price. Only
    filled quantity is used for USD notional; original q and limit p are not
    substituted for actual filled quantity/average execution price.
    """
    if message.get("e") != "forceOrder":
        raise ValueError("Not a Binance forceOrder event.")
    order = message.get("o")
    if not isinstance(order, dict):
        raise ValueError("Binance forceOrder payload is missing order data.")
    symbol = str(order.get("s", "")).upper()
    if symbol != "BTCUSDT":
        raise ValueError("Only Binance BTCUSDT USDⓈ-M liquidations are accepted.")
    side = str(order.get("S", "")).upper()
    if side not in {"BUY", "SELL"}:
        raise ValueError("Invalid Binance liquidation order side.")
    status = str(order.get("X", "")).upper()
    if status != "FILLED":
        raise ValueError("Binance forceOrder snapshot is not a completed fill.")
    quantity = _number(order.get("z"), "cumulative executed quantity")
    average_price = _number(order.get("ap"), "average fill price")
    event_time = _timestamp(order.get("T") or message.get("E"), "trade time")
    event = {
        "venue": "binance_usdm",
        "symbol": symbol,
        "market_type": "USDT-M perpetual",
        "event_time_ms": event_time,
        "liquidated_side": "LONG" if side == "SELL" else "SHORT",
        "order_side": side,
        "raw_size": quantity,
        "quantity_unit": "BTC",
        "reference_price": average_price,
        "reference_price_kind": "average_fill_price",
        "notional_usd": quantity * average_price,
        "source_event_type": "forceOrder",
    }
    event["event_key"] = _event_key(event)
    return event


def normalize_bybit_liquidation(message: Mapping[str, Any]) -> list[dict[str, Any]]:
    """
    Normalize Bybit allLiquidation.BTCUSDT data.

    Bybit documents S=Buy as a liquidated long position and S=Sell as a
    liquidated short position. p is bankruptcy price, not execution price.
    The reported size unit is kept venue-specific and not converted to USD.
    """
    if message.get("topic") != "allLiquidation.BTCUSDT":
        raise ValueError("Not a Bybit BTCUSDT allLiquidation message.")
    rows = message.get("data")
    if not isinstance(rows, list):
        raise ValueError("Bybit liquidation data must be a list.")
    result: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Bybit liquidation row must be an object.")
        symbol = str(row.get("s", "")).upper()
        side = str(row.get("S", "")).title()
        if symbol != "BTCUSDT" or side not in {"Buy", "Sell"}:
            raise ValueError("Invalid Bybit liquidation symbol or side.")
        quantity = _number(row.get("v"), "Bybit executed size")
        bankruptcy_price = _number(row.get("p"), "Bybit bankruptcy price")
        event_time = _timestamp(row.get("T") or message.get("ts"), "Bybit liquidation time")
        event = {
            "venue": "bybit_linear",
            "symbol": symbol,
            "market_type": "linear perpetual",
            "event_time_ms": event_time,
            "liquidated_side": "LONG" if side == "Buy" else "SHORT",
            "order_side": side.upper(),
            "raw_size": quantity,
            "quantity_unit": "venue_reported_contract_units",
            "reference_price": bankruptcy_price,
            "reference_price_kind": "bankruptcy_price",
            "notional_usd": None,
            "source_event_type": "allLiquidation",
        }
        event["event_key"] = _event_key(event)
        result.append(event)
    return result


def normalize_okx_liquidation(message: Mapping[str, Any]) -> list[dict[str, Any]]:
    """
    Normalize the public OKX liquidation-orders channel for BTC-USDT swaps.

    OKX sz is a contract quantity and bkPx is the liquidation/bankruptcy mark
    price. Contract multipliers are intentionally not guessed, so USD
    notional stays unavailable until instrument metadata is applied.
    """
    arg = message.get("arg")
    if not isinstance(arg, dict) or arg.get("channel") != "liquidation-orders":
        raise ValueError("Not an OKX liquidation-orders event.")
    rows = message.get("data")
    if not isinstance(rows, list):
        raise ValueError("OKX liquidation data must be a list.")
    result: list[dict[str, Any]] = []
    for item in rows:
        if not isinstance(item, dict):
            raise ValueError("OKX liquidation batch row must be an object.")
        instrument = str(item.get("instId", "")).upper()
        if instrument != "BTC-USDT-SWAP":
            continue
        details = item.get("details")
        if not isinstance(details, list):
            raise ValueError("OKX liquidation details must be a list.")
        for detail in details:
            if not isinstance(detail, dict):
                raise ValueError("OKX liquidation detail must be an object.")
            side = str(detail.get("side", "")).lower()
            pos_side = str(detail.get("posSide", "")).lower()
            if side not in {"buy", "sell"}:
                raise ValueError("Invalid OKX liquidation order side.")
            if pos_side in {"long", "short"}:
                liquidated_side = pos_side.upper()
            elif pos_side == "net":
                liquidated_side = "LONG" if side == "sell" else "SHORT"
            else:
                raise ValueError("Invalid OKX liquidation position side.")
            quantity = _number(detail.get("sz"), "OKX liquidation contract size")
            bankruptcy_price = _number(detail.get("bkPx"), "OKX bankruptcy price")
            event_time = _timestamp(detail.get("ts"), "OKX liquidation time")
            event = {
                "venue": "okx_swap",
                "symbol": "BTC-USDT-SWAP",
                "market_type": "USDT swap",
                "event_time_ms": event_time,
                "liquidated_side": liquidated_side,
                "order_side": side.upper(),
                "raw_size": quantity,
                "quantity_unit": "contracts",
                "reference_price": bankruptcy_price,
                "reference_price_kind": "bankruptcy_price",
                "notional_usd": None,
                "source_event_type": "liquidation-orders",
            }
            event["event_key"] = _event_key(event)
            result.append(event)
    return result


def summarize_liquidations(events: list[Mapping[str, Any]]) -> dict[str, Any]:
    """Summarize events by venue, side and native quantity units without false cross-venue totals."""
    groups: dict[tuple[str, str, str], dict[str, Any]] = {}
    for event in events:
        venue = str(event["venue"])
        side = str(event["liquidated_side"])
        unit = str(event["quantity_unit"])
        key = (venue, side, unit)
        group = groups.setdefault(key, {
            "venue": venue,
            "liquidated_side": side,
            "quantity_unit": unit,
            "event_count": 0,
            "total_native_size": 0.0,
            "notional_usd": 0.0,
            "priced_notional_events": 0,
        })
        group["event_count"] += 1
        group["total_native_size"] += float(event["raw_size"])
        if event.get("notional_usd") is not None:
            group["notional_usd"] += float(event["notional_usd"])
            group["priced_notional_events"] += 1
    results = []
    for group in groups.values():
        group["total_native_size"] = round(group["total_native_size"], 8)
        group["notional_usd"] = round(group["notional_usd"], 2) if group["priced_notional_events"] else None
        results.append(group)
    results.sort(key=lambda row: (row["venue"], row["liquidated_side"]))
    return {
        "status": "ok" if events else "empty",
        "event_count": len(events),
        "groups": results,
        "limitations": [
            "Liquidation feeds are venue-specific samples, not a consolidated market-wide total.",
            "Bybit bankruptcy price and OKX bkPx are not execution prices.",
            "OKX size is contracts and Bybit size is kept in venue-reported units; USD notional is not inferred.",
            "Binance forceOrder stream is throttled to the latest event per symbol within each 1000 ms window.",
        ],
    }
