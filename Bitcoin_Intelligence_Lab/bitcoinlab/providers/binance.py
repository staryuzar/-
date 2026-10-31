from __future__ import annotations

from datetime import datetime, timezone
import math
from urllib.parse import urlencode

from ..models import Bar
from ..quality import utc_now_ms
from .http import get_json


SPOT_BASE = "https://data-api.binance.vision"
FUTURES_BASE = "https://fapi.binance.com"
_ALLOWED_INTERVALS = {"1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "8h", "12h", "1d"}


def _url(base: str, path: str, params: dict) -> str:
    return f"{base}{path}?{urlencode(params)}"


def fetch_spot_klines(symbol: str = "BTCUSDT", interval: str = "1m", limit: int = 200, *, now_ms: int | None = None) -> list[Bar]:
    symbol = symbol.upper().strip()
    if not symbol.isalnum() or interval not in _ALLOWED_INTERVALS or not 60 <= limit <= 1000:
        raise ValueError("Invalid Binance symbol, interval or candle limit.")
    payload = get_json(_url(SPOT_BASE, "/api/v3/klines", {"symbol": symbol, "interval": interval, "limit": limit}))
    if not isinstance(payload, list):
        raise ValueError("Unexpected Binance kline payload.")
    now = utc_now_ms() if now_ms is None else int(now_ms)
    result = []
    for row in payload:
        if not isinstance(row, list) or len(row) < 7:
            raise ValueError("Malformed Binance kline row.")
        close_time = int(row[6])
        if close_time >= now:
            continue  # The currently forming candle is deliberately excluded.
        bar = Bar(
            open_time_ms=int(row[0]), open=float(row[1]), high=float(row[2]),
            low=float(row[3]), close=float(row[4]), volume=float(row[5]),
            close_time_ms=close_time, is_closed=True,
        )
        result.append(bar)
    if len(result) < 60:
        raise ValueError("Fewer than 60 completed Binance candles were returned.")
    return result


def fetch_spot_depth(symbol: str = "BTCUSDT", limit: int = 100) -> dict:
    if not symbol.isalnum() or limit not in {5, 10, 20, 50, 100, 500, 1000, 5000}:
        raise ValueError("Invalid Binance order-book request.")
    payload = get_json(_url(SPOT_BASE, "/api/v3/depth", {"symbol": symbol.upper(), "limit": limit}))
    if not isinstance(payload, dict) or not isinstance(payload.get("bids"), list) or not isinstance(payload.get("asks"), list):
        raise ValueError("Malformed Binance depth response.")
    return {"fetched_at_ms": utc_now_ms(), "snapshot_id": payload.get("lastUpdateId"), "bids": payload["bids"], "asks": payload["asks"]}


def fetch_spot_agg_trades(symbol: str = "BTCUSDT", limit: int = 500) -> list[dict]:
    if not symbol.isalnum() or not 1 <= limit <= 1000:
        raise ValueError("Invalid aggregate-trades request.")
    payload = get_json(_url(SPOT_BASE, "/api/v3/aggTrades", {"symbol": symbol.upper(), "limit": limit}))
    if not isinstance(payload, list) or any(not isinstance(x, dict) for x in payload):
        raise ValueError("Malformed Binance aggregate trades.")
    return payload


def fetch_funding_history(symbol: str = "BTCUSDT", limit: int = 20) -> list[dict]:
    if not symbol.isalnum() or not 1 <= limit <= 1000:
        raise ValueError("Invalid funding request.")
    payload = get_json(_url(FUTURES_BASE, "/fapi/v1/fundingRate", {"symbol": symbol.upper(), "limit": limit}))
    if not isinstance(payload, list) or any(not isinstance(x, dict) for x in payload):
        raise ValueError("Malformed funding response.")
    return payload


def fetch_open_interest(symbol: str = "BTCUSDT") -> dict:
    if not symbol.isalnum():
        raise ValueError("Invalid futures symbol.")
    payload = get_json(_url(FUTURES_BASE, "/fapi/v1/openInterest", {"symbol": symbol.upper()}))
    if not isinstance(payload, dict) or "openInterest" not in payload or "time" not in payload:
        raise ValueError("Malformed open-interest response.")
    return payload


def fetch_open_interest_history(symbol: str = "BTCUSDT", period: str = "5m", limit: int = 6) -> list[dict]:
    if not symbol.isalnum() or period not in {"5m", "15m", "30m", "1h", "2h", "4h", "6h", "12h", "1d"} or not 2 <= limit <= 500:
        raise ValueError("Invalid open-interest history request.")
    payload = get_json(_url(FUTURES_BASE, "/futures/data/openInterestHist", {
        "symbol": symbol.upper(), "period": period, "limit": limit,
    }))
    if not isinstance(payload, list) or any(not isinstance(x, dict) for x in payload):
        raise ValueError("Malformed open-interest history response.")
    return payload


def normalize_derivatives(
    funding_rows: list[dict], open_interest: dict, taker_rows: list[dict], *,
    prior_open_interest: float | None = None,
    open_interest_history: list[dict] | None = None,
) -> dict:
    funding_row = max(funding_rows, key=lambda row: int(row.get("fundingTime", 0))) if funding_rows else None
    taker_row = max(taker_rows, key=lambda row: int(row.get("timestamp", 0))) if taker_rows else None
    funding = float(funding_row["fundingRate"]) if funding_row else None

    history = sorted(open_interest_history or [], key=lambda row: int(row.get("timestamp", 0)))
    oi_change = None
    if len(history) >= 2:
        current_oi = float(history[-1]["sumOpenInterest"])
        previous_oi = float(history[-2]["sumOpenInterest"])
        if not math.isfinite(current_oi) or not math.isfinite(previous_oi) or current_oi <= 0 or previous_oi <= 0:
            raise ValueError("Invalid open-interest history values.")
        oi_change = (current_oi - previous_oi) / previous_oi * 100.0
        oi = current_oi
        oi_timestamp = int(history[-1]["timestamp"])
    else:
        oi = float(open_interest["openInterest"])
        oi_timestamp = int(open_interest["time"])
        if prior_open_interest is not None:
            old = float(prior_open_interest)
            if old <= 0 or not math.isfinite(old):
                raise ValueError("Invalid prior open interest.")
            oi_change = (oi - old) / old * 100.0

    if not math.isfinite(oi) or oi < 0:
        raise ValueError("Invalid open interest.")
    taker = float(taker_row["buySellRatio"]) if taker_row else None
    taker_timestamp = int(taker_row["timestamp"]) if taker_row else 0
    if funding is not None and not math.isfinite(funding):
        raise ValueError("Invalid funding rate.")
    if taker is not None and (not math.isfinite(taker) or taker <= 0):
        raise ValueError("Invalid taker ratio.")
    if taker is None or taker_timestamp <= 0:
        raise ValueError("Taker ratio or its timestamp is unavailable.")

    # The oldest required fast input controls the freshness gate.
    observed_at = min(oi_timestamp, taker_timestamp)
    return {
        "funding_rate": funding, "funding_time_ms": int(funding_row.get("fundingTime", 0)) if funding_row else None,
        "open_interest": oi, "open_interest_change_pct": oi_change,
        "open_interest_observed_at_ms": oi_timestamp,
        "taker_buy_sell_ratio": taker, "taker_observed_at_ms": taker_timestamp,
        "observed_at_ms": observed_at,
        "observed_at_utc": datetime.fromtimestamp(observed_at / 1000, tz=timezone.utc).isoformat(),
    }


def fetch_usdm_premium_index(symbol: str = "BTCUSDT") -> dict:
    """Return USDⓈ-M mark/index prices and current last funding rate."""
    if not symbol.isalnum():
        raise ValueError("Invalid USDⓈ-M futures symbol.")
    payload = get_json(_url(FUTURES_BASE, "/fapi/v1/premiumIndex", {"symbol": symbol.upper()}))
    required = {"symbol", "markPrice", "indexPrice", "lastFundingRate", "time"}
    if not isinstance(payload, dict) or not required.issubset(payload):
        raise ValueError("Malformed USDⓈ-M premium-index response.")
    if payload["symbol"] != symbol.upper():
        raise ValueError("USDⓈ-M premium-index symbol mismatch.")
    return payload


def fetch_usdm_book_ticker(symbol: str = "BTCUSDT") -> dict:
    """Return the current USDⓈ-M perpetual best bid/ask."""
    if not symbol.isalnum():
        raise ValueError("Invalid USDⓈ-M futures symbol.")
    payload = get_json(_url(FUTURES_BASE, "/fapi/v1/ticker/bookTicker", {"symbol": symbol.upper()}))
    if not isinstance(payload, dict) or payload.get("symbol") != symbol.upper():
        raise ValueError("Malformed USDⓈ-M book-ticker response.")
    if "bidPrice" not in payload or "askPrice" not in payload:
        raise ValueError("USDⓈ-M book ticker lacks a best bid or ask.")
    return payload


def fetch_spot_book_ticker(symbol: str = "BTCUSDT") -> dict:
    """Return current spot best bid/ask without downloading a full depth snapshot."""
    if not symbol.isalnum():
        raise ValueError("Invalid Binance spot symbol.")
    payload = get_json(_url(SPOT_BASE, "/api/v3/ticker/bookTicker", {"symbol": symbol.upper()}))
    if not isinstance(payload, dict) or payload.get("symbol") != symbol.upper():
        raise ValueError("Malformed Binance spot book-ticker response.")
    if "bidPrice" not in payload or "askPrice" not in payload:
        raise ValueError("Binance spot book ticker lacks a best bid or ask.")
    return payload
