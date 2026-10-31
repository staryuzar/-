from __future__ import annotations

from urllib.parse import urlencode
import time
from typing import Any

from . import binance, bybit
from .http import get_json


OKX_BASE = "https://www.okx.com"


def _okx_rows(path: str, params: dict[str, object], label: str) -> list[dict[str, Any]]:
    payload = get_json(f"{OKX_BASE}{path}?{urlencode(params)}", timeout=10.0)
    if not isinstance(payload, dict) or str(payload.get("code")) != "0":
        raise ValueError(f"OKX {label} response failed: {str(payload)[:180]}")
    rows = payload.get("data")
    if not isinstance(rows, list) or not rows or any(not isinstance(row, dict) for row in rows):
        raise ValueError(f"OKX {label} returned no valid data rows.")
    return rows


def _first_bybit(payload: object, label: str) -> tuple[dict[str, Any], int]:
    if not isinstance(payload, dict) or payload.get("retCode") != 0:
        raise ValueError(f"Bybit {label} request failed: {str(payload)[:180]}")
    result = payload.get("result")
    rows = result.get("list") if isinstance(result, dict) else None
    if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
        raise ValueError(f"Bybit {label} returned no data row.")
    timestamp = int(payload.get("time") or time.time() * 1000)
    return rows[0], timestamp


def fetch_cross_venue_derivatives_rows(symbol: str = "BTCUSDT") -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Fetch public read-only spot/perpetual basis, funding, and OI context."""
    symbol = symbol.upper().strip()
    if symbol != "BTCUSDT":
        raise ValueError("Cross-venue derivative context is currently limited to BTCUSDT.")
    rows: list[dict[str, Any]] = []
    errors: dict[str, str] = {}

    # Binance USDⓈ-M: the current mark/index premium plus the actual interval
    # inferred from the two latest settled funding timestamps.
    try:
        premium = binance.fetch_usdm_premium_index(symbol)
        spot = binance.fetch_spot_book_ticker(symbol)
        perp = binance.fetch_usdm_book_ticker(symbol)
        oi = binance.fetch_open_interest(symbol)
        funding_history = binance.fetch_funding_history(symbol, 3)
        funding_times = sorted({
            int(item.get("fundingTime", 0))
            for item in funding_history
            if isinstance(item, dict) and int(item.get("fundingTime", 0)) > 0
        })
        interval_minutes = (
            (funding_times[-1] - funding_times[-2]) / 60_000
            if len(funding_times) >= 2 else None
        )
        observed_candidates = [
            int(premium.get("time", 0)), int(oi.get("time", 0)),
        ]
        observed = min(value for value in observed_candidates if value > 0)
        rows.append({
            "venue": "binance_usdm", "symbol": symbol,
            "observed_at_ms": observed,
            "timestamp_kind": "oldest_exchange_timestamp_plus_receive-time-book-samples",
            "spot_bid": spot.get("bidPrice"), "spot_ask": spot.get("askPrice"),
            "perp_bid": perp.get("bidPrice"), "perp_ask": perp.get("askPrice"),
            "mark_price": premium.get("markPrice"), "index_price": premium.get("indexPrice"),
            "funding_rate": premium.get("lastFundingRate"),
            "funding_interval_minutes": interval_minutes,
            "open_interest_native": oi.get("openInterest"),
            "open_interest_native_unit": "Binance USDⓈ-M native openInterest; unit not inferred by this adapter",
            "warnings": [] if interval_minutes else ["funding_interval_unavailable_for_8h_normalization"],
        })
    except Exception as exc:
        errors["binance_usdm"] = f"{type(exc).__name__}: {exc}"[:240]

    # Bybit: tickers expose funding/mark/index/OI and instrument-info provides
    # the exact settlement interval in minutes. OI for BTCUSDT linear is BTC.
    try:
        linear_payload = bybit._request(
            "/v5/market/tickers", {"category": "linear", "symbol": symbol},
        )
        linear, linear_observed = _first_bybit(linear_payload, "linear ticker")
        spot_payload = bybit._request(
            "/v5/market/tickers", {"category": "spot", "symbol": symbol},
        )
        spot, spot_observed = _first_bybit(spot_payload, "spot ticker")
        instrument_payload = bybit._request(
            "/v5/market/instruments-info", {"category": "linear", "symbol": symbol},
        )
        instrument, instrument_observed = _first_bybit(instrument_payload, "linear instrument info")
        observed = min(linear_observed, spot_observed, instrument_observed)
        rows.append({
            "venue": "bybit_linear", "symbol": symbol,
            "observed_at_ms": observed, "timestamp_kind": "bybit_server_response_time",
            "spot_bid": spot.get("bid1Price"), "spot_ask": spot.get("ask1Price"),
            "perp_bid": linear.get("bid1Price"), "perp_ask": linear.get("ask1Price"),
            "mark_price": linear.get("markPrice"), "index_price": linear.get("indexPrice"),
            "funding_rate": linear.get("fundingRate"),
            "funding_interval_minutes": instrument.get("fundingInterval"),
            "open_interest_btc": linear.get("openInterest"),
            "open_interest_quote_value": linear.get("openInterestValue"),
            "open_interest_quote_currency": "USDT",
            "warnings": [],
        })
    except Exception as exc:
        errors["bybit_linear"] = f"{type(exc).__name__}: {exc}"[:240]

    # OKX: oiCcy is explicitly a crypto-unit value and oiUsd is a USD value;
    # no conversion from raw contract count is attempted.
    try:
        spot_ticker = _okx_rows(
            "/api/v5/market/ticker", {"instId": "BTC-USDT"}, "spot ticker",
        )[0]
        swap_ticker = _okx_rows(
            "/api/v5/market/ticker", {"instId": "BTC-USDT-SWAP"}, "swap ticker",
        )[0]
        index = _okx_rows(
            "/api/v5/market/index-tickers", {"instId": "BTC-USDT"}, "index ticker",
        )[0]
        mark = _okx_rows(
            "/api/v5/public/mark-price",
            {"instType": "SWAP", "instId": "BTC-USDT-SWAP"},
            "swap mark price",
        )[0]
        funding = _okx_rows(
            "/api/v5/public/funding-rate",
            {"instId": "BTC-USDT-SWAP"},
            "swap funding rate",
        )[0]
        oi = _okx_rows(
            "/api/v5/public/open-interest",
            {"instType": "SWAP", "instId": "BTC-USDT-SWAP"},
            "swap open interest",
        )[0]
        funding_start = int(funding.get("fundingTime", 0))
        funding_next = int(funding.get("nextFundingTime", 0))
        interval_minutes = (
            (funding_next - funding_start) / 60_000
            if funding_next > funding_start > 0 else None
        )
        timestamps = [
            int(item.get("ts", 0))
            for item in (spot_ticker, swap_ticker, index, mark, funding, oi)
            if int(item.get("ts", 0)) > 0
        ]
        observed = min(timestamps) if timestamps else 0
        rows.append({
            "venue": "okx_swap", "symbol": "BTC-USDT-SWAP",
            "observed_at_ms": observed, "timestamp_kind": "oldest_exchange_feed_timestamp",
            "spot_bid": spot_ticker.get("bidPx"), "spot_ask": spot_ticker.get("askPx"),
            "perp_bid": swap_ticker.get("bidPx"), "perp_ask": swap_ticker.get("askPx"),
            "mark_price": mark.get("markPx"), "index_price": index.get("idxPx"),
            "funding_rate": funding.get("fundingRate"),
            "funding_interval_minutes": interval_minutes,
            "open_interest_btc": oi.get("oiCcy"),
            "open_interest_native": oi.get("oi"),
            "open_interest_native_unit": "contracts",
            "open_interest_quote_value": oi.get("oiUsd"),
            "open_interest_quote_currency": "USD",
            "warnings": [] if interval_minutes else ["funding_interval_unavailable_for_8h_normalization"],
        })
    except Exception as exc:
        errors["okx_swap"] = f"{type(exc).__name__}: {exc}"[:240]

    return rows, errors
