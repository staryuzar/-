from __future__ import annotations

from datetime import datetime, timezone
import time
from typing import Iterable

from .models import Bar


def utc_now_ms() -> int:
    return int(time.time() * 1000)


def freshness(observed_at_ms: int | None, max_age_seconds: float, *, now_ms: int | None = None) -> dict:
    if observed_at_ms is None or observed_at_ms <= 0:
        return {"status": "unavailable", "age_seconds": None, "observed_at_utc": None}
    now = utc_now_ms() if now_ms is None else int(now_ms)
    age = (now - int(observed_at_ms)) / 1000.0
    stamp = datetime.fromtimestamp(observed_at_ms / 1000, tz=timezone.utc).isoformat()
    if age < -5:
        status = "clock_skew"
    elif age > max_age_seconds:
        status = "stale"
    else:
        status = "fresh"
    # Small negative ages come from sequential HTTP requests against a
    # snapshot clock captured at function entry; report zero, not negative age.
    return {"status": status, "age_seconds": round(max(0.0, age), 3), "observed_at_utc": stamp}


def validate_bars(
    bars: Iterable[Bar], *, min_bars: int = 60, max_age_seconds: float = 180.0,
    now_ms: int | None = None,
) -> dict:
    items = list(bars)
    if len(items) < min_bars:
        return {"status": "incomplete", "count": len(items), "reason": f"Need at least {min_bars} completed bars."}
    if any(not bar.is_closed for bar in items):
        return {"status": "open_bar_present", "count": len(items), "reason": "Open candles are not valid for a decision."}
    times = [bar.open_time_ms for bar in items]
    if times != sorted(times) or len(set(times)) != len(times):
        return {"status": "invalid_order", "count": len(items), "reason": "Candles must be ordered and unique."}
    last = items[-1]
    age = freshness(last.close_time_ms, max_age_seconds, now_ms=now_ms)
    if age["status"] != "fresh":
        return {"status": age["status"], "count": len(items), "reason": "Latest completed candle is not fresh.", **age}
    return {"status": "fresh", "count": len(items), "reason": None, **age}
