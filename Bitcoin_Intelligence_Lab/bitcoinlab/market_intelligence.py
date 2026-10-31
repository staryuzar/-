from __future__ import annotations

import math
import statistics
from typing import Any, Mapping


def _finite(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def market_structure_signal(profile: Mapping[str, Any]) -> dict[str, Any]:
    """
    Build a cautious direction score from session VWAP location and sampled
    aggressor delta. The two inputs are separately labelled and never
    represented as a full-session footprint.
    """
    bars = profile.get("bars") or {}
    volume_profile = profile.get("volume_profile") or {}
    components: dict[str, float] = {}
    warnings: list[str] = []

    close = _finite(bars.get("last_close"))
    vwap = _finite(bars.get("session_vwap_utc"))
    true_range = _finite(bars.get("last_true_range"))
    coverage = _finite(bars.get("session_vwap_coverage_minutes"))
    session_bars = int(bars.get("session_vwap_bars") or 0)

    if (
        bars.get("status") == "ok"
        and close is not None and vwap is not None
        and true_range is not None and true_range > 0
        and coverage is not None and coverage >= 15
        and session_bars >= 5
    ):
        distance = (close - vwap) / (2.0 * true_range)
        components["session_vwap_location"] = math.tanh(distance)
    else:
        warnings.append("session_vwap_coverage_or_baseline_insufficient")

    delta_ratio = _finite(volume_profile.get("delta_ratio"))
    sample_count = int(volume_profile.get("sample_trade_count") or 0)
    if (
        volume_profile.get("status") == "ok"
        and delta_ratio is not None and -1 <= delta_ratio <= 1
        and sample_count >= 30
    ):
        components["sampled_trade_delta"] = delta_ratio
    else:
        warnings.append("trade_profile_sample_insufficient")

    if not components:
        return {
            "status": "incomplete",
            "score": None,
            "components": {},
            "warnings": warnings,
            "reason": "Insufficient session VWAP coverage and recent trade profile depth.",
        }

    weights = {
        "session_vwap_location": 0.65,
        "sampled_trade_delta": 0.35,
    }
    active_total = sum(weights[name] for name in components)
    normalized = {name: weights[name] / active_total for name in components}
    score = sum(components[name] * normalized[name] for name in components)
    return {
        "status": "ok",
        "score": max(-1.0, min(1.0, score)),
        "components": components,
        "weights": normalized,
        "warnings": warnings,
        "evidence": [
            "closed_bar_session_vwap_position",
            "bounded_recent_aggregate_trade_delta",
        ],
        "limitations": [
            "The session VWAP is bar-derived and depends on selected chart interval.",
            "The trade delta is a bounded sample, not a full-session CVD.",
            "This domain is low-weight and requires independent confirmation.",
        ],
    }


def cross_venue_orderbook_profile(
    stream_state: Mapping[str, Any],
    *,
    now_ms: int,
    max_age_seconds: int = 20,
    minimum_venues: int = 2,
) -> dict[str, Any]:
    """Compare fresh order-book imbalance ratios without adding native sizes across markets."""
    if not 1 <= minimum_venues <= 5:
        raise ValueError("minimum_venues must be between one and five.")
    valid: list[dict[str, Any]] = []
    stale: list[str] = []
    status_by_venue = {
        str(row.get("venue")): row
        for row in stream_state.get("venues", [])
        if isinstance(row, Mapping)
    }
    for row in stream_state.get("latest_books", []):
        if not isinstance(row, Mapping):
            continue
        venue = str(row.get("venue", ""))
        status = status_by_venue.get(venue, {})
        imbalance = _finite(row.get("imbalance"))
        spread = _finite(row.get("spread_bps"))
        try:
            observed = int(row.get("observed_at_ms") or 0)
        except (TypeError, ValueError):
            observed = 0
        age = (now_ms - observed) / 1000 if observed else math.inf
        if (
            status.get("status") != "live"
            or not (0 <= age <= max_age_seconds)
            or imbalance is None or not -1 <= imbalance <= 1
            or spread is None or spread < 0
        ):
            stale.append(venue or "unknown")
            continue
        market_type = (
            "perpetual" if "bybit_linear" in venue
            else "spot" if venue in {"binance_spot", "okx_spot"}
            else "other"
        )
        valid.append({
            "venue": venue,
            "market_type": market_type,
            "imbalance": imbalance,
            "spread_bps": spread,
            "age_seconds": round(age, 2),
            "observed_at_ms": observed,
        })

    unique_venues = {row["venue"] for row in valid}
    if len(unique_venues) < minimum_venues:
        return {
            "status": "incomplete",
            "score": None,
            "active_venues": sorted(unique_venues),
            "venue_count": len(unique_venues),
            "stale_venues": sorted(set(stale)),
            "venue_metrics": valid,
            "warnings": ["insufficient_fresh_cross_venue_books"],
        }

    scores = [row["imbalance"] for row in valid]
    score = float(statistics.median(scores))
    positive = sum(value > 0.05 for value in scores)
    negative = sum(value < -0.05 for value in scores)
    neutral = len(scores) - positive - negative
    aligned = max(positive, negative, neutral)
    agreement = aligned / len(scores)
    warnings: list[str] = []
    if positive and negative:
        warnings.append("spot_or_perpetual_book_imbalance_conflict")
        score *= 0.5
    spread_values = [row["spread_bps"] for row in valid]
    return {
        "status": "ok",
        "score": max(-1.0, min(1.0, score)),
        "venue_count": len(unique_venues),
        "active_venues": sorted(unique_venues),
        "agreement_ratio": round(agreement, 4),
        "median_spread_bps": round(float(statistics.median(spread_values)), 4),
        "venue_metrics": valid,
        "warnings": warnings,
        "interpretation": (
            "Median normalized book imbalance across fresh venues. Spot and "
            "perpetual order books remain separately labelled; native quantities are not summed."
        ),
    }


def liquidation_risk_profile(
    stream_state: Mapping[str, Any],
) -> dict[str, Any]:
    """Expose recent liquidation stress as context, not a directional prediction."""
    groups = stream_state.get("liquidation_short_window_summary") or []
    by_venue: dict[str, dict[str, Any]] = {}
    long_venues: set[str] = set()
    short_venues: set[str] = set()
    total_events = 0
    for row in groups:
        if not isinstance(row, Mapping):
            continue
        venue = str(row.get("venue", "unknown"))
        side = str(row.get("liquidated_side", "unknown"))
        count = int(row.get("event_count") or 0)
        total_events += count
        record = by_venue.setdefault(venue, {"long_events": 0, "short_events": 0})
        if side == "LONG":
            record["long_events"] += count
            if count:
                long_venues.add(venue)
        elif side == "SHORT":
            record["short_events"] += count
            if count:
                short_venues.add(venue)

    warnings: list[str] = []
    if len(long_venues) >= 2:
        warnings.append("cross_venue_long_liquidation_pressure")
    if len(short_venues) >= 2:
        warnings.append("cross_venue_short_liquidation_pressure")
    return {
        "status": "ok" if groups else "empty",
        "window_seconds": 300,
        "event_count": total_events,
        "long_liquidation_venues": sorted(long_venues),
        "short_liquidation_venues": sorted(short_venues),
        "by_venue": by_venue,
        "warnings": warnings,
        "use_in_decision": "risk_context_only_not_directional_vote",
        "limitations": [
            "Venue feeds have different sampling and size semantics.",
            "Long liquidations show forced selling, not a guaranteed reversal; short liquidations show forced buying, not a guaranteed continuation.",
            "No cross-venue USD notional is inferred from contract counts.",
        ],
    }


def build_market_intelligence(
    stream_state: Mapping[str, Any],
    market_structure: Mapping[str, Any],
    *,
    now_ms: int,
) -> dict[str, Any]:
    cross_venue = cross_venue_orderbook_profile(stream_state, now_ms=now_ms)
    structure = market_structure_signal(market_structure)
    liquidations = liquidation_risk_profile(stream_state)
    return {
        "cross_venue_orderbook": cross_venue,
        "market_structure_signal": structure,
        "liquidation_risk": liquidations,
        "limitations": [
            "Cross-venue book imbalance is a normalized comparison, not summed depth.",
            "Spot and perpetual order books are not interchangeable and are labelled separately.",
            "Liquidation flows are risk context and do not independently trigger BUY or SELL.",
        ],
    }
