"""Local append-only ledger for explicitly saved analysis snapshots."""
from __future__ import annotations
from datetime import datetime, timezone
import hashlib, json, sqlite3, uuid
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
SENSITIVE_MARKERS = ("password","passwd","secret","token","credential","authorization","api_key","apikey","login","account_number")

class AuditLedgerError(RuntimeError):
    """Local audit storage could not be written, read, or verified."""

def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _redact(v) for k,v in value.items()
                if not any(marker in str(k).casefold() for marker in SENSITIVE_MARKERS)}
    if isinstance(value, (list, tuple)):
        return [_redact(v) for v in value]
    return value

def _pick(source: Any, keys: tuple[str, ...]) -> dict[str, Any]:
    if not isinstance(source, dict): return {}
    return {k: source[k] for k in keys if k in source}

def build_audit_payload(report: dict[str, Any]) -> dict[str, Any]:
    """Whitelist analysis facts and omit credentials and unknown caller fields."""
    if not isinstance(report, dict): raise ValueError("Analysis report must be a dictionary.")
    source, market = report.get("market_source", {}), report.get("market", {})
    analysis, scanner, advisor = report.get("analysis", {}), report.get("scanner", {}), report.get("advisor", {})
    if not isinstance(source, dict) or not source.get("symbol") or not source.get("timeframe"):
        raise ValueError("Analysis report is missing the market symbol or timeframe.")
    if not isinstance(analysis, dict): analysis = {}
    if not isinstance(scanner, dict): scanner = {}
    if not isinstance(advisor, dict): advisor = {}
    if not isinstance(market, dict): market = {}
    ratings, ready = analysis.get("ratings", {}), analysis.get("readiness", {})
    review, trend = analysis.get("current_market_review", {}), scanner.get("trend", {})
    volatility = scanner.get("volatility", {})
    components = analysis.get("components", [])
    payload = {
        "schema_version": SCHEMA_VERSION,
        "market_source": _pick(source, ("symbol","timeframe","terminal_connected","bars_requested","bars_received","closed_bar_start_position")),
        "market": _pick(market, ("bid","ask","spread_price","spread_points","quote_time_utc","quote_age_seconds","quote_fresh","last_closed_bar_open_utc","last_closed_bar_close_utc","last_closed_bar_age_seconds","closed_bar_fresh","maximum_quote_age_seconds","maximum_closed_bar_age_seconds","price_digits","point","trade_tick_size")),
        "analysis": {
            "engine_version": analysis.get("engine_version"), "bar_time": analysis.get("bar_time"), "adx_profile": analysis.get("adx_profile"),
            "readiness": _pick(ready, ("moving_averages_ready","moving_averages_total","oscillators_ready","oscillators_total","total_ready","total_components","complete")),
            "ratings": _pick(ratings, ("moving_averages","moving_averages_category_ar","oscillators","oscillators_category_ar","overall","overall_category_ar","is_complete")),
            "current_market_review": _pick(review, ("eligible","status","reason_ar")),
            "components": [_pick(c, ("key","name_ar","group","group_ar","ready","status_ar","vote","vote_label_ar","raw_values","reason_ar")) for c in components if isinstance(c, dict)] if isinstance(components, list) else [],
        },
        "scanner": {
            "timeframe": scanner.get("timeframe"), "bar_time_utc": scanner.get("bar_time_utc"), "bars_received": scanner.get("bars_received"),
            "trend": _pick(trend, ("state","state_ar","ema20","ema50","reason_ar")),
            "volatility": _pick(volatility, ("atr14","atr_median_recent","atr_ratio","state","state_ar")),
            "parameters": _pick(scanner.get("parameters", {}), ("lookback","swing_left","swing_right","level_tolerance","tick_size")),
            "support_zones": scanner.get("support_zones", []) if isinstance(scanner.get("support_zones", []), list) else [],
            "resistance_zones": scanner.get("resistance_zones", []) if isinstance(scanner.get("resistance_zones", []), list) else [],
            "setups": scanner.get("setups", []) if isinstance(scanner.get("setups", []), list) else [],
            "limitations_ar": scanner.get("limitations_ar", []) if isinstance(scanner.get("limitations_ar", []), list) else [],
        },
        "advisor": _pick(advisor, ("rule_version","status","title_ar","summary_ar","evidence_ar","conflicts_ar","missing_evidence_ar","rating","rating_category_ar","trend_state","confirmed_bullish_setups","confirmed_bearish_setups","probability","trade_execution_enabled","mode","interpretation_ar")),
    }
    return _redact(payload)

class LocalAuditLedger:
    """SQLite append-only journal. UPDATE and DELETE are rejected by triggers."""
    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser().resolve()
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._initialize()
        except (OSError, sqlite3.Error) as exc:
            raise AuditLedgerError(f"Could not initialize local audit storage: {exc}") from exc

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path), timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _initialize(self) -> None:
        conn = self._connect()
        try:
            conn.executescript("""
            CREATE TABLE IF NOT EXISTS audit_events (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              event_id TEXT NOT NULL UNIQUE, schema_version INTEGER NOT NULL,
              created_at_utc TEXT NOT NULL, symbol TEXT NOT NULL, timeframe TEXT NOT NULL,
              quote_time_utc TEXT, bar_time_utc TEXT, advisor_status TEXT,
              payload_json TEXT NOT NULL, payload_sha256 TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_audit_events_created ON audit_events(created_at_utc DESC);
            CREATE TRIGGER IF NOT EXISTS audit_events_no_update BEFORE UPDATE ON audit_events
              BEGIN SELECT RAISE(ABORT, 'audit events are append-only'); END;
            CREATE TRIGGER IF NOT EXISTS audit_events_no_delete BEFORE DELETE ON audit_events
              BEGIN SELECT RAISE(ABORT, 'audit events are append-only'); END;
            """)
            conn.commit()
        finally: conn.close()

    def append_analysis(self, report: dict[str, Any]) -> dict[str, Any]:
        payload = build_audit_payload(report)
        try:
            payload_json = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise AuditLedgerError(f"Analysis report is not valid finite JSON: {exc}") from exc
        source, market = payload["market_source"], payload["market"]
        event = {
            "event_id": str(uuid.uuid4()), "schema_version": SCHEMA_VERSION,
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "symbol": str(source["symbol"]), "timeframe": str(source["timeframe"]),
            "quote_time_utc": market.get("quote_time_utc"),
            "bar_time_utc": payload["analysis"].get("bar_time") or payload["scanner"].get("bar_time_utc"),
            "advisor_status": payload["advisor"].get("status"),
            "payload_json": payload_json,
            "payload_sha256": hashlib.sha256(payload_json.encode("utf-8")).hexdigest(),
        }
        conn = None
        try:
            conn = self._connect()
            conn.execute("""INSERT INTO audit_events
             (event_id,schema_version,created_at_utc,symbol,timeframe,quote_time_utc,bar_time_utc,advisor_status,payload_json,payload_sha256)
             VALUES (?,?,?,?,?,?,?,?,?,?)""",
             (event["event_id"],event["schema_version"],event["created_at_utc"],event["symbol"],event["timeframe"],event["quote_time_utc"],event["bar_time_utc"],event["advisor_status"],event["payload_json"],event["payload_sha256"]))
            conn.commit()
        except (sqlite3.Error, OSError) as exc:
            if conn is not None: conn.rollback()
            raise AuditLedgerError(f"Could not append local audit event: {exc}") from exc
        finally:
            if conn is not None: conn.close()
        return {k:v for k,v in event.items() if k != "payload_json"}

    def list_recent(self, limit: int = 20) -> list[dict[str, Any]]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
            raise ValueError("limit must be an integer from 1 to 500.")
        conn = None
        try:
            conn = self._connect()
            rows = conn.execute("""SELECT id,event_id,schema_version,created_at_utc,symbol,timeframe,quote_time_utc,bar_time_utc,advisor_status,payload_json,payload_sha256
                FROM audit_events ORDER BY id DESC LIMIT ?""", (limit,)).fetchall()
            result = []
            for row in rows:
                serialized = str(row["payload_json"])
                digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
                try: payload = json.loads(serialized)
                except json.JSONDecodeError: payload = None
                result.append({
                    "id":row["id"],"event_id":row["event_id"],"schema_version":row["schema_version"],
                    "created_at_utc":row["created_at_utc"],"symbol":row["symbol"],"timeframe":row["timeframe"],
                    "quote_time_utc":row["quote_time_utc"],"bar_time_utc":row["bar_time_utc"],
                    "advisor_status":row["advisor_status"],"payload_sha256":row["payload_sha256"],
                    "payload_integrity_ok":digest == row["payload_sha256"] and payload is not None,"payload":payload,
                })
            return result
        except sqlite3.Error as exc:
            raise AuditLedgerError(f"Could not read local audit events: {exc}") from exc
        finally:
            if conn is not None: conn.close()

__all__ = ["AuditLedgerError", "LocalAuditLedger", "build_audit_payload"]
