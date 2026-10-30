from __future__ import annotations

import math


def derivatives_profile(
    *, funding_rate: float | None, open_interest_change_pct: float | None,
    taker_buy_sell_ratio: float | None, global_long_short_ratio: float | None = None,
) -> dict:
    """Directional pressure uses taker flow; OI is context, funding is a crowding risk."""
    values = (funding_rate, open_interest_change_pct, taker_buy_sell_ratio, global_long_short_ratio)
    if any(v is not None and (not math.isfinite(float(v))) for v in values):
        raise ValueError("Derivatives inputs must be finite or None.")
    if taker_buy_sell_ratio is None or taker_buy_sell_ratio <= 0:
        return {"status": "incomplete", "score": None, "reason": "Taker buy/sell ratio is required."}
    taker_score = max(-1.0, min(1.0, math.log(taker_buy_sell_ratio) / math.log(1.5)))
    crowding = "neutral"
    crowd_penalty = 0.0
    if funding_rate is not None:
        if funding_rate >= 0.0005:
            crowding, crowd_penalty = "long_crowded", -0.20
        elif funding_rate <= -0.0005:
            crowding, crowd_penalty = "short_crowded", 0.20
    score = max(-1.0, min(1.0, 0.85 * taker_score + crowd_penalty))
    if abs(score) < 0.12:
        state = "balanced"
    else:
        state = "bullish" if score > 0 else "bearish"
    return {
        "status": "ok", "score": score, "state": state,
        "funding_rate": funding_rate, "open_interest_change_pct": open_interest_change_pct,
        "taker_buy_sell_ratio": taker_buy_sell_ratio,
        "global_long_short_ratio": global_long_short_ratio,
        "crowding": crowding,
        "open_interest_interpretation": (
            "rising" if open_interest_change_pct is not None and open_interest_change_pct > 1.0
            else ("falling" if open_interest_change_pct is not None and open_interest_change_pct < -1.0 else "flat_or_unavailable")
        ),
        "note": "Open interest is not directional by itself; long/short account ratios are crowding context, not a standalone signal.",
    }
