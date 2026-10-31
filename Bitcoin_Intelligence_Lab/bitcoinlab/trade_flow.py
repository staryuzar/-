from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Mapping


def _positive(value: object, field: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{field} must be numeric.") from exc
    if not math.isfinite(number) or number <= 0:
        raise ValueError(f"{field} must be finite and positive.")
    return number


def _timestamp(value: object) -> int:
    try:
        timestamp = int(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("Trade timestamp must be a positive millisecond value.") from exc
    if timestamp <= 0:
        raise ValueError("Trade timestamp must be a positive millisecond value.")
    return timestamp


def _trade_event(
    *,
    venue: str,
    symbol: str,
    market_type: str,
    trade_id: str,
    event_time_ms: int,
    aggressor_side: str,
    price: float,
    base_quantity: float,
    trade_count: int = 1,
    source_event_type: str,
) -> dict[str, Any]:
    if aggressor_side not in {"BUY", "SELL"}:
        raise ValueError("Aggressor side must be BUY or SELL.")
    if not trade_id:
        raise ValueError("A stable source trade ID is required for deduplication.")
    if trade_count < 1:
        raise ValueError("Trade count must be positive.")
    event = {
        "event_key": f"{venue}:{symbol}:{trade_id}",
        "venue": venue,
        "symbol": symbol,
        "market_type": market_type,
        "event_time_ms": int(event_time_ms),
        "trade_id": str(trade_id),
        "aggressor_side": aggressor_side,
        "price": float(price),
        "base_quantity": float(base_quantity),
        "quantity_unit": "BTC",
        "notional_usd": float(price) * float(base_quantity),
        "notional_unit": "USD_approx_from_USDT_or_USD_quote",
        "trade_count": int(trade_count),
        "source_event_type": source_event_type,
    }
    return event


def normalize_binance_usdm_agg_trade(message: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize a Binance USDⓈ-M BTCUSDT aggregate trade; m identifies buyer-maker."""
    if message.get("e") != "aggTrade":
        raise ValueError("Not a Binance USDⓈ-M aggTrade event.")
    if str(message.get("s", "")).upper() != "BTCUSDT":
        raise ValueError("Only Binance BTCUSDT USDⓈ-M aggTrades are accepted.")
    price = _positive(message.get("p"), "Binance trade price")
    quantity = _positive(message.get("q"), "Binance base quantity")
    timestamp = _timestamp(message.get("T") or message.get("E"))
    buyer_is_maker = message.get("m")
    if not isinstance(buyer_is_maker, bool):
        raise ValueError("Binance buyer-maker flag must be boolean.")
    try:
        first_trade_id = int(message["f"])
        last_trade_id = int(message["l"])
        aggregate_id = int(message["a"])
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise ValueError("Binance aggregate trade IDs are invalid.") from exc
    if min(first_trade_id, last_trade_id, aggregate_id) < 0 or last_trade_id < first_trade_id:
        raise ValueError("Binance aggregate trade ID range is invalid.")
    return _trade_event(
        venue="binance_usdm",
        symbol="BTCUSDT",
        market_type="linear_perpetual",
        trade_id=str(aggregate_id),
        event_time_ms=timestamp,
        aggressor_side="SELL" if buyer_is_maker else "BUY",
        price=price,
        base_quantity=quantity,
        trade_count=max(1, last_trade_id - first_trade_id + 1),
        source_event_type="aggTrade",
    )


def normalize_bybit_public_trades(message: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Normalize Bybit V5 publicTrade.BTCUSDT; S is the taker/aggressor side."""
    if message.get("topic") != "publicTrade.BTCUSDT":
        raise ValueError("Not a Bybit BTCUSDT publicTrade message.")
    rows = message.get("data")
    if not isinstance(rows, list):
        raise ValueError("Bybit publicTrade data must be a list.")
    events: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Bybit publicTrade row must be an object.")
        if str(row.get("s", "")).upper() != "BTCUSDT":
            raise ValueError("Bybit publicTrade symbol mismatch.")
        side = str(row.get("S", "")).upper()
        if side not in {"BUY", "SELL"}:
            raise ValueError("Bybit publicTrade taker side is invalid.")
        price = _positive(row.get("p"), "Bybit trade price")
        quantity = _positive(row.get("v"), "Bybit trade base quantity")
        timestamp = _timestamp(row.get("T") or message.get("ts"))
        trade_id = str(row.get("i") or "")
        events.append(_trade_event(
            venue="bybit_linear",
            symbol="BTCUSDT",
            market_type="linear_perpetual",
            trade_id=trade_id,
            event_time_ms=timestamp,
            aggressor_side=side,
            price=price,
            base_quantity=quantity,
            trade_count=1,
            source_event_type="publicTrade",
        ))
    return events


def normalize_okx_spot_trades(message: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Normalize OKX public trades channel; spot sz is reported in base currency."""
    arg = message.get("arg")
    if not isinstance(arg, dict) or arg.get("channel") != "trades" or arg.get("instId") != "BTC-USDT":
        raise ValueError("Not an OKX BTC-USDT spot trades message.")
    rows = message.get("data")
    if not isinstance(rows, list):
        raise ValueError("OKX trades data must be a list.")
    events: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("OKX trade row must be an object.")
        if str(row.get("instId", "")).upper() != "BTC-USDT":
            raise ValueError("OKX trade instrument mismatch.")
        side = str(row.get("side", "")).upper()
        if side not in {"BUY", "SELL"}:
            raise ValueError("OKX taker side is invalid.")
        price = _positive(row.get("px"), "OKX trade price")
        quantity = _positive(row.get("sz"), "OKX spot base quantity")
        timestamp = _timestamp(row.get("ts"))
        trade_id = str(row.get("tradeId") or "")
        try:
            trade_count = int(row.get("count") or 1)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("OKX aggregate trade count is invalid.") from exc
        events.append(_trade_event(
            venue="okx_spot",
            symbol="BTCUSDT",
            market_type="spot",
            trade_id=trade_id,
            event_time_ms=timestamp,
            aggressor_side=side,
            price=price,
            base_quantity=quantity,
            trade_count=trade_count,
            source_event_type="trades",
        ))
    return events
