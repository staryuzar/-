from __future__ import annotations

import math
import statistics
from collections import defaultdict
from collections.abc import Iterable, Mapping
from typing import Any


def _finite(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _market_group(value: object) -> str | None:
    text = str(value or "").lower()
    if text == "spot":
        return "spot"
    if text in {"perpetual", "linear_perpetual"}:
        return "perpetual"
    return None


def build_streamed_trade_flow_profile(
    rows: Iterable[Mapping[str, Any]],
    *,
    now_ms: int,
    timeframe: str = "5m",
    max_age_seconds: int = 35,
    minimum_trade_count: int = 5,
    minimum_venues: int = 2,
) -> dict[str, Any]:
    """Create a directional CVD context from distinct fresh venues, not summed volume."""
    if max_age_seconds < 1 or minimum_trade_count < 1 or minimum_venues < 2:
        raise ValueError("Invalid streamed trade-flow quality thresholds.")
    active: list[dict[str, Any]] = []
    rejected: list[str] = []
    for row in rows:
        if str(row.get("timeframe")) != timeframe or row.get("status") != "ok":
            continue
        venue = str(row.get("venue") or "")
        group = _market_group(row.get("market_type"))
        event_time = _finite(row.get("last_trade_time_ms"))
        count = _finite(row.get("trade_count"))
        ratio = _finite(row.get("delta_notional_ratio"))
        total = _finite(row.get("total_notional_usd"))
        if not venue or group is None:
            continue
        age = (int(now_ms) - int(event_time)) / 1000 if event_time and event_time > 0 else math.inf
        if (
            age < -5 or age > max_age_seconds
            or count is None or count < minimum_trade_count
            or ratio is None or not -1 <= ratio <= 1
            or total is None or total <= 0
        ):
            rejected.append(venue)
            continue
        active.append({
            "venue": venue, "market_type": group, "score": ratio,
            "trade_count": int(count), "total_notional_usd": total,
            "last_trade_time_ms": int(event_time),
            "age_seconds": round(max(0.0, age), 3),
        })

    # Only one observation per exchange is allowed for a decision window.
    unique: dict[str, dict[str, Any]] = {}
    for item in active:
        previous = unique.get(item["venue"])
        if previous is None or item["last_trade_time_ms"] > previous["last_trade_time_ms"]:
            unique[item["venue"]] = item
    active = list(unique.values())
    if len(active) < minimum_venues:
        return {
            "status": "incomplete", "score": None, "timeframe": timeframe,
            "venue_count": len(active),
            "active_venues": sorted(item["venue"] for item in active),
            "rejected_venues": sorted(set(rejected)),
            "reason": f"Need {minimum_venues} fresh venues with at least {minimum_trade_count} trades.",
            "warnings": ["multi_venue_trade_flow_coverage_insufficient"],
        }

    spot_scores = [item["score"] for item in active if item["market_type"] == "spot"]
    perp_scores = [item["score"] for item in active if item["market_type"] == "perpetual"]
    spot_score = statistics.median(spot_scores) if spot_scores else None
    perp_score = statistics.median(perp_scores) if perp_scores else None
    if spot_score is not None and perp_score is not None:
        score = 0.55 * spot_score + 0.45 * perp_score
    elif spot_score is not None:
        score = spot_score
    else:
        score = perp_score
    assert score is not None

    warnings: list[str] = []
    if spot_score is not None and perp_score is not None:
        if spot_score * perp_score < 0 and abs(spot_score - perp_score) >= 0.35:
            warnings.append("spot_perpetual_aggressor_flow_disagreement")
    if rejected:
        warnings.append("some_venue_trade_flow_rows_stale_or_under_sampled")

    return {
        "status": "ok", "score": max(-1.0, min(1.0, float(score))),
        "timeframe": timeframe, "venue_count": len(active),
        "active_venues": sorted(item["venue"] for item in active),
        "spot_score": round(spot_score, 6) if spot_score is not None else None,
        "perpetual_score": round(perp_score, 6) if perp_score is not None else None,
        "last_trade_time_ms": max(item["last_trade_time_ms"] for item in active),
        "trade_count": sum(item["trade_count"] for item in active),
        "venues": active, "warnings": warnings,
        "evidence": ["rolling_venue_separated_aggressor_cvd", "spot_perpetual_group_medians"],
        "limitations": [
            "Only selected public venues are represented, not the whole Bitcoin market.",
            "CVD measures aggressor-side traded volume; it is not buyer/seller inventory.",
            "Spot and linear perpetual volumes are never added together.",
        ],
    }


def build_streamed_footprint_profiles(
    rows: Iterable[Mapping[str, Any]],
    *,
    minimum_notional_usd: float = 1.0,
    value_area_fraction: float = 0.70,
) -> list[dict[str, Any]]:
    """Compute a per-venue price-bucket footprint and POC/VAH/VAL."""
    if minimum_notional_usd < 0 or not 0.5 <= value_area_fraction <= 0.9:
        raise ValueError("Invalid footprint thresholds.")
    grouped: dict[tuple[str, str], dict[float, dict[str, float]]] = defaultdict(
        lambda: defaultdict(lambda: {
            "buy_btc": 0.0, "sell_btc": 0.0,
            "buy_usd": 0.0, "sell_usd": 0.0, "count": 0.0,
        })
    )
    for row in rows:
        venue = str(row.get("venue") or "")
        group = _market_group(row.get("market_type"))
        price = _finite(row.get("price_bucket_usd"))
        values = {
            "buy_btc": _finite(row.get("buy_base_volume_btc")) or 0.0,
            "sell_btc": _finite(row.get("sell_base_volume_btc")) or 0.0,
            "buy_usd": _finite(row.get("buy_notional_usd")) or 0.0,
            "sell_usd": _finite(row.get("sell_notional_usd")) or 0.0,
            "count": _finite(row.get("trade_count")) or 0.0,
        }
        if (
            not venue or group is None or price is None or price <= 0
            or any(not math.isfinite(v) or v < 0 for v in values.values())
        ):
            continue
        if values["buy_usd"] + values["sell_usd"] < minimum_notional_usd:
            continue
        target = grouped[(venue, group)][price]
        for key, value in values.items():
            target[key] += value

    profiles: list[dict[str, Any]] = []
    for (venue, market_type), price_rows in sorted(grouped.items()):
        levels = []
        for price, values in sorted(price_rows.items()):
            total = values["buy_usd"] + values["sell_usd"]
            levels.append({
                "price_bucket_usd": price,
                **values,
                "total_notional_usd": total,
                "delta_btc": values["buy_btc"] - values["sell_btc"],
                "delta_notional_usd": values["buy_usd"] - values["sell_usd"],
            })
        if not levels:
            continue
        total = sum(item["total_notional_usd"] for item in levels)
        poc_index = max(range(len(levels)), key=lambda i: levels[i]["total_notional_usd"])
        included = {poc_index}
        accumulated = levels[poc_index]["total_notional_usd"]
        lower, upper = poc_index - 1, poc_index + 1
        target_value = total * value_area_fraction
        while accumulated < target_value and (lower >= 0 or upper < len(levels)):
            lower_volume = levels[lower]["total_notional_usd"] if lower >= 0 else -1.0
            upper_volume = levels[upper]["total_notional_usd"] if upper < len(levels) else -1.0
            if upper_volume > lower_volume:
                included.add(upper)
                accumulated += upper_volume
                upper += 1
            else:
                included.add(lower)
                accumulated += lower_volume
                lower -= 1
        buy_usd = sum(item["buy_usd"] for item in levels)
        sell_usd = sum(item["sell_usd"] for item in levels)
        profiles.append({
            "status": "ok", "venue": venue, "market_type": market_type,
            "poc": levels[poc_index]["price_bucket_usd"],
            "vah": max(levels[i]["price_bucket_usd"] for i in included),
            "val": min(levels[i]["price_bucket_usd"] for i in included),
            "total_notional_usd": round(total, 2),
            "delta_notional_usd": round(buy_usd - sell_usd, 2),
            "delta_ratio": (buy_usd - sell_usd) / total if total else 0.0,
            "trade_count": int(sum(item["count"] for item in levels)),
            "bins": [
                {
                    "price_bucket_usd": item["price_bucket_usd"],
                    "buy_btc": round(item["buy_btc"], 8),
                    "sell_btc": round(item["sell_btc"], 8),
                    "delta_btc": round(item["delta_btc"], 8),
                    "buy_notional_usd": round(item["buy_usd"], 2),
                    "sell_notional_usd": round(item["sell_usd"], 2),
                    "delta_notional_usd": round(item["delta_notional_usd"], 2),
                    "total_notional_usd": round(item["total_notional_usd"], 2),
                    "trade_count": int(item["count"]),
                }
                for item in levels
            ],
            "limitations": [
                "Price bins use fixed USD buckets, not native tick sizes.",
                "Profiles remain separate by venue and market type.",
            ],
        })
    return profiles


def blend_orderflow_evidence(
    base_orderflow: Mapping[str, Any],
    streamed_orderflow: Mapping[str, Any],
) -> dict[str, Any]:
    """Blend existing order-book/REST evidence with the independent multi-venue tape."""
    if streamed_orderflow.get("status") != "ok":
        return dict(base_orderflow)
    stream_score = _finite(streamed_orderflow.get("score"))
    if stream_score is None or not -1 <= stream_score <= 1:
        return dict(base_orderflow)
    base_score = _finite(base_orderflow.get("score")) if base_orderflow.get("status") == "ok" else None
    warnings = list(base_orderflow.get("warnings") or [])
    warnings.extend(streamed_orderflow.get("warnings") or [])
    if base_score is not None and -1 <= base_score <= 1:
        score = 0.65 * base_score + 0.35 * stream_score
        components = {"book_and_bounded_rest_flow": round(base_score, 6),
                      "multi_venue_cvd_5m": round(stream_score, 6)}
        weights = {"book_and_bounded_rest_flow": 0.65, "multi_venue_cvd_5m": 0.35}
    else:
        score = stream_score
        components = {"multi_venue_cvd_5m": round(stream_score, 6)}
        weights = {"multi_venue_cvd_5m": 1.0}
        warnings.append("orderflow_uses_streamed_cvd_without_fresh_rest_sample")
    score = max(-1.0, min(1.0, score))
    return {
        "status": "ok", "score": score,
        "state": "buy_pressure" if score >= 0.15 else ("sell_pressure" if score <= -0.15 else "balanced"),
        "components": components, "weights": weights,
        "streamed_trade_flow": dict(streamed_orderflow), "warnings": warnings,
        "evidence": ["existing_book_and_bounded_rest_sample", "rolling_multi_venue_cvd"],
        "limitations": [
            "CVD covers only selected public venues, not all Bitcoin markets.",
            "Binance USDⓈ-M and Bybit linear are derivatives evidence; OKX is spot evidence.",
            "Directional evidence is not a probability of profit.",
        ],
    }
