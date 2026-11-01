from __future__ import annotations

import json
import statistics
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from ..config import PROVIDERS, SYMBOL

USER_AGENT = "MirsadBTC/0.1 (+public-market-data; no-order-endpoints)"

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

def _binance(base: str) -> dict[str, Any]:
    book, latency = _get_json(base, "/api/v3/ticker/bookTicker", {"symbol": SYMBOL})
    raw_candles, _ = _get_json(base, "/api/v3/klines", {"symbol": SYMBOL, "interval": "1m", "limit": 120})
    depth, _ = _get_json(base, "/api/v3/depth", {"symbol": SYMBOL, "limit": 50})
    trades, _ = _get_json(base, "/api/v3/aggTrades", {"symbol": SYMBOL, "limit": 100})
    candles = [{
        "open_time_ms": int(row[0]), "open": float(row[1]), "high": float(row[2]),
        "low": float(row[3]), "close": float(row[4]), "volume": float(row[5]),
        "closed": int(row[6]) < int(time.time() * 1000),
    } for row in raw_candles]
    bids = [[float(p), float(q)] for p, q in depth.get("bids", [])]
    asks = [[float(p), float(q)] for p, q in depth.get("asks", [])]
    bid_qty = sum(q for _, q in bids)
    ask_qty = sum(q for _, q in asks)
    trades_norm = [{
        "id": str(t["a"]), "time_ms": int(t["T"]), "price": float(t["p"]),
        "quantity": float(t["q"]), "taker_side": "SELL" if t.get("m") else "BUY",
    } for t in trades]
    return {
        "price": (_num(book["bidPrice"]) + _num(book["askPrice"])) / 2,
        "bid": _num(book["bidPrice"]), "ask": _num(book["askPrice"]),
        "candles": candles, "orderbook": {
            "bids": bids, "asks": asks,
            "imbalance": (bid_qty - ask_qty) / (bid_qty + ask_qty) if bid_qty + ask_qty else None,
        },
        "trades": trades_norm, "latency_ms": latency,
    }

def _bybit(base: str) -> dict[str, Any]:
    ticker, latency = _get_json(base, "/v5/market/tickers", {"category": "spot", "symbol": SYMBOL})
    result = ticker.get("result", {}).get("list", [])
    if not result:
        raise RuntimeError(f"Bybit ticker returned no {SYMBOL} row")
    row = result[0]
    raw_candles, _ = _get_json(base, "/v5/market/kline", {
        "category": "spot", "symbol": SYMBOL, "interval": "1", "limit": 120})
    book, _ = _get_json(base, "/v5/market/orderbook", {
        "category": "spot", "symbol": SYMBOL, "limit": 50})
    trades, _ = _get_json(base, "/v5/market/recent-trade", {
        "category": "spot", "symbol": SYMBOL, "limit": 60})
    if ticker.get("retCode") != 0 or raw_candles.get("retCode") != 0:
        raise RuntimeError("Bybit API returned a non-zero retCode")
    candles = [{
        "open_time_ms": int(x[0]), "open": float(x[1]), "high": float(x[2]),
        "low": float(x[3]), "close": float(x[4]), "volume": float(x[5]),
        "closed": int(x[0]) + 60000 < int(time.time() * 1000),
    } for x in reversed(raw_candles.get("result", {}).get("list", []))]
    bids = [[float(p), float(q)] for p, q in book.get("result", {}).get("b", [])]
    asks = [[float(p), float(q)] for p, q in book.get("result", {}).get("a", [])]
    bq, aq = sum(q for _, q in bids), sum(q for _, q in asks)
    trades_norm = [{
        "id": str(t.get("execId", t.get("time"))), "time_ms": int(t["time"]),
        "price": float(t["price"]), "quantity": float(t["size"]),
        "taker_side": str(t.get("side", "")).upper(),
    } for t in trades.get("result", {}).get("list", [])]
    return {
        "price": _num(row["lastPrice"]), "bid": _num(row["bid1Price"]),
        "ask": _num(row["ask1Price"]), "candles": candles,
        "orderbook": {"bids": bids, "asks": asks,
                      "imbalance": (bq - aq) / (bq + aq) if bq + aq else None},
        "trades": trades_norm, "latency_ms": latency,
    }

def _okx(base: str) -> dict[str, Any]:
    ticker, latency = _get_json(base, "/api/v5/market/ticker", {"instId": "BTC-USDT"})
    raw_candles, _ = _get_json(base, "/api/v5/market/candles", {
        "instId": "BTC-USDT", "bar": "1m", "limit": 120})
    book, _ = _get_json(base, "/api/v5/market/books", {"instId": "BTC-USDT", "sz": 50})
    trades, _ = _get_json(base, "/api/v5/market/trades", {"instId": "BTC-USDT", "limit": 100})
    if ticker.get("code") != "0" or not ticker.get("data"):
        raise RuntimeError("OKX ticker response was not successful")
    row = ticker["data"][0]
    candles = [{
        "open_time_ms": int(x[0]), "open": float(x[1]), "high": float(x[2]),
        "low": float(x[3]), "close": float(x[4]), "volume": float(x[5]),
        "closed": str(x[8]) == "1",
    } for x in reversed(raw_candles.get("data", []))]
    order = book.get("data", [{}])[0]
    bids = [[float(p), float(q)] for p, q, *_ in order.get("bids", [])]
    asks = [[float(p), float(q)] for p, q, *_ in order.get("asks", [])]
    bq, aq = sum(q for _, q in bids), sum(q for _, q in asks)
    trades_norm = [{
        "id": str(t["tradeId"]), "time_ms": int(t["ts"]), "price": float(t["px"]),
        "quantity": float(t["sz"]), "taker_side": str(t.get("side", "")).upper(),
    } for t in trades.get("data", [])]
    return {
        "price": _num(row["last"]), "bid": _num(row["bidPx"]),
        "ask": _num(row["askPx"]), "candles": candles,
        "orderbook": {"bids": bids, "asks": asks,
                      "imbalance": (bq - aq) / (bq + aq) if bq + aq else None},
        "trades": trades_norm, "latency_ms": latency,
    }

class MarketEngine:
    """Reads public spot market data only; there are no exchange order functions."""
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
                            "candles": [], "trades": [], "orderbook": None, "latency_ms": None}
                venues[name] = data

        healthy = [(name, row) for name, row in venues.items() if row.get("status") == "LIVE"]
        prices = [row["price"] for _, row in healthy]
        price = statistics.median(prices) if prices else None
        primary = next((name for name in ("Binance Spot", "Bybit Spot", "OKX Spot")
                        if venues.get(name, {}).get("status") == "LIVE"), None)
        freshness = "LIVE" if len(healthy) >= 2 else ("PARTIAL" if healthy else "OFFLINE")
        return {
            "captured_at_ms": captured, "symbol": SYMBOL, "price": price,
            "primary_venue": primary, "venue_count": len(healthy),
            "status": freshness, "venues": venues,
        }
