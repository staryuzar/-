from __future__ import annotations
import json
import sqlite3
from pathlib import Path
from typing import Any
from .config import DB_PATH

SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS market_snapshots (
 id INTEGER PRIMARY KEY AUTOINCREMENT,captured_at_ms INTEGER NOT NULL,
 symbol TEXT NOT NULL,aggregate_price REAL,primary_venue TEXT,payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_market_snapshots_time ON market_snapshots(captured_at_ms);
CREATE TABLE IF NOT EXISTS candles (
 venue TEXT NOT NULL,symbol TEXT NOT NULL,interval TEXT NOT NULL,open_time_ms INTEGER NOT NULL,
 open REAL NOT NULL,high REAL NOT NULL,low REAL NOT NULL,close REAL NOT NULL,
 volume REAL NOT NULL,is_closed INTEGER NOT NULL,
 PRIMARY KEY(venue,symbol,interval,open_time_ms)
);
CREATE TABLE IF NOT EXISTS orderbook_snapshots (
 id INTEGER PRIMARY KEY AUTOINCREMENT,venue TEXT NOT NULL,captured_at_ms INTEGER NOT NULL,
 symbol TEXT NOT NULL,bids_json TEXT NOT NULL,asks_json TEXT NOT NULL,imbalance REAL
);
CREATE TABLE IF NOT EXISTS public_trades (
 venue TEXT NOT NULL,trade_id TEXT NOT NULL,symbol TEXT NOT NULL,trade_time_ms INTEGER NOT NULL,
 price REAL NOT NULL,quantity REAL NOT NULL,taker_side TEXT,
 PRIMARY KEY(venue,trade_id)
);
CREATE TABLE IF NOT EXISTS feed_health (
 venue TEXT PRIMARY KEY,checked_at_ms INTEGER NOT NULL,status TEXT NOT NULL,
 latency_ms REAL,error TEXT
);
CREATE TABLE IF NOT EXISTS visual_knowledge_meta (
 namespace TEXT PRIMARY KEY,version TEXT NOT NULL,updated_at_ms INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS visual_candle_pattern_knowledge (
 pattern_id TEXT PRIMARY KEY,version TEXT NOT NULL,name_en TEXT NOT NULL,name_ar TEXT NOT NULL,
 family TEXT NOT NULL,direction TEXT NOT NULL,formation_bars INTEGER NOT NULL,
 definition_json TEXT NOT NULL,empirical_status TEXT NOT NULL,updated_at_ms INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS visual_structure_knowledge (
 structure_id TEXT PRIMARY KEY,version TEXT NOT NULL,name_en TEXT NOT NULL,name_ar TEXT NOT NULL,
 category TEXT NOT NULL,definition_json TEXT NOT NULL,empirical_status TEXT NOT NULL,
 updated_at_ms INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS visual_pattern_observations (
 observation_id TEXT PRIMARY KEY,sample_fingerprint TEXT NOT NULL,symbol TEXT NOT NULL,
 timeframe TEXT NOT NULL,observed_at_ms INTEGER NOT NULL,pattern_id TEXT NOT NULL,
 start_index INTEGER NOT NULL,end_index INTEGER NOT NULL,confirmation_state TEXT NOT NULL,
 evidence_json TEXT NOT NULL,engine_version TEXT NOT NULL,
 FOREIGN KEY(pattern_id) REFERENCES visual_candle_pattern_knowledge(pattern_id)
);
CREATE INDEX IF NOT EXISTS ix_visual_pattern_observations_lookup
 ON visual_pattern_observations(symbol,timeframe,pattern_id,observed_at_ms);
CREATE TABLE IF NOT EXISTS visual_structure_observations (
 observation_id TEXT PRIMARY KEY,sample_fingerprint TEXT NOT NULL,symbol TEXT NOT NULL,
 timeframe TEXT NOT NULL,observed_at_ms INTEGER NOT NULL,structure_id TEXT NOT NULL,
 start_index INTEGER NOT NULL,end_index INTEGER NOT NULL,confirmed INTEGER NOT NULL,
 level_price REAL,zone_low REAL,zone_high REAL,evidence_json TEXT NOT NULL,
 engine_version TEXT NOT NULL,
 FOREIGN KEY(structure_id) REFERENCES visual_structure_knowledge(structure_id)
);
CREATE INDEX IF NOT EXISTS ix_visual_structure_observations_lookup
 ON visual_structure_observations(symbol,timeframe,structure_id,observed_at_ms);
CREATE TABLE IF NOT EXISTS visual_pattern_evaluations (
 evaluation_id INTEGER PRIMARY KEY AUTOINCREMENT,pattern_id TEXT NOT NULL,
 symbol TEXT NOT NULL,timeframe TEXT NOT NULL,market_regime TEXT,
 sample_count INTEGER NOT NULL,precision REAL,recall REAL,f1 REAL,
 mean_return_pct REAL,median_return_pct REAL,mae_pct REAL,mfe_pct REAL,
 fee_adjusted_expectancy_pct REAL,dataset_fingerprint TEXT NOT NULL,
 validation_status TEXT NOT NULL CHECK(validation_status IN ('UNVALIDATED','IN_PROGRESS','VALIDATED','REJECTED')),
 calculated_at_ms INTEGER NOT NULL,
 UNIQUE(pattern_id,symbol,timeframe,market_regime,dataset_fingerprint),
 FOREIGN KEY(pattern_id) REFERENCES visual_candle_pattern_knowledge(pattern_id)
);
CREATE INDEX IF NOT EXISTS ix_visual_pattern_evaluations_status
 ON visual_pattern_evaluations(validation_status,pattern_id,symbol,timeframe);
"""

def connect(db_path: Path | str = DB_PATH) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True,exist_ok=True)
    conn=sqlite3.connect(str(db_path),timeout=15)
    conn.row_factory=sqlite3.Row
    conn.executescript(SCHEMA)
    return conn

def save_market_snapshot(snapshot: dict[str,Any],db_path: Path | str = DB_PATH) -> None:
    captured=int(snapshot["captured_at_ms"])
    conn=connect(db_path)
    try:
        with conn:
            # Keep a compact index row here. Candle, order book and trade detail
            # are stored in their dedicated tables below, not duplicated in every
            # 10-second market snapshot.
            summary = {
                "captured_at_ms": captured,
                "symbol": snapshot["symbol"],
                "price": snapshot.get("price"),
                "primary_venue": snapshot.get("primary_venue"),
                "venue_count": snapshot.get("venue_count", 0),
                "status": snapshot.get("status", "unknown"),
                "venues": {
                    name: {
                        "status": item.get("status"),
                        "bid": item.get("bid"),
                        "ask": item.get("ask"),
                        "latency_ms": item.get("latency_ms"),
                        "error": item.get("error"),
                        "orderflow": item.get("orderflow"),
                    }
                    for name, item in snapshot.get("venues", {}).items()
                },
            }
            conn.execute(
                "INSERT INTO market_snapshots(captured_at_ms,symbol,aggregate_price,primary_venue,payload_json) VALUES(?,?,?,?,?)",
                (captured,snapshot["symbol"],snapshot.get("price"),snapshot.get("primary_venue"),
                 json.dumps(summary,ensure_ascii=False,separators=(",",":"))))
            for venue,item in snapshot.get("venues",{}).items():
                conn.execute(
                    """INSERT INTO feed_health(venue,checked_at_ms,status,latency_ms,error)
                    VALUES(?,?,?,?,?) ON CONFLICT(venue) DO UPDATE SET checked_at_ms=excluded.checked_at_ms,
                    status=excluded.status,latency_ms=excluded.latency_ms,error=excluded.error""",
                    (venue,captured,item.get("status","unknown"),item.get("latency_ms"),item.get("error")))
                timeframe_data=item.get("candles_by_tf") or {"1m":item.get("candles",[])}
                for timeframe,candles in timeframe_data.items():
                    for candle in candles:
                        conn.execute(
                            "INSERT OR REPLACE INTO candles VALUES(?,?,?,?,?,?,?,?,?,?)",
                            (venue,snapshot["symbol"],str(timeframe),int(candle["open_time_ms"]),
                             float(candle["open"]),float(candle["high"]),float(candle["low"]),
                             float(candle["close"]),float(candle["volume"]),1 if candle.get("closed") else 0))
                book=item.get("orderbook")
                if book:
                    conn.execute(
                        "INSERT INTO orderbook_snapshots(venue,captured_at_ms,symbol,bids_json,asks_json,imbalance) VALUES(?,?,?,?,?,?)",
                        (venue,captured,snapshot["symbol"],json.dumps(book.get("bids",[])),
                         json.dumps(book.get("asks",[])),book.get("imbalance")))
                for trade in item.get("trades",[]):
                    conn.execute("INSERT OR IGNORE INTO public_trades VALUES(?,?,?,?,?,?,?)",
                        (venue,str(trade["id"]),snapshot["symbol"],int(trade["time_ms"]),
                         float(trade["price"]),float(trade["quantity"]),trade.get("taker_side")))
            cutoff=captured-7*24*60*60*1000
            conn.execute("DELETE FROM market_snapshots WHERE captured_at_ms < ?",(cutoff,))
            orderbook_cutoff=captured-24*60*60*1000
            conn.execute("DELETE FROM orderbook_snapshots WHERE captured_at_ms < ?",(orderbook_cutoff,))
            conn.execute("DELETE FROM public_trades WHERE trade_time_ms < ?",(captured-30*24*60*60*1000,))
            conn.execute("DELETE FROM candles WHERE open_time_ms < ?",(captured-30*24*60*60*1000,))
    finally:
        conn.close()

def write_json_atomic(path: Path | str,payload: dict[str,Any]) -> None:
    target=Path(path)
    target.parent.mkdir(parents=True,exist_ok=True)
    temp=target.with_suffix(target.suffix+".tmp")
    temp.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")
    temp.replace(target)

def read_json(path: Path | str,default: Any = None) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError,json.JSONDecodeError,UnicodeError):
        return default
