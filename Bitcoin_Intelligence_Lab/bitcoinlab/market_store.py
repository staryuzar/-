from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any, Mapping


class MarketDataStore:
    """Small local SQLite store for sampled live order-book history and feed health."""

    def __init__(self, path: str | Path, *, retention_hours: int = 24) -> None:
        if not 1 <= retention_hours <= 24 * 30:
            raise ValueError("retention_hours must be between 1 and 720.")
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.retention_ms = retention_hours * 3_600_000
        self.db = sqlite3.connect(self.path, timeout=10.0)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=NORMAL")
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS stream_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            venue TEXT NOT NULL,
            symbol TEXT NOT NULL,
            event_time_ms INTEGER,
            received_at_ms INTEGER NOT NULL,
            event_type TEXT NOT NULL,
            sequence_id INTEGER,
            payload_json TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS stream_events_venue_time
            ON stream_events(venue, symbol, received_at_ms);
        CREATE TABLE IF NOT EXISTS orderbook_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            venue TEXT NOT NULL,
            symbol TEXT NOT NULL,
            observed_at_ms INTEGER NOT NULL,
            best_bid REAL NOT NULL,
            best_ask REAL NOT NULL,
            spread_bps REAL NOT NULL,
            imbalance REAL NOT NULL,
            bids_json TEXT NOT NULL,
            asks_json TEXT NOT NULL,
            update_id INTEGER,
            sequence_id INTEGER
        );
        CREATE INDEX IF NOT EXISTS orderbook_snapshots_venue_time
            ON orderbook_snapshots(venue, symbol, observed_at_ms);
        CREATE TABLE IF NOT EXISTS stream_status (
            venue TEXT NOT NULL,
            symbol TEXT NOT NULL,
            status TEXT NOT NULL,
            updated_at_ms INTEGER NOT NULL,
            last_message_ms INTEGER,
            reconnects INTEGER NOT NULL DEFAULT 0,
            last_error TEXT,
            PRIMARY KEY(venue, symbol)
        );
        """)
        self.db.commit()

    def record_event(
        self,
        *,
        venue: str,
        symbol: str,
        received_at_ms: int,
        event_type: str,
        payload: Mapping[str, Any],
        event_time_ms: int | None = None,
        sequence_id: int | None = None,
    ) -> None:
        self.db.execute(
            """INSERT INTO stream_events
            (venue,symbol,event_time_ms,received_at_ms,event_type,sequence_id,payload_json)
            VALUES (?,?,?,?,?,?,?)""",
            (
                venue, symbol, event_time_ms, received_at_ms, event_type,
                sequence_id,
                json.dumps(payload, separators=(",", ":"), ensure_ascii=False, allow_nan=False),
            ),
        )
        self.db.commit()

    def record_snapshot(
        self,
        *,
        venue: str,
        symbol: str,
        observed_at_ms: int,
        book: Mapping[str, Any],
        metrics: Mapping[str, Any],
    ) -> None:
        bids = book.get("bids")
        asks = book.get("asks")
        if not isinstance(bids, list) or not isinstance(asks, list) or not bids or not asks:
            raise ValueError("Cannot persist an unavailable order book.")
        best_bid, best_ask = float(metrics["best_bid"]), float(metrics["best_ask"])
        if best_bid <= 0 or best_ask <= best_bid:
            raise ValueError("Cannot persist an invalid best bid/ask.")
        self.db.execute(
            """INSERT INTO orderbook_snapshots
            (venue,symbol,observed_at_ms,best_bid,best_ask,spread_bps,imbalance,
             bids_json,asks_json,update_id,sequence_id)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                venue, symbol, observed_at_ms, best_bid, best_ask,
                float(metrics["spread_bps"]), float(metrics["imbalance"]),
                json.dumps(bids, separators=(",", ":"), allow_nan=False),
                json.dumps(asks, separators=(",", ":"), allow_nan=False),
                book.get("last_update_id", book.get("update_id")),
                book.get("sequence_id"),
            ),
        )
        self.db.commit()

    def record_status(
        self,
        *,
        venue: str,
        symbol: str,
        status: str,
        updated_at_ms: int,
        last_message_ms: int | None = None,
        reconnects: int = 0,
        last_error: str | None = None,
    ) -> None:
        self.db.execute(
            """INSERT INTO stream_status
            (venue,symbol,status,updated_at_ms,last_message_ms,reconnects,last_error)
            VALUES (?,?,?,?,?,?,?)
            ON CONFLICT(venue,symbol) DO UPDATE SET
              status=excluded.status, updated_at_ms=excluded.updated_at_ms,
              last_message_ms=COALESCE(excluded.last_message_ms,stream_status.last_message_ms),
              reconnects=excluded.reconnects,last_error=excluded.last_error""",
            (
                venue, symbol, status, updated_at_ms, last_message_ms,
                reconnects, last_error[:300] if last_error else None,
            ),
        )
        self.db.commit()

    def prune(self, *, now_ms: int) -> dict[str, int]:
        cutoff = int(now_ms) - self.retention_ms
        removed = {}
        for table, column in (
            ("stream_events", "received_at_ms"),
            ("orderbook_snapshots", "observed_at_ms"),
        ):
            cursor = self.db.execute(f"DELETE FROM {table} WHERE {column} < ?", (cutoff,))
            removed[table] = cursor.rowcount
        self.db.commit()
        return removed

    def latest_status(self) -> list[dict[str, Any]]:
        self.db.row_factory = sqlite3.Row
        rows = self.db.execute(
            "SELECT venue,symbol,status,updated_at_ms,last_message_ms,reconnects,last_error "
            "FROM stream_status ORDER BY venue,symbol"
        ).fetchall()
        return [dict(row) for row in rows]

    def recent_snapshots(
        self, *, venue: str, symbol: str, since_ms: int, limit: int = 500,
    ) -> list[dict[str, Any]]:
        if not 1 <= limit <= 10_000:
            raise ValueError("limit must be between 1 and 10000.")
        self.db.row_factory = sqlite3.Row
        rows = self.db.execute(
            """SELECT venue,symbol,observed_at_ms,best_bid,best_ask,spread_bps,
            imbalance,bids_json,asks_json,update_id,sequence_id
            FROM orderbook_snapshots
            WHERE venue=? AND symbol=? AND observed_at_ms>=?
            ORDER BY observed_at_ms DESC LIMIT ?""",
            (venue, symbol, int(since_ms), limit),
        ).fetchall()
        return [
            {
                **{key: row[key] for key in (
                    "venue","symbol","observed_at_ms","best_bid","best_ask",
                    "spread_bps","imbalance","update_id","sequence_id",
                )},
                "bids": json.loads(row["bids_json"]),
                "asks": json.loads(row["asks_json"]),
                "observed_at_utc": datetime.fromtimestamp(
                    row["observed_at_ms"] / 1000, timezone.utc,
                ).isoformat(),
            }
            for row in reversed(rows)
        ]

    def close(self) -> None:
        self.db.close()

    def __enter__(self) -> "MarketDataStore":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()
