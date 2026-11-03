from __future__ import annotations

import json
import statistics
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from ..config import PROVIDERS, SYMBOL

USER_AGENT = "MirsadBTC/0.2 (+public-market-data; no-order-endpoints)"
TIMEFRAMES = ("1m", "5m", "15m", "1h", "4h", "1d")
BYBIT_INTERVALS = {"1m": "1", "5m": "5", "15m": "15", "1h": "60", "4h": "240", "1d": "D"}
OKX_INTERVALS = {"1m": "1m", "5m": "5m", "15m": "15m", "1h": "1H", "4h": "4H", "1d": "1Dutc"}

def _get_json(base: str, path: str, params: dict[str, Any]) -> tuple[Any, float]:
    url = base.rstrip("/") + path + "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    started = time.monotonic()
    with urllib.request.urlopen(request, timeout=9) as response:
        if response.status != 200:
            raise RuntimeError(f"HTTP {response.status}")
        payload = json.loads(response.read().decode("utf-8"))
    return payload, (time.monotonic() - started) * 1000

def _num(value: Any) -> float:
    number = float(value)
    if not (number > 0 and number < float("inf")):
        raise ValueError("Non-finite or non-positive market value")
    return number

def _candle_rows(rows: list[Any], *, source: str, timeframe: str) -> list[dict[str, Any]]:
    now_ms = int(time.time() * 1000)
    durations = {"1m": 60_000, "5m": 300_000, "15m": 900_000,
                 "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}
    result: list[dict[str, Any]] = []
    for row in rows:
        if source == "binance":
            opened, open_, high, low, close, volume, closed_at = row[:7]
            is_closed = int(closed_at) < now_ms
        elif source == "bybit":
            opened, open_, high, low, close, volume = row[:6]
            is_closed = int(opened) + durations[timeframe] <= now_ms
        else:
            opened, open_, high, low, close, volume = row[:6]
            is_closed = str(row[8]) == "1"
        candle = {
            "open_time_ms": int(opened), "open": _num(open_), "high": _num(high),
            "low": _num(low), "close": _num(close), "volume": float(volume),
            "closed": bool(is_closed),
        }
        if candle["high"] < max(candle["open"], candle["close"], candle["low"]):
            raise ValueError("Invalid candle OHLC high")
        if candle["low"] > min(candle["open"], candle["close"], candle["high"]):
            raise ValueError("Invalid candle OHLC low")
        result.append(candle)
    result.sort(key=lambda item: item["open_time_ms"])
    return result

def _book(bids_raw: list[Any], asks_raw: list[Any]) -> dict[str, Any]:
    bids = [[_num(p), float(q)] for p, q, *_ in bids_raw]
    asks = [[_num(p), float(q)] for p, q, *_ in asks_raw]
    bid_qty = sum(q for _, q in bids)
    ask_qty = sum(q for _, q in asks)
    total = bid_qty + ask_qty
    return {
        "bids": bids, "asks": asks,
        "imbalance": (bid_qty - ask_qty) / total if total > 0 else None,
    }

def _orderflow(trades: list[dict[str, Any]]) -> dict[str, Any]:
    buy_qty = sum(t["quantity"] for t in trades if t["taker_side"] == "BUY")
    sell_qty = sum(t["quantity"] for t in trades if t["taker_side"] == "SELL")
    total = buy_qty + sell_qty
    return {
        "trade_count": len(trades), "taker_buy_quantity": buy_qty,
        "taker_sell_quantity": sell_qty,
        "signed_quantity_delta": buy_qty - sell_qty,
        "taker_buy_ratio": buy_qty / total if total else None,
        "unit": "BTC",
        "scope": "recent public trades returned by venue; not a full historical CVD",
    }

def _binance(base: str) -> dict[str, Any]:
    ticker, latency = _get_json(base, "/api/v3/ticker/bookTicker", {"symbol": SYMBOL})
    candles_by_tf: dict[str, list[dict[str, Any]]] = {}
    for timeframe in TIMEFRAMES:
        raw, _ = _get_json(base, "/api/v3/klines", {
            "symbol": SYMBOL, "interval": timeframe, "limit": 120})
        candles_by_tf[timeframe] = _candle_rows(raw, source="binance", timeframe=timeframe)
    depth, _ = _get_json(base, "/api/v3/depth", {"symbol": SYMBOL, "limit": 50})
    trades_raw, _ = _get_json(base, "/api/v3/aggTrades", {"symbol": SYMBOL, "limit": 100})
    trades = [{
        "id": str(t["a"]), "time_ms": int(t["T"]), "price": _num(t["p"]),
        "quantity": float(t["q"]), "taker_side": "SELL" if t.get("m") else "BUY",
    } for t in trades_raw]
    return {
        "price": (_num(ticker["bidPrice"]) + _num(ticker["askPrice"])) / 2,
        "bid": _num(ticker["bidPrice"]), "ask": _num(ticker["askPrice"]),
        "candles_by_tf": candles_by_tf, "candles": candles_by_tf["1m"],
        "orderbook": _book(depth.get("bids", []), depth.get("asks", [])),
        "trades": trades, "orderflow": _orderflow(trades), "latency_ms": latency,
    }

def _bybit(base: str) -> dict[str, Any]:
    ticker, latency = _get_json(base, "/v5/market/tickers", {"category": "spot", "symbol": SYMBOL})
    if ticker.get("retCode") != 0:
        raise RuntimeError(f"Bybit ticker retCode={ticker.get('retCode')}")
    rows = ticker.get("result", {}).get("list", [])
    if not rows:
        raise RuntimeError(f"Bybit ticker returned no {SYMBOL} row")
    row = rows[0]
    candles_by_tf: dict[str, list[dict[str, Any]]] = {}
    for timeframe, interval in BYBIT_INTERVALS.items():
        raw, _ = _get_json(base, "/v5/market/kline", {
            "category": "spot", "symbol": SYMBOL, "interval": interval, "limit": 120})
        if raw.get("retCode") != 0:
            raise RuntimeError(f"Bybit {timeframe} kline retCode={raw.get('retCode')}")
        candles_by_tf[timeframe] = _candle_rows(
            list(reversed(raw.get("result", {}).get("list", []))),
            source="bybit", timeframe=timeframe)
    book, _ = _get_json(base, "/v5/market/orderbook", {
        "category": "spot", "symbol": SYMBOL, "limit": 50})
    if book.get("retCode") != 0:
        raise RuntimeError(f"Bybit orderbook retCode={book.get('retCode')}")
    trades_payload, _ = _get_json(base, "/v5/market/recent-trade", {
        "category": "spot", "symbol": SYMBOL, "limit": 60})
    if trades_payload.get("retCode") != 0:
        raise RuntimeError(f"Bybit trades retCode={trades_payload.get('retCode')}")
    trades = [{
        "id": str(t.get("execId", t.get("time"))), "time_ms": int(t["time"]),
        "price": _num(t["price"]), "quantity": float(t["size"]),
        "taker_side": str(t.get("side", "")).upper(),
    } for t in trades_payload.get("result", {}).get("list", [])]
    result = book.get("result", {})
    return {
        "price": _num(row["lastPrice"]), "bid": _num(row["bid1Price"]),
        "ask": _num(row["ask1Price"]),
        "candles_by_tf": candles_by_tf, "candles": candles_by_tf["1m"],
        "orderbook": _book(result.get("b", []), result.get("a", [])),
        "trades": trades, "orderflow": _orderflow(trades), "latency_ms": latency,
    }

def _okx(base: str) -> dict[str, Any]:
    instrument = {"BTCUSDT": "BTC-USDT", "BTCUSDC": "BTC-USDC"}.get(SYMBOL)
    if not instrument:
        raise ValueError(f"Unsupported OKX spot instrument for configured symbol {SYMBOL}")
    ticker, latency = _get_json(base, "/api/v5/market/ticker", {"instId": instrument})
    if ticker.get("code") != "0" or not ticker.get("data"):
        raise RuntimeError(f"OKX ticker code={ticker.get('code')}")
    row = ticker["data"][0]
    candles_by_tf: dict[str, list[dict[str, Any]]] = {}
    for timeframe, bar in OKX_INTERVALS.items():
        raw, _ = _get_json(base, "/api/v5/market/candles", {
            "instId": instrument, "bar": bar, "limit": 120})
        if raw.get("code") != "0":
            raise RuntimeError(f"OKX {timeframe} candles code={raw.get('code')}")
        candles_by_tf[timeframe] = _candle_rows(
            list(reversed(raw.get("data", []))), source="okx", timeframe=timeframe)
    book_payload, _ = _get_json(base, "/api/v5/market/books", {"instId": instrument, "sz": 50})
    if book_payload.get("code") != "0" or not book_payload.get("data"):
        raise RuntimeError(f"OKX orderbook code={book_payload.get('code')}")
    trades_payload, _ = _get_json(base, "/api/v5/market/trades", {"instId": instrument, "limit": 100})
    if trades_payload.get("code") != "0":
        raise RuntimeError(f"OKX trades code={trades_payload.get('code')}")
    trades = [{
        "id": str(t["tradeId"]), "time_ms": int(t["ts"]), "price": _num(t["px"]),
        "quantity": float(t["sz"]), "taker_side": str(t.get("side", "")).upper(),
    } for t in trades_payload.get("data", [])]
    order = book_payload["data"][0]
    return {
        "price": _num(row["last"]), "bid": _num(row["bidPx"]), "ask": _num(row["askPx"]),
        "candles_by_tf": candles_by_tf, "candles": candles_by_tf["1m"],
        "orderbook": _book(order.get("bids", []), order.get("asks", [])),
        "trades": trades, "orderflow": _orderflow(trades), "latency_ms": latency,
    }

class MarketEngine:
    """Reads public spot market data only; no exchange order endpoints are present."""
    def collect(self) -> dict[str, Any]:
        captured = int(time.time() * 1000)
        fetchers = {
            "Binance Spot": lambda: _binance(PROVIDERS["Binance Spot"]),
            "Bybit Spot": lambda: _bybit(PROVIDERS["Bybit Spot"]),
            "OKX Spot": lambda: _okx(PROVIDERS["OKX Spot"]),
        }
        venues: dict[str, Any] = {}
        with ThreadPoolExecutor(max_workers=3) as pool:
            pending = {pool.submit(fn): name for name, fn in fetchers.items()}
            for future in as_completed(pending):
                name = pending[future]
                try:
                    data = future.result()
                    data.update({"status": "LIVE", "error": None})
                except Exception as exc:
                    data = {"status": "OFFLINE", "error": f"{type(exc).__name__}: {exc}",
                            "candles": [], "candles_by_tf": {}, "trades": [],
                            "orderbook": None, "orderflow": None, "latency_ms": None}
                venues[name] = data
        healthy = [(name, row) for name, row in venues.items() if row.get("status") == "LIVE"]
        prices = [row["price"] for _, row in healthy]
        price = statistics.median(prices) if prices else None
        primary = next((name for name in ("Binance Spot", "Bybit Spot", "OKX Spot")
                        if venues.get(name, {}).get("status") == "LIVE"), None)
        market_status = "LIVE" if len(healthy) >= 2 else ("PARTIAL" if healthy else "OFFLINE")
        return {
            "captured_at_ms": captured, "symbol": SYMBOL, "price": price,
            "primary_venue": primary, "venue_count": len(healthy),
            "status": market_status, "timeframes": list(TIMEFRAMES), "venues": venues,
        }
