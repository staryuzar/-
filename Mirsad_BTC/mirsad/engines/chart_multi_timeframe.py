from __future__ import annotations

from typing import Any

from .chart_structure_knowledge import analyze_chart_structure_knowledge

TIMEFRAME_MS = {
    "1m": 60_000,
    "5m": 5 * 60_000,
    "15m": 15 * 60_000,
    "1h": 60 * 60_000,
    "4h": 4 * 60 * 60_000,
    "1d": 24 * 60 * 60_000,
    "1w": 7 * 24 * 60 * 60_000,
}
TIMEFRAME_ORDER = tuple(TIMEFRAME_MS)


def analyze_multi_timeframe_structure(
    bars_by_timeframe: dict[str, list[dict[str, Any]]],
    *,
    as_of_ms: int,
    last_candle_closed_by_timeframe: dict[str, bool] | None = None,
) -> dict[str, Any]:
    """Compare independently analysed, timestamp-aligned closed candle series.

    Each timeframe requires open_time_ms on every candle. Bars whose scheduled
    close is after as_of_ms are excluded, even when caller says they are closed.
    No directions are weighted or converted into trade instructions.
    """
    if not isinstance(bars_by_timeframe, dict):
        raise TypeError("bars_by_timeframe must be a mapping")
    if not isinstance(as_of_ms, int) or as_of_ms <= 0:
        raise ValueError("as_of_ms must be a positive Unix timestamp in milliseconds")

    closed_flags = last_candle_closed_by_timeframe or {}
    reports: dict[str, Any] = {}
    errors: dict[str, str] = {}

    ordered = [tf for tf in TIMEFRAME_ORDER if tf in bars_by_timeframe]
    unsupported = sorted(set(bars_by_timeframe) - set(TIMEFRAME_MS))
    for timeframe in unsupported:
        errors[timeframe] = "UNSUPPORTED_TIMEFRAME"

    for timeframe in ordered:
        bars = bars_by_timeframe[timeframe]
        if not isinstance(bars, list):
            errors[timeframe] = "BARS_MUST_BE_LIST"
            continue
        if not bars:
            errors[timeframe] = "NO_CANDLES"
            continue
        duration = TIMEFRAME_MS[timeframe]
        timestamps: list[int] = []
        valid = True
        for index, bar in enumerate(bars):
            try:
                stamp = int(bar["open_time_ms"])
            except (KeyError, TypeError, ValueError, OverflowError):
                errors[timeframe] = f"MISSING_OPEN_TIME_MS_AT_INDEX_{index}"
                valid = False
                break
            if timestamps and stamp <= timestamps[-1]:
                errors[timeframe] = "CANDLES_NOT_STRICTLY_CHRONOLOGICAL"
                valid = False
                break
            timestamps.append(stamp)
        if not valid:
            continue

        # A caller's closed flag cannot override the timestamp cutoff.
        selected = [
            bar for bar, stamp in zip(bars, timestamps)
            if stamp + duration <= as_of_ms
        ]
        if not bool(closed_flags.get(timeframe, True)) and selected and selected[-1] is bars[-1]:
            selected = selected[:-1]
        if len(selected) < 8:
            errors[timeframe] = "INSUFFICIENT_CLOSED_CANDLES"
            continue
        try:
            report = analyze_chart_structure_knowledge(selected, last_candle_closed=True)
        except (TypeError, ValueError, OverflowError) as exc:
            errors[timeframe] = f"{type(exc).__name__}: {exc}"
            continue
        candle_gaps = []
        for gap_index, (left_open, right_open) in enumerate(zip(
            timestamps[:len(selected) - 1],
            timestamps[1:len(selected)],
        )):
            delta_ms = right_open - left_open
            if delta_ms > duration * 1.5:
                candle_gaps.append({
                    "after_candle_index": gap_index,
                    "gap_duration_ms": delta_ms,
                    "estimated_missing_intervals": max(
                        1, int(round(delta_ms / duration)) - 1
                    ),
                })
        if candle_gaps:
            report = {
                **report,
                "structure_status_before_gap_check": report.get("status"),
                "status": "PARTIAL",
            }
        latest_close_ms = timestamps[len(selected) - 1] + duration
        staleness_ms = as_of_ms - latest_close_ms
        if staleness_ms < 0:
            errors[timeframe] = "FUTURE_CANDLE_SELECTED"
            continue
        max_allowed_staleness_ms = duration * 2
        if staleness_ms > max_allowed_staleness_ms:
            errors[timeframe] = "STALE_TIMEFRAME_DATA"
            continue
        report = {
            **report,
            "timeframe": timeframe,
            "last_open_time_ms": timestamps[len(selected) - 1],
            "last_close_time_ms": latest_close_ms,
            "staleness_ms": staleness_ms,
            "max_allowed_staleness_ms": max_allowed_staleness_ms,
            "data_continuity": "GAPS_DETECTED" if candle_gaps else "CONTIGUOUS",
            "candle_gaps": candle_gaps,
            "as_of_ms": as_of_ms,
        }
        reports[timeframe] = report

    directional = {
        timeframe: report["structure_direction"]
        for timeframe, report in reports.items()
        if report.get("status") == "READY"
        and report.get("structure_direction") in {"BULLISH", "BEARISH"}
    }
    bullish = [tf for tf, direction in directional.items() if direction == "BULLISH"]
    bearish = [tf for tf, direction in directional.items() if direction == "BEARISH"]
    if len(directional) < 2:
        alignment = "INSUFFICIENT_TIMEFRAME_CONFLUENCE"
    elif bullish and bearish:
        alignment = "MIXED_TIMEFRAME_STRUCTURE"
    elif bullish:
        alignment = "BULLISH_TIMEFRAME_CONFLUENCE"
    else:
        alignment = "BEARISH_TIMEFRAME_CONFLUENCE"

    eligible_timeframes = [
        timeframe for timeframe, report in reports.items()
        if report.get("status") == "READY"
    ]
    return {
        "status": "READY" if len(eligible_timeframes) >= 2 else "PARTIAL",
        "as_of_ms": as_of_ms,
        "available_timeframes": list(reports),
        "eligible_timeframes": eligible_timeframes,
        "errors": errors,
        "timeframe_reports": reports,
        "directional_structure_by_timeframe": directional,
        "alignment": alignment,
        "bullish_timeframes": bullish,
        "bearish_timeframes": bearish,
        "interpretation": "STRUCTURE_CONFLUENCE_ONLY_NOT_A_TRADE_SIGNAL",
        "limitations": [
            "Each timeframe must supply genuine open_time_ms values; untimestamped screenshot bars cannot be combined.",
            "Scheduled close times are derived from the declared timeframe duration; exchange-specific candle calendars may differ.",
            "Timeframes are compared at or before one explicit as_of_ms cutoff; no future candle may enter a frame.",
            "A matching multi-timeframe structure is descriptive confluence, not a probability or a trade recommendation.",
            "A frame whose latest closed candle is more than two declared intervals stale is excluded from confluence.",
        ],
    }


def analyze_stored_multi_timeframe_structure(
    *,
    symbol: str,
    venue: str | None,
    as_of_ms: int,
    timeframes: tuple[str, ...] = ("1m", "5m", "15m", "1h", "4h", "1d", "1w"),
    limit: int = 120,
    db_path: str | None = None,
) -> dict[str, Any]:
    """Analyse Engine 1's stored closed candles as an isolated Engine 2 report.

    The adapter reads a single explicitly selected venue. It derives a weekly
    bar from seven closed UTC daily candles only when no native weekly data is
    stored. It does not modify market ingestion, blend venues, or affect sizing.
    """
    clean_symbol = str(symbol).strip().upper()
    clean_venue = str(venue or "").strip()
    if not clean_venue:
        return {
            "status": "PARTIAL",
            "source": "market_candles_sqlite",
            "symbol": clean_symbol,
            "venue": None,
            "requested_timeframes": list(timeframes),
            "available_timeframes": [],
            "loaded_candle_counts": {},
            "errors": {"venue": "NO_PRIMARY_VENUE_AVAILABLE"},
            "alignment": "INSUFFICIENT_TIMEFRAME_CONFLUENCE",
            "interpretation": "STRUCTURE_CONFLUENCE_ONLY_NOT_A_TRADE_SIGNAL",
        }

    from ..storage import load_candles_by_timeframe

    try:
        kwargs: dict[str, Any] = {
            "symbol": clean_symbol,
            "venue": clean_venue,
            "timeframes": timeframes,
            "as_of_ms": as_of_ms,
            "limit": limit,
        }
        if db_path is not None:
            kwargs["db_path"] = db_path
        bars_by_timeframe = load_candles_by_timeframe(**kwargs)
    except (TypeError, ValueError, OSError) as exc:
        return {
            "status": "ERROR",
            "source": "market_candles_sqlite",
            "symbol": clean_symbol,
            "venue": clean_venue,
            "requested_timeframes": list(timeframes),
            "available_timeframes": [],
            "loaded_candle_counts": {},
            "errors": {"storage": f"{type(exc).__name__}: {exc}"},
            "alignment": "INSUFFICIENT_TIMEFRAME_CONFLUENCE",
            "interpretation": "STRUCTURE_CONFLUENCE_ONLY_NOT_A_TRADE_SIGNAL",
        }

    report = analyze_multi_timeframe_structure(
        bars_by_timeframe,
        as_of_ms=as_of_ms,
        last_candle_closed_by_timeframe={
            timeframe: True for timeframe in bars_by_timeframe
        },
    )
    return {
        **report,
        "source": "market_candles_sqlite",
        "symbol": clean_symbol,
        "venue": clean_venue,
        "requested_timeframes": list(timeframes),
        "loaded_candle_counts": {
            timeframe: len(bars) for timeframe, bars in bars_by_timeframe.items()
        },
        "candle_source_intervals": {
            timeframe: sorted({
                str(bar.get("source_interval", timeframe)) for bar in bars
            })
            for timeframe, bars in bars_by_timeframe.items()
        },
        "weekly_derivation": (
            "Seven consecutive closed UTC daily candles, Monday 00:00 UTC boundary"
            if any(
                bar.get("source_interval") == "1d_aggregated_to_1w_utc_monday"
                for bar in bars_by_timeframe.get("1w", [])
            )
            else "Native weekly candles if present; otherwise unavailable until seven complete daily candles exist"
        ),
        "venue_policy": "SINGLE_PRIMARY_VENUE_NO_CROSS_EXCHANGE_CANDLE_MERGE",
        "does_not_affect_decision_engine": True,
    }


__all__ = ["TIMEFRAME_MS", "analyze_multi_timeframe_structure", "analyze_stored_multi_timeframe_structure"]
