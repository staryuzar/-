from __future__ import annotations

from datetime import datetime, timezone
import math
from pathlib import Path
from contextlib import closing
import sqlite3
from typing import Any


def read_liquidation_heatmap(
    path: str | Path,
    *,
    symbol: str = "BTCUSDT",
    now_ms: int,
    lookback_minutes: int = 60,
    price_bucket_usd: float = 100.0,
    max_events: int = 10_000,
    minimum_cluster_events: int = 1,
) -> dict[str, Any]:
    """Read sampled liquidation events into separate per-venue price clusters."""
    if not 1 <= lookback_minutes <= 24 * 60:
        raise ValueError("lookback_minutes must be between 1 and 1440.")
    if not math.isfinite(price_bucket_usd) or not 1 <= price_bucket_usd <= 10_000:
        raise ValueError("price_bucket_usd must be between 1 and 10000.")
    if not 1 <= max_events <= 100_000:
        raise ValueError("max_events must be between 1 and 100000.")
    if not 1 <= minimum_cluster_events <= 1000:
        raise ValueError("minimum_cluster_events must be between 1 and 1000.")
    now = int(now_ms)
    if now <= 0:
        raise ValueError("now_ms must be positive.")

    empty = {
        "status": "not_started",
        "lookback_minutes": lookback_minutes,
        "price_bucket_usd": price_bucket_usd,
        "event_count": 0,
        "clusters": [],
        "venues": [],
        "warnings": ["liquidation_heatmap_not_started"],
        "use_in_decision": "risk_context_only_not_a_directional_vote",
    }
    db_path = Path(path)
    if not db_path.is_file():
        return {**empty, "reason": "Liquidation database was not found."}

    uri = db_path.resolve().as_uri() + "?mode=ro"
    try:
        with closing(sqlite3.connect(uri, uri=True, timeout=2.0)) as connection:
            connection.row_factory = sqlite3.Row
            tables = {
                row[0] for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            if "liquidation_events" not in tables:
                return {**empty, "status": "unavailable", "reason": "Liquidation event table is unavailable."}
            since = now - lookback_minutes * 60_000
            rows = connection.execute(
                """SELECT venue,symbol,market_type,event_time_ms,liquidated_side,
                raw_size,quantity_unit,reference_price,reference_price_kind,notional_usd
                FROM liquidation_events
                WHERE symbol IN (?, 'BTC-USDT-SWAP')
                  AND event_time_ms>=? AND event_time_ms<=?
                ORDER BY event_time_ms DESC,id DESC LIMIT ?""",
                (symbol.upper(), since, now + 5_000, max_events),
            ).fetchall()
            status_rows = []
            if "stream_status" in tables:
                status_rows = connection.execute(
                    """SELECT venue,symbol,status,updated_at_ms,last_message_ms,
                    reconnects,last_error FROM stream_status
                    WHERE symbol IN (?, 'BTC-USDT-SWAP') AND venue LIKE '%liquidations'
                    ORDER BY venue""",
                    (symbol.upper(),),
                ).fetchall()

        groups: dict[tuple[str, str, str, str, str, float], dict[str, Any]] = {}
        venue_counts: dict[str, dict[str, Any]] = {}
        for row in rows:
            venue = str(row["venue"])
            market_type = str(row["market_type"])
            side = str(row["liquidated_side"])
            unit = str(row["quantity_unit"])
            price_kind = str(row["reference_price_kind"])
            price = float(row["reference_price"])
            size = float(row["raw_size"])
            notional = float(row["notional_usd"]) if row["notional_usd"] is not None else None
            event_time = int(row["event_time_ms"])
            if (
                not venue or side not in {"LONG", "SHORT"}
                or not unit or not price_kind
                or not math.isfinite(price) or price <= 0
                or not math.isfinite(size) or size <= 0
                or (notional is not None and (not math.isfinite(notional) or notional < 0))
                or event_time <= 0
            ):
                continue
            bucket = round(math.floor(price / price_bucket_usd) * price_bucket_usd, 8)
            key = (venue, market_type, side, unit, price_kind, bucket)
            group = groups.setdefault(key, {
                "venue": venue,
                "market_type": market_type,
                "liquidated_side": side,
                "quantity_unit": unit,
                "reference_price_kind": price_kind,
                "price_bucket_low_usd": bucket,
                "price_bucket_high_usd": bucket + price_bucket_usd,
                "event_count": 0,
                "total_native_size": 0.0,
                "priced_event_count": 0,
                "priced_notional_usd": 0.0,
                "latest_event_time_ms": 0,
            })
            group["event_count"] += 1
            group["total_native_size"] += size
            group["latest_event_time_ms"] = max(group["latest_event_time_ms"], event_time)
            if notional is not None:
                group["priced_event_count"] += 1
                group["priced_notional_usd"] += notional

            venue_row = venue_counts.setdefault(venue, {
                "venue": venue, "event_count": 0,
                "latest_event_time_ms": 0, "quantity_units": set(),
                "reference_price_kinds": set(), "market_types": set(),
            })
            venue_row["event_count"] += 1
            venue_row["latest_event_time_ms"] = max(venue_row["latest_event_time_ms"], event_time)
            venue_row["quantity_units"].add(unit)
            venue_row["reference_price_kinds"].add(price_kind)
            venue_row["market_types"].add(market_type)

        clusters = []
        for group in groups.values():
            if group["event_count"] < minimum_cluster_events:
                continue
            latest = group["latest_event_time_ms"]
            age = (now - latest) / 1000.0
            clusters.append({
                **group,
                "total_native_size": round(group["total_native_size"], 8),
                "priced_notional_usd": (
                    round(group["priced_notional_usd"], 2)
                    if group["priced_event_count"] else None
                ),
                "price_bucket_center_usd": (
                    group["price_bucket_low_usd"] + price_bucket_usd / 2.0
                ),
                "latest_event_age_seconds": round(max(0.0, age), 2),
                "coverage_note": (
                    "notional_is_partial_subset" if 0 < group["priced_event_count"] < group["event_count"]
                    else "notional_unavailable" if not group["priced_event_count"]
                    else "all_events_have_source_notional"
                ),
            })
        clusters.sort(key=lambda item: (
            item["venue"], item["market_type"], item["reference_price_kind"],
            item["liquidated_side"], item["price_bucket_low_usd"],
        ))

        venue_profiles = []
        status_by_venue = {str(row["venue"]): dict(row) for row in status_rows}
        for venue, record in sorted(venue_counts.items()):
            latest = record["latest_event_time_ms"]
            feed = status_by_venue.get({
                "binance_usdm": "binance_usdm_liquidations",
                "bybit_linear": "bybit_linear_liquidations",
                "okx_swap": "okx_swap_liquidations",
            }.get(venue, ""), {})
            venue_profiles.append({
                "venue": venue,
                "event_count": record["event_count"],
                "latest_event_time_ms": latest,
                "latest_event_age_seconds": round(max(0.0, (now - latest) / 1000.0), 2),
                "quantity_units": sorted(record["quantity_units"]),
                "reference_price_kinds": sorted(record["reference_price_kinds"]),
                "market_types": sorted(record["market_types"]),
                "feed_status": feed.get("status", "unknown"),
                "feed_updated_at_ms": feed.get("updated_at_ms"),
                "feed_last_message_ms": feed.get("last_message_ms"),
                "feed_reconnects": feed.get("reconnects"),
                "feed_error": feed.get("last_error"),
            })

        warnings: list[str] = []
        if not rows:
            warnings.append("no_liquidation_events_in_selected_window")
        if len(rows) >= max_events:
            warnings.append("liquidation_event_query_limit_reached")
        if any(cluster["coverage_note"] == "notional_unavailable" for cluster in clusters):
            warnings.append("some_liquidation_clusters_have_no_usd_notional")
        if any(cluster["coverage_note"] == "notional_is_partial_subset" for cluster in clusters):
            warnings.append("some_liquidation_cluster_usd_notionals_are_partial")

        return {
            "status": "ok" if clusters else ("empty" if rows else "incomplete"),
            "lookback_minutes": lookback_minutes,
            "price_bucket_usd": price_bucket_usd,
            "event_count": len(rows),
            "cluster_count": len(clusters),
            "clusters": clusters,
            "venues": venue_profiles,
            "warnings": warnings,
            "as_of_utc": datetime.fromtimestamp(now / 1000, timezone.utc).isoformat(),
            "use_in_decision": "risk_context_only_not_a_directional_vote",
            "aggregation_policy": (
                "Clusters are grouped independently by venue, market type, liquidated side, "
                "quantity unit, reference-price kind and price bucket. No raw size or USD total "
                "is combined across venues or incompatible reference-price semantics."
            ),
            "limitations": [
                "Liquidation feeds are sampled, delayed and venue-specific; this is not a complete market liquidation map.",
                "Binance reference price is average fill price; Bybit and OKX use bankruptcy/reference prices and remain separated.",
                "Bybit and OKX native quantities are not converted to USD without confirmed contract multipliers and source metadata.",
                "USD notional only includes events for which the source provided a supported notional; partial coverage is labelled.",
                "The chart bins price coordinates; it does not identify resting liquidity or predict a liquidation cascade.",
            ],
        }
    except sqlite3.Error as exc:
        return {
            **empty,
            "status": "unavailable",
            "reason": f"{type(exc).__name__}: {exc}",
        }
