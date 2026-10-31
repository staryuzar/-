from __future__ import annotations

from datetime import datetime, timezone
import math
from pathlib import Path
from contextlib import closing
import sqlite3
from typing import Any, Mapping

from .market_store import MarketDataStore


def ensure_trade_footprint_schema(store: MarketDataStore) -> None:
    """Create the additive footprint table once per store connection."""
    if getattr(store, "_trade_footprint_schema_ready", False):
        return
    store.db.executescript("""
    CREATE TABLE IF NOT EXISTS trade_footprint (
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
        PRIMARY KEY(venue,symbol,bucket_start_ms,price_bucket_usd)
    );
    CREATE INDEX IF NOT EXISTS trade_footprint_venue_time
        ON trade_footprint(venue,symbol,bucket_start_ms);
    """)
    store.db.commit()
    store._trade_footprint_schema_ready = True


def record_trade_batch(
    store: MarketDataStore,
    *,
    events: list[Mapping[str, Any]],
    received_at_ms: int,
) -> int:
    """Persist deduplicated CVD and per-price footprint in one SQLite transaction."""
    ensure_trade_footprint_schema(store)
    inserted = 0
    with store.db:
        for event in events:
            if not store._insert_trade_event(event, received_at_ms):
                continue
            venue = str(event["venue"])
            symbol = str(event["symbol"])
            market_type = str(event["market_type"])
            event_time = int(event["event_time_ms"])
            price_bucket = float(event.get("price_bucket_usd", math.floor(float(event["price"]) / 10.0) * 10.0))
            quantity = float(event["base_quantity"])
            notional = float(event["notional_usd"])
            count = int(event["trade_count"])
            if (
                not math.isfinite(price_bucket) or price_bucket <= 0
                or not math.isfinite(quantity) or quantity <= 0
                or not math.isfinite(notional) or notional <= 0
                or count < 1
            ):
                raise ValueError("Invalid footprint event values.")
            side = str(event["aggressor_side"]).upper()
            if side == "BUY":
                buy_btc, sell_btc, buy_usd, sell_usd = quantity, 0.0, notional, 0.0
            elif side == "SELL":
                buy_btc, sell_btc, buy_usd, sell_usd = 0.0, quantity, 0.0, notional
            else:
                raise ValueError("Footprint aggressor side must be BUY or SELL.")
            bucket = event_time // 60_000 * 60_000
            store.db.execute(
                """INSERT INTO trade_footprint
                (venue,symbol,market_type,bucket_start_ms,price_bucket_usd,
                 buy_base_volume_btc,sell_base_volume_btc,
                 buy_notional_usd,sell_notional_usd,trade_count)
                VALUES (?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(venue,symbol,bucket_start_ms,price_bucket_usd)
                DO UPDATE SET
                  buy_base_volume_btc=trade_footprint.buy_base_volume_btc+excluded.buy_base_volume_btc,
                  sell_base_volume_btc=trade_footprint.sell_base_volume_btc+excluded.sell_base_volume_btc,
                  buy_notional_usd=trade_footprint.buy_notional_usd+excluded.buy_notional_usd,
                  sell_notional_usd=trade_footprint.sell_notional_usd+excluded.sell_notional_usd,
                  trade_count=trade_footprint.trade_count+excluded.trade_count,
                  market_type=excluded.market_type""",
                (venue, symbol, market_type, bucket, price_bucket,
                 buy_btc, sell_btc, buy_usd, sell_usd, count),
            )
            inserted += 1
    return inserted


def read_trade_analytics(
    path: str | Path,
    *,
    symbol: str = "BTCUSDT",
    now_ms: int | None = None,
    windows_seconds: tuple[int, ...] = (60, 300, 900, 3600, 14400),
    footprint_seconds: int = 900,
) -> dict[str, Any]:
    """Read CVD windows and price footprint from the shared SQLite DB (read-only)."""
    if not windows_seconds or any(
        isinstance(item, bool) or not isinstance(item, int) or item < 60
        for item in windows_seconds
    ):
        raise ValueError("Trade-flow windows must be whole seconds >= 60.")
    if isinstance(footprint_seconds, bool) or not isinstance(footprint_seconds, int) or footprint_seconds < 60:
        raise ValueError("footprint_seconds must be an integer >= 60.")
    now = int(now_ms if now_ms is not None else datetime.now(timezone.utc).timestamp() * 1000)
    db_path = Path(path)
    empty = {
        "status": "not_started",
        "trade_flow_summary": [],
        "trade_footprint": [],
        "trade_feed_status": [],
    }
    if not db_path.is_file():
        return {**empty, "reason": "Local trade analytics database was not found."}
    uri = db_path.resolve().as_uri() + "?mode=ro"
    try:
        with closing(sqlite3.connect(uri, uri=True, timeout=2.0)) as connection:
            connection.row_factory = sqlite3.Row
            tables = {
                row[0] for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            if "trade_flow_minutes" not in tables:
                return {**empty, "status": "unavailable", "reason": "Trade-flow table is unavailable."}

            rows = connection.execute(
                """SELECT venue,symbol,market_type,bucket_start_ms,
                buy_base_volume_btc,sell_base_volume_btc,
                buy_notional_usd,sell_notional_usd,
                buy_trade_count,sell_trade_count,last_trade_time_ms
                FROM trade_flow_minutes
                WHERE symbol=? AND bucket_start_ms>=? AND bucket_start_ms<=?
                ORDER BY venue,bucket_start_ms""",
                (
                    symbol.upper(),
                    (now - max(windows_seconds) * 1000) // 60_000 * 60_000,
                    now // 60_000 * 60_000,
                ),
            ).fetchall()

            labels = {60: "1m", 300: "5m", 900: "15m", 3600: "1h", 14400: "4h"}
            flow_summary: list[dict[str, Any]] = []
            grouped: dict[tuple[str, str], list[sqlite3.Row]] = {}
            for row in rows:
                grouped.setdefault((str(row["venue"]), str(row["market_type"])), []).append(row)
            for (venue, market_type), venue_rows in sorted(grouped.items()):
                for window in windows_seconds:
                    start = (now - window * 1000) // 60_000 * 60_000
                    selected = [row for row in venue_rows if int(row["bucket_start_ms"]) >= start]
                    buy_btc = sum(float(row["buy_base_volume_btc"]) for row in selected)
                    sell_btc = sum(float(row["sell_base_volume_btc"]) for row in selected)
                    buy_usd = sum(float(row["buy_notional_usd"]) for row in selected)
                    sell_usd = sum(float(row["sell_notional_usd"]) for row in selected)
                    buy_count = sum(int(row["buy_trade_count"]) for row in selected)
                    sell_count = sum(int(row["sell_trade_count"]) for row in selected)
                    total_usd = buy_usd + sell_usd
                    last_trade = max(
                        (int(row["last_trade_time_ms"]) for row in selected),
                        default=None,
                    )
                    flow_summary.append({
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
                        "buy_trade_count": buy_count,
                        "sell_trade_count": sell_count,
                        "trade_count": buy_count + sell_count,
                        "last_trade_time_ms": last_trade,
                    })

            footprint_rows: list[dict[str, Any]] = []
            if "trade_footprint" in tables:
                since = (now - footprint_seconds * 1000) // 60_000 * 60_000
                footprint_rows = [
                    dict(row) for row in connection.execute(
                        """SELECT venue,symbol,market_type,price_bucket_usd,
                        SUM(buy_base_volume_btc) AS buy_base_volume_btc,
                        SUM(sell_base_volume_btc) AS sell_base_volume_btc,
                        SUM(buy_notional_usd) AS buy_notional_usd,
                        SUM(sell_notional_usd) AS sell_notional_usd,
                        SUM(trade_count) AS trade_count
                        FROM trade_footprint
                        WHERE symbol=? AND bucket_start_ms>=? AND bucket_start_ms<=?
                        GROUP BY venue,symbol,market_type,price_bucket_usd
                        ORDER BY venue,market_type,price_bucket_usd""",
                        (symbol.upper(), since, now // 60_000 * 60_000),
                    ).fetchall()
                ]
            feed_status: list[dict[str, Any]] = []
            if "stream_status" in tables:
                feed_status = [
                    dict(row) for row in connection.execute(
                        """SELECT venue,symbol,status,updated_at_ms,last_message_ms,
                        reconnects,last_error FROM stream_status
                        WHERE symbol=? AND venue LIKE '%_trades'
                        ORDER BY venue""",
                        (symbol.upper(),),
                    ).fetchall()
                ]
            return {
                "status": "ok",
                "trade_flow_summary": flow_summary,
                "trade_footprint": footprint_rows,
                "trade_feed_status": feed_status,
                "footprint_window_seconds": footprint_seconds,
                "database_path": str(db_path),
            }
    except sqlite3.Error as exc:
        return {
            **empty,
            "status": "unavailable",
            "reason": f"{type(exc).__name__}: {exc}",
        }


def prune_trade_footprint(
    store: MarketDataStore,
    *,
    now_ms: int,
) -> int:
    """Apply the same configured retention horizon to persistent price-level buckets."""
    ensure_trade_footprint_schema(store)
    cutoff = int(now_ms) - store.retention_ms
    with store.db:
        cursor = store.db.execute(
            "DELETE FROM trade_footprint WHERE bucket_start_ms < ?",
            (cutoff,),
        )
    return cursor.rowcount
