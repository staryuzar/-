from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
import math


def _level(level: Sequence[object]) -> tuple[float, float]:
    if len(level) < 2:
        raise ValueError("Order-book level must contain price and quantity.")
    price, quantity = float(level[0]), float(level[1])
    if not math.isfinite(price) or not math.isfinite(quantity) or price <= 0 or quantity < 0:
        raise ValueError("Invalid order-book level.")
    return price, quantity


def order_book_metrics(bids: Sequence[Sequence[object]], asks: Sequence[Sequence[object]], *, levels: int = 20) -> dict:
    if isinstance(levels, bool) or not isinstance(levels, int) or levels < 1:
        raise ValueError("levels must be a positive integer")
    if not bids or not asks:
        raise ValueError("Both sides of the order book are required.")
    bid_levels = [_level(x) for x in bids[:levels]]
    ask_levels = [_level(x) for x in asks[:levels]]
    best_bid = max(x[0] for x in bid_levels)
    best_ask = min(x[0] for x in ask_levels)
    if best_ask <= best_bid:
        raise ValueError("Crossed or locked order book.")
    bid_notional = sum(price * qty for price, qty in bid_levels)
    ask_notional = sum(price * qty for price, qty in ask_levels)
    total = bid_notional + ask_notional
    if total <= 0:
        raise ValueError("Order book contains no executable depth.")
    mid = (best_bid + best_ask) / 2.0
    return {
        "best_bid": best_bid, "best_ask": best_ask, "mid": mid,
        "spread_bps": (best_ask - best_bid) / mid * 10000.0,
        "bid_notional": bid_notional, "ask_notional": ask_notional,
        "imbalance": (bid_notional - ask_notional) / total,
        "levels_used": min(len(bid_levels), len(ask_levels)),
    }


def trade_flow_metrics(trades: Iterable[Mapping[str, object]]) -> dict:
    buy_volume = sell_volume = 0.0
    count = 0
    for trade in trades:
        qty = trade.get("q", trade.get("qty", trade.get("quantity")))
        quantity = float(qty)
        if not math.isfinite(quantity) or quantity < 0:
            raise ValueError("Trade quantity must be finite and non-negative.")
        if quantity == 0:
            continue
        # Binance aggTrade m=true means buyer was maker; aggressive side was SELL.
        buyer_is_maker = trade.get("m")
        if not isinstance(buyer_is_maker, bool):
            raise ValueError("Aggregate trade is missing the buyer-maker flag.")
        if buyer_is_maker:
            sell_volume += quantity
        else:
            buy_volume += quantity
        count += 1
    total = buy_volume + sell_volume
    return {
        "buy_volume": buy_volume, "sell_volume": sell_volume,
        "delta": buy_volume - sell_volume,
        "delta_ratio": (buy_volume - sell_volume) / total if total else 0.0,
        "trade_count": count,
    }


def orderflow_profile(book: Mapping[str, object], flow: Mapping[str, object]) -> dict:
    imbalance = float(book["imbalance"])
    delta = float(flow["delta_ratio"])
    if not -1 <= imbalance <= 1 or not -1 <= delta <= 1:
        raise ValueError("Order-flow ratios must be within [-1, 1].")
    score = max(-1.0, min(1.0, 0.55 * imbalance + 0.45 * delta))
    return {
        "status": "ok", "score": score, "imbalance": imbalance,
        "delta_ratio": delta, "spread_bps": float(book["spread_bps"]),
        "state": "buy_pressure" if score >= 0.15 else ("sell_pressure" if score <= -0.15 else "balanced"),
    }
