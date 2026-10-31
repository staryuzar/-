from __future__ import annotations

import math
import statistics
from collections.abc import Iterable, Mapping
from typing import Any


def _number(value: object, field: str) -> float | None:
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{field} must be numeric.") from exc
    if not math.isfinite(number):
        raise ValueError(f"{field} must be finite.")
    return number


def _positive(value: object, field: str, *, required: bool = False) -> float | None:
    number = _number(value, field)
    if number is None:
        if required:
            raise ValueError(f"{field} is required.")
        return None
    if number <= 0:
        raise ValueError(f"{field} must be positive.")
    return number


def _mid(bid: float | None, ask: float | None, field: str) -> float | None:
    if bid is None or ask is None:
        return None
    if bid <= 0 or ask <= bid:
        raise ValueError(f"{field} requires positive, non-crossed bid/ask.")
    return (bid + ask) / 2.0


def funding_rate_per_8h(rate: object, interval_minutes: object) -> float | None:
    """Linearly scale the per-settlement funding rate to an 8-hour equivalent."""
    value = _number(rate, "funding_rate")
    interval = _positive(interval_minutes, "funding_interval_minutes")
    if value is None or interval is None:
        return None
    if interval < 1 or interval > 24 * 60:
        raise ValueError("Funding interval must be between 1 minute and 24 hours.")
    return value * (480.0 / interval)


def _normalize_row(raw: Mapping[str, Any], *, now_ms: int, max_age_seconds: int) -> dict[str, Any]:
    venue = str(raw.get("venue") or "").strip().lower()
    if venue not in {"binance_usdm", "bybit_linear", "okx_swap"}:
        raise ValueError("Unsupported derivatives venue.")
    observed = int(_positive(raw.get("observed_at_ms"), "observed_at_ms", required=True))
    age = (int(now_ms) - observed) / 1000.0
    if age < -5 or age > max_age_seconds:
        return {
            "venue": venue,
            "status": "stale",
            "observed_at_ms": observed,
            "age_seconds": round(max(0.0, age), 3),
            "reason": "Exchange derivatives snapshot is outside the freshness window.",
        }

    spot_bid = _positive(raw.get("spot_bid"), "spot_bid")
    spot_ask = _positive(raw.get("spot_ask"), "spot_ask")
    perp_bid = _positive(raw.get("perp_bid"), "perp_bid")
    perp_ask = _positive(raw.get("perp_ask"), "perp_ask")
    spot_mid = _mid(spot_bid, spot_ask, "spot")
    perp_mid = _mid(perp_bid, perp_ask, "perpetual")
    mark = _positive(raw.get("mark_price"), "mark_price")
    index = _positive(raw.get("index_price"), "index_price")
    funding = _number(raw.get("funding_rate"), "funding_rate")
    interval = _positive(raw.get("funding_interval_minutes"), "funding_interval_minutes")
    oi_btc = _positive(raw.get("open_interest_btc"), "open_interest_btc")
    oi_native = _positive(raw.get("open_interest_native"), "open_interest_native")
    oi_quote = _positive(raw.get("open_interest_quote_value"), "open_interest_quote_value")

    funding_8h = funding_rate_per_8h(funding, interval)
    perp_spot_bps = (
        (perp_mid / spot_mid - 1.0) * 10_000.0
        if perp_mid is not None and spot_mid is not None else None
    )
    mark_index_bps = (
        (mark / index - 1.0) * 10_000.0
        if mark is not None and index is not None else None
    )
    spot_index_bps = (
        (spot_mid / index - 1.0) * 10_000.0
        if spot_mid is not None and index is not None else None
    )

    return {
        "venue": venue,
        "status": "ok" if spot_mid is not None and perp_mid is not None else "partial",
        "symbol": str(raw.get("symbol") or "BTCUSDT"),
        "observed_at_ms": observed,
        "timestamp_kind": str(raw.get("timestamp_kind") or "exchange"),
        "age_seconds": round(max(0.0, age), 3),
        "spot_bid": spot_bid,
        "spot_ask": spot_ask,
        "spot_mid": round(spot_mid, 8) if spot_mid is not None else None,
        "perpetual_bid": perp_bid,
        "perpetual_ask": perp_ask,
        "perpetual_mid": round(perp_mid, 8) if perp_mid is not None else None,
        "perpetual_vs_spot_bps": round(perp_spot_bps, 4) if perp_spot_bps is not None else None,
        "mark_price": mark,
        "index_price": index,
        "mark_vs_index_bps": round(mark_index_bps, 4) if mark_index_bps is not None else None,
        "spot_vs_index_bps": round(spot_index_bps, 4) if spot_index_bps is not None else None,
        "funding_rate_per_settlement": funding,
        "funding_interval_minutes": interval,
        "funding_rate_per_8h_equivalent": round(funding_8h, 10) if funding_8h is not None else None,
        "open_interest_btc": oi_btc,
        "open_interest_native": oi_native,
        "open_interest_native_unit": str(raw.get("open_interest_native_unit") or "unverified_native_units"),
        "open_interest_quote_value": oi_quote,
        "open_interest_quote_currency": str(raw.get("open_interest_quote_currency") or "") or None,
        "warnings": list(raw.get("warnings") or []),
        "limitations": list(raw.get("limitations") or []),
    }


def build_cross_venue_derivatives_context(
    rows: Iterable[Mapping[str, Any]],
    *,
    now_ms: int,
    max_age_seconds: int = 120,
) -> dict[str, Any]:
    """Compare fresh per-venue basis/funding without pooling incompatible OI units."""
    if max_age_seconds < 1:
        raise ValueError("max_age_seconds must be positive.")
    normalized: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    seen: set[str] = set()
    for raw in rows:
        venue = str(raw.get("venue") or "").lower()
        if venue in seen:
            errors.append({"venue": venue or "unknown", "error": "duplicate_venue_row"})
            continue
        seen.add(venue)
        try:
            normalized.append(_normalize_row(raw, now_ms=now_ms, max_age_seconds=max_age_seconds))
        except (TypeError, ValueError, OverflowError) as exc:
            errors.append({"venue": venue or "unknown", "error": f"{type(exc).__name__}: {exc}"[:200]})

    usable = [row for row in normalized if row["status"] == "ok"]
    funding_values = [
        row["funding_rate_per_8h_equivalent"] for row in usable
        if row["funding_rate_per_8h_equivalent"] is not None
    ]
    basis_values = [
        row["perpetual_vs_spot_bps"] for row in usable
        if row["perpetual_vs_spot_bps"] is not None
    ]
    mark_values = [
        row["mark_vs_index_bps"] for row in usable
        if row["mark_vs_index_bps"] is not None
    ]

    def summary(values: list[float], unit: str) -> dict[str, Any]:
        if not values:
            return {"venue_count": 0, "median": None, "min": None, "max": None, "range": None, "unit": unit}
        return {
            "venue_count": len(values),
            "median": round(statistics.median(values), 6),
            "min": round(min(values), 6),
            "max": round(max(values), 6),
            "range": round(max(values) - min(values), 6),
            "unit": unit,
        }

    funding_summary = summary(funding_values, "decimal rate per 8 hours")
    basis_summary = summary(basis_values, "basis points")
    mark_summary = summary(mark_values, "basis points")

    warnings: list[str] = []
    if len(usable) < 2:
        warnings.append("cross_venue_derivatives_coverage_below_two_venues")
    if len(funding_values) >= 2 and funding_summary["range"] is not None:
        if funding_summary["range"] >= 0.0003:
            warnings.append("funding_rate_dispersion_across_venues")
    if len(basis_values) >= 2 and basis_summary["range"] is not None:
        if basis_summary["range"] >= 12.0:
            warnings.append("perpetual_spot_basis_dispersion_across_venues")
    if len(mark_values) >= 2 and mark_summary["range"] is not None:
        if mark_summary["range"] >= 8.0:
            warnings.append("mark_index_premium_dispersion_across_venues")

    oi_rows = [
        {
            "venue": row["venue"],
            "open_interest_btc": row["open_interest_btc"],
            "open_interest_native": row["open_interest_native"],
            "open_interest_native_unit": row["open_interest_native_unit"],
            "open_interest_quote_value": row["open_interest_quote_value"],
            "open_interest_quote_currency": row["open_interest_quote_currency"],
        }
        for row in normalized
        if any(row.get(key) is not None for key in (
            "open_interest_btc", "open_interest_native", "open_interest_quote_value",
        ))
    ]

    return {
        "status": "ok" if len(usable) >= 2 else ("partial" if normalized else "unavailable"),
        "venue_count": len(usable),
        "venues": normalized,
        "funding_8h_equivalent": funding_summary,
        "perpetual_spot_basis": basis_summary,
        "mark_index_premium": mark_summary,
        "open_interest_by_venue": oi_rows,
        "errors": errors,
        "warnings": warnings,
        "vote_policy": "context_only_funding_basis_and_open_interest_do_not_create_a_sixth_decision_vote",
        "method": {
            "funding": "Simple linear scaling to 8h: rate * 480 / settlement_interval_minutes. This is a comparison unit, not a predicted compounded return.",
            "basis": "Per-venue perpetual best-bid/ask midpoint divided by that venue's spot best-bid/ask midpoint, minus one.",
            "mark_index": "Mark price divided by index price, minus one.",
            "open_interest": "Values remain per venue and in explicitly reported units; no cross-venue sum is calculated.",
        },
        "limitations": [
            "USDT and USD quote values are shown with their source currency and are not assumed to be exactly equal.",
            "Funding intervals can change; each venue requires current interval metadata or a timestamp-derived interval.",
            "Open interest is two-sided outstanding exposure, not net long direction.",
            "OI values remain per venue; no cross-venue sum is calculated because contract, BTC, USD and USDT units are not interchangeable.",
            "Cross-venue snapshots are asynchronous and can be separated by request latency.",
            "This context is descriptive only and is not an independent directional vote.",
        ],
    }
