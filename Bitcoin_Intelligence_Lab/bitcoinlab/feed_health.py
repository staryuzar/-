from __future__ import annotations

from datetime import datetime, timezone
import math
from typing import Any, Mapping, Sequence


CORE_FEEDS = ("spot", "orderflow", "derivatives")
BOOK_VENUES = {"binance_spot", "bybit_linear", "okx_spot"}


def _age_seconds(timestamp_ms: object, now_ms: int) -> float | None:
    try:
        timestamp = int(timestamp_ms)
    except (TypeError, ValueError, OverflowError):
        return None
    if timestamp <= 0:
        return None
    age = (now_ms - timestamp) / 1000.0
    if not math.isfinite(age):
        return None
    return age


def _source_state(name: str, row: Mapping[str, Any]) -> dict[str, Any]:
    status = str(row.get("status", "unavailable")).lower()
    normalized = {
        "fresh": "fresh",
        "loaded": "fresh",
        "ok": "fresh",
        "partial": "partial",
        "incomplete": "partial",
        "stale": "stale",
        "error": "error",
        "unavailable": "unavailable",
        "empty": "empty",
    }.get(status, "unavailable")
    return {
        "name": name,
        "status": normalized,
        "reported_status": status,
        "age_seconds": row.get("age_seconds"),
        "observed_at_utc": row.get("observed_at_utc") or row.get("fetched_at_utc"),
        "reason": row.get("reason"),
        "venue": row.get("venue"),
    }


def _feed_type(name: str) -> str:
    if name in BOOK_VENUES:
        return "orderbook"
    if name.endswith("_liquidations"):
        return "liquidations"
    if name.endswith("_trades"):
        return "trades"
    return "event"


def _stream_states(
    venues: Sequence[Mapping[str, Any]],
    latest_books: Sequence[Mapping[str, Any]],
    *,
    now_ms: int,
    book_stale_seconds: int,
    trade_stale_seconds: int,
) -> list[dict[str, Any]]:
    status_rows = {
        str(row.get("venue", "")): row
        for row in venues
        if isinstance(row, Mapping)
    }
    latest_by_venue = {
        str(row.get("venue", "")): row
        for row in latest_books
        if isinstance(row, Mapping)
    }
    result: list[dict[str, Any]] = []
    for name, status_row in status_rows.items():
        status = str(status_row.get("status", "unavailable")).lower()
        last_message = _age_seconds(status_row.get("last_message_ms"), now_ms)
        heartbeat_age = _age_seconds(status_row.get("updated_at_ms"), now_ms)
        book = latest_by_venue.get(name)
        book_age = _age_seconds(book.get("observed_at_ms"), now_ms) if book else None
        feed_type = _feed_type(name)
        is_book_feed = feed_type == "orderbook"
        if status in {"reconnecting", "connecting", "error"}:
            health = "recovering" if status in {"reconnecting", "connecting"} else "error"
        elif is_book_feed:
            if status != "live" or book_age is None or book_age < -5 or book_age > book_stale_seconds:
                health = "stale" if status == "live" else "unavailable"
            else:
                health = "live"
        elif status in {"live", "connected"}:
            # Liquidations are sparse event feeds; a fresh heartbeat is enough.
            # BTC trade feeds are high-frequency and must also deliver recent trades.
            if heartbeat_age is None or heartbeat_age < -5 or heartbeat_age > 45:
                health = "stale"
            elif feed_type == "trades":
                if last_message is None or last_message < -5 or last_message > trade_stale_seconds:
                    health = "stale"
                else:
                    health = "live"
            elif status == "connected" or last_message is None or last_message > 45:
                health = "connected_quiet_ok"
            else:
                health = "live"
        else:
            health = "unavailable"
        result.append({
            "name": name,
            "feed_type": feed_type,
            "symbol": status_row.get("symbol"),
            "status": health,
            "reported_status": status,
            "last_message_age_seconds": (
                round(max(0.0, last_message), 2)
                if last_message is not None else None
            ),
            "heartbeat_age_seconds": (
                round(max(0.0, heartbeat_age), 2)
                if heartbeat_age is not None else None
            ),
            "book_age_seconds": (
                round(max(0.0, book_age), 2)
                if book_age is not None else None
            ),
            "reconnects": int(status_row.get("reconnects") or 0),
            "last_error": status_row.get("last_error"),
            "event_driven": not is_book_feed,
        })
    return sorted(result, key=lambda item: item["name"])


def build_data_health(
    *,
    source_states: Mapping[str, Mapping[str, Any]],
    stream_state: Mapping[str, Any] | None = None,
    now_ms: int,
    book_stale_seconds: int = 30,
    trade_stale_seconds: int = 45,
) -> dict[str, Any]:
    """
    Audit source coverage, freshness and WebSocket state without creating a
    directional vote. Sparse event feeds remain connected/quiet rather than
    being mislabeled as stale merely because no liquidation event occurred.
    """
    if now_ms <= 0:
        raise ValueError("now_ms must be positive.")
    if not 5 <= book_stale_seconds <= 180:
        raise ValueError("book_stale_seconds must be between 5 and 180.")
    if not 5 <= trade_stale_seconds <= 180:
        raise ValueError("trade_stale_seconds must be between 5 and 180.")

    normalized_sources = {
        name: _source_state(name, row if isinstance(row, Mapping) else {})
        for name, row in source_states.items()
    }
    for name in CORE_FEEDS:
        normalized_sources.setdefault(
            name,
            {
                "name": name, "status": "unavailable",
                "reported_status": "missing", "age_seconds": None,
                "observed_at_utc": None, "reason": "Source state was not provided.",
                "venue": None,
            },
        )

    fresh_core = [
        name for name in CORE_FEEDS
        if normalized_sources[name]["status"] == "fresh"
    ]
    missing_core = [
        name for name in CORE_FEEDS
        if normalized_sources[name]["status"] != "fresh"
    ]
    core_ready = (
        normalized_sources["spot"]["status"] == "fresh"
        and any(
            normalized_sources[name]["status"] == "fresh"
            for name in ("orderflow", "derivatives")
        )
    )

    stream = stream_state or {}
    stream_rows = _stream_states(
        stream.get("venues", []) if isinstance(stream, Mapping) else [],
        stream.get("latest_books", []) if isinstance(stream, Mapping) else [],
        now_ms=now_ms,
        book_stale_seconds=book_stale_seconds,
        trade_stale_seconds=trade_stale_seconds,
    )
    live_books = [row["name"] for row in stream_rows if row["status"] == "live"]
    quiet_event_feeds = [
        row["name"] for row in stream_rows
        if row["status"] == "connected_quiet_ok"
    ]
    quiet_liquidation_feeds = [
        row["name"] for row in stream_rows
        if row["status"] == "connected_quiet_ok" and row["feed_type"] == "liquidations"
    ]
    quiet_trade_feeds = [
        row["name"] for row in stream_rows
        if row["status"] == "stale" and row["feed_type"] == "trades"
    ]
    stale_or_down = [
        row["name"] for row in stream_rows
        if row["status"] in {"stale", "unavailable", "recovering", "error"}
    ]

    warnings: list[str] = []
    if missing_core:
        warnings.append("core_market_data_incomplete")
    if stale_or_down:
        warnings.append("one_or_more_websocket_feeds_not_live")
    if not stream_rows:
        warnings.append("market_stream_not_started")
    if quiet_liquidation_feeds:
        warnings.append("event_driven_feeds_connected_no_recent_liquidation_events")
    if quiet_trade_feeds:
        warnings.append("trade_feeds_missing_recent_trade_events")

    if not core_ready:
        overall = "degraded"
    elif missing_core or stale_or_down:
        overall = "partial"
    else:
        overall = "healthy"

    return {
        "status": overall,
        "as_of_utc": datetime.fromtimestamp(
            now_ms / 1000.0, timezone.utc,
        ).isoformat(),
        "core_ready": core_ready,
        "fresh_core_count": len(fresh_core),
        "core_feed_count": len(CORE_FEEDS),
        "fresh_core_feeds": fresh_core,
        "missing_core_feeds": missing_core,
        "source_feeds": list(normalized_sources.values()),
        "stream_feeds": stream_rows,
        "live_orderbook_venues": live_books,
        "connected_quiet_event_feeds": quiet_event_feeds,
        "connected_quiet_liquidation_feeds": quiet_liquidation_feeds,
        "trade_feeds_missing_recent_events": quiet_trade_feeds,
        "non_live_stream_feeds": stale_or_down,
        "warnings": warnings,
        "use_in_decision": "quality_monitor_only_no_directional_vote",
        "limitations": [
            "A fresh HTTP snapshot does not prove a continuously healthy WebSocket.",
            "Liquidation feeds are event-driven; no event is not the same as a disconnected socket.",
            "Trade feeds are expected to deliver frequent BTC trades; a fresh heartbeat without recent trades is reported stale.",
            "A book freshness threshold is a monitoring rule, not proof of market liquidity or feed completeness.",
        ],
    }
