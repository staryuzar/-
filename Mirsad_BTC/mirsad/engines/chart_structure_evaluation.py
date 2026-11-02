from __future__ import annotations

import hashlib
import json
import math
import time
from statistics import mean, median
from typing import Any

from ..config import DB_PATH
from ..storage import CANDLE_INTERVAL_MS, connect, load_candles_by_timeframe
from .visual_knowledge import MARKET_STRUCTURE_CATALOG, seed_visual_knowledge

DEFAULT_HORIZONS = (1, 3, 5, 10, 20)
VALID_DATA_SPLITS = frozenset({"train", "validation", "test"})

STRUCTURE_PATTERN_IDS = frozenset({
    "double_top",
    "double_bottom",
    "head_and_shoulders",
    "inverse_head_and_shoulders",
    "ascending_triangle",
    "descending_triangle",
    "symmetrical_triangle",
    "rising_wedge",
    "falling_wedge",
    "rising_channel",
    "falling_channel",
    "horizontal_channel",
    "bull_flag",
    "bear_flag",
    "bull_pennant",
    "bear_pennant",
})

_REVERSAL_DIRECTIONS = {
    "double_top": "BEARISH",
    "double_bottom": "BULLISH",
    "head_and_shoulders": "BEARISH",
    "inverse_head_and_shoulders": "BULLISH",
}


def _finite_positive(value: Any, field: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a finite positive number") from exc
    if not math.isfinite(number) or number <= 0:
        raise ValueError(f"{field} must be a finite positive number")
    return number


def _normalise_bars(
    bars: list[dict[str, Any]],
    timeframe: str,
) -> list[dict[str, float | int]]:
    interval_ms = CANDLE_INTERVAL_MS.get(timeframe)
    if interval_ms is None:
        raise ValueError(f"Unsupported timeframe: {timeframe}")
    if not isinstance(bars, list) or len(bars) < 2:
        raise ValueError("At least two closed OHLC bars are required")

    normalised: list[dict[str, float | int]] = []
    previous_open_time: int | None = None
    for position, source in enumerate(bars):
        if not isinstance(source, dict):
            raise ValueError(f"Bar {position} must be an object")
        closed = source.get("closed", source.get("is_closed"))
        if closed is not True and closed != 1:
            raise ValueError(f"Bar {position} is not explicitly marked closed")

        try:
            open_time_ms = int(source["open_time_ms"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"Bar {position} needs a valid open_time_ms") from exc
        if open_time_ms <= 0:
            raise ValueError(f"Bar {position} has a non-positive open_time_ms")
        if previous_open_time is not None:
            delta = open_time_ms - previous_open_time
            if delta != interval_ms:
                raise ValueError(
                    "OHLC bars must be strictly chronological and contiguous; "
                    f"bar {position} is separated by {delta} ms, expected {interval_ms} ms"
                )

        open_price = _finite_positive(source.get("open"), f"bar {position} open")
        high_price = _finite_positive(source.get("high"), f"bar {position} high")
        low_price = _finite_positive(source.get("low"), f"bar {position} low")
        close_price = _finite_positive(source.get("close"), f"bar {position} close")
        if high_price < max(open_price, close_price, low_price):
            raise ValueError(f"Bar {position} has an inconsistent high")
        if low_price > min(open_price, close_price, high_price):
            raise ValueError(f"Bar {position} has an inconsistent low")

        normalised.append({
            "open_time_ms": open_time_ms,
            "open": open_price,
            "high": high_price,
            "low": low_price,
            "close": close_price,
        })
        previous_open_time = open_time_ms
    return normalised


def _dataset_fingerprint(
    bars: list[dict[str, float | int]],
    *,
    symbol: str,
    venue: str,
    timeframe: str,
    dataset_id: str,
) -> str:
    payload = {
        "schema": "mirsad-structure-event-study-v1",
        "symbol": symbol,
        "venue": venue,
        "timeframe": timeframe,
        "dataset_id": dataset_id,
        "bars": [
            [
                int(bar["open_time_ms"]),
                float(bar["open"]),
                float(bar["high"]),
                float(bar["low"]),
                float(bar["close"]),
            ]
            for bar in bars
        ],
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _event_identity(
    event: dict[str, Any],
    *,
    pattern_id: str,
    event_index: int,
    direction: str,
) -> tuple[str, int, str]:
    return pattern_id, event_index, direction


def _summarise_horizon(
    rows: list[dict[str, float | None]],
    *,
    costs_applied: bool,
) -> dict[str, Any]:
    if not rows:
        return {
            "sample_count": 0,
            "win_rate_pct": None,
            "mean_return_pct": None,
            "median_return_pct": None,
            "mean_net_return_pct": None,
            "median_net_return_pct": None,
            "mean_mae_pct": None,
            "mean_mfe_pct": None,
            "fee_adjusted_expectancy_pct": None,
            "profit_factor": None,
        }

    gross = [float(row["gross_return_pct"]) for row in rows]
    mae = [float(row["mae_pct"]) for row in rows]
    mfe = [float(row["mfe_pct"]) for row in rows]
    net = [float(row["net_return_pct"]) for row in rows] if costs_applied else []
    outcome = net if costs_applied else gross
    gains = sum(value for value in outcome if value > 0)
    losses = abs(sum(value for value in outcome if value < 0))
    profit_factor = gains / losses if losses > 0 else None

    return {
        "sample_count": len(rows),
        "win_rate_pct": round(100.0 * sum(value > 0 for value in outcome) / len(outcome), 6),
        "mean_return_pct": round(mean(gross), 6),
        "median_return_pct": round(median(gross), 6),
        "mean_net_return_pct": round(mean(net), 6) if net else None,
        "median_net_return_pct": round(median(net), 6) if net else None,
        "mean_mae_pct": round(mean(mae), 6),
        "mean_mfe_pct": round(mean(mfe), 6),
        "fee_adjusted_expectancy_pct": round(mean(net), 6) if net else None,
        "profit_factor": round(profit_factor, 6) if profit_factor is not None else None,
    }


def evaluate_structure_events(
    bars: list[dict[str, Any]],
    events: list[dict[str, Any]],
    *,
    symbol: str,
    venue: str,
    timeframe: str,
    data_split: str,
    dataset_id: str,
    split_start_ms: int,
    split_end_ms: int,
    embargo_bars: int = 0,
    market_regime: str = "UNSPECIFIED",
    horizons: tuple[int, ...] | list[int] = DEFAULT_HORIZONS,
    fee_bps_per_side: float | None = None,
    slippage_bps_per_side: float | None = None,
) -> dict[str, Any]:
    """Measure confirmed Engine 2 structure events against subsequent closed OHLC bars.

    The event candle is never used as an entry fill. Entry is the next candle's
    open; exit is the close of the selected forward horizon. Candidate and
    invalidated structures are excluded. Results are event-study statistics,
    not a portfolio backtest or a trade instruction.
    """
    clean_symbol = str(symbol).strip().upper()
    clean_venue = str(venue).strip()
    clean_timeframe = str(timeframe).strip()
    clean_dataset_id = str(dataset_id).strip()
    clean_regime = str(market_regime).strip() or "UNSPECIFIED"
    if not clean_symbol or not clean_venue or not clean_dataset_id:
        raise ValueError("symbol, venue and dataset_id are required")
    if data_split not in VALID_DATA_SPLITS:
        raise ValueError("data_split must be train, validation or test")
    if not isinstance(events, list):
        raise ValueError("events must be a list")

    requested_horizons = tuple(sorted(set(int(value) for value in horizons)))
    if not requested_horizons or any(value <= 0 for value in requested_horizons):
        raise ValueError("horizons must contain unique positive candle counts")

    if (fee_bps_per_side is None) != (slippage_bps_per_side is None):
        raise ValueError("fee and slippage assumptions must both be supplied or both omitted")
    costs_applied = fee_bps_per_side is not None
    if costs_applied:
        fee_bps_per_side = float(fee_bps_per_side)
        slippage_bps_per_side = float(slippage_bps_per_side)
        if (
            not math.isfinite(fee_bps_per_side)
            or not math.isfinite(slippage_bps_per_side)
            or fee_bps_per_side < 0
            or slippage_bps_per_side < 0
        ):
            raise ValueError("fee and slippage must be finite non-negative basis-point values")
        round_trip_cost_pct = 2.0 * (fee_bps_per_side + slippage_bps_per_side) / 100.0
    else:
        round_trip_cost_pct = None

    normalised_bars = _normalise_bars(bars, clean_timeframe)
    interval_ms = CANDLE_INTERVAL_MS[clean_timeframe]
    if (
        not isinstance(split_start_ms, int)
        or isinstance(split_start_ms, bool)
        or not isinstance(split_end_ms, int)
        or isinstance(split_end_ms, bool)
        or split_start_ms <= 0
        or split_end_ms <= split_start_ms
    ):
        raise ValueError("split_start_ms and split_end_ms must define a positive increasing time window")
    # Weekly UTC candles are anchored to Monday 00:00 UTC, while Unix
    # epoch zero was a Thursday. All other stored intervals use epoch alignment.
    interval_anchor_ms = 4 * CANDLE_INTERVAL_MS["1d"] if clean_timeframe == "1w" else 0
    if (
        (split_start_ms - interval_anchor_ms) % interval_ms
        or (split_end_ms - interval_anchor_ms) % interval_ms
    ):
        raise ValueError("split window boundaries must align to the selected candle interval")
    if not isinstance(embargo_bars, int) or isinstance(embargo_bars, bool) or embargo_bars < 0:
        raise ValueError("embargo_bars must be a non-negative integer")
    series_start_ms = int(normalised_bars[0]["open_time_ms"])
    series_end_ms = int(normalised_bars[-1]["open_time_ms"]) + interval_ms
    if split_start_ms < series_start_ms or split_end_ms > series_end_ms:
        raise ValueError("split window must be fully contained in the supplied OHLC series")
    first_split_index = next(
        (index for index, bar in enumerate(normalised_bars)
         if int(bar["open_time_ms"]) >= split_start_ms),
        len(normalised_bars),
    )
    embargo_end_index = first_split_index + embargo_bars
    known_structures = {item["structure_id"] for item in MARKET_STRUCTURE_CATALOG}
    if not STRUCTURE_PATTERN_IDS.issubset(known_structures):
        raise RuntimeError("The visual structure knowledge catalog is missing evaluated pattern ids")

    accumulators: dict[str, dict[str, Any]] = {}
    seen_events: set[tuple[str, int, str]] = set()
    counts = {
        "input_events": len(events),
        "confirmed_events": 0,
        "candidate_events_skipped": 0,
        "invalidated_events_skipped": 0,
        "duplicate_events_skipped": 0,
        "events_without_next_bar": 0,
        "events_outside_split_skipped": 0,
        "events_embargoed_at_split_start": 0,
        "events_without_any_complete_horizon": 0,
        "incomplete_horizon_samples_by_horizon": {
            str(horizon): 0 for horizon in requested_horizons
        },
    }

    for event_number, event in enumerate(events):
        if not isinstance(event, dict):
            raise ValueError(f"Event {event_number} must be an object")
        pattern_id = str(event.get("pattern_id", "")).strip()
        if pattern_id not in STRUCTURE_PATTERN_IDS:
            raise ValueError(f"Unsupported structure pattern id: {pattern_id}")

        status = str(event.get("status", "")).strip().upper()
        if status in {"CANDIDATE", "FORMING", "UNCONFIRMED"}:
            counts["candidate_events_skipped"] += 1
            continue
        if status in {"INVALIDATED", "REJECTED"}:
            counts["invalidated_events_skipped"] += 1
            continue

        if status == "CONFIRMED":
            if pattern_id not in _REVERSAL_DIRECTIONS:
                raise ValueError(
                    f"{pattern_id} must have a closed breakout status before evaluation"
                )
            direction = str(event.get("direction", "")).strip().upper()
            expected_direction = _REVERSAL_DIRECTIONS[pattern_id]
            if direction != expected_direction:
                raise ValueError(f"{pattern_id} direction must be {expected_direction}")
            raw_event_index = event.get("confirmation_index")
        elif status == "BREAKOUT_UP":
            direction = "BULLISH"
            raw_event_index = event.get("breakout_index")
            if pattern_id in _REVERSAL_DIRECTIONS:
                raise ValueError(f"{pattern_id} uses CONFIRMED reversal status")
        elif status == "BREAKOUT_DOWN":
            direction = "BEARISH"
            raw_event_index = event.get("breakout_index")
            if pattern_id in _REVERSAL_DIRECTIONS:
                raise ValueError(f"{pattern_id} uses CONFIRMED reversal status")
        else:
            raise ValueError(f"Unsupported active event status: {status}")

        try:
            event_index = int(raw_event_index)
            formation_confirmed_at = int(event.get("formation_confirmed_at"))
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"Confirmed event {event_number} needs an event index and formation_confirmed_at"
            ) from exc
        if event_index < 0 or event_index >= len(normalised_bars):
            raise ValueError(f"Event {event_number} index is outside the supplied OHLC series")
        if formation_confirmed_at < 0 or formation_confirmed_at >= event_index:
            raise ValueError(
                f"Event {event_number} must occur after all formation pivots were confirmable"
            )

        event_open_time_ms = int(normalised_bars[event_index]["open_time_ms"])
        if not split_start_ms <= event_open_time_ms < split_end_ms:
            counts["events_outside_split_skipped"] += 1
            continue
        if event_index < embargo_end_index:
            counts["events_embargoed_at_split_start"] += 1
            continue

        identity = _event_identity(
            event, pattern_id=pattern_id, event_index=event_index, direction=direction
        )
        if identity in seen_events:
            counts["duplicate_events_skipped"] += 1
            continue
        seen_events.add(identity)
        counts["confirmed_events"] += 1

        if event_index + 1 >= len(normalised_bars):
            counts["events_without_next_bar"] += 1
            continue

        accumulator = accumulators.setdefault(
            pattern_id,
            {
                "pattern_id": pattern_id,
                "direction_counts": {"BULLISH": 0, "BEARISH": 0},
                "horizon_rows": {str(horizon): [] for horizon in requested_horizons},
            },
        )
        accumulator["direction_counts"][direction] += 1
        any_horizon = False

        # The next candle's open is the earliest defensible fill after the
        # confirmed close. The signal candle itself is excluded from excursions.
        for horizon in requested_horizons:
            exit_index = event_index + horizon
            if exit_index >= len(normalised_bars):
                counts["incomplete_horizon_samples_by_horizon"][str(horizon)] += 1
                continue
            exit_close_time_ms = int(normalised_bars[exit_index]["open_time_ms"]) + interval_ms
            if exit_close_time_ms > split_end_ms:
                counts["incomplete_horizon_samples_by_horizon"][str(horizon)] += 1
                continue
            future = normalised_bars[event_index + 1:exit_index + 1]
            entry_price = float(future[0]["open"])
            exit_price = float(future[-1]["close"])
            highest = max(float(bar["high"]) for bar in future)
            lowest = min(float(bar["low"]) for bar in future)

            sign = 1.0 if direction == "BULLISH" else -1.0
            gross_return_pct = sign * (exit_price / entry_price - 1.0) * 100.0
            if direction == "BULLISH":
                mae_pct = (lowest / entry_price - 1.0) * 100.0
                mfe_pct = (highest / entry_price - 1.0) * 100.0
            else:
                mae_pct = (entry_price - highest) / entry_price * 100.0
                mfe_pct = (entry_price - lowest) / entry_price * 100.0

            net_return_pct = (
                gross_return_pct - float(round_trip_cost_pct)
                if costs_applied and round_trip_cost_pct is not None
                else None
            )
            accumulator["horizon_rows"][str(horizon)].append({
                "gross_return_pct": gross_return_pct,
                "net_return_pct": net_return_pct,
                "mae_pct": mae_pct,
                "mfe_pct": mfe_pct,
                "event_index": event_index,
                "entry_index": event_index + 1,
                "exit_index": exit_index,
                "direction": direction,
            })
            any_horizon = True

        if not any_horizon:
            counts["events_without_any_complete_horizon"] += 1

    results_by_pattern: dict[str, Any] = {}
    for pattern_id, accumulator in sorted(accumulators.items()):
        results_by_pattern[pattern_id] = {
            "pattern_id": pattern_id,
            "direction_counts": accumulator["direction_counts"],
            "horizons": {
                horizon: _summarise_horizon(rows, costs_applied=costs_applied)
                for horizon, rows in accumulator["horizon_rows"].items()
            },
        }

    fingerprint = _dataset_fingerprint(
        normalised_bars,
        symbol=clean_symbol,
        venue=clean_venue,
        timeframe=clean_timeframe,
        dataset_id=clean_dataset_id,
    )
    return {
        "schema_version": "1.0.0",
        "symbol": clean_symbol,
        "venue": clean_venue,
        "timeframe": clean_timeframe,
        "market_regime": clean_regime,
        "dataset_id": clean_dataset_id,
        "dataset_fingerprint": fingerprint,
        "data_split": data_split,
        "split_start_ms": split_start_ms,
        "split_end_ms": split_end_ms,
        "embargo_bars": embargo_bars,
        "event_source": "engine_2_confirmed_structure_events",
        "human_reviewed": False,
        "validation_status": "IN_PROGRESS",
        "empirical_status": "UNVALIDATED",
        "bar_count": len(normalised_bars),
        "bar_interval_ms": CANDLE_INTERVAL_MS[clean_timeframe],
        "entry_rule": "next_closed_candle_open_after_signal_confirmation",
        "exit_rule": "close_of_forward_horizon_candle",
        "price_basis": "direction_adjusted_close_to_close_with_intrabar_MAE_MFE",
        "costs_applied": costs_applied,
        "fee_bps_per_side": fee_bps_per_side,
        "slippage_bps_per_side": slippage_bps_per_side,
        "round_trip_cost_pct": round_trip_cost_pct,
        "horizons": list(requested_horizons),
        "counts": counts,
        "results_by_pattern": results_by_pattern,
        "overlapping_events_possible": True,
        "portfolio_backtest": False,
    }




def scan_historical_structure_events(
    bars: list[dict[str, Any]],
    *,
    timeframe: str,
    pivot_left: int = 2,
    pivot_right: int = 2,
    minimum_bars: int = 16,
    maximum_bars: int = 5000,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Replay Engine 2's confirmed pattern detectors one closed candle at a time.

    Each prefix ends at the candle being tested. Only patterns whose closed
    breakout/confirmation occurs on that final prefix candle are emitted. This
    reconstructs a historical event stream without letting later candles alter
    an earlier event. The scan is limited to a configurable number of bars.
    """
    from .chart_classical_patterns import detect_classical_reversal_patterns
    from .chart_continuation_patterns import detect_classical_continuation_patterns
    from .chart_structure_knowledge import _pivots, _true_ranges

    if not isinstance(pivot_left, int) or pivot_left < 1:
        raise ValueError("pivot_left must be a positive integer")
    if not isinstance(pivot_right, int) or pivot_right < 1:
        raise ValueError("pivot_right must be a positive integer")
    if not isinstance(minimum_bars, int) or minimum_bars < 10:
        raise ValueError("minimum_bars must be at least 10")
    if not isinstance(maximum_bars, int) or maximum_bars < minimum_bars:
        raise ValueError("maximum_bars must be greater than or equal to minimum_bars")

    normalised_bars = _normalise_bars(bars, timeframe)
    if len(normalised_bars) > maximum_bars:
        raise ValueError(
            f"Historical structure scan is limited to {maximum_bars} bars; "
            f"received {len(normalised_bars)}"
        )
    if len(normalised_bars) < minimum_bars:
        return [], {
            "status": "INSUFFICIENT",
            "bars_scanned": 0,
            "confirmed_events": 0,
            "pivot_left": pivot_left,
            "pivot_right": pivot_right,
            "lookahead_policy": "closed_prefix_replay",
        }

    true_ranges = _true_ranges(normalised_bars)
    interval_ms = CANDLE_INTERVAL_MS[timeframe]
    events_by_identity: dict[tuple[str, str, int], dict[str, Any]] = {}
    prefixes_scanned = 0

    for end_index in range(minimum_bars - 1, len(normalised_bars)):
        # Never pass bars after end_index to either detector.
        prefix = normalised_bars[:end_index + 1]
        prefixes_scanned += 1
        swing_highs = _pivots(prefix, pivot_left, pivot_right, "high")
        swing_lows = _pivots(prefix, pivot_left, pivot_right, "low")
        atr = median(true_ranges[max(0, end_index - 13):end_index + 1])

        reversal = detect_classical_reversal_patterns(
            prefix, swing_highs, swing_lows, atr=atr
        )
        continuation = detect_classical_continuation_patterns(
            prefix, swing_highs, swing_lows, atr=atr
        )
        for pattern in reversal:
            if (
                pattern.get("status") != "CONFIRMED"
                or pattern.get("confirmation_index") != end_index
            ):
                continue
            direction = str(pattern.get("direction", "")).upper()
            identity = (str(pattern["pattern_id"]), direction, end_index)
            events_by_identity[identity] = {
                **pattern,
                "event_index": end_index,
                "event_open_time_ms": int(normalised_bars[end_index]["open_time_ms"]),
                "event_close_time_ms": (
                    int(normalised_bars[end_index]["open_time_ms"]) + interval_ms
                ),
                "detector_prefix_end_index": end_index,
                "scan_method": "closed_prefix_replay",
            }

        for pattern in continuation:
            breakout_direction = pattern.get("breakout_direction")
            if (
                pattern.get("status") not in {"BREAKOUT_UP", "BREAKOUT_DOWN"}
                or pattern.get("breakout_index") != end_index
            ):
                continue
            direction = (
                "BULLISH" if breakout_direction == "UP" else "BEARISH"
            )
            identity = (str(pattern["pattern_id"]), direction, end_index)
            events_by_identity[identity] = {
                **pattern,
                "event_index": end_index,
                "event_open_time_ms": int(normalised_bars[end_index]["open_time_ms"]),
                "event_close_time_ms": (
                    int(normalised_bars[end_index]["open_time_ms"]) + interval_ms
                ),
                "detector_prefix_end_index": end_index,
                "scan_method": "closed_prefix_replay",
            }

    events = sorted(
        events_by_identity.values(),
        key=lambda event: (
            int(event["event_index"]),
            str(event["pattern_id"]),
            str(event.get("direction", "")),
        ),
    )
    return events, {
        "status": "READY",
        "bars_scanned": prefixes_scanned,
        "confirmed_events": len(events),
        "pivot_left": pivot_left,
        "pivot_right": pivot_right,
        "lookahead_policy": "closed_prefix_replay",
        "future_bars_used_for_event_detection": 0,
    }


def evaluate_stored_structure_events(
    events: list[dict[str, Any]],
    *,
    symbol: str,
    venue: str,
    timeframe: str,
    as_of_ms: int,
    data_split: str,
    dataset_id: str,
    split_start_ms: int,
    split_end_ms: int,
    embargo_bars: int = 0,
    market_regime: str = "UNSPECIFIED",
    limit: int = 2000,
    horizons: tuple[int, ...] | list[int] = DEFAULT_HORIZONS,
    fee_bps_per_side: float | None = None,
    slippage_bps_per_side: float | None = None,
    db_path: str | None = None,
) -> dict[str, Any]:
    """Evaluate events on one venue's closed candles already stored by Engine 1.

    No venue merging is permitted. The caller must provide events produced from
    a matching time-bounded analysis of the same OHLC sequence.
    """
    clean_venue = str(venue).strip()
    if not clean_venue:
        raise ValueError("venue is required; stored candle feeds must not be mixed")
    candle_map = load_candles_by_timeframe(
        symbol=symbol,
        venue=clean_venue,
        timeframes=(timeframe,),
        as_of_ms=as_of_ms,
        limit=limit,
        db_path=db_path if db_path is not None else DB_PATH,
    )
    bars = candle_map.get(timeframe, [])
    if len(bars) < 2:
        raise ValueError(
            f"Insufficient stored closed candles for {symbol} on {clean_venue} {timeframe}"
        )

    result = evaluate_structure_events(
        bars,
        events,
        symbol=symbol,
        venue=clean_venue,
        timeframe=timeframe,
        data_split=data_split,
        dataset_id=dataset_id,
        split_start_ms=split_start_ms,
        split_end_ms=split_end_ms,
        embargo_bars=embargo_bars,
        market_regime=market_regime,
        horizons=horizons,
        fee_bps_per_side=fee_bps_per_side,
        slippage_bps_per_side=slippage_bps_per_side,
    )
    result["storage_source"] = "engine_1_stored_closed_candles"
    result["as_of_ms"] = int(as_of_ms)
    result["stored_bar_count"] = len(bars)
    return result



def analyze_and_evaluate_stored_market_structures(
    *,
    symbol: str,
    venue: str,
    timeframe: str,
    as_of_ms: int,
    data_split: str,
    dataset_id: str,
    split_start_ms: int,
    split_end_ms: int,
    embargo_bars: int = 0,
    market_regime: str = "UNSPECIFIED",
    limit: int = 2000,
    horizons: tuple[int, ...] | list[int] = DEFAULT_HORIZONS,
    fee_bps_per_side: float | None = None,
    slippage_bps_per_side: float | None = None,
    db_path: str | None = None,
) -> dict[str, Any]:
    """Run Engine 2 structure detectors and the event study on stored market bars."""
    from .chart_structure_knowledge import analyze_chart_structure_knowledge

    clean_venue = str(venue).strip()
    if not clean_venue:
        raise ValueError("venue is required; stored candle feeds must not be mixed")
    candle_map = load_candles_by_timeframe(
        symbol=symbol,
        venue=clean_venue,
        timeframes=(timeframe,),
        as_of_ms=as_of_ms,
        limit=limit,
        db_path=db_path if db_path is not None else DB_PATH,
    )
    bars = candle_map.get(timeframe, [])
    if len(bars) < 16:
        raise ValueError(
            f"At least 16 stored closed candles are required to scan structures; got {len(bars)}"
        )

    structure_analysis = analyze_chart_structure_knowledge(
        bars,
        last_candle_closed=True,
    )
    events, historical_scan = scan_historical_structure_events(
        bars,
        timeframe=timeframe,
    )
    evaluation = evaluate_structure_events(
        bars,
        events,
        symbol=symbol,
        venue=clean_venue,
        timeframe=timeframe,
        data_split=data_split,
        dataset_id=dataset_id,
        split_start_ms=split_start_ms,
        split_end_ms=split_end_ms,
        embargo_bars=embargo_bars,
        market_regime=market_regime,
        horizons=horizons,
        fee_bps_per_side=fee_bps_per_side,
        slippage_bps_per_side=slippage_bps_per_side,
    )
    evaluation["event_source"] = "engine_2_closed_prefix_replay"
    evaluation["storage_source"] = "engine_1_stored_closed_candles"
    evaluation["as_of_ms"] = int(as_of_ms)
    evaluation["stored_bar_count"] = len(bars)
    return {
        "structure_analysis_status": structure_analysis.get("status"),
        "structure_analysis_limitations": structure_analysis.get("limitations", []),
        "historical_scan": historical_scan,
        "detected_structure_events": events,
        "evaluation": evaluation,
    }


def persist_structure_evaluations(
    evaluation: dict[str, Any],
    *,
    primary_horizon_bars: int = 5,
    db_path: str | None = None,
    calculated_at_ms: int | None = None,
) -> int:
    """Persist one IN_PROGRESS record per pattern; never auto-promote to VALIDATED."""
    if not isinstance(evaluation, dict):
        raise ValueError("evaluation must be an object")
    if primary_horizon_bars <= 0:
        raise ValueError("primary_horizon_bars must be positive")

    symbol = str(evaluation.get("symbol", "")).strip().upper()
    venue = str(evaluation.get("venue", "")).strip()
    timeframe = str(evaluation.get("timeframe", "")).strip()
    market_regime = str(evaluation.get("market_regime", "UNSPECIFIED")).strip() or "UNSPECIFIED"
    dataset_fingerprint = str(evaluation.get("dataset_fingerprint", "")).strip()
    data_split = str(evaluation.get("data_split", "")).strip()
    dataset_id = str(evaluation.get("dataset_id", "")).strip()
    split_start_ms = evaluation.get("split_start_ms")
    split_end_ms = evaluation.get("split_end_ms")
    embargo_bars = evaluation.get("embargo_bars")
    results = evaluation.get("results_by_pattern")
    if not symbol or not venue or not timeframe or not dataset_fingerprint:
        raise ValueError("evaluation needs symbol, venue, timeframe and dataset_fingerprint")
    if data_split not in VALID_DATA_SPLITS or not isinstance(results, dict):
        raise ValueError("evaluation has an invalid split or results_by_pattern")
    if (
        not dataset_id
        or not isinstance(split_start_ms, int)
        or isinstance(split_start_ms, bool)
        or not isinstance(split_end_ms, int)
        or isinstance(split_end_ms, bool)
        or split_start_ms <= 0
        or split_end_ms <= split_start_ms
        or not isinstance(embargo_bars, int)
        or isinstance(embargo_bars, bool)
        or embargo_bars < 0
    ):
        raise ValueError("evaluation needs a valid dataset_id, split window and embargo_bars")
    if evaluation.get("human_reviewed") is not False:
        raise ValueError("detector event studies cannot be marked human-reviewed")
    if evaluation.get("empirical_status") != "UNVALIDATED":
        raise ValueError("detector event studies must remain UNVALIDATED")

    seed_visual_knowledge(db_path)
    known = {item["structure_id"] for item in MARKET_STRUCTURE_CATALOG}
    now = int(calculated_at_ms or time.time() * 1000)
    fee = evaluation.get("fee_bps_per_side")
    slippage = evaluation.get("slippage_bps_per_side")
    round_trip_cost = evaluation.get("round_trip_cost_pct")
    primary_horizon = str(int(primary_horizon_bars))
    persisted = 0

    conn = connect(db_path) if db_path is not None else connect()
    try:
        with conn:
            overlap = conn.execute(
                """SELECT data_split,split_start_ms,split_end_ms
                   FROM visual_structure_evaluations
                   WHERE dataset_id=? AND symbol=? AND venue=? AND timeframe=?
                     AND data_split<>? AND split_start_ms < ? AND split_end_ms > ?
                   LIMIT 1""",
                (
                    dataset_id, symbol, venue, timeframe, data_split,
                    split_end_ms, split_start_ms,
                ),
            ).fetchone()
            if overlap:
                raise ValueError(
                    "Split window overlaps previously stored "
                    f"{overlap['data_split']} window "
                    f"[{overlap['split_start_ms']},{overlap['split_end_ms']})"
                )

            existing_split = conn.execute(
                """SELECT MIN(split_start_ms) AS split_start_ms,
                          MAX(split_end_ms) AS split_end_ms
                   FROM visual_structure_evaluations
                   WHERE dataset_id=? AND symbol=? AND venue=? AND timeframe=?
                     AND data_split=?""",
                (dataset_id, symbol, venue, timeframe, data_split),
            ).fetchone()

            split_order = {"train": 0, "validation": 1, "test": 2}
            prior_splits = conn.execute(
                """SELECT data_split,split_start_ms,split_end_ms
                   FROM visual_structure_evaluations
                   WHERE dataset_id=? AND symbol=? AND venue=? AND timeframe=?
                     AND data_split<>?""",
                (dataset_id, symbol, venue, timeframe, data_split),
            ).fetchall()
            for prior in prior_splits:
                prior_rank = split_order[str(prior["data_split"])]
                current_rank = split_order[data_split]
                prior_start = int(prior["split_start_ms"])
                prior_end = int(prior["split_end_ms"])
                if prior_rank < current_rank and prior_end > split_start_ms:
                    raise ValueError(
                        f"{prior['data_split']} must end before {data_split} begins"
                    )
                if prior_rank > current_rank and prior_start < split_end_ms:
                    raise ValueError(
                        f"{data_split} must end before {prior['data_split']} begins"
                    )
            if (
                existing_split
                and existing_split["split_start_ms"] is not None
                and (
                    int(existing_split["split_start_ms"]) != split_start_ms
                    or int(existing_split["split_end_ms"]) != split_end_ms
                )
            ):
                raise ValueError("A stored data_split cannot be reused with different time bounds")

            for pattern_id, pattern_result in results.items():
                if pattern_id not in STRUCTURE_PATTERN_IDS or pattern_id not in known:
                    raise ValueError(f"Unsupported structure pattern id: {pattern_id}")
                horizon_metrics = (pattern_result.get("horizons") or {}).get(primary_horizon)
                if not isinstance(horizon_metrics, dict):
                    continue
                sample_count = int(horizon_metrics.get("sample_count", 0))
                if sample_count <= 0:
                    continue
                conn.execute(
                    """INSERT INTO visual_structure_evaluations
                    (structure_id,symbol,venue,timeframe,market_regime,sample_count,
                     mean_return_pct,median_return_pct,mae_pct,mfe_pct,
                     fee_adjusted_expectancy_pct,dataset_fingerprint,validation_status,
                     calculated_at_ms,horizon_metrics_json,primary_horizon_bars,data_split,
                     event_source,human_reviewed,fee_bps_per_side,slippage_bps_per_side,
                     round_trip_cost_pct,dataset_id,split_start_ms,split_end_ms,embargo_bars)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(structure_id,symbol,venue,timeframe,market_regime,
                                dataset_fingerprint,data_split)
                    DO UPDATE SET sample_count=excluded.sample_count,
                      mean_return_pct=excluded.mean_return_pct,
                      median_return_pct=excluded.median_return_pct,
                      mae_pct=excluded.mae_pct,mfe_pct=excluded.mfe_pct,
                      fee_adjusted_expectancy_pct=excluded.fee_adjusted_expectancy_pct,
                      validation_status='IN_PROGRESS',
                      calculated_at_ms=excluded.calculated_at_ms,
                      horizon_metrics_json=excluded.horizon_metrics_json,
                      primary_horizon_bars=excluded.primary_horizon_bars,
                      event_source=excluded.event_source,human_reviewed=0,
                      fee_bps_per_side=excluded.fee_bps_per_side,
                      slippage_bps_per_side=excluded.slippage_bps_per_side,
                      round_trip_cost_pct=excluded.round_trip_cost_pct,
                      dataset_id=excluded.dataset_id,
                      split_start_ms=excluded.split_start_ms,
                      split_end_ms=excluded.split_end_ms,
                      embargo_bars=excluded.embargo_bars""",
                    (
                        pattern_id, symbol, venue, timeframe, market_regime, sample_count,
                        horizon_metrics.get("mean_return_pct"),
                        horizon_metrics.get("median_return_pct"),
                        horizon_metrics.get("mean_mae_pct"),
                        horizon_metrics.get("mean_mfe_pct"),
                        horizon_metrics.get("fee_adjusted_expectancy_pct"),
                        dataset_fingerprint, "IN_PROGRESS", now,
                        json.dumps(pattern_result.get("horizons", {}), ensure_ascii=False, separators=(",", ":")),
                        int(primary_horizon_bars), data_split,
                        str(evaluation.get("event_source", "engine_2_confirmed_structure_events")),
                        0, fee, slippage, round_trip_cost,
                        dataset_id, split_start_ms, split_end_ms, embargo_bars,
                    ),
                )
                persisted += 1
        return persisted
    finally:
        conn.close()


__all__ = [
    "DEFAULT_HORIZONS",
    "STRUCTURE_PATTERN_IDS",
    "evaluate_structure_events",
    "scan_historical_structure_events",
    "evaluate_stored_structure_events",
    "analyze_and_evaluate_stored_market_structures",
    "persist_structure_evaluations",
]
