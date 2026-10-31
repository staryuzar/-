from __future__ import annotations

from datetime import datetime, timezone
import math
from typing import Any, Mapping


DAY_MS = 86_400_000


def _value(row: Mapping[str, Any], key: str) -> float | None:
    raw = row.get(key)
    if raw in (None, ""):
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError, OverflowError):
        return None
    return value if math.isfinite(value) else None


def _time_ms(row: Mapping[str, Any]) -> int | None:
    raw = row.get("time")
    if not isinstance(raw, str) or not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return int(parsed.timestamp() * 1000)
    except (TypeError, ValueError, OverflowError):
        return None


def _latest(rows: object) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    if not isinstance(rows, list):
        return None, []
    valid = [
        dict(row) for row in rows
        if isinstance(row, Mapping) and row.get("asset") == "btc" and _time_ms(row)
    ]
    valid.sort(key=lambda row: _time_ms(row) or 0)
    return (valid[-1] if valid else None), valid


def _seven_day_change(rows: list[dict[str, Any]], field: str, latest_time_ms: int) -> float | None:
    latest = next((row for row in reversed(rows) if _time_ms(row) == latest_time_ms), None)
    latest_value = _value(latest, field) if latest else None
    if latest_value is None:
        return None
    candidates = [
        row for row in rows
        if (_time_ms(row) or 0) <= latest_time_ms - 7 * DAY_MS
        and (_time_ms(row) or 0) >= latest_time_ms - 9 * DAY_MS
    ]
    if not candidates:
        return None
    prior_value = _value(candidates[-1], field)
    if prior_value is None or prior_value == 0:
        return None
    return (latest_value / prior_value - 1.0) * 100.0


def build_onchain_context(
    payload: Mapping[str, Any] | None,
    *,
    now_ms: int,
    max_age_hours: int = 72,
) -> dict[str, Any]:
    """Normalize daily Coin Metrics Community series as slow context, never an intraday vote."""
    if max_age_hours < 1 or max_age_hours > 24 * 30:
        raise ValueError("max_age_hours must be between 1 and 720.")
    if not isinstance(payload, Mapping):
        return {
            "status": "unavailable",
            "reason": "Coin Metrics payload is unavailable.",
            "use": "slow_daily_context_only_not_an_intraday_vote",
        }

    base_latest, base_rows = _latest(payload.get("data"))
    metrics_latest, metric_rows = _latest(payload.get("onchain_data"))
    z_latest, z_rows = _latest(payload.get("mvrv_z_data"))

    cap_market = _value(metrics_latest or {}, "CapMrktCurUSD")
    cap_realized = _value(metrics_latest or {}, "CapRealUSD")
    mvrv = _value(metrics_latest or {}, "CapMVRVCur")
    if mvrv is None and cap_market is not None and cap_realized not in (None, 0):
        mvrv = cap_market / cap_realized
    nupl = (
        (cap_market - cap_realized) / cap_market
        if cap_market is not None and cap_market > 0 and cap_realized is not None
        else None
    )
    mvrv_z = _value(z_latest or {}, "CapMVRVZ")

    source_time = _time_ms(metrics_latest or {}) or _time_ms(base_latest or {}) or _time_ms(z_latest or {})
    age_hours = (int(now_ms) - source_time) / 3_600_000 if source_time else None
    freshness = (
        "unavailable" if age_hours is None
        else "fresh" if -1 <= age_hours <= max_age_hours
        else "stale"
    )

    activity = {
        "active_addresses": _value(base_latest or {}, "AdrActCnt"),
        "block_height": _value(base_latest or {}, "BlkHgt"),
        "time": (base_latest or {}).get("time"),
    }
    values_available = [
        value for value in (mvrv, cap_market, cap_realized, mvrv_z, activity["active_addresses"])
        if value is not None
    ]
    status = (
        "unavailable" if not values_available
        else "stale" if freshness == "stale"
        else "ok" if mvrv is not None and cap_realized is not None
        else "partial"
    )
    latest_metric_time = _time_ms(metrics_latest or {}) or source_time
    mvrv_change = (
        _seven_day_change(metric_rows, "CapMVRVCur", latest_metric_time)
        if latest_metric_time else None
    )
    realized_change = (
        _seven_day_change(metric_rows, "CapRealUSD", latest_metric_time)
        if latest_metric_time else None
    )
    market_change = (
        _seven_day_change(metric_rows, "CapMrktCurUSD", latest_metric_time)
        if latest_metric_time else None
    )

    optional_errors = payload.get("onchain_errors")
    if not isinstance(optional_errors, Mapping):
        optional_errors = {}
    warnings: list[str] = []
    if freshness == "stale":
        warnings.append("coinmetrics_daily_onchain_data_stale")
    if mvrv is None:
        warnings.append("coinmetrics_mvrv_unavailable_on_community_tier")
    if mvrv_z is None:
        warnings.append("coinmetrics_mvrv_zscore_unavailable_on_community_tier")

    return {
        "status": status,
        "freshness": freshness,
        "source": payload.get("source", "Coin Metrics Community API"),
        "source_time": (
            datetime.fromtimestamp(source_time / 1000, timezone.utc).isoformat()
            if source_time else None
        ),
        "age_hours": round(max(0.0, age_hours), 2) if age_hours is not None else None,
        "market_cap_usd": cap_market,
        "realized_cap_usd": cap_realized,
        "mvrv": round(mvrv, 6) if mvrv is not None else None,
        "mvrv_zscore": round(mvrv_z, 6) if mvrv_z is not None else None,
        "nupl_derived": round(nupl, 6) if nupl is not None else None,
        "active_addresses": activity["active_addresses"],
        "block_height": activity["block_height"],
        "seven_day_changes_pct": {
            "mvrv": round(mvrv_change, 4) if mvrv_change is not None else None,
            "market_cap": round(market_change, 4) if market_change is not None else None,
            "realized_cap": round(realized_change, 4) if realized_change is not None else None,
        },
        "metric_rows": len(metric_rows),
        "activity_rows": len(base_rows),
        "mvrv_z_rows": len(z_rows),
        "optional_errors": dict(optional_errors),
        "warnings": warnings,
        "use": "slow_daily_context_only_not_an_intraday_vote",
        "limitations": [
            "Daily data is not an intraday signal and may be delayed or unavailable on the Community tier.",
            "NUPL is calculated here from (market capitalization - realized capitalization) / market capitalization; it is labelled as derived.",
            "SOPR is not supplied by this Coin Metrics adapter and is not estimated.",
            "MVRV Z-score is shown only when the source returns CapMVRVZ.",
            "Coin Metrics Community data is licensed for community non-commercial use; review terms before redistribution or commercial deployment.",
        ],
    }
