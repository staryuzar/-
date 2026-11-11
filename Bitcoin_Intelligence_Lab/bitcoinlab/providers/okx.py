from __future__ import annotations

from collections.abc import Mapping
import math
from urllib.parse import urlencode
from typing import Any

from .http import get_json


BASE = "https://www.okx.com"
SWAP_SYMBOL = "BTC-USDT-SWAP"


def _okx_rows(path: str, params: Mapping[str, object], label: str) -> list[dict[str, Any]]:
    url = f"{BASE}{path}?{urlencode(params)}"
    payload = get_json(url, timeout=10.0)
    if not isinstance(payload, dict) or str(payload.get("code")) != "0":
        raise ValueError(f"OKX {label} response failed: {str(payload)[:180]}")
    rows = payload.get("data")
    if not isinstance(rows, list) or not rows or any(not isinstance(row, dict) for row in rows):
        raise ValueError(f"OKX {label} returned no valid data rows.")
    return rows


def _number(value: object, label: str, *, positive: bool = False) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"OKX {label} is not numeric.") from exc
    if not math.isfinite(result) or (positive and result <= 0):
        raise ValueError(f"OKX {label} is invalid.")
    return result


def fetch_derivatives_snapshot(
    symbol: str = "BTCUSDT",
    *,
    cross_venue_context: Mapping[str, Any] | None = None,
    trade_limit: int = 500,
) -> dict[str, Any]:
    """
    Build a read-only OKX BTC perpetual derivatives snapshot.

    Directional evidence comes only from the recent public perpetual trades'
    taker-side ratio. Funding and open interest are optional positioning context.
    Contract quantities are never converted to BTC/USD by this adapter.
    """
    normalized_symbol = symbol.upper().replace("-", "").strip()
    if normalized_symbol != "BTCUSDT":
        raise ValueError("OKX derivatives fallback is restricted to BTCUSDT.")
    if not 10 <= trade_limit <= 500:
        raise ValueError("trade_limit must be between 10 and 500.")

    context_row = None
    if isinstance(cross_venue_context, Mapping):
        for row in (cross_venue_context.get("venues") or []):
            if isinstance(row, Mapping) and row.get("venue") == "okx_swap":
                context_row = row
                break

    warnings: list[str] = []
    funding_rate = None
    funding_interval = None
    funding_kind = "unavailable"
    oi_btc = None
    oi_native = None
    oi_quote = None
    observed_context = None

    # Reuse the already validated cross-venue row where possible. This avoids
    # repeating the same public ticker/mark/funding/OI requests on each refresh.
    if isinstance(context_row, Mapping) and context_row.get("status") in {"ok", "partial"}:
        warnings.extend(str(item) for item in context_row.get("warnings", []))
        funding_rate = context_row.get("funding_rate_per_settlement")
        funding_interval = context_row.get("funding_interval_minutes")
        oi_btc = context_row.get("open_interest_btc")
        oi_native = context_row.get("open_interest_native")
        oi_quote = context_row.get("open_interest_quote_value")
        observed_context = context_row.get("observed_at_ms")
        funding_kind = context_row.get("funding_rate_kind", "source_reported_current_period_rate")
        if funding_rate is None:
            warnings.append("okx_funding_unavailable_in_cross_venue_context")
        if funding_kind == "current_period_estimate":
            warnings.append("okx_funding_rate_is_current_period_estimate_not_settled")
    else:
        warnings.append("cross_venue_okx_context_unavailable")
        try:
            funding = _okx_rows(
                "/api/v5/public/funding-rate",
                {"instId": SWAP_SYMBOL},
                "funding rate",
            )[0]
            raw_rate = (
                funding.get("settFundingRate")
                if funding.get("settState") == "settled"
                else funding.get("fundingRate")
            )
            funding_rate = _number(raw_rate, "funding rate")
            funding_start = int(funding.get("fundingTime", 0))
            funding_next = int(funding.get("nextFundingTime", 0))
            if funding_next > funding_start > 0:
                funding_interval = (funding_next - funding_start) / 60_000.0
            funding_kind = (
                "settled" if funding.get("settState") == "settled"
                else "current_period_estimate"
            )
            if funding_kind != "settled":
                warnings.append("okx_funding_rate_is_current_period_estimate_not_settled")
            observed_context = int(funding.get("ts", 0)) or None
        except Exception as exc:
            warnings.append(f"okx_funding_unavailable:{type(exc).__name__}")

        try:
            oi = _okx_rows(
                "/api/v5/public/open-interest",
                {"instType": "SWAP", "instId": SWAP_SYMBOL},
                "open interest",
            )[0]
            oi_btc = _number(oi.get("oiCcy"), "open interest BTC", positive=True)
            oi_native = _number(oi.get("oi"), "open interest contracts", positive=True)
            oi_quote = _number(oi.get("oiUsd"), "open interest USD", positive=True)
            observed_context = min(
                x for x in (observed_context, int(oi.get("ts", 0)) or None) if x
            ) if observed_context else (int(oi.get("ts", 0)) or None)
        except Exception as exc:
            warnings.append(f"okx_open_interest_unavailable:{type(exc).__name__}")

    # OKX market trades report side as the taker side. For SWAP, sz is in
    # contracts; using the same instrument/contract for numerator and
    # denominator makes a within-venue ratio valid without converting units.
    trades = _okx_rows(
        "/api/v5/market/trades",
        {"instId": SWAP_SYMBOL, "limit": str(trade_limit)},
        "perpetual trades",
    )
    buy_contracts = sell_contracts = 0.0
    latest_trade_ms = 0
    trade_count = 0
    for trade in trades:
        side = str(trade.get("side", "")).lower()
        if side not in {"buy", "sell"}:
            raise ValueError("OKX trade side is not a recognized taker side.")
        size = _number(trade.get("sz"), "trade size", positive=True)
        timestamp = int(trade.get("ts", 0))
        if timestamp <= 0:
            raise ValueError("OKX trade timestamp is invalid.")
        if side == "buy":
            buy_contracts += size
        else:
            sell_contracts += size
        latest_trade_ms = max(latest_trade_ms, timestamp)
        trade_count += 1

    if buy_contracts <= 0 or sell_contracts <= 0:
        raise ValueError("OKX recent trades do not contain both taker sides.")
    taker_ratio = buy_contracts / sell_contracts
    if not math.isfinite(taker_ratio) or taker_ratio <= 0:
        raise ValueError("OKX taker buy/sell ratio is invalid.")

    return {
        "venue": "OKX",
        "symbol": SWAP_SYMBOL,
        "category": "SWAP",
        "funding_rate": (
            _number(funding_rate, "funding rate")
            if funding_rate is not None else None
        ),
        "funding_rate_kind": funding_kind,
        "funding_interval_minutes": (
            _number(funding_interval, "funding interval", positive=True)
            if funding_interval is not None else None
        ),
        "open_interest_btc": (
            _number(oi_btc, "open interest BTC", positive=True)
            if oi_btc is not None else None
        ),
        "open_interest_native": (
            _number(oi_native, "open interest contracts", positive=True)
            if oi_native is not None else None
        ),
        "open_interest_native_unit": "contracts",
        "open_interest_quote_value": (
            _number(oi_quote, "open interest USD", positive=True)
            if oi_quote is not None else None
        ),
        "open_interest_quote_currency": "USD",
        "open_interest_change_pct": None,
        "taker_buy_volume_contracts": buy_contracts,
        "taker_sell_volume_contracts": sell_contracts,
        "taker_buy_sell_ratio": taker_ratio,
        "trade_count": trade_count,
        "observed_at_ms": latest_trade_ms,
        "context_observed_at_ms": observed_context,
        "warnings": warnings,
        "source": "OKX V5 public SWAP market trades, funding and open interest",
        "limitations": [
            "Taker-side ratio is calculated from the bounded latest public trade sample, not full-session CVD.",
            "Trade sizes are native BTC-USDT-SWAP contracts; buy/sell ratio is within the same instrument and no contract-to-BTC conversion is inferred.",
            "Open interest is context only and remains in published BTC/contracts/USD units; no cross-venue sum is calculated.",
            "Funding is settled when the exchange reports settState=settled; otherwise it is labelled as current-period estimate.",
            "Open-interest change is unavailable unless a timestamped, compatible history baseline is available.",
        ],
    }
