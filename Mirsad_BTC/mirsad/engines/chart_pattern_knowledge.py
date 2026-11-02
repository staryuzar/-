from __future__ import annotations

import math
from statistics import median
from typing import Any

SUPPORTED_PATTERN_IDS = (
    "doji", "dragonfly_doji", "gravestone_doji", "long_legged_doji",
    "hammer", "hanging_man", "inverted_hammer", "shooting_star",
    "bullish_marubozu", "bearish_marubozu", "spinning_top",
    "bullish_engulfing", "bearish_engulfing", "bullish_harami",
    "bearish_harami", "harami_cross", "piercing_line", "dark_cloud_cover",
    "tweezer_bottom", "tweezer_top", "inside_bar", "outside_bar",
    "morning_star", "evening_star", "three_white_soldiers", "three_black_crows",
)

def _features(bar: dict[str, Any]) -> dict[str, float | bool]:
    o, h, low, c = (float(bar[k]) for k in ("open", "high", "low", "close"))
    if not all(math.isfinite(x) for x in (o, h, low, c)):
        raise ValueError("OHLC candle contains a non-finite price")
    if low <= 0 or h < low or h < max(o, c) or low > min(o, c):
        raise ValueError("OHLC candle has inconsistent high/low bounds")
    span = max(h - low, 1e-12)
    body = abs(c - o)
    upper = max(0.0, h - max(o, c))
    lower = max(0.0, min(o, c) - low)
    return {
        "open": o, "high": h, "low": low, "close": c, "range": span,
        "body": body, "body_ratio": body / span,
        "upper": upper, "lower": lower,
        "upper_ratio": upper / span, "lower_ratio": lower / span,
        "bullish": c > o, "bearish": c < o,
        "body_top": max(o, c), "body_bottom": min(o, c),
        "close_location": (c - low) / span,
    }

def _prior_trend(features: list[dict[str, Any]], index: int, lookback: int = 6) -> str:
    start = max(0, index - lookback)
    sample = features[start:index]
    if len(sample) < 4:
        return "UNKNOWN"
    closes = [float(x["close"]) for x in sample]
    changes = [b - a for a, b in zip(closes, closes[1:])]
    if not changes:
        return "UNKNOWN"
    up = sum(x > 0 for x in changes)
    down = sum(x < 0 for x in changes)
    net = closes[-1] - closes[0]
    scale = max(abs(closes[0]), 1e-12)
    if net / scale >= 0.001 and up / len(changes) >= 0.60:
        return "UP"
    if net / scale <= -0.001 and down / len(changes) >= 0.60:
        return "DOWN"
    return "RANGE"

def analyze_candle_patterns(
    bars: list[dict[str, Any]], *, last_candle_closed: bool = True,
) -> dict[str, Any]:
    """Detect OHLC candle formations without assigning probabilities or trade votes."""
    if not isinstance(bars, list):
        raise TypeError("bars must be a list of OHLC mappings")
    if not bars:
        return {"status": "INSUFFICIENT", "detected": [], "count": 0,
                "supported_pattern_ids": list(SUPPORTED_PATTERN_IDS)}
    features = [_features(bar) for bar in bars]
    output: list[dict[str, Any]] = []

    def add(pattern_id: str, start: int, end: int, direction: str,
            context_required: str | None = None) -> None:
        if end == len(features) - 1 and not last_candle_closed:
            state = "FORMING"
        else:
            state = "CANDIDATE_ONLY"
        trend = _prior_trend(features, end)
        output.append({
            "pattern_id": pattern_id, "index": end,
            "start_index": start, "end_index": end,
            "direction": direction,
            "confirmation_state": state,
            "uses_unconfirmed_latest_candle": state == "FORMING",
            "prior_trend": trend,
            "context_required": context_required,
            "context_match": (
                None if context_required is None else trend == context_required
            ),
            "interpretation": "RULE_MATCH_NOT_PROBABILITY",
        })

    for i, cur in enumerate(features):
        span = float(cur["range"])
        body = float(cur["body"])
        upper = float(cur["upper"])
        lower = float(cur["lower"])
        br = float(cur["body_ratio"])
        bull, bear = bool(cur["bullish"]), bool(cur["bearish"])
        trend = _prior_trend(features, i)

        if br <= 0.10:
            add("doji", i, i, "NEUTRAL")
            if lower / span >= 0.60 and upper / span <= 0.12:
                add("dragonfly_doji", i, i, "CONTEXTUAL")
            if upper / span >= 0.60 and lower / span <= 0.12:
                add("gravestone_doji", i, i, "CONTEXTUAL")
            if upper / span >= 0.30 and lower / span >= 0.30:
                add("long_legged_doji", i, i, "NEUTRAL")

        if br >= 0.90 and upper / span <= 0.06 and lower / span <= 0.06:
            if bull:
                add("bullish_marubozu", i, i, "BULLISH")
            elif bear:
                add("bearish_marubozu", i, i, "BEARISH")

        if 0.10 < br <= 0.32 and upper / span >= 0.20 and lower / span >= 0.20:
            add("spinning_top", i, i, "NEUTRAL")

        body_near_high = float(cur["close_location"]) >= 0.62
        body_near_low = float(cur["close_location"]) <= 0.38
        if body > 0 and lower >= max(body * 2.0, span * 0.42) and upper <= max(body * 0.35, span * 0.08) and body_near_high:
            if trend == "DOWN":
                add("hammer", i, i, "BULLISH", "DOWN")
            elif trend == "UP":
                add("hanging_man", i, i, "BEARISH", "UP")
        if body > 0 and upper >= max(body * 2.0, span * 0.42) and lower <= max(body * 0.35, span * 0.08) and body_near_low:
            if trend == "DOWN":
                add("inverted_hammer", i, i, "BULLISH", "DOWN")
            elif trend == "UP":
                add("shooting_star", i, i, "BEARISH", "UP")

        if i >= 1:
            prev = features[i - 1]
            prev_top, prev_bottom = float(prev["body_top"]), float(prev["body_bottom"])
            curr_top, curr_bottom = float(cur["body_top"]), float(cur["body_bottom"])
            previous_bull = bool(prev["bullish"])
            previous_bear = bool(prev["bearish"])

            # Harami: the second real body is contained by the first.
            contained = curr_top <= prev_top and curr_bottom >= prev_bottom
            if previous_bear and bull and contained:
                add("bullish_harami", i - 1, i, "BULLISH", "DOWN")
            if previous_bull and bear and contained:
                add("bearish_harami", i - 1, i, "BEARISH", "UP")
            if br <= 0.10 and float(prev["body_ratio"]) >= 0.45 and contained:
                add("harami_cross", i - 1, i, "CONTEXTUAL")

            # Engulfing: the second real body spans the first real body.
            engulfed = curr_top >= prev_top and curr_bottom <= prev_bottom
            if previous_bear and bull and engulfed:
                add("bullish_engulfing", i - 1, i, "BULLISH", "DOWN")
            if previous_bull and bear and engulfed:
                add("bearish_engulfing", i - 1, i, "BEARISH", "UP")

            if float(cur["high"]) < float(prev["high"]) and float(cur["low"]) > float(prev["low"]):
                add("inside_bar", i - 1, i, "NEUTRAL")
            if float(cur["high"]) > float(prev["high"]) and float(cur["low"]) < float(prev["low"]):
                add("outside_bar", i - 1, i, "CONTEXTUAL")
            midpoint = (prev_top + prev_bottom) / 2
            if (
                previous_bear and bull
                and float(cur["open"]) < midpoint
                and float(cur["close"]) > midpoint
                and float(cur["close"]) < prev_top
            ):
                add("piercing_line", i - 1, i, "BULLISH", "DOWN")
            if (
                previous_bull and bear
                and float(cur["open"]) > midpoint
                and float(cur["close"]) < midpoint
                and float(cur["close"]) > prev_bottom
            ):
                add("dark_cloud_cover", i - 1, i, "BEARISH", "UP")

            tolerance = max(
                median([float(x["range"]) for x in features[max(0, i - 14):i]]) * 0.15,
                abs(float(cur["close"])) * 0.0001,
            )
            if abs(float(cur["low"]) - float(prev["low"])) <= tolerance:
                add("tweezer_bottom", i - 1, i, "BULLISH", "DOWN")
            if abs(float(cur["high"]) - float(prev["high"])) <= tolerance:
                add("tweezer_top", i - 1, i, "BEARISH", "UP")

        if i >= 2:
            first, middle = features[i - 2], features[i - 1]
            first_body = float(first["body"])
            middle_body = float(middle["body"])
            last_body = float(cur["body"])
            first_mid = (float(first["body_top"]) + float(first["body_bottom"])) / 2
            if bool(first["bearish"]) and middle_body <= max(first_body * 0.55, 1e-12) and bull and last_body >= first_body * 0.35 and float(cur["close"]) > first_mid:
                add("morning_star", i - 2, i, "BULLISH", "DOWN")
            if bool(first["bullish"]) and middle_body <= max(first_body * 0.55, 1e-12) and bear and last_body >= first_body * 0.35 and float(cur["close"]) < first_mid:
                add("evening_star", i - 2, i, "BEARISH", "UP")
            trio = features[i - 2:i + 1]
            strong = all(float(x["body_ratio"]) >= 0.45 for x in trio)
            if strong and all(bool(x["bullish"]) for x in trio) and float(trio[0]["close"]) < float(trio[1]["close"]) < float(trio[2]["close"]):
                add("three_white_soldiers", i - 2, i, "BULLISH")
            if strong and all(bool(x["bearish"]) for x in trio) and float(trio[0]["close"]) > float(trio[1]["close"]) > float(trio[2]["close"]):
                add("three_black_crows", i - 2, i, "BEARISH")

    # Stable de-duplication guards against duplicate rule paths.
    unique: dict[tuple[str, int, int], dict[str, Any]] = {}
    for item in output:
        unique[(item["pattern_id"], item["start_index"], item["end_index"])] = item
    detected = sorted(unique.values(), key=lambda x: (x["end_index"], x["start_index"], x["pattern_id"]))
    return {
        "status": "READY" if detected else "NO_PATTERN_CANDIDATES",
        "count": len(detected),
        "detected": detected[-100:],
        "supported_pattern_ids": list(SUPPORTED_PATTERN_IDS),
        "limitations": [
            "Rule matches are candidates, not probabilities, expected returns or trading instructions.",
            "Gap-dependent textbook rules are adapted for continuous crypto markets and must be validated separately.",
            "Reversal context is reported separately; a geometric match without matching prior trend is not a confirmed reversal.",
            "Patterns using the current unclosed candle are marked FORMING.",
        ],
    }

__all__ = ["SUPPORTED_PATTERN_IDS", "analyze_candle_patterns"]
