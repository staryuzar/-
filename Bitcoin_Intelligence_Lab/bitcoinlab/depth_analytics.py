from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import sqlite3
import statistics
from typing import Any


MARKET_TYPES = {
    "binance_spot": "spot",
    "bybit_linear": "linear_perpetual",
    "okx_spot": "spot",
}


def _finite_positive(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def _price_bucket(price: float, step: float) -> float:
    return round(math.floor(price / step) * step, 8)


def _normalize_levels(raw: object, *, step: float) -> dict[float, float]:
    if not isinstance(raw, list):
        return {}
    levels: dict[float, float] = defaultdict(float)
    for item in raw:
        if not isinstance(item, (list, tuple)) or len(item) < 2:
            continue
        price = _finite_positive(item[0])
        size = _finite_positive(item[1])
        if price is None or size is None:
            continue
        levels[_price_bucket(price, step)] += size
    return dict(levels)


def _venue_profile(
    venue: str,
    rows: list[dict[str, Any]],
    *,
    now_ms: int,
    lookback_minutes: int,
    bucket_step_usd: float,
    min_snapshots: int,
    min_coverage_ratio: float,
    max_live_age_seconds: int,
    minimum_level_btc: float,
    change_threshold: float,
    max_pair_gap_seconds: int,
) -> dict[str, Any]:
    rows.sort(key=lambda row: row["observed_at_ms"])
    snapshot_maps: list[dict[str, Any]] = []
    for row in rows:
        bids = _normalize_levels(row.get("bids"), step=bucket_step_usd)
        asks = _normalize_levels(row.get("asks"), step=bucket_step_usd)
        if bids and asks:
            snapshot_maps.append({
                "observed_at_ms": int(row["observed_at_ms"]),
                "bids": bids,
                "asks": asks,
            })
    count = len(snapshot_maps)
    last_snapshot_ms = snapshot_maps[-1]["observed_at_ms"] if snapshot_maps else None
    age = (now_ms - last_snapshot_ms) / 1000 if last_snapshot_ms else None
    fresh = age is not None and -5 <= age <= max_live_age_seconds
    expected = lookback_minutes * 12  # snapshots are sampled approximately every 5 seconds
    coverage_ratio = min(1.0, count / expected) if expected else 0.0
    status = (
        "ok" if count >= min_snapshots and fresh and coverage_ratio >= min_coverage_ratio
        else ("stale" if count and not fresh else "incomplete")
    )

    heatmap: dict[str, list[dict[str, Any]]] = {"bid": [], "ask": []}
    for side in ("bids", "asks"):
        samples: dict[float, list[float]] = defaultdict(list)
        for snapshot in snapshot_maps:
            for price_bucket, size in snapshot[side].items():
                samples[price_bucket].append(size)
        output_side = "bid" if side == "bids" else "ask"
        for price_bucket, values in samples.items():
            current = snapshot_maps[-1][side].get(price_bucket, 0.0) if snapshot_maps else 0.0
            heatmap[output_side].append({
                "price_bucket_usd": price_bucket,
                "mean_visible_size_btc": round(sum(values) / count, 8) if count else 0.0,
                "median_when_visible_btc": round(statistics.median(values), 8),
                "max_visible_size_btc": round(max(values), 8),
                "persistence_ratio": round(len(values) / count, 4) if count else 0.0,
                "current_size_btc": round(current, 8),
                "observed_snapshots": len(values),
                "total_snapshots": count,
            })
        heatmap[output_side].sort(
            key=lambda item: (item["persistence_ratio"], item["mean_visible_size_btc"]),
            reverse=True,
        )

    # Compare only price buckets present in both adjacent snapshots. A level that
    # vanishes from the displayed depth is not automatically labelled as a pull.
    changes: dict[tuple[str, float], dict[str, Any]] = defaultdict(
        lambda: {
            "stack_events": 0, "pull_events": 0,
            "stacked_btc": 0.0, "pulled_btc": 0.0,
            "last_change_pct": None, "last_observed_ms": None,
        }
    )
    for previous, current in zip(snapshot_maps, snapshot_maps[1:]):
        gap = (current["observed_at_ms"] - previous["observed_at_ms"]) / 1000
        if gap <= 0 or gap > max_pair_gap_seconds:
            continue
        for side in ("bids", "asks"):
            common = previous[side].keys() & current[side].keys()
            side_label = "bid" if side == "bids" else "ask"
            for price_bucket in common:
                before = previous[side][price_bucket]
                after = current[side][price_bucket]
                if before < minimum_level_btc:
                    continue
                change_pct = (after - before) / before
                if change_pct >= change_threshold:
                    record = changes[(side_label, price_bucket)]
                    record["stack_events"] += 1
                    record["stacked_btc"] += after - before
                    record["last_change_pct"] = round(change_pct, 4)
                    record["last_observed_ms"] = current["observed_at_ms"]
                elif change_pct <= -change_threshold:
                    record = changes[(side_label, price_bucket)]
                    record["pull_events"] += 1
                    record["pulled_btc"] += before - after
                    record["last_change_pct"] = round(change_pct, 4)
                    record["last_observed_ms"] = current["observed_at_ms"]

    pull_stack = []
    for (side, price_bucket), record in sorted(changes.items()):
        if not record["stack_events"] and not record["pull_events"]:
            continue
        pull_stack.append({
            "side": side,
            "price_bucket_usd": price_bucket,
            "stack_events": record["stack_events"],
            "pull_events": record["pull_events"],
            "stacked_btc": round(record["stacked_btc"], 8),
            "pulled_btc": round(record["pulled_btc"], 8),
            "last_change_pct": record["last_change_pct"],
            "last_observed_ms": record["last_observed_ms"],
        })

    return {
        "status": status,
        "venue": venue,
        "market_type": MARKET_TYPES.get(venue, "unknown"),
        "snapshot_count": count,
        "expected_snapshots_approx": expected,
        "sample_coverage_ratio": round(coverage_ratio, 4),
        "last_snapshot_ms": last_snapshot_ms,
        "last_snapshot_age_seconds": round(max(0.0, age), 2) if age is not None else None,
        "heatmap": heatmap,
        "pull_stack": pull_stack,
        "warnings": (
            ["historical_depth_stale"] if status == "stale"
            else (["historical_depth_samples_insufficient"] if status == "incomplete" else [])
        ),
    }


def read_depth_liquidity_context(
    path: str | Path,
    *,
    symbol: str = "BTCUSDT",
    now_ms: int | None = None,
    lookback_minutes: int = 30,
    bucket_step_usd: float = 50.0,
    max_snapshots: int = 1500,
    min_snapshots: int = 3,
    min_coverage_ratio: float = 0.10,
    max_live_age_seconds: int = 45,
    minimum_level_btc: float = 0.01,
    change_threshold: float = 0.25,
    max_pair_gap_seconds: int = 20,
) -> dict[str, Any]:
    """Read sampled depth history and calculate per-venue liquidity persistence and Pull/Stack proxies."""
    if not 1 <= lookback_minutes <= 24 * 60:
        raise ValueError("lookback_minutes must be between 1 and 1440.")
    if not math.isfinite(bucket_step_usd) or not 1 <= bucket_step_usd <= 5000:
        raise ValueError("bucket_step_usd must be between 1 and 5000.")
    if not 10 <= max_snapshots <= 10_000:
        raise ValueError("max_snapshots must be between 10 and 10000.")
    if min_snapshots < 2 or max_live_age_seconds < 5 or max_pair_gap_seconds < 1:
        raise ValueError("Invalid depth-history freshness thresholds.")
    if not math.isfinite(min_coverage_ratio) or not 0 <= min_coverage_ratio <= 1:
        raise ValueError("min_coverage_ratio must be between 0 and 1.")
    if not math.isfinite(minimum_level_btc) or minimum_level_btc <= 0 or not math.isfinite(change_threshold) or not 0.05 <= change_threshold <= 2:
        raise ValueError("Invalid depth change thresholds.")
    now = int(now_ms if now_ms is not None else datetime.now(timezone.utc).timestamp() * 1000)
    if now <= 0:
        raise ValueError("now_ms must be positive.")
    empty = {
        "status": "not_started",
        "lookback_minutes": lookback_minutes,
        "bucket_step_usd": bucket_step_usd,
        "venues": [],
        "warnings": ["historical_depth_not_started"],
        "use_in_decision": "liquidity_context_only_not_a_directional_vote",
    }
    db_path = Path(path)
    if not db_path.is_file():
        return {**empty, "reason": "Order-book snapshot database was not found."}
    uri = db_path.resolve().as_uri() + "?mode=ro"
    try:
        with sqlite3.connect(uri, uri=True, timeout=2.0) as connection:
            connection.row_factory = sqlite3.Row
            tables = {
                row[0] for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            if "orderbook_snapshots" not in tables:
                return {**empty, "status": "unavailable", "reason": "Order-book history table is unavailable."}
            rows = connection.execute(
                """SELECT venue,symbol,observed_at_ms,bids_json,asks_json
                FROM orderbook_snapshots
                WHERE symbol IN (?, 'BTC-USDT')
                  AND observed_at_ms>=? AND observed_at_ms<=?
                ORDER BY venue,observed_at_ms DESC LIMIT ?""",
                (
                    symbol.upper(),
                    now - lookback_minutes * 60_000,
                    now + 5_000,
                    max_snapshots,
                ),
            ).fetchall()
            grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for row in rows:
                try:
                    bids = json.loads(row["bids_json"])
                    asks = json.loads(row["asks_json"])
                except (TypeError, ValueError, json.JSONDecodeError):
                    continue
                grouped[str(row["venue"])].append({
                    "observed_at_ms": int(row["observed_at_ms"]),
                    "bids": bids,
                    "asks": asks,
                })
        profiles = [
            _venue_profile(
                venue, venue_rows, now_ms=now,
                lookback_minutes=lookback_minutes,
                bucket_step_usd=bucket_step_usd,
                min_snapshots=min_snapshots,
                min_coverage_ratio=min_coverage_ratio,
                max_live_age_seconds=max_live_age_seconds,
                minimum_level_btc=minimum_level_btc,
                change_threshold=change_threshold,
                max_pair_gap_seconds=max_pair_gap_seconds,
            )
            for venue, venue_rows in sorted(grouped.items())
        ]
        ready = [profile for profile in profiles if profile["status"] == "ok"]
        warnings = [
            warning for profile in profiles for warning in profile["warnings"]
        ]
        overall = "ok" if len(ready) >= 2 else ("partial" if profiles else "incomplete")
        if profiles and len(ready) < 2:
            warnings.append("fewer_than_two_fresh_depth_history_venues")
        return {
            "status": overall,
            "lookback_minutes": lookback_minutes,
            "bucket_step_usd": bucket_step_usd,
            "venues": profiles,
            "fresh_venue_count": len(ready),
            "warnings": sorted(set(warnings)),
            "as_of_utc": datetime.fromtimestamp(now / 1000, timezone.utc).isoformat(),
            "use_in_decision": "liquidity_context_only_not_a_directional_vote",
            "limitations": [
                "Heatmap is derived from sampled visible top-of-book depth, not the full exchange order book.",
                "Pull/Stack is calculated only when the same price bucket appears in consecutive snapshots; disappearance alone is not labelled a pull.",
                "Displayed size can be cancelled, replenished, spoofed or repriced; persistence is not proof of executable liquidity.",
                "Each venue and market type is kept separate; no cross-venue size sum is performed.",
            ],
        }
    except sqlite3.Error as exc:
        return {
            **empty,
            "status": "unavailable",
            "reason": f"{type(exc).__name__}: {exc}",
        }
