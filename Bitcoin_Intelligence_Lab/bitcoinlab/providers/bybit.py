from __future__ import annotations

from urllib.parse import urlencode
import math

from ..quality import freshness, utc_now_ms
from .http import get_json


BASE = "https://api.bybit.com"
_ALLOWED_INTERVALS = {"5min", "15min", "30min", "1h", "4h", "1d"}


def _result(payload: object, label: str) -> dict:
    if not isinstance(payload, dict):
        raise ValueError(f"Bybit {label} response is not an object.")
    if payload.get("retCode") != 0:
        raise ValueError(
            f"Bybit {label} error retCode={payload.get('retCode')}: "
            f"{str(payload.get('retMsg', 'unknown error'))[:180]}"
        )
    result = payload.get("result")
    if not isinstance(result, dict):
        raise ValueError(f"Bybit {label} result is malformed.")
    return result


def _request(path: str, params: dict[str, object]) -> dict:
    return get_json(f"{BASE}{path}?{urlencode(params)}")


def fetch_derivatives_snapshot(
    symbol: str = "BTCUSDT",
    *,
    interval_time: str = "5min",
    trade_limit: int = 500,
) -> dict:
    """
    Fetch read-only Bybit linear-perpetual context.

    Taker buy/sell is reconstructed from public trade sides; OI change is
    measured across two exchange-provided intervals. Funding is contextual,
    not treated as a contrarian directional signal.
    """
    symbol = symbol.upper().strip()
    if not symbol.isalnum() or not symbol.startswith("BTC"):
        raise ValueError("Bybit fallback accepts a BTC quote symbol only.")
    if interval_time not in _ALLOWED_INTERVALS or not 1 <= trade_limit <= 1000:
        raise ValueError("Invalid Bybit derivatives interval or trade limit.")

    oi_result = _result(
        _request("/v5/market/open-interest", {
            "category": "linear", "symbol": symbol,
            "intervalTime": interval_time, "limit": 2,
        }),
        "open-interest",
    )
    oi_rows = oi_result.get("list")
    if not isinstance(oi_rows, list) or len(oi_rows) < 2:
        raise ValueError("Bybit returned fewer than two open-interest observations.")

    oi_points = sorted(
        oi_rows,
        key=lambda row: int(row.get("timestamp", 0)) if isinstance(row, dict) else 0,
    )
    if any(not isinstance(row, dict) for row in oi_points):
        raise ValueError("Bybit open-interest rows are malformed.")
    previous_oi = float(oi_points[-2]["openInterest"])
    current_oi = float(oi_points[-1]["openInterest"])
    oi_timestamp = int(oi_points[-1]["timestamp"])
    if (
        not math.isfinite(previous_oi) or not math.isfinite(current_oi)
        or previous_oi <= 0 or current_oi <= 0 or oi_timestamp <= 0
    ):
        raise ValueError("Bybit open-interest values are invalid.")
    oi_change_pct = (current_oi - previous_oi) / previous_oi * 100.0

    funding_result = _result(
        _request("/v5/market/funding/history", {
            "category": "linear", "symbol": symbol, "limit": 1,
        }),
        "funding-history",
    )
    funding_rows = funding_result.get("list", [])
    if not isinstance(funding_rows, list):
        raise ValueError("Bybit funding rows are malformed.")
    latest_funding = max(
        (row for row in funding_rows if isinstance(row, dict)),
        key=lambda row: int(row.get("fundingRateTimestamp", 0)),
        default=None,
    )
    funding_rate = float(latest_funding["fundingRate"]) if latest_funding else None
    if funding_rate is not None and not math.isfinite(funding_rate):
        raise ValueError("Bybit funding rate is not finite.")
    funding_timestamp = (
        int(latest_funding.get("fundingRateTimestamp", 0))
        if latest_funding else None
    )

    trade_result = _result(
        _request("/v5/market/recent-trade", {
            "category": "linear", "symbol": symbol, "limit": trade_limit,
        }),
        "recent-trades",
    )
    trade_rows = trade_result.get("list")
    if not isinstance(trade_rows, list) or not trade_rows:
        raise ValueError("Bybit returned no public derivative trades.")
    buy_volume = sell_volume = 0.0
    normalized_trades = []
    latest_trade_timestamp = 0
    for row in trade_rows:
        if not isinstance(row, dict) or str(row.get("side", "")).title() not in {"Buy", "Sell"}:
            raise ValueError("Bybit public trade row has no valid taker side.")
        quantity = float(row["size"])
        timestamp = int(row["time"])
        if not math.isfinite(quantity) or quantity <= 0 or timestamp <= 0:
            raise ValueError("Bybit public trade has invalid size or timestamp.")
        side = str(row["side"]).title()
        if side == "Buy":
            buy_volume += quantity
        else:
            sell_volume += quantity
        latest_trade_timestamp = max(latest_trade_timestamp, timestamp)
        # Shared order-flow engine uses Binance's buyer-is-maker convention.
        normalized_trades.append({
            "q": quantity, "m": side == "Sell", "T": timestamp,
            "source": "Bybit", "side": side,
        })
    if buy_volume <= 0 or sell_volume <= 0:
        raise ValueError("Bybit recent-trade sample lacks both taker sides.")

    observed_at_ms = min(oi_timestamp, latest_trade_timestamp)
    quality = freshness(observed_at_ms, 600)
    return {
        "venue": "Bybit", "symbol": symbol, "category": "linear",
        "funding_rate": funding_rate, "funding_time_ms": funding_timestamp,
        "open_interest": current_oi, "open_interest_change_pct": oi_change_pct,
        "open_interest_observed_at_ms": oi_timestamp,
        "taker_buy_volume": buy_volume, "taker_sell_volume": sell_volume,
        "taker_buy_sell_ratio": buy_volume / sell_volume,
        "taker_observed_at_ms": latest_trade_timestamp,
        "observed_at_ms": observed_at_ms,
        "observed_at_utc": quality["observed_at_utc"],
        "freshness": quality,
        "trades": normalized_trades,
        "source": "Bybit V5 public linear-perpetual market data",
        "limitations": [
            "This is a Bybit venue sample, not the consolidated Bitcoin derivatives market.",
            "Recent public trades are a bounded sample, not full-session taker CVD.",
            "Open interest is non-directional by itself; funding is positioning context.",
        ],
    }
