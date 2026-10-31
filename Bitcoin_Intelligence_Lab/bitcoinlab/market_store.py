from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import sqlite3
from typing import Any, Mapping


def read_market_stream_dashboard(
    path: str | Path,
    *,
    symbol: str = "BTCUSDT",
    limit: int = 6,
) -> dict[str, Any]:
    """Read collector health and latest venue books without creating a database."""
    db_path = Path(path)
    if not db_path.is_file():
        return {
            "status": "not_started",
            "reason": "Local market stream database was not found.",
            "venues": [],
            "latest_books": [],
            "liquidation_summary": [],
            "recent_liquidations": [],
        }
    if not 1 <= limit <= 20:
        raise ValueError("limit must be between 1 and 20.")
    uri = db_path.resolve().as_uri() + "?mode=ro"
    try:
        with closing(sqlite3.connect(uri, uri=True, timeout=2.0)) as connection:
            connection.row_factory = sqlite3.Row
            tables = {
                row[0] for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            if not {"stream_status", "orderbook_snapshots"}.issubset(tables):
                return {
                    "status": "unavailable",
                    "reason": "Market stream database schema is incomplete.",
                    "venues": [],
                    "latest_books": [],
                }
            venue_rows = connection.execute(
                """SELECT venue,symbol,status,updated_at_ms,last_message_ms,
                reconnects,last_error FROM stream_status
                WHERE symbol IN (?, 'BTC-USDT') ORDER BY venue LIMIT ?""",
                (symbol.upper(), limit),
            ).fetchall()
            latest_rows = connection.execute(
                """SELECT s.venue,s.symbol,s.observed_at_ms,s.best_bid,s.best_ask,
                s.spread_bps,s.imbalance
                FROM orderbook_snapshots AS s
                JOIN (
                    SELECT venue,symbol,MAX(observed_at_ms) AS latest
                    FROM orderbook_snapshots WHERE symbol IN (?, 'BTC-USDT')
                    GROUP BY venue,symbol
                ) AS x
                ON s.venue=x.venue AND s.symbol=x.symbol AND s.observed_at_ms=x.latest
                ORDER BY s.venue LIMIT ?""",
                (symbol.upper(), limit),
            ).fetchall()
            liquidation_groups = []
            recent_liquidations = []
            if "liquidation_events" in tables:
                since_ms = int(datetime.now(timezone.utc).timestamp() * 1000) - 60 * 60_000
                liquidation_groups = connection.execute(
                    """SELECT venue,market_type,liquidated_side,quantity_unit,
                    COUNT(*) AS event_count,SUM(raw_size) AS total_native_size,
                    SUM(CASE WHEN notional_usd IS NOT NULL THEN notional_usd ELSE 0 END) AS priced_notional_usd,
                    SUM(CASE WHEN notional_usd IS NOT NULL THEN 1 ELSE 0 END) AS priced_event_count,
                    MAX(event_time_ms) AS latest_event_time_ms
                    FROM liquidation_events
                    WHERE event_time_ms>=? AND symbol IN (?, 'BTC-USDT-SWAP')
                    GROUP BY venue,market_type,liquidated_side,quantity_unit
                    ORDER BY venue,liquidated_side""",
                    (since_ms, symbol.upper()),
                ).fetchall()
                recent_liquidations = connection.execute(
                    """SELECT venue,symbol,event_time_ms,liquidated_side,order_side,
                    raw_size,quantity_unit,reference_price,reference_price_kind,notional_usd
                    FROM liquidation_events
                    WHERE symbol IN (?, 'BTC-USDT-SWAP')
                    ORDER BY event_time_ms DESC,id DESC LIMIT 20""",
                    (symbol.upper(),),
                ).fetchall()
                liquidation_short_window = connection.execute(
                    """SELECT venue,market_type,liquidated_side,quantity_unit,
                    COUNT(*) AS event_count,
                    MAX(event_time_ms) AS latest_event_time_ms
                    FROM liquidation_events
                    WHERE event_time_ms>=? AND symbol IN (?, 'BTC-USDT-SWAP')
                    GROUP BY venue,market_type,liquidated_side,quantity_unit
                    ORDER BY venue,liquidated_side""",
                    (
                        int(datetime.now(timezone.utc).timestamp() * 1000) - 300_000,
                        symbol.upper(),
                    ),
                ).fetchall()
        return {
            "status": "ok",
            "venues": [dict(row) for row in venue_rows],
            "latest_books": [dict(row) for row in latest_rows],
            "liquidation_summary": [
                {
                    **dict(row),
                    "notional_usd": (
                        round(row["priced_notional_usd"], 2)
                        if row["priced_event_count"] else None
                    ),
                }
                for row in liquidation_groups
            ],
            "recent_liquidations": [dict(row) for row in recent_liquidations],
            "liquidation_short_window_summary": [
                dict(row) for row in liquidation_short_window
            ],
            "database_path": str(db_path),
        }
    except sqlite3.Error as exc:
        return {
            "status": "unavailable",
            "reason": f"{type(exc).__name__}: {exc}",
            "venues": [],
            "latest_books": [],
        }


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
        CREATE TABLE IF NOT EXISTS liquidation_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_key TEXT NOT NULL UNIQUE,
            venue TEXT NOT NULL,
            symbol TEXT NOT NULL,
            market_type TEXT NOT NULL,
            event_time_ms INTEGER NOT NULL,
            received_at_ms INTEGER NOT NULL,
            liquidated_side TEXT NOT NULL,
            order_side TEXT NOT NULL,
            raw_size REAL NOT NULL,
            quantity_unit TEXT NOT NULL,
            reference_price REAL NOT NULL,
            reference_price_kind TEXT NOT NULL,
            notional_usd REAL,
            payload_json TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS liquidation_events_venue_time
            ON liquidation_events(venue, symbol, event_time_ms);
        CREATE TABLE IF NOT EXISTS trade_seen (
            event_key TEXT PRIMARY KEY,
            venue TEXT NOT NULL,
            event_time_ms INTEGER NOT NULL,
            seen_at_ms INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS trade_seen_venue_time
            ON trade_seen(venue, seen_at_ms);
        CREATE TABLE IF NOT EXISTS trade_flow_minutes (
            venue TEXT NOT NULL,
            symbol TEXT NOT NULL,
            market_type TEXT NOT NULL,
            bucket_start_ms INTEGER NOT NULL,
            buy_base_volume_btc REAL NOT NULL DEFAULT 0,
            sell_base_volume_btc REAL NOT NULL DEFAULT 0,
            buy_notional_usd REAL NOT NULL DEFAULT 0,
            sell_notional_usd REAL NOT NULL DEFAULT 0,
            buy_trade_count INTEGER NOT NULL DEFAULT 0,
            sell_trade_count INTEGER NOT NULL DEFAULT 0,
            last_trade_time_ms INTEGER NOT NULL,
            PRIMARY KEY(venue, symbol, market_type, bucket_start_ms)
        );
        CREATE INDEX IF NOT EXISTS trade_flow_minutes_venue_time
            ON trade_flow_minutes(venue, symbol, bucket_start_ms);
        """)
        self.db.commit()
        self.ensure_market_type_dimension("trade_flow_minutes")

    def ensure_market_type_dimension(self, table_name: str) -> None:
        """Rebuild legacy aggregates so market_type is part of their uniqueness key.

        The old schema could merge Spot and Perpetual values before assigning the
        most recently observed market_type. Those aggregates cannot be safely
        separated after the fact, so preserve the old table as a legacy archive
        and start a clean, correctly keyed table rather than relabel mixed volume.
        """
        configs = {
            "trade_flow_minutes": (
                ("venue", "symbol", "market_type", "bucket_start_ms"),
                """CREATE TABLE trade_flow_minutes (
                    venue TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    market_type TEXT NOT NULL,
                    bucket_start_ms INTEGER NOT NULL,
                    buy_base_volume_btc REAL NOT NULL DEFAULT 0,
                    sell_base_volume_btc REAL NOT NULL DEFAULT 0,
                    buy_notional_usd REAL NOT NULL DEFAULT 0,
                    sell_notional_usd REAL NOT NULL DEFAULT 0,
                    buy_trade_count INTEGER NOT NULL DEFAULT 0,
                    sell_trade_count INTEGER NOT NULL DEFAULT 0,
                    last_trade_time_ms INTEGER NOT NULL,
                    PRIMARY KEY(venue,symbol,market_type,bucket_start_ms)
                )""",
                "CREATE INDEX IF NOT EXISTS trade_flow_minutes_venue_time ON trade_flow_minutes(venue,symbol,bucket_start_ms)",
            ),
            "trade_footprint": (
                ("venue", "symbol", "market_type", "bucket_start_ms", "price_bucket_usd"),
                """CREATE TABLE trade_footprint (
                    venue TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    market_type TEXT NOT NULL,
                    bucket_start_ms INTEGER NOT NULL,
                    price_bucket_usd REAL NOT NULL,
                    buy_base_volume_btc REAL NOT NULL DEFAULT 0,
                    sell_base_volume_btc REAL NOT NULL DEFAULT 0,
                    buy_notional_usd REAL NOT NULL DEFAULT 0,
                    sell_notional_usd REAL NOT NULL DEFAULT 0,
                    trade_count INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY(venue,symbol,market_type,bucket_start_ms,price_bucket_usd)
                )""",
                "CREATE INDEX IF NOT EXISTS trade_footprint_venue_time ON trade_footprint(venue,symbol,bucket_start_ms)",
            ),
        }
        if table_name not in configs:
            raise ValueError("Unsupported market_type dimension table.")
        expected_pk, create_sql, index_sql = configs[table_name]
        info = self.db.execute(f"PRAGMA table_info({table_name})").fetchall()
        current_pk = tuple(
            row[1] for row in sorted(
                (row for row in info if int(row[5]) > 0),
                key=lambda row: int(row[5]),
            )
        )
        if current_pk == expected_pk:
            self.db.execute(index_sql)
            self.db.commit()
            return

        legacy_table = f"{table_name}_legacy_pk_v1"
        legacy_exists = self.db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (legacy_table,),
        ).fetchone()
        if legacy_exists:
            raise RuntimeError(
                f"Cannot migrate {table_name}: legacy archive {legacy_table} already exists."
            )
        self.db.execute("BEGIN IMMEDIATE")
        try:
            self.db.execute(f"ALTER TABLE {table_name} RENAME TO {legacy_table}")
            legacy_index = (
                "trade_flow_minutes_venue_time"
                if table_name == "trade_flow_minutes"
                else "trade_footprint_venue_time"
            )
            self.db.execute(f"DROP INDEX IF EXISTS {legacy_index}")
            self.db.execute(create_sql)
            self.db.execute(index_sql)
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

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
            ("liquidation_events", "event_time_ms"),
            ("trade_flow_minutes", "bucket_start_ms"),
            ("trade_seen", "seen_at_ms"),
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

    def _insert_trade_event(
        self,
        event: Mapping[str, Any],
        received_at_ms: int,
    ) -> bool:
        required = (
            "event_key", "venue", "symbol", "market_type", "event_time_ms",
            "aggressor_side", "price", "base_quantity", "quantity_unit",
            "notional_usd", "trade_count",
        )
        if any(key not in event for key in required):
            raise ValueError("Trade event is missing required normalized fields.")
        price = float(event["price"])
        quantity = float(event["base_quantity"])
        notional = float(event["notional_usd"])
        event_time = int(event["event_time_ms"])
        received = int(received_at_ms)
        count = int(event["trade_count"])
        side = str(event["aggressor_side"])
        if (
            not math.isfinite(price) or price <= 0
            or not math.isfinite(quantity) or quantity <= 0
            or not math.isfinite(notional) or notional <= 0
            or event_time <= 0 or received <= 0 or count < 1
            or side not in {"BUY", "SELL"}
            or event["quantity_unit"] != "BTC"
        ):
            raise ValueError("Invalid normalized BTC trade event.")
        venue = str(event["venue"])
        symbol = str(event["symbol"])
        market_type = str(event["market_type"])
        if not venue or not symbol or not market_type:
            raise ValueError("Trade venue, symbol and market type must be non-empty.")
        bucket = event_time // 60_000 * 60_000

        cursor = self.db.execute(
            """INSERT OR IGNORE INTO trade_seen
            (event_key,venue,event_time_ms,seen_at_ms) VALUES (?,?,?,?)""",
            (str(event["event_key"]), venue, event_time, received),
        )
        if cursor.rowcount != 1:
            return False

        if side == "BUY":
            self.db.execute(
                """INSERT INTO trade_flow_minutes
                (venue,symbol,market_type,bucket_start_ms,buy_base_volume_btc,
                 buy_notional_usd,buy_trade_count,last_trade_time_ms)
                VALUES (?,?,?,?,?,?,?,?)
                ON CONFLICT(venue,symbol,market_type,bucket_start_ms) DO UPDATE SET
                  buy_base_volume_btc=buy_base_volume_btc+excluded.buy_base_volume_btc,
                  buy_notional_usd=buy_notional_usd+excluded.buy_notional_usd,
                  buy_trade_count=buy_trade_count+excluded.buy_trade_count,
                  last_trade_time_ms=MAX(last_trade_time_ms,excluded.last_trade_time_ms)""",
                (venue, symbol, market_type, bucket, quantity, notional, count, event_time),
            )
        else:
            self.db.execute(
                """INSERT INTO trade_flow_minutes
                (venue,symbol,market_type,bucket_start_ms,sell_base_volume_btc,
                 sell_notional_usd,sell_trade_count,last_trade_time_ms)
                VALUES (?,?,?,?,?,?,?,?)
                ON CONFLICT(venue,symbol,market_type,bucket_start_ms) DO UPDATE SET
                  sell_base_volume_btc=sell_base_volume_btc+excluded.sell_base_volume_btc,
                  sell_notional_usd=sell_notional_usd+excluded.sell_notional_usd,
                  sell_trade_count=sell_trade_count+excluded.sell_trade_count,
                  last_trade_time_ms=MAX(last_trade_time_ms,excluded.last_trade_time_ms)""",
                (venue, symbol, market_type, bucket, quantity, notional, count, event_time),
            )
        return True

    def record_trade_event(
        self,
        *,
        event: Mapping[str, Any],
        received_at_ms: int,
    ) -> bool:
        with self.db:
            return self._insert_trade_event(event, received_at_ms)

    def record_trade_events(
        self,
        *,
        events: list[Mapping[str, Any]],
        received_at_ms: int,
    ) -> int:
        """Insert a WebSocket batch in one SQLite transaction."""
        inserted = 0
        with self.db:
            for event in events:
                inserted += int(self._insert_trade_event(event, received_at_ms))
        return inserted

    def trade_flow_summary(
        self,
        *,
        symbol: str = "BTCUSDT",
        now_ms: int,
        windows_seconds: tuple[int, ...] = (60, 300, 900, 3600, 14400),
    ) -> list[dict[str, Any]]:
        if not windows_seconds or any(
            isinstance(item, bool) or not isinstance(item, int) or item < 60
            for item in windows_seconds
        ):
            raise ValueError("Trade-flow windows must contain positive whole seconds >= 60.")
        largest_window = max(windows_seconds)
        since_ms = int(now_ms) - largest_window * 1000
        self.db.row_factory = sqlite3.Row
        rows = self.db.execute(
            """SELECT venue,symbol,market_type,bucket_start_ms,
            buy_base_volume_btc,sell_base_volume_btc,
            buy_notional_usd,sell_notional_usd,
            buy_trade_count,sell_trade_count,last_trade_time_ms
            FROM trade_flow_minutes
            WHERE symbol=? AND bucket_start_ms>=?
            ORDER BY venue,bucket_start_ms""",
            (symbol.upper(), since_ms // 60_000 * 60_000),
        ).fetchall()
        by_venue: dict[tuple[str, str], list[sqlite3.Row]] = {}
        for row in rows:
            by_venue.setdefault((row["venue"], row["market_type"]), []).append(row)

        labels = {60: "1m", 300: "5m", 900: "15m", 3600: "1h", 14400: "4h"}
        result: list[dict[str, Any]] = []
        for (venue, market_type), venue_rows in sorted(by_venue.items()):
            for window in windows_seconds:
                start = int(now_ms) - window * 1000
                selected = [row for row in venue_rows if row["bucket_start_ms"] >= start // 60_000 * 60_000]
                buy_btc = sum(float(row["buy_base_volume_btc"]) for row in selected)
                sell_btc = sum(float(row["sell_base_volume_btc"]) for row in selected)
                buy_usd = sum(float(row["buy_notional_usd"]) for row in selected)
                sell_usd = sum(float(row["sell_notional_usd"]) for row in selected)
                buy_count = sum(int(row["buy_trade_count"]) for row in selected)
                sell_count = sum(int(row["sell_trade_count"]) for row in selected)
                total_usd = buy_usd + sell_usd
                total_btc = buy_btc + sell_btc
                result.append({
                    "venue": venue,
                    "symbol": symbol.upper(),
                    "market_type": market_type,
                    "timeframe": labels.get(window, f"{window}s"),
                    "window_seconds": window,
                    "status": "ok" if total_usd > 0 else "empty",
                    "buy_base_volume_btc": round(buy_btc, 8),
                    "sell_base_volume_btc": round(sell_btc, 8),
                    "delta_base_volume_btc": round(buy_btc - sell_btc, 8),
                    "buy_notional_usd": round(buy_usd, 2),
                    "sell_notional_usd": round(sell_usd, 2),
                    "delta_notional_usd": round(buy_usd - sell_usd, 2),
                    "delta_notional_ratio": (
                        round((buy_usd - sell_usd) / total_usd, 6)
                        if total_usd > 0 else None
                    ),
                    "total_notional_usd": round(total_usd, 2),
                    "total_base_volume_btc": round(total_btc, 8),
                    "buy_trade_count": buy_count,
                    "sell_trade_count": sell_count,
                    "trade_count": buy_count + sell_count,
                    "last_trade_time_ms": (
                        max(int(row["last_trade_time_ms"]) for row in selected)
                        if selected else None
                    ),
                })
        return result

    def record_liquidation(
        self,
        *,
        event: Mapping[str, Any],
        received_at_ms: int,
    ) -> bool:
        required = (
            "event_key", "venue", "symbol", "market_type", "event_time_ms",
            "liquidated_side", "order_side", "raw_size", "quantity_unit",
            "reference_price", "reference_price_kind",
        )
        if any(key not in event for key in required):
            raise ValueError("Liquidation event is missing required normalized fields.")
        size = float(event["raw_size"])
        price = float(event["reference_price"])
        if (
            not math.isfinite(size) or size <= 0
            or not math.isfinite(price) or price <= 0
            or int(event["event_time_ms"]) <= 0
            or int(received_at_ms) <= 0
            or event["liquidated_side"] not in {"LONG", "SHORT"}
        ):
            raise ValueError("Invalid normalized liquidation event.")
        payload = json.dumps(
            dict(event), separators=(",", ":"), ensure_ascii=False, allow_nan=False,
        )
        cursor = self.db.execute(
            """INSERT OR IGNORE INTO liquidation_events
            (event_key,venue,symbol,market_type,event_time_ms,received_at_ms,
             liquidated_side,order_side,raw_size,quantity_unit,reference_price,
             reference_price_kind,notional_usd,payload_json)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                str(event["event_key"]), str(event["venue"]), str(event["symbol"]),
                str(event["market_type"]), int(event["event_time_ms"]),
                int(received_at_ms), str(event["liquidated_side"]),
                str(event["order_side"]), size, str(event["quantity_unit"]),
                price, str(event["reference_price_kind"]),
                float(event["notional_usd"]) if event.get("notional_usd") is not None else None,
                payload,
            ),
        )
        self.db.commit()
        return cursor.rowcount == 1

    def recent_liquidations(
        self, *, since_ms: int, limit: int = 200,
    ) -> list[dict[str, Any]]:
        if not 1 <= limit <= 10_000:
            raise ValueError("limit must be between 1 and 10000.")
        self.db.row_factory = sqlite3.Row
        rows = self.db.execute(
            """SELECT * FROM liquidation_events
            WHERE event_time_ms>=?
            ORDER BY event_time_ms DESC,id DESC LIMIT ?""",
            (int(since_ms), limit),
        ).fetchall()
        return [
            {
                "event_key": row["event_key"],
                "venue": row["venue"],
                "symbol": row["symbol"],
                "market_type": row["market_type"],
                "event_time_ms": row["event_time_ms"],
                "received_at_ms": row["received_at_ms"],
                "liquidated_side": row["liquidated_side"],
                "order_side": row["order_side"],
                "raw_size": row["raw_size"],
                "quantity_unit": row["quantity_unit"],
                "reference_price": row["reference_price"],
                "reference_price_kind": row["reference_price_kind"],
                "notional_usd": row["notional_usd"],
                "payload": json.loads(row["payload_json"]),
            }
            for row in reversed(rows)
        ]

    def liquidation_summary(
        self, *, since_ms: int,
    ) -> list[dict[str, Any]]:
        self.db.row_factory = sqlite3.Row
        rows = self.db.execute(
            """SELECT venue,market_type,liquidated_side,quantity_unit,
            COUNT(*) AS event_count,SUM(raw_size) AS total_native_size,
            SUM(CASE WHEN notional_usd IS NOT NULL THEN notional_usd ELSE 0 END) AS priced_notional_usd,
            SUM(CASE WHEN notional_usd IS NOT NULL THEN 1 ELSE 0 END) AS priced_event_count,
            MAX(event_time_ms) AS latest_event_time_ms
            FROM liquidation_events WHERE event_time_ms>=?
            GROUP BY venue,market_type,liquidated_side,quantity_unit
            ORDER BY venue,liquidated_side""",
            (int(since_ms),),
        ).fetchall()
        return [
            {
                "venue": row["venue"],
                "market_type": row["market_type"],
                "liquidated_side": row["liquidated_side"],
                "quantity_unit": row["quantity_unit"],
                "event_count": row["event_count"],
                "total_native_size": row["total_native_size"],
                "notional_usd": (
                    round(row["priced_notional_usd"], 2)
                    if row["priced_event_count"] else None
                ),
                "priced_event_count": row["priced_event_count"],
                "latest_event_time_ms": row["latest_event_time_ms"],
            }
            for row in rows
        ]

    def close(self) -> None:
        self.db.close()

    def __enter__(self) -> "MarketDataStore":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()
