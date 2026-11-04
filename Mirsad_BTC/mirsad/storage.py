from __future__ import annotations
import json
import math
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from .config import DB_PATH, DECISION_CALIBRATION_DB_PATH

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
CREATE TABLE IF NOT EXISTS market_intelligence_snapshots (
 id INTEGER PRIMARY KEY AUTOINCREMENT,captured_at_ms INTEGER NOT NULL,
 symbol TEXT NOT NULL,status TEXT NOT NULL,directional_score REAL,confidence REAL,
 payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_market_intelligence_time ON market_intelligence_snapshots(captured_at_ms);
CREATE TABLE IF NOT EXISTS mt5_deals (
 deal_ticket TEXT PRIMARY KEY,
 order_ticket TEXT NOT NULL,
 position_id TEXT NOT NULL,
 magic INTEGER NOT NULL,
 symbol TEXT NOT NULL,
 deal_type INTEGER NOT NULL,
 deal_entry INTEGER NOT NULL,
 deal_reason INTEGER NOT NULL,
 time_server_ms INTEGER NOT NULL,
 time_basis TEXT NOT NULL DEFAULT 'MT5_SERVER_TIME',
 volume REAL NOT NULL,
 price REAL NOT NULL,
 profit REAL NOT NULL,
 commission REAL NOT NULL,
 swap REAL NOT NULL,
 fee REAL NOT NULL,
 net_cashflow REAL NOT NULL,
 currency TEXT NOT NULL,
 comment TEXT NOT NULL,
 payload_json TEXT NOT NULL,
 observed_at_ms INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS storage_migrations (
 migration_id TEXT PRIMARY KEY,
 applied_at_ms INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS decision_calibration_samples (
 sample_key TEXT PRIMARY KEY,
 captured_at_ms INTEGER NOT NULL,
 signal_bar_time_ms INTEGER NOT NULL,
 symbol TEXT NOT NULL,
 profile_version TEXT NOT NULL,
 engine1_status TEXT NOT NULL,
 engine1_score REAL,
 engine1_confidence REAL,
 engine1_coverage REAL,
 engine2_status TEXT NOT NULL,
 engine2_direction TEXT,
 engine2_score REAL,
 engine2_quality REAL,
 engine2_coverage REAL,
 engine2_agreement REAL,
 engine3_status TEXT NOT NULL,
 engine3_score REAL,
 engine3_quality REAL,
 engine3_timeframe_coverage REAL,
 native_parity_status TEXT NOT NULL,
 native_parity_passed_metrics INTEGER,
 native_parity_total_metrics INTEGER,
 combined_score REAL,
 directional_threshold REAL,
 candidate_action TEXT NOT NULL,
 final_action TEXT NOT NULL,
 decision_status TEXT NOT NULL,
 reference_price REAL,
 broker_spread_pct REAL,
 effective_weights_json TEXT NOT NULL,
 calibration_config_json TEXT NOT NULL,
 evidence_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_decision_calibration_time
 ON decision_calibration_samples(symbol,captured_at_ms);
CREATE TABLE IF NOT EXISTS decision_calibration_candles (
 symbol TEXT NOT NULL,
 timeframe TEXT NOT NULL,
 open_time_ms INTEGER NOT NULL,
 open REAL NOT NULL,
 high REAL NOT NULL,
 low REAL NOT NULL,
 close REAL NOT NULL,
 volume REAL NOT NULL,
 PRIMARY KEY(symbol,timeframe,open_time_ms)
);
CREATE INDEX IF NOT EXISTS ix_decision_calibration_candles_time
 ON decision_calibration_candles(symbol,timeframe,open_time_ms);

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
 horizon_metrics_json TEXT NOT NULL DEFAULT '{}',
 primary_horizon_bars INTEGER NOT NULL DEFAULT 5,
 data_split TEXT NOT NULL DEFAULT 'train',
 label_source TEXT NOT NULL DEFAULT 'UNSPECIFIED',
 human_reviewed INTEGER NOT NULL DEFAULT 0,
 fee_bps REAL NOT NULL DEFAULT 0,
 slippage_bps REAL NOT NULL DEFAULT 0,
 UNIQUE(pattern_id,symbol,timeframe,market_regime,dataset_fingerprint),
 FOREIGN KEY(pattern_id) REFERENCES visual_candle_pattern_knowledge(pattern_id)
);
CREATE INDEX IF NOT EXISTS ix_visual_pattern_evaluations_status
 ON visual_pattern_evaluations(validation_status,pattern_id,symbol,timeframe);
CREATE TABLE IF NOT EXISTS visual_structure_evaluations (
 evaluation_id INTEGER PRIMARY KEY AUTOINCREMENT,
 structure_id TEXT NOT NULL,
 symbol TEXT NOT NULL,
 venue TEXT NOT NULL,
 timeframe TEXT NOT NULL,
 market_regime TEXT NOT NULL DEFAULT 'UNSPECIFIED',
 sample_count INTEGER NOT NULL,
 mean_return_pct REAL,
 median_return_pct REAL,
 mae_pct REAL,
 mfe_pct REAL,
 fee_adjusted_expectancy_pct REAL,
 dataset_fingerprint TEXT NOT NULL,
 validation_status TEXT NOT NULL DEFAULT 'IN_PROGRESS'
   CHECK(validation_status IN ('UNVALIDATED','IN_PROGRESS','VALIDATED','REJECTED')),
 calculated_at_ms INTEGER NOT NULL,
 horizon_metrics_json TEXT NOT NULL DEFAULT '{}',
 primary_horizon_bars INTEGER NOT NULL DEFAULT 5,
 data_split TEXT NOT NULL CHECK(data_split IN ('train','validation','test')),
 event_source TEXT NOT NULL DEFAULT 'engine_2_detector',
 human_reviewed INTEGER NOT NULL DEFAULT 0,
 fee_bps_per_side REAL,
 slippage_bps_per_side REAL,
 round_trip_cost_pct REAL,
 dataset_id TEXT NOT NULL DEFAULT '',
 split_start_ms INTEGER NOT NULL DEFAULT 0,
 split_end_ms INTEGER NOT NULL DEFAULT 0,
 embargo_bars INTEGER NOT NULL DEFAULT 0,
 UNIQUE(structure_id,symbol,venue,timeframe,market_regime,dataset_fingerprint,data_split),
 FOREIGN KEY(structure_id) REFERENCES visual_structure_knowledge(structure_id)
);
CREATE INDEX IF NOT EXISTS ix_visual_structure_evaluations_lookup
 ON visual_structure_evaluations(validation_status,structure_id,symbol,timeframe,data_split);
CREATE TABLE IF NOT EXISTS visual_structure_evaluation_splits (
 split_id INTEGER PRIMARY KEY AUTOINCREMENT,
 dataset_id TEXT NOT NULL,
 symbol TEXT NOT NULL,
 venue TEXT NOT NULL,
 timeframe TEXT NOT NULL,
 data_split TEXT NOT NULL CHECK(data_split IN ('train','validation','test')),
 split_start_ms INTEGER NOT NULL,
 split_end_ms INTEGER NOT NULL,
 embargo_bars INTEGER NOT NULL DEFAULT 0,
 dataset_fingerprint TEXT NOT NULL,
 registered_at_ms INTEGER NOT NULL,
 UNIQUE(dataset_id,symbol,venue,timeframe,data_split),
 CHECK(split_end_ms > split_start_ms),
 CHECK(embargo_bars >= 0)
);
CREATE INDEX IF NOT EXISTS ix_visual_structure_split_windows
 ON visual_structure_evaluation_splits(dataset_id,symbol,venue,timeframe,split_start_ms,split_end_ms);
"""

def connect(db_path: Path | str = DB_PATH) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True,exist_ok=True)
    conn=sqlite3.connect(str(db_path),timeout=15)
    conn.row_factory=sqlite3.Row
    conn.executescript(SCHEMA)
    # Migrate the first deal-ledger schema without discarding historical rows.
    # The former time_utc_ms column contains UTC-normalized values, while the
    # current producer preserves native MT5 server-clock timestamps. Keep that
    # distinction explicit per row rather than silently shifting old history.
    deal_columns = {
        row["name"] for row in conn.execute("PRAGMA table_info(mt5_deals)").fetchall()
    }
    if "time_server_ms" not in deal_columns:
        if "time_utc_ms" not in deal_columns:
            conn.close()
            raise sqlite3.DatabaseError(
                "mt5_deals has neither time_server_ms nor the supported legacy time_utc_ms column."
            )
        with conn:
            conn.execute("DROP INDEX IF EXISTS ix_mt5_deals_position_time")
            conn.execute("DROP INDEX IF EXISTS ix_mt5_deals_time")
            conn.execute("DROP TABLE IF EXISTS mt5_deals_server_time_migration")
            conn.execute(
                """CREATE TABLE mt5_deals_server_time_migration (
                    deal_ticket TEXT PRIMARY KEY,
                    order_ticket TEXT NOT NULL,
                    position_id TEXT NOT NULL,
                    magic INTEGER NOT NULL,
                    symbol TEXT NOT NULL,
                    deal_type INTEGER NOT NULL,
                    deal_entry INTEGER NOT NULL,
                    deal_reason INTEGER NOT NULL,
                    time_server_ms INTEGER NOT NULL,
                    time_basis TEXT NOT NULL,
                    volume REAL NOT NULL,
                    price REAL NOT NULL,
                    profit REAL NOT NULL,
                    commission REAL NOT NULL,
                    swap REAL NOT NULL,
                    fee REAL NOT NULL,
                    net_cashflow REAL NOT NULL,
                    currency TEXT NOT NULL,
                    comment TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    observed_at_ms INTEGER NOT NULL
                )"""
            )
            conn.execute(
                """INSERT INTO mt5_deals_server_time_migration
                   (deal_ticket,order_ticket,position_id,magic,symbol,deal_type,
                    deal_entry,deal_reason,time_server_ms,time_basis,volume,price,
                    profit,commission,swap,fee,net_cashflow,currency,comment,
                    payload_json,observed_at_ms)
                   SELECT deal_ticket,order_ticket,position_id,magic,symbol,deal_type,
                          deal_entry,deal_reason,time_utc_ms,'LEGACY_UTC_NORMALIZED',
                          volume,price,profit,commission,swap,fee,net_cashflow,
                          currency,comment,payload_json,observed_at_ms
                   FROM mt5_deals"""
            )
            conn.execute("DROP TABLE mt5_deals")
            conn.execute(
                "ALTER TABLE mt5_deals_server_time_migration RENAME TO mt5_deals"
            )
    elif "time_basis" not in deal_columns:
        with conn:
            conn.execute(
                "ALTER TABLE mt5_deals ADD COLUMN time_basis TEXT NOT NULL DEFAULT 'MT5_SERVER_TIME'"
            )
    # Recreate indexes after schema migration so existing databases with the
    # old column names cannot block application startup.
    with conn:
        conn.execute(
            "CREATE INDEX IF NOT EXISTS ix_mt5_deals_position_time ON mt5_deals(magic,symbol,position_id,time_server_ms)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS ix_mt5_deals_time ON mt5_deals(magic,symbol,time_server_ms)"
        )
    # Separate legacy OKX UTC+8 daily bars before new UTC (1Dutc) bars are
    # written into the canonical '1d' interval. Preserve the old data under a
    # distinct interval key instead of mixing incompatible day boundaries.
    migration_id = "okx_daily_utc8_separation_v1"
    with conn:
        # The marker insert takes the SQLite write lock; only the connection
        # that inserts it performs the one-time data separation.
        migration_cursor = conn.execute(
            """INSERT OR IGNORE INTO storage_migrations(migration_id,applied_at_ms)
               VALUES(?,?)""",
            (migration_id, int(time.time() * 1000)),
        )
        if migration_cursor.rowcount:
            conn.execute(
                """UPDATE candles SET interval='1d_utc8'
                   WHERE venue='OKX Spot' AND interval='1d'"""
            )
    # Forward-compatible columns for the visual pattern evaluation archive.
    evaluation_columns = {
        row["name"] for row in conn.execute(
            "PRAGMA table_info(visual_pattern_evaluations)"
        ).fetchall()
    }
    evaluation_migrations = {
        "horizon_metrics_json": "TEXT NOT NULL DEFAULT '{}'",
        "primary_horizon_bars": "INTEGER NOT NULL DEFAULT 5",
        "data_split": "TEXT NOT NULL DEFAULT 'train'",
        "label_source": "TEXT NOT NULL DEFAULT 'UNSPECIFIED'",
        "human_reviewed": "INTEGER NOT NULL DEFAULT 0",
        "fee_bps": "REAL NOT NULL DEFAULT 0",
        "slippage_bps": "REAL NOT NULL DEFAULT 0",
    }
    for column_name, column_type in evaluation_migrations.items():
        if column_name not in evaluation_columns:
            conn.execute(
                f"ALTER TABLE visual_pattern_evaluations ADD COLUMN {column_name} {column_type}"
            )
    structure_columns = {
        row["name"] for row in conn.execute(
            "PRAGMA table_info(visual_structure_evaluations)"
        ).fetchall()
    }
    structure_migrations = {
        "dataset_id": "TEXT NOT NULL DEFAULT ''",
        "split_start_ms": "INTEGER NOT NULL DEFAULT 0",
        "split_end_ms": "INTEGER NOT NULL DEFAULT 0",
        "embargo_bars": "INTEGER NOT NULL DEFAULT 0",
    }
    for column_name, column_type in structure_migrations.items():
        if column_name not in structure_columns:
            conn.execute(
                f"ALTER TABLE visual_structure_evaluations ADD COLUMN {column_name} {column_type}"
            )
    # Backfill the independent split registry from structure evaluations
    # written by earlier versions, preserving the first-seen dataset window.
    with conn:
        conn.execute(
            """INSERT OR IGNORE INTO visual_structure_evaluation_splits
               (dataset_id,symbol,venue,timeframe,data_split,split_start_ms,
                split_end_ms,embargo_bars,dataset_fingerprint,registered_at_ms)
               SELECT dataset_id,symbol,venue,timeframe,data_split,
                      MIN(split_start_ms),MAX(split_end_ms),MAX(embargo_bars),
                      MAX(dataset_fingerprint),MAX(calculated_at_ms)
               FROM visual_structure_evaluations
               WHERE dataset_id<>'' AND split_start_ms>0 AND split_end_ms>split_start_ms
               GROUP BY dataset_id,symbol,venue,timeframe,data_split"""
        )
    return conn

def save_market_intelligence_snapshot(snapshot: dict[str,Any],db_path: Path | str = DB_PATH) -> None:
    if not isinstance(snapshot,dict) or not snapshot:
        return
    captured=int(snapshot.get("captured_at_ms") or time.time_ns()//1_000_000)
    symbol=str(snapshot.get("symbol") or "BTCUSDT")
    score=snapshot.get("directional_score")
    confidence=snapshot.get("confidence")
    conn=connect(db_path)
    try:
        with conn:
            conn.execute(
                "INSERT INTO market_intelligence_snapshots(captured_at_ms,symbol,status,directional_score,confidence,payload_json) VALUES(?,?,?,?,?,?)",
                (captured,symbol,str(snapshot.get("status","UNKNOWN")),score,confidence,
                 json.dumps(snapshot,ensure_ascii=False,separators=(",",":"))),
            )
            conn.execute("DELETE FROM market_intelligence_snapshots WHERE captured_at_ms < ?",
                         (captured-30*24*60*60*1000,))
    finally:
        conn.close()


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
            # Preserve intraday candles for 30 days, daily candles for 400 days,
            # and weekly candles for 5 years so Engine 2 can form larger structures.
            intraday_cutoff = captured - 30 * 24 * 60 * 60 * 1000
            daily_cutoff = captured - 400 * 24 * 60 * 60 * 1000
            weekly_cutoff = captured - 5 * 365 * 24 * 60 * 60 * 1000
            conn.execute(
                """DELETE FROM candles
                   WHERE interval NOT IN ('1d','1d_utc8','1w') AND open_time_ms < ?""",
                (intraday_cutoff,),
            )
            conn.execute(
                "DELETE FROM candles WHERE interval IN ('1d','1d_utc8') AND open_time_ms < ?",
                (daily_cutoff,),
            )
            conn.execute(
                "DELETE FROM candles WHERE interval='1w' AND open_time_ms < ?",
                (weekly_cutoff,),
            )
    finally:
        conn.close()


DECISION_CALIBRATION_PROFILE_VERSION = "mirsad-engine-weights-fixed-share-v5-2026-11-04"
DECISION_CALIBRATION_RETENTION_DAYS = 180


def _calibration_finite(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def save_decision_calibration_sample(
    *,
    market: dict[str, Any],
    candle_history: dict[str, Any],
    market_intelligence: dict[str, Any],
    engine2_price_action: dict[str, Any],
    indicators: dict[str, Any],
    decision: dict[str, Any],
    db_path: Path | str = DECISION_CALIBRATION_DB_PATH,
) -> dict[str, Any]:
    """Persist one auditable, non-executing sample per completed M1 signal bar.

    Samples are accepted only when Engine 2, Engine 3 and the native MT5
    numeric-parity gate are READY/PASS. This is data collection for later
    chronological calibration; it never changes a decision or sends a command.
    """
    if not all(isinstance(item, dict) for item in (
        market, candle_history, market_intelligence, engine2_price_action,
        indicators, decision,
    )):
        return {"status": "SKIPPED", "reason": "A required calibration input is not an object."}

    if engine2_price_action.get("status") != "READY":
        return {"status": "SKIPPED", "reason": "Engine 2 price action is not READY."}
    if indicators.get("status") != "READY":
        return {"status": "SKIPPED", "reason": "Engine 3 indicators are not READY."}
    parity = indicators.get("mt5_native_parity")
    if not isinstance(parity, dict) or parity.get("status") != "PASS":
        return {"status": "SKIPPED", "reason": "Engine 3 native MT5 numeric parity has not passed."}
    if int(parity.get("passed_metrics", 0) or 0) != 120 or int(parity.get("total_metrics", 0) or 0) != 120:
        return {"status": "SKIPPED", "reason": "Engine 3 parity must pass all 120 metrics."}

    candle_sets = candle_history.get("candles_by_tf")
    if not isinstance(candle_sets, dict):
        return {"status": "SKIPPED", "reason": "Engine 2 candle timeframe map is missing."}
    one_minute = candle_sets.get("1m")
    if not isinstance(one_minute, list):
        return {"status": "SKIPPED", "reason": "Engine 2 M1 candles are missing."}
    closed_one_minute = [
        row for row in one_minute
        if isinstance(row, dict) and row.get("closed") is True
    ]
    if not closed_one_minute:
        return {"status": "SKIPPED", "reason": "No closed M1 candle is available."}

    try:
        signal_bar_time_ms = int(closed_one_minute[-1]["open_time_ms"])
        captured_at_ms = int(market.get("captured_at_ms") or time.time() * 1000)
    except (KeyError, TypeError, ValueError, OverflowError):
        return {"status": "SKIPPED", "reason": "Calibration timestamps are invalid."}
    if signal_bar_time_ms <= 0 or captured_at_ms <= 0:
        return {"status": "SKIPPED", "reason": "Calibration timestamps must be positive."}

    symbol = str(market.get("symbol") or candle_history.get("symbol") or "BTCUSDT").strip().upper()
    profile_version = DECISION_CALIBRATION_PROFILE_VERSION
    sample_key = f"{symbol}:1m:{signal_bar_time_ms}:{profile_version}"
    scores = decision.get("decision_scores") if isinstance(decision.get("decision_scores"), dict) else {}
    weights = decision.get("decision_weights") if isinstance(decision.get("decision_weights"), dict) else {}
    engine2_summary = (
        engine2_price_action.get("summary")
        if isinstance(engine2_price_action.get("summary"), dict) else {}
    )
    engine2_context = (
        decision.get("engine_2_native_price_action_context")
        if isinstance(decision.get("engine_2_native_price_action_context"), dict) else {}
    )
    engine1_components = (
        market_intelligence.get("components")
        if isinstance(market_intelligence.get("components"), dict) else {}
    )
    engine2_timeframes: dict[str, Any] = {}
    for timeframe, row in (engine2_price_action.get("timeframes") or {}).items():
        if not isinstance(row, dict):
            continue
        engine2_timeframes[str(timeframe)] = {
            "status": row.get("status"),
            "direction": row.get("direction"),
            "directional_evidence_score": row.get("directional_evidence_score"),
            "directional_evidence": row.get("directional_evidence"),
        }
    engine3_components = (
        indicators.get("signal_components_by_timeframe")
        if isinstance(indicators.get("signal_components_by_timeframe"), dict) else {}
    )
    native_report = indicators.get("mt5_native") if isinstance(indicators.get("mt5_native"), dict) else {}
    reference_price = _calibration_finite(market.get("price"))
    broker_spread_pct = _calibration_finite(decision.get("broker_spread_pct"))
    effective_weights = weights.get("effective_weights")
    if not isinstance(effective_weights, dict):
        effective_weights = {
            key: value for key, value in weights.items()
            if key != "configured" and isinstance(value, (int, float))
        }
    config_payload = {
        "profile_version": profile_version,
        "decision_weights": weights,
        "engine1_component_weights": {
            name: item.get("weight")
            for name, item in engine1_components.items() if isinstance(item, dict)
        },
        "engine2_directional_evidence_weights": engine2_summary.get("directional_evidence_weights"),
        "engine2_timeframe_weights": engine2_summary.get("timeframe_weights"),
        "engine3_signal_group_weights": indicators.get("signal_group_weights"),
        "engine3_timeframe_weights": indicators.get("timeframe_weights"),
        "directional_threshold": scores.get("threshold"),
        "minimum_engine2_direction_score": scores.get("minimum_engine_2_direction_score"),
    }
    evidence_payload = {
        "engine1": {
            "status": market_intelligence.get("status"),
            "direction": market_intelligence.get("direction"),
            "components": engine1_components,
            "source_statuses": market_intelligence.get("source_statuses"),
        },
        "engine2": {
            "status": engine2_price_action.get("status"),
            "direction": engine2_price_action.get("direction"),
            "summary": engine2_summary,
            "timeframes": engine2_timeframes,
            "decision_context": engine2_context,
        },
        "engine3": {
            "status": indicators.get("status"),
            "signal_score": indicators.get("signal_score"),
            "signal_quality": indicators.get("signal_quality"),
            "signal_timeframe_weight_coverage": indicators.get("signal_timeframe_weight_coverage"),
            "signal_group_weights": indicators.get("signal_group_weights"),
            "signal_components_by_timeframe": engine3_components,
            "native_parity": {
                "status": parity.get("status"),
                "passed_metrics": parity.get("passed_metrics"),
                "total_metrics": parity.get("total_metrics"),
            },
            "native_feed_status": native_report.get("status"),
        },
        "engine4": {
            "status": decision.get("status"),
            "action": decision.get("action"),
            "candidate_action": decision.get("candidate_action"),
            "chart_gate": decision.get("chart_gate"),
            "decision_scores": scores,
            "decision_weights": weights,
        },
    }
    valid_candles: list[tuple[Any, ...]] = []
    for timeframe, bars in candle_sets.items():
        if not isinstance(bars, list):
            continue
        for bar in bars:
            if not isinstance(bar, dict) or bar.get("closed") is not True:
                continue
            try:
                stamp = int(bar.get("open_time_ms", 0))
                values = [
                    float(bar[name]) for name in ("open", "high", "low", "close")
                ]
                volume = float(bar.get("volume", bar.get("tick_volume", 0.0)))
            except (KeyError, TypeError, ValueError, OverflowError):
                continue
            if (
                stamp <= 0 or not all(math.isfinite(value) and value > 0 for value in values)
                or not math.isfinite(volume) or volume < 0
            ):
                continue
            opening, high, low, close = values
            if high < max(opening, close, low) or low > min(opening, close, high):
                continue
            valid_candles.append((symbol, str(timeframe), stamp, opening, high, low, close, volume))

    conn = connect(db_path)
    try:
        with conn:
            cursor = conn.execute(
                """INSERT OR IGNORE INTO decision_calibration_samples (
                    sample_key,captured_at_ms,signal_bar_time_ms,symbol,profile_version,
                    engine1_status,engine1_score,engine1_confidence,engine1_coverage,
                    engine2_status,engine2_direction,engine2_score,engine2_quality,
                    engine2_coverage,engine2_agreement,
                    engine3_status,engine3_score,engine3_quality,engine3_timeframe_coverage,
                    native_parity_status,native_parity_passed_metrics,native_parity_total_metrics,
                    combined_score,directional_threshold,candidate_action,final_action,
                    decision_status,reference_price,broker_spread_pct,effective_weights_json,
                    calibration_config_json,evidence_json
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    sample_key, captured_at_ms, signal_bar_time_ms, symbol, profile_version,
                    str(market_intelligence.get("status", "UNKNOWN")),
                    _calibration_finite(market_intelligence.get("directional_score")),
                    _calibration_finite(market_intelligence.get("confidence")),
                    _calibration_finite(market_intelligence.get("evidence_coverage")),
                    str(engine2_price_action.get("status", "UNKNOWN")),
                    str(engine2_price_action.get("direction", "UNKNOWN")),
                    _calibration_finite(scores.get("engine_2_native_ohlc_score")),
                    _calibration_finite(scores.get("engine_2_quality")),
                    _calibration_finite(engine2_summary.get("timeframe_weight_coverage")),
                    _calibration_finite(engine2_summary.get("directional_structure_agreement")),
                    str(indicators.get("status", "UNKNOWN")),
                    _calibration_finite(indicators.get("signal_score")),
                    _calibration_finite(indicators.get("signal_quality")),
                    _calibration_finite(indicators.get("signal_timeframe_weight_coverage")),
                    str(parity.get("status", "UNKNOWN")),
                    int(parity.get("passed_metrics", 0) or 0),
                    int(parity.get("total_metrics", 0) or 0),
                    _calibration_finite(scores.get("combined_score")),
                    _calibration_finite(scores.get("threshold")),
                    str(decision.get("candidate_action", "WAIT")),
                    str(decision.get("action", "WAIT")),
                    str(decision.get("status", "UNKNOWN")),
                    reference_price, broker_spread_pct,
                    json.dumps(effective_weights, ensure_ascii=False, separators=(",", ":"), allow_nan=False),
                    json.dumps(config_payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False),
                    json.dumps(evidence_payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False),
                ),
            )
            inserted = cursor.rowcount == 1
            candles_inserted = 0
            if inserted and valid_candles:
                candle_cursor = conn.executemany(
                    """INSERT OR IGNORE INTO decision_calibration_candles
                       (symbol,timeframe,open_time_ms,open,high,low,close,volume)
                       VALUES(?,?,?,?,?,?,?,?)""",
                    valid_candles,
                )
                candles_inserted = max(0, candle_cursor.rowcount)
            cutoff = captured_at_ms - DECISION_CALIBRATION_RETENTION_DAYS * 24 * 60 * 60 * 1000
            conn.execute(
                "DELETE FROM decision_calibration_samples WHERE captured_at_ms < ?",
                (cutoff,),
            )
            conn.execute(
                "DELETE FROM decision_calibration_candles WHERE open_time_ms < ?",
                (cutoff,),
            )
        sample_count = int(conn.execute(
            "SELECT COUNT(*) FROM decision_calibration_samples WHERE profile_version=? AND symbol=?",
            (profile_version, symbol),
        ).fetchone()[0])
        # Checkpoint WAL so the single-file cache contains every committed sample.
        checkpoint = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        if checkpoint and int(checkpoint[0]) != 0:
            raise sqlite3.OperationalError("Calibration database WAL checkpoint is busy.")
        return {
            "status": "STORED" if inserted else "ALREADY_STORED",
            "sample_key": sample_key,
            "signal_bar_time_ms": signal_bar_time_ms,
            "candles_inserted": candles_inserted,
            "sample_count": sample_count,
            "profile_version": profile_version,
        }
    except (sqlite3.Error, TypeError, ValueError, OverflowError) as exc:
        return {"status": "ERROR", "reason": f"{type(exc).__name__}: {exc}"}
    finally:
        conn.close()

CANDLE_INTERVAL_MS = {
    "1m": 60_000,
    "5m": 5 * 60_000,
    "15m": 15 * 60_000,
    "1h": 60 * 60_000,
    "4h": 4 * 60 * 60_000,
    "1d": 24 * 60 * 60_000,
    "1w": 7 * 24 * 60 * 60_000,
}


def load_candles_by_timeframe(
    *,
    symbol: str,
    venue: str,
    timeframes: tuple[str, ...] | list[str],
    as_of_ms: int,
    limit: int = 120,
    db_path: Path | str = DB_PATH,
) -> dict[str, list[dict[str, Any]]]:
    """Read one venue's closed OHLCV candles without merging exchanges.

    A candle is returned only when its stored closed flag is true and its
    scheduled close is at or before as_of_ms. Results are chronological.
    """
    clean_symbol = str(symbol).strip().upper()
    clean_venue = str(venue).strip()
    if not clean_symbol:
        raise ValueError("symbol is required")
    if not clean_venue:
        raise ValueError("venue is required; candle feeds must not be merged implicitly")
    if not isinstance(as_of_ms, int) or as_of_ms <= 0:
        raise ValueError("as_of_ms must be a positive Unix timestamp in milliseconds")
    if not isinstance(limit, int) or not 8 <= limit <= 2000:
        raise ValueError("limit must be between 8 and 2000")
    requested = tuple(dict.fromkeys(str(tf).strip() for tf in timeframes))
    if not requested:
        raise ValueError("at least one timeframe is required")
    unsupported = [tf for tf in requested if tf not in CANDLE_INTERVAL_MS]
    if unsupported:
        raise ValueError(f"unsupported timeframe(s): {', '.join(unsupported)}")

    conn = connect(db_path)
    result: dict[str, list[dict[str, Any]]] = {}
    try:
        for timeframe in requested:
            cutoff_open_ms = as_of_ms - CANDLE_INTERVAL_MS[timeframe]
            rows = conn.execute(
                """SELECT open_time_ms,open,high,low,close,volume,is_closed
                   FROM candles
                   WHERE venue=? AND symbol=? AND interval=?
                     AND is_closed=1 AND open_time_ms<=?
                   ORDER BY open_time_ms DESC
                   LIMIT ?""",
                (clean_venue, clean_symbol, timeframe, cutoff_open_ms, limit),
            ).fetchall()
            selected = list(reversed(rows))
            candles = [
                {
                    "open_time_ms": int(row["open_time_ms"]),
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "volume": float(row["volume"]),
                    "closed": bool(row["is_closed"]),
                    "source_interval": timeframe,
                }
                for row in selected
            ]

            # Market Engine 1 currently stores daily but not weekly candles.
            # Engine 2 may derive a weekly bar only from seven consecutive,
            # individually closed UTC daily bars in the same venue.
            if timeframe == "1w" and not candles:
                daily_cutoff = as_of_ms - CANDLE_INTERVAL_MS["1d"]
                daily_rows = conn.execute(
                    """SELECT open_time_ms,open,high,low,close,volume,is_closed
                       FROM candles
                       WHERE venue=? AND symbol=? AND interval='1d'
                         AND is_closed=1 AND open_time_ms<=?
                       ORDER BY open_time_ms DESC
                       LIMIT ?""",
                    (
                        clean_venue, clean_symbol, daily_cutoff,
                        min(3000, limit * 7 + 14),
                    ),
                ).fetchall()
                daily = list(reversed(daily_rows))
                weekly_groups: dict[int, list[sqlite3.Row]] = {}
                for row in daily:
                    stamp_ms = int(row["open_time_ms"])
                    stamp = datetime.fromtimestamp(
                        stamp_ms / 1000, tz=timezone.utc
                    )
                    monday = (
                        stamp - timedelta(days=stamp.weekday())
                    ).replace(hour=0, minute=0, second=0, microsecond=0)
                    week_open_ms = int(monday.timestamp() * 1000)
                    weekly_groups.setdefault(week_open_ms, []).append(row)

                derived: list[dict[str, Any]] = []
                day_ms = CANDLE_INTERVAL_MS["1d"]
                week_ms = CANDLE_INTERVAL_MS["1w"]
                for week_open_ms, group in sorted(weekly_groups.items()):
                    group = sorted(group, key=lambda row: int(row["open_time_ms"]))
                    expected_times = [
                        week_open_ms + index * day_ms for index in range(7)
                    ]
                    actual_times = [int(row["open_time_ms"]) for row in group]
                    if actual_times != expected_times:
                        continue
                    if week_open_ms + week_ms > as_of_ms:
                        continue
                    derived.append({
                        "open_time_ms": week_open_ms,
                        "open": float(group[0]["open"]),
                        "high": max(float(row["high"]) for row in group),
                        "low": min(float(row["low"]) for row in group),
                        "close": float(group[-1]["close"]),
                        "volume": sum(float(row["volume"]) for row in group),
                        "closed": True,
                        "source_interval": "1d_aggregated_to_1w_utc_monday",
                    })
                candles = derived[-limit:]

            result[timeframe] = candles
        return result
    finally:
        conn.close()


def save_mt5_deal_history(
    history: dict[str, Any] | None,
    db_path: Path | str = DB_PATH,
) -> dict[str, Any]:
    """Persist validated Mirsad-owned broker deals idempotently by deal ticket."""
    if not isinstance(history, dict) or history.get("schema") != "MIR1-DEALS-1":
        return {"status": "NOT_REPORTED", "received": 0, "stored": 0}
    producer_status = str(history.get("status") or "UNAVAILABLE").strip().upper()
    if producer_status != "READY":
        preserved_status = (
            producer_status
            if producer_status in {"UNAVAILABLE", "STALE", "INVALID", "NOT_REPORTED"}
            else "INVALID"
        )
        return {
            "status": preserved_status, "received": 0, "stored": 0,
            "reason": str(history.get("reason") or "MT5 deal history is not ready."),
        }
    try:
        observed_at = int(history["queried_at_utc_ms"])
        magic = int(history["magic"])
        symbol = str(history["symbol"]).strip().upper()
        currency = str(history["currency"]).strip()
        rows = history["deals"]
    except (KeyError, TypeError, ValueError, OverflowError):
        return {"status": "INVALID", "received": 0, "stored": 0}
    if observed_at <= 0 or magic <= 0 or not symbol or not currency or not isinstance(rows, list):
        return {"status": "INVALID", "received": 0, "stored": 0}

    validated: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            return {"status": "INVALID", "received": len(rows), "stored": 0,
                    "reason": f"Deal {index} is not an object."}
        try:
            item = {
                "deal_ticket": str(int(row["deal_ticket"])),
                "order_ticket": str(int(row.get("order_ticket", 0) or 0)),
                "position_id": str(int(row["position_id"])),
                "magic": int(row["magic"]),
                "symbol": str(row["symbol"]).strip().upper(),
                "deal_type": int(row["type"]),
                "deal_entry": int(row["entry"]),
                "deal_reason": int(row.get("reason", 0) or 0),
                "time_server_ms": int(row["time_server_ms"]),
                "time_basis": str(history.get("time_basis") or ""),
                "volume": float(row["volume"]),
                "price": float(row["price"]),
                "profit": float(row["profit"]),
                "commission": float(row["commission"]),
                "swap": float(row["swap"]),
                "fee": float(row["fee"]),
                "net_cashflow": float(row["net_cashflow"]),
                "currency": str(row["currency"]).strip(),
                "comment": str(row.get("comment", "")),
            }
        except (KeyError, TypeError, ValueError, OverflowError):
            return {"status": "INVALID", "received": len(rows), "stored": 0,
                    "reason": f"Deal {index} contains missing or invalid fields."}
        numeric = (
            item["volume"], item["price"], item["profit"], item["commission"],
            item["swap"], item["fee"], item["net_cashflow"],
        )
        if (
            int(item["deal_ticket"]) <= 0 or int(item["position_id"]) <= 0
            or item["magic"] != magic or item["symbol"] != symbol
            or item["time_server_ms"] <= 0 or item["time_basis"] != "MT5_SERVER_TIME"
            or not item["currency"] or item["deal_ticket"] in seen
            or any(not math.isfinite(value) for value in numeric)
            or item["volume"] < 0 or item["price"] < 0
            or abs(item["net_cashflow"] - (
                item["profit"] + item["commission"] + item["swap"] + item["fee"]
            )) > 0.02
        ):
            return {"status": "INVALID", "received": len(rows), "stored": 0,
                    "reason": f"Deal {index} failed identity or financial validation."}
        seen.add(item["deal_ticket"])
        validated.append(item)

    conn = connect(db_path)
    try:
        with conn:
            for item in validated:
                conn.execute(
                    """INSERT INTO mt5_deals
                       (deal_ticket,order_ticket,position_id,magic,symbol,deal_type,
                        deal_entry,deal_reason,time_server_ms,time_basis,volume,price,profit,
                        commission,swap,fee,net_cashflow,currency,comment,
                        payload_json,observed_at_ms)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(deal_ticket) DO UPDATE SET
                        order_ticket=excluded.order_ticket,
                        position_id=excluded.position_id,
                        magic=excluded.magic,
                        symbol=excluded.symbol,
                        deal_type=excluded.deal_type,
                        deal_entry=excluded.deal_entry,
                        deal_reason=excluded.deal_reason,
                        time_server_ms=excluded.time_server_ms,
                        time_basis=excluded.time_basis,
                        volume=excluded.volume,
                        price=excluded.price,
                        profit=excluded.profit,
                        commission=excluded.commission,
                        swap=excluded.swap,
                        fee=excluded.fee,
                        net_cashflow=excluded.net_cashflow,
                        currency=excluded.currency,
                        comment=excluded.comment,
                        payload_json=excluded.payload_json,
                        observed_at_ms=excluded.observed_at_ms""",
                    (
                        item["deal_ticket"], item["order_ticket"], item["position_id"],
                        item["magic"], item["symbol"], item["deal_type"],
                        item["deal_entry"], item["deal_reason"], item["time_server_ms"],
                        item["time_basis"], item["volume"], item["price"], item["profit"],
                        item["commission"], item["swap"], item["fee"],
                        item["net_cashflow"], item["currency"], item["comment"],
                        json.dumps(item, ensure_ascii=False, separators=(",", ":")),
                        observed_at,
                    ),
                )
    except sqlite3.Error as exc:
        return {"status": "STORAGE_ERROR", "received": len(rows), "stored": 0,
                "reason": f"{type(exc).__name__}: {exc}"}
    finally:
        conn.close()
    return {
        "status": "READY",
        "received": len(validated),
        "stored": len(validated),
        "queried_at_utc_ms": observed_at,
        "magic": magic,
        "symbol": symbol,
        "currency": currency,
        "truncated": bool(history.get("truncated")),
    }


def load_mt5_deal_history(
    *,
    magic_number: int,
    symbol: str,
    from_server_ms: int = 0,
    limit: int = 1000,
    db_path: Path | str = DB_PATH,
) -> list[dict[str, Any]]:
    """Load persisted broker deals for one Mirsad magic number and symbol."""
    clean_symbol = str(symbol).strip().upper()
    if int(magic_number) <= 0 or not clean_symbol:
        raise ValueError("A positive Mirsad magic number and symbol are required.")
    if not isinstance(from_server_ms, int) or from_server_ms < 0:
        raise ValueError("from_server_ms must be a non-negative Unix timestamp in milliseconds.")
    if not isinstance(limit, int) or not 1 <= limit <= 10000:
        raise ValueError("limit must be between 1 and 10000.")
    conn = connect(db_path)
    try:
        rows = conn.execute(
            """SELECT deal_ticket,order_ticket,position_id,magic,symbol,deal_type,
                      deal_entry,deal_reason,time_server_ms,time_basis,volume,price,profit,
                      commission,swap,fee,net_cashflow,currency,comment
               FROM mt5_deals
               WHERE magic=? AND symbol=? AND time_server_ms>=?
               ORDER BY time_server_ms DESC, deal_ticket DESC LIMIT ?""",
            (int(magic_number), clean_symbol, from_server_ms, limit),
        ).fetchall()
        return [
            {key: row[key] for key in row.keys()}
            for row in rows
        ]
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
