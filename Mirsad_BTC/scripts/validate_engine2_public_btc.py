from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mirsad.engines.mt5_price_action import analyze_mt5_native_price_action
from mirsad.engines.chart_structure_evaluation import (
    evaluate_structure_events,
    scan_historical_structure_events,
)

API_BASES = ("https://data-api.binance.vision", "https://api.binance.com")
TIMEFRAME_MS = {
    "1m": 60_000, "5m": 300_000, "15m": 900_000,
    "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000,
}
MAX_PAGE = 1000
USER_AGENT = "Mirsad-Engine2-Public-BTC-Validation/1.0"


def get_json(path: str, params: dict[str, Any] | None = None) -> Any:
    query = urlencode(params or {})
    last_error: Exception | None = None
    for base in API_BASES:
        url = f"{base}{path}" + (f"?{query}" if query else "")
        for attempt in range(3):
            try:
                request = Request(url, headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "application/json",
                })
                with urlopen(request, timeout=15) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                if isinstance(payload, dict) and "code" in payload and "msg" in payload:
                    raise RuntimeError(f"Binance API {payload.get('code')}: {payload.get('msg')}")
                return payload
            except (HTTPError, URLError, TimeoutError, OSError,
                    UnicodeError, json.JSONDecodeError, RuntimeError) as exc:
                last_error = exc
                if attempt < 2:
                    time.sleep(0.5 * (attempt + 1))
    raise RuntimeError(f"Public Binance endpoint failed: {last_error}")


def server_time_ms() -> int:
    payload = get_json("/api/v3/time")
    stamp = int(payload.get("serverTime", 0)) if isinstance(payload, dict) else 0
    if stamp <= 0:
        raise ValueError("Binance server time is missing or invalid")
    return stamp


def parse_row(row: Any, timeframe: str) -> dict[str, Any]:
    duration = TIMEFRAME_MS[timeframe]
    if not isinstance(row, list) or len(row) < 7:
        raise ValueError(f"{timeframe} Kline row has an invalid shape")
    try:
        open_ms, close_ms = int(row[0]), int(row[6])
        values = [float(row[index]) for index in (1, 2, 3, 4, 5)]
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{timeframe} Kline row has invalid numeric fields") from exc
    if open_ms <= 0 or close_ms < open_ms or close_ms >= open_ms + duration:
        raise ValueError(f"{timeframe} Kline row has invalid time boundaries")
    if not all(math.isfinite(value) for value in values):
        raise ValueError(f"{timeframe} Kline row contains non-finite values")
    open_price, high, low, close, volume = values
    if min(open_price, high, low, close) <= 0 or volume < 0:
        raise ValueError(f"{timeframe} Kline row contains an invalid price or volume")
    if high < max(open_price, close, low) or low > min(open_price, close):
        raise ValueError(f"{timeframe} Kline row has inconsistent OHLC geometry")
    return {
        "open_time_ms": open_ms,
        "open": open_price,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
        "close_time_ms": close_ms,
    }


def normalise_kline_rows(
    rows: Any, timeframe: str, *, as_of_ms: int
) -> list[dict[str, Any]]:
    if timeframe not in TIMEFRAME_MS:
        raise ValueError(f"Unsupported timeframe: {timeframe}")
    if not isinstance(rows, list) or len(rows) < 25:
        raise ValueError(f"{timeframe} response has fewer than 25 Kline rows")
    result: list[dict[str, Any]] = []
    previous = 0
    for index, raw in enumerate(rows):
        if not isinstance(raw, list) or not raw:
            raise ValueError(f"{timeframe} Kline row has an invalid shape")
        try:
            row_open_time = int(raw[0])
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(f"{timeframe} Kline row has an invalid open time") from exc
        if row_open_time <= previous:
            raise ValueError(f"{timeframe} timestamps are not strictly increasing")
        bar = parse_row(raw, timeframe)
        closed = bar["close_time_ms"] < as_of_ms
        if index < len(rows) - 1 and not closed:
            raise ValueError(f"{timeframe} contains a forming candle before its final row")
        bar["closed"] = closed
        del bar["close_time_ms"]
        result.append(bar)
        previous = bar["open_time_ms"]
    if result[-1]["closed"]:
        raise ValueError(f"{timeframe} response has no current forming candle")
    if sum(1 for bar in result if bar["closed"]) < 24:
        raise ValueError(f"{timeframe} has fewer than 24 closed candles")
    return result


def fetch_latest_bars(timeframe: str, *, as_of_ms: int, limit: int) -> list[dict[str, Any]]:
    rows = get_json(
        "/api/v3/klines",
        {"symbol": "BTCUSDT", "interval": timeframe, "limit": limit},
    )
    return normalise_kline_rows(rows, timeframe, as_of_ms=as_of_ms)


def fetch_closed_hourly_history(*, as_of_ms: int, limit: int) -> list[dict[str, Any]]:
    if not 300 <= limit <= 5000:
        raise ValueError("history-bars must be between 300 and 5000")
    duration = TIMEFRAME_MS["1h"]
    cursor = (as_of_ms // duration - limit - 2) * duration
    collected: dict[int, dict[str, Any]] = {}
    while len(collected) < limit:
        page_limit = min(MAX_PAGE, limit - len(collected) + 2)
        rows = get_json("/api/v3/klines", {
            "symbol": "BTCUSDT", "interval": "1h",
            "startTime": cursor, "endTime": as_of_ms, "limit": page_limit,
        })
        if not isinstance(rows, list) or not rows:
            break
        last_open = 0
        for raw in rows:
            bar = parse_row(raw, "1h")
            last_open = max(last_open, bar["open_time_ms"])
            if bar["close_time_ms"] < as_of_ms:
                bar["closed"] = True
                del bar["close_time_ms"]
                collected[bar["open_time_ms"]] = bar
        next_cursor = last_open + duration
        if last_open <= 0 or next_cursor <= cursor:
            raise RuntimeError("Hourly Binance pagination did not advance")
        cursor = next_cursor
        if len(rows) < page_limit:
            break
    return [collected[key] for key in sorted(collected)][-limit:]


def longest_contiguous_segment(
    bars: list[dict[str, Any]], *, interval_ms: int
) -> tuple[list[dict[str, Any]], int]:
    if not bars:
        return [], 0
    segments: list[list[dict[str, Any]]] = []
    current = [bars[0]]
    excluded = 0
    for bar in bars[1:]:
        delta = int(bar["open_time_ms"]) - int(current[-1]["open_time_ms"])
        if delta == interval_ms:
            current.append(bar)
        else:
            if delta > interval_ms:
                excluded += max(1, delta // interval_ms - 1)
            segments.append(current)
            current = [bar]
    segments.append(current)
    longest = max(segments, key=len)
    excluded += len(bars) - len(longest)
    return longest, excluded


def summarise_split(metrics: dict[str, Any]) -> dict[str, Any]:
    patterns = []
    for pattern_id, row in sorted((metrics.get("results_by_pattern") or {}).items()):
        h5 = (row.get("horizons") or {}).get("5", {})
        direction_rows: dict[str, Any] = {}
        for direction, comparison in (row.get("directional_comparisons") or {}).items():
            stats = (comparison.get("horizons") or {}).get("5", {})
            event = stats.get("event") or {}
            baseline = stats.get("unconditional_non_event_baseline") or {}
            direction_rows[direction] = {
                "sample_count": event.get("sample_count"),
                "mean_return_pct": event.get("mean_return_pct"),
                "baseline_mean_return_pct": baseline.get("mean_return_pct"),
                "excess_mean_return_pct": stats.get("excess_mean_return_pct"),
            }
        patterns.append({
            "pattern_id": pattern_id,
            "direction_counts": row.get("direction_counts"),
            "horizon_5": {
                "sample_count": h5.get("sample_count"),
                "mean_return_pct": h5.get("mean_return_pct"),
                "win_rate_pct": h5.get("win_rate_pct"),
            },
            "directional_comparisons": direction_rows,
        })
    return {
        "data_split": metrics["data_split"],
        "dataset_fingerprint": metrics["dataset_fingerprint"],
        "counts": metrics["counts"],
        "patterns": patterns,
        "empirical_status": metrics["empirical_status"],
        "validation_status": metrics["validation_status"],
        "costs_applied": metrics["costs_applied"],
    }


def run_validation(
    *, timeframe_limit: int = 1000, history_bars: int = 3000
) -> dict[str, Any]:
    if not 100 <= timeframe_limit <= MAX_PAGE:
        raise ValueError("timeframe-limit must be between 100 and 1000")
    as_of = server_time_ms()
    frames = {
        tf: fetch_latest_bars(tf, as_of_ms=as_of, limit=timeframe_limit)
        for tf in TIMEFRAME_MS
    }
    analysis = analyze_mt5_native_price_action({
        "status": "READY",
        "source": "BINANCE_PUBLIC_SPOT_KLINES",
        "symbol": "BTCUSDT",
        "broker_symbol": "BTCUSDT",
        "account_server": "BINANCE_PUBLIC_DATA",
        "captured_at_ms": as_of,
        "candles_by_tf": frames,
    })

    raw_history = fetch_closed_hourly_history(as_of_ms=as_of, limit=history_bars)
    hourly, excluded_intervals = longest_contiguous_segment(
        raw_history, interval_ms=TIMEFRAME_MS["1h"]
    )
    if len(hourly) < 300:
        raise RuntimeError(
            f"Only {len(hourly)} contiguous closed 1h bars are available; at least 300 are required"
        )
    events, scan = scan_historical_structure_events(
        hourly, timeframe="1h", minimum_bars=24, maximum_bars=5000
    )
    n = len(hourly)
    edges = (0, int(n * 0.60), int(n * 0.80), n)
    dataset_id = (
        f"binance_spot_btcusdt_1h_{hourly[0]['open_time_ms']}_{hourly[-1]['open_time_ms']}"
    )
    splits = []
    for name, first, last in (
        ("train", edges[0], edges[1]),
        ("validation", edges[1], edges[2]),
        ("test", edges[2], edges[3]),
    ):
        start_ms = int(hourly[first]["open_time_ms"])
        end_ms = (
            int(hourly[last]["open_time_ms"])
            if last < n else int(hourly[-1]["open_time_ms"]) + TIMEFRAME_MS["1h"]
        )
        metrics = evaluate_structure_events(
            hourly,
            events,
            symbol="BTCUSDT",
            venue="Binance Spot",
            timeframe="1h",
            data_split=name,
            dataset_id=dataset_id,
            split_start_ms=start_ms,
            split_end_ms=end_ms,
            embargo_bars=10,
            horizons=(1, 3, 5, 10),
        )
        splits.append(summarise_split(metrics))

    rows = {}
    for timeframe, row in (analysis.get("timeframes") or {}).items():
        structure = row.get("structure") or {}
        swing = structure.get("swing") or {}
        rows[timeframe] = {
            "status": row.get("status"),
            "direction": row.get("direction"),
            "closed_bars": row.get("closed_bars"),
            "gap_count": (row.get("data_quality") or {}).get("gap_count"),
            "staleness_ms": row.get("staleness_ms"),
            "swing_high_count": len(swing.get("swing_highs", [])),
            "swing_low_count": len(swing.get("swing_lows", [])),
            "bos_choch_count": len(structure.get("bos_choch_events", [])),
            "liquidity_sweep_count": len(structure.get("liquidity_sweeps", [])),
            "fair_value_gap_count": len(structure.get("fair_value_gaps", [])),
            "order_block_candidate_count": len(structure.get("order_block_candidates", [])),
            "candle_pattern_count": (row.get("candle_analysis") or {}).get("detected_count", 0),
        }
    fingerprint_data = json.dumps(
        {
            tf: [[b["open_time_ms"], b["open"], b["high"], b["low"], b["close"]]
                 for b in frames[tf]]
            for tf in TIMEFRAME_MS
        },
        sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return {
        "schema": "MIR-ENGINE2-PUBLIC-BTC-VALIDATION-1",
        "status": "READY" if analysis.get("status") == "READY" else "PARTIAL",
        "source": "BINANCE_PUBLIC_SPOT_API",
        "symbol": "BTCUSDT",
        "as_of_utc": datetime.fromtimestamp(as_of / 1000, tz=timezone.utc).isoformat(),
        "as_of_utc_ms": as_of,
        "public_data_fingerprint": hashlib.sha256(fingerprint_data).hexdigest(),
        "timeframe_limit": timeframe_limit,
        "analysis_status": analysis.get("status"),
        "direction": analysis.get("direction"),
        "direction_ar": analysis.get("direction_ar"),
        "summary": analysis.get("summary"),
        "timeframes": rows,
        "warnings": analysis.get("warnings", []),
        "historical_event_study": {
            "timeframe": "1h",
            "requested_closed_bars": history_bars,
            "contiguous_bars_used": len(hourly),
            "excluded_gap_count_and_bars": excluded_intervals,
            "historical_scan": scan,
            "detected_confirmed_event_count": len(events),
            "chronological_splits": splits,
            "empirical_status": "UNVALIDATED",
            "costs_applied": False,
            "limitations": [
                "Descriptive event study, not a portfolio backtest or trading instruction.",
                "Detector outcomes are compared with a non-event baseline; this does not measure human-labelled pattern precision.",
                "No broker fee or slippage assumption has been invented.",
                "The results remain UNVALIDATED pending independent human review and reproduction on a separate source.",
            ],
        },
        "scope": {
            "native_ohlc_only": True,
            "chart_images_used": False,
            "technical_indicators_calculated_in_engine2": False,
            "decision_eligible": False,
            "order_execution_enabled": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Independently validate native Engine 2 with public Binance BTCUSDT OHLC."
    )
    parser.add_argument("--timeframe-limit", type=int, default=1000)
    parser.add_argument("--history-bars", type=int, default=3000)
    parser.add_argument("--output-json", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = run_validation(
            timeframe_limit=args.timeframe_limit,
            history_bars=args.history_bars,
        )
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(json.dumps({
            "status": report["status"],
            "analysis_status": report["analysis_status"],
            "direction": report["direction"],
            "eligible_timeframes": (report.get("summary") or {}).get("eligible_timeframes", []),
            "history_bars": report["historical_event_study"]["contiguous_bars_used"],
            "detected_events": report["historical_event_study"]["detected_confirmed_event_count"],
            "split_event_counts": {
                row["data_split"]: row["counts"]["confirmed_events"]
                for row in report["historical_event_study"]["chronological_splits"]
            },
            "empirical_status": "UNVALIDATED",
            "decision_eligible": False,
        }, ensure_ascii=False))
        return 0 if report["status"] == "READY" else 1
    except Exception as exc:
        parser.exit(2, f"Public BTC validation failed: {type(exc).__name__}: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
