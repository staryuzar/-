from __future__ import annotations

import math
from typing import Callable, Mapping, Sequence

from .indicators import technical_profile
from .models import Bar
from .providers import binance
from .quality import utc_now_ms, validate_bars


# Long frames set the regime; mid frames describe the setup; fast frames time entries.
TIMEFRAME_SPECS: dict[str, dict[str, object]] = {
    "1d": {"weight": 0.25, "role": "daily_regime", "max_age_seconds": 172800},
    "4h": {"weight": 0.25, "role": "swing_structure", "max_age_seconds": 43200},
    "1h": {"weight": 0.20, "role": "intraday_bias", "max_age_seconds": 10800},
    "15m": {"weight": 0.18, "role": "setup_confirmation", "max_age_seconds": 2700},
    "5m": {"weight": 0.09, "role": "entry_timing", "max_age_seconds": 900},
    "1m": {"weight": 0.03, "role": "microstructure_timing", "max_age_seconds": 180},
}


def _weighted_score(
    frames: Mapping[str, Mapping[str, object]],
    names: Sequence[str],
) -> float | None:
    selected = [
        (name, frames[name])
        for name in names
        if name in frames and frames[name].get("status") == "fresh"
        and isinstance(frames[name].get("score"), (int, float))
    ]
    if not selected:
        return None
    total_weight = sum(float(TIMEFRAME_SPECS[name]["weight"]) for name, _ in selected)
    if total_weight <= 0:
        return None
    return sum(
        float(row["score"]) * float(TIMEFRAME_SPECS[name]["weight"])
        for name, row in selected
    ) / total_weight


def build_multi_timeframe_profile(
    *,
    symbol: str = "BTCUSDT",
    now_ms: int | None = None,
    preloaded_bars: Mapping[str, Sequence[Bar]] | None = None,
    fetcher: Callable[..., list[Bar]] | None = None,
) -> dict:
    """
    Build a top-down BTC trend map from 1D/4H/1H/15M/5M/1M completed candles.

    1D/4H establish the market regime, 1H/15M describe the active setup,
    and 5M/1M provide execution timing. Missing or stale frames are reported
    independently; no missing score is replaced with zero.
    """
    symbol = symbol.upper().strip()
    if not symbol.isalnum() or not symbol.startswith("BTC"):
        raise ValueError("The multi-timeframe engine accepts BTC symbols only.")

    now = utc_now_ms() if now_ms is None else int(now_ms)
    reader = fetcher or binance.fetch_spot_klines
    seed = dict(preloaded_bars or {})
    frames: dict[str, dict[str, object]] = {}
    errors: dict[str, str] = {}

    for interval, spec in TIMEFRAME_SPECS.items():
        try:
            bars = list(seed[interval]) if interval in seed else reader(
                symbol, interval, 200, now_ms=now,
            )
            freshness = validate_bars(
                bars,
                min_bars=60,
                max_age_seconds=float(spec["max_age_seconds"]),
                now_ms=now,
            )
            if freshness.get("status") != "fresh":
                frames[interval] = {
                    "status": freshness.get("status", "incomplete"),
                    "role": spec["role"],
                    "weight": spec["weight"],
                    "age_seconds": freshness.get("age_seconds"),
                    "reason": freshness.get("reason"),
                    "score": None,
                }
                continue

            profile = technical_profile(bars)
            if profile.get("status") != "ok":
                frames[interval] = {
                    "status": "incomplete",
                    "role": spec["role"],
                    "weight": spec["weight"],
                    "age_seconds": freshness.get("age_seconds"),
                    "reason": profile.get("reason"),
                    "score": None,
                }
                continue

            score = float(profile["score"])
            if not math.isfinite(score) or not -1.0 <= score <= 1.0:
                raise ValueError("Timeframe score is outside [-1, 1].")
            frames[interval] = {
                "status": "fresh",
                "role": spec["role"],
                "weight": spec["weight"],
                "age_seconds": freshness.get("age_seconds"),
                "observed_at_utc": freshness.get("observed_at_utc"),
                "score": round(score, 6),
                "state": profile["state"],
                "close": profile["close"],
                "last_bar": {
                    "open_time_ms": bars[-1].open_time_ms,
                    "close_time_ms": bars[-1].close_time_ms,
                    "open": bars[-1].open,
                    "high": bars[-1].high,
                    "low": bars[-1].low,
                    "close": bars[-1].close,
                    "volume": bars[-1].volume,
                },
                "ema20": profile["ema20"],
                "ema50": profile["ema50"],
                "rsi14": profile["rsi14"],
                "atr14": profile["atr14"],
                "breakout": profile["breakout"],
            }
        except Exception as exc:
            errors[interval] = f"{type(exc).__name__}: {exc}"[:240]
            frames[interval] = {
                "status": "error",
                "role": spec["role"],
                "weight": spec["weight"],
                "score": None,
                "reason": errors[interval],
            }

    fresh_names = [
        name for name, row in frames.items() if row.get("status") == "fresh"
    ]
    macro_names = [name for name in ("1d", "4h") if name in fresh_names]
    coverage_weight = sum(
        float(TIMEFRAME_SPECS[name]["weight"]) for name in fresh_names
    )
    warnings: list[str] = []
    blockers: list[str] = []
    if len(fresh_names) < 3:
        blockers.append("insufficient_fresh_timeframes")
    if not macro_names:
        blockers.append("missing_daily_or_four_hour_context")

    score = None
    if not blockers:
        score = _weighted_score(frames, list(TIMEFRAME_SPECS))
        if score is None:
            blockers.append("timeframe_score_unavailable")

    macro_score = _weighted_score(frames, ("1d", "4h"))
    intraday_score = _weighted_score(frames, ("1h", "15m"))
    timing_score = _weighted_score(frames, ("5m", "1m"))

    if score is None:
        state = "incomplete"
        direction = "HOLD"
        alignment = None
    else:
        direction = "BUY" if score >= 0.20 else ("SELL" if score <= -0.20 else "HOLD")
        state = "bullish" if direction == "BUY" else ("bearish" if direction == "SELL" else "mixed")
        total = coverage_weight
        positive_weight = sum(
            float(TIMEFRAME_SPECS[name]["weight"])
            for name in fresh_names if float(frames[name]["score"]) >= 0.10
        )
        negative_weight = sum(
            float(TIMEFRAME_SPECS[name]["weight"])
            for name in fresh_names if float(frames[name]["score"]) <= -0.10
        )
        alignment = round(max(positive_weight, negative_weight) / total, 4) if total else None

    if "1d" not in fresh_names:
        warnings.append("daily_regime_unavailable")
    if "4h" not in fresh_names:
        warnings.append("four_hour_structure_unavailable")
    if "1m" not in fresh_names or "5m" not in fresh_names:
        warnings.append("micro_timing_incomplete")

    macro_conflict = (
        len(macro_names) == 2
        and abs(float(frames["1d"]["score"])) >= 0.20
        and abs(float(frames["4h"]["score"])) >= 0.20
        and float(frames["1d"]["score"]) * float(frames["4h"]["score"]) < 0
    )
    if macro_conflict:
        warnings.append("daily_and_four_hour_regimes_conflict")

    countertrend_setup = (
        macro_score is not None and intraday_score is not None
        and abs(macro_score) >= 0.20 and abs(intraday_score) >= 0.20
        and macro_score * intraday_score < 0
    )
    if countertrend_setup:
        warnings.append("intraday_setup_runs_against_higher_timeframe")

    return {
        "status": "ok" if not blockers else "incomplete",
        "symbol": symbol,
        "as_of_utc_ms": now,
        "score": round(score, 6) if score is not None else None,
        "state": state,
        "direction": direction,
        "alignment_ratio": alignment,
        "coverage": {
            "fresh_frames": len(fresh_names),
            "total_frames": len(TIMEFRAME_SPECS),
            "weight_covered": round(coverage_weight, 4),
            "names": fresh_names,
        },
        "macro_score": round(macro_score, 6) if macro_score is not None else None,
        "intraday_score": round(intraday_score, 6) if intraday_score is not None else None,
        "timing_score": round(timing_score, 6) if timing_score is not None else None,
        "macro_conflict": macro_conflict,
        "countertrend_setup": countertrend_setup,
        "frames": frames,
        "warnings": warnings,
        "blockers": blockers,
        "errors": errors,
        "roles": {
            "1d": "نظام السوق العام",
            "4h": "الاتجاه البنيوي",
            "1h": "ميل التداول داخل اليوم",
            "15m": "تأكيد الإعداد",
            "5m": "توقيت الدخول",
            "1m": "تفاصيل التنفيذ الدقيقة",
        },
        "interpretation": (
            "Composite trend score across independently validated timeframes; "
            "not a probability of profit."
        ),
    }
