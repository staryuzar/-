from __future__ import annotations

import argparse
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone


ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "artifacts"
DB_PATH = ROOT / "data" / "windows_runtime.sqlite"
COLLECTOR_LOG = ARTIFACTS / "windows_market_stream.log"
DASHBOARD_LOG = ARTIFACTS / "windows_streamlit.log"
REPORT = ARTIFACTS / "windows_runtime_smoke.json"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_runtime_state() -> dict:
    if not DB_PATH.is_file():
        return {"database_exists": False}
    with closing(sqlite3.connect(DB_PATH, timeout=3.0)) as db:
        tables = {
            row[0] for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        expected = {
            "stream_status", "orderbook_snapshots", "stream_events",
            "trade_flow_minutes", "trade_footprint", "liquidation_events",
        }
        missing = sorted(expected - tables)
        if missing:
            return {
                "database_exists": True,
                "missing_tables": missing,
                "tables": sorted(tables),
            }

        statuses = [
            dict(zip(
                ("venue", "status", "last_message_ms", "reconnects", "last_error"),
                row,
            ))
            for row in db.execute(
                "SELECT venue,status,last_message_ms,reconnects,last_error "
                "FROM stream_status ORDER BY venue"
            ).fetchall()
        ]
        snapshot_count = int(db.execute("SELECT COUNT(*) FROM orderbook_snapshots").fetchone()[0])
        event_count = int(db.execute("SELECT COUNT(*) FROM stream_events").fetchone()[0])
        trade_minutes = int(db.execute("SELECT COUNT(*) FROM trade_flow_minutes").fetchone()[0])
        trade_footprint = int(db.execute("SELECT COUNT(*) FROM trade_footprint").fetchone()[0])
        liquidation_count = int(db.execute("SELECT COUNT(*) FROM liquidation_events").fetchone()[0])
        integrity = str(db.execute("PRAGMA integrity_check").fetchone()[0])
        journal_mode = str(db.execute("PRAGMA journal_mode").fetchone()[0])

    book_names = {"binance_spot", "bybit_linear", "okx_spot"}
    live_books = sorted(
        row["venue"] for row in statuses
        if row["venue"] in book_names and row["status"] == "live"
    )
    live_trade_feeds = sorted(
        row["venue"] for row in statuses
        if row["venue"].endswith("_trades") and row["status"] == "live"
        and row["last_message_ms"] is not None
    )
    return {
        "database_exists": True,
        "tables": sorted(tables),
        "statuses": statuses,
        "live_orderbook_feeds": live_books,
        "live_trade_feeds_with_recent_messages": live_trade_feeds,
        "orderbook_snapshot_count": snapshot_count,
        "stream_event_count": event_count,
        "trade_flow_minute_count": trade_minutes,
        "trade_footprint_count": trade_footprint,
        "liquidation_event_count": liquidation_count,
        "sqlite_integrity": integrity,
        "sqlite_journal_mode": journal_mode,
    }


def check_streamlit(url: str) -> tuple[bool, str]:
    try:
        with urllib.request.urlopen(url, timeout=3) as response:
            payload = response.read(4096).decode("utf-8", errors="replace")
            return response.status == 200, payload[:200]
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def write_report(payload: dict) -> None:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def terminate(process: subprocess.Popen | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=10)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration-seconds", type=int, default=180)
    parser.add_argument("--port", type=int, default=8502)
    args = parser.parse_args()
    if not 60 <= args.duration_seconds <= 300:
        parser.error("duration-seconds must be between 60 and 300.")

    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    DB_PATH.unlink(missing_ok=True)

    env = dict(os.environ)
    env["PYTHONUNBUFFERED"] = "1"
    collector = dashboard = None
    report: dict = {
        "started_at_utc": utc_now(),
        "platform": sys.platform,
        "database_path": str(DB_PATH.relative_to(ROOT)),
        "collector": "not_started",
        "dashboard": "not_started",
        "status": "failed",
    }
    deadline = time.monotonic() + args.duration_seconds
    health_url = f"http://127.0.0.1:{args.port}/_stcore/health"

    try:
        with COLLECTOR_LOG.open("w", encoding="utf-8") as collector_log:
            collector = subprocess.Popen(
                [
                    sys.executable, "-m", "bitcoinlab.market_stream",
                    "--symbol", "BTCUSDT",
                    "--venues", "binance,bybit,okx",
                    "--depth", "50",
                    "--db", str(DB_PATH),
                    "--retention-hours", "2",
                    "--log-level", "INFO",
                ],
                cwd=ROOT, env=env, stdout=collector_log,
                stderr=subprocess.STDOUT,
            )
            report["collector"] = "started"
            report["collector_pid"] = collector.pid

            with DASHBOARD_LOG.open("w", encoding="utf-8") as dashboard_log:
                dashboard = subprocess.Popen(
                    [
                        sys.executable, "-m", "streamlit", "run", "app.py",
                        "--server.headless", "true",
                        "--server.address", "127.0.0.1",
                        "--server.port", str(args.port),
                        "--browser.gatherUsageStats", "false",
                    ],
                    cwd=ROOT, env=env, stdout=dashboard_log,
                    stderr=subprocess.STDOUT,
                )
                report["dashboard"] = "started"
                report["dashboard_pid"] = dashboard.pid

                last_state: dict = {}
                dashboard_ok = False
                dashboard_detail = "health endpoint not ready"
                stream_ok = False
                while time.monotonic() < deadline:
                    if collector.poll() is not None:
                        raise RuntimeError(f"Market collector exited early: {collector.returncode}")
                    if dashboard.poll() is not None:
                        raise RuntimeError(f"Streamlit exited early: {dashboard.returncode}")

                    dashboard_ok, dashboard_detail = check_streamlit(health_url)
                    last_state = read_runtime_state() if DB_PATH.exists() else {}
                    if (
                        dashboard_ok
                        and last_state.get("sqlite_integrity") == "ok"
                        and last_state.get("sqlite_journal_mode", "").lower() == "wal"
                        and len(last_state.get("live_orderbook_feeds", [])) >= 1
                        and last_state.get("orderbook_snapshot_count", 0) >= 1
                        and len(last_state.get("live_trade_feeds_with_recent_messages", [])) >= 1
                        and last_state.get("trade_flow_minute_count", 0) >= 1
                    ):
                        stream_ok = True
                        break
                    time.sleep(3)

                report["dashboard_health"] = {
                    "ok": dashboard_ok,
                    "detail": dashboard_detail,
                    "url": health_url,
                }
                report["runtime_state"] = last_state
                report["collector_log_tail"] = COLLECTOR_LOG.read_text(
                    encoding="utf-8", errors="replace"
                )[-12000:]
                report["dashboard_log_tail"] = DASHBOARD_LOG.read_text(
                    encoding="utf-8", errors="replace"
                )[-6000:]

                if not dashboard_ok:
                    raise RuntimeError("Streamlit health endpoint did not become ready.")
                if not stream_ok:
                    raise RuntimeError(
                        "Windows collector did not prove at least one live book feed, "
                        "a persisted order-book snapshot, a live trade feed with an event, "
                        "and a persisted trade-flow minute within the test window."
                    )

                # Exercise the dashboard's read-only SQLite reader against the running DB.
                from bitcoinlab.market_store import read_market_stream_dashboard
                dashboard_state = read_market_stream_dashboard(DB_PATH, limit=20)
                if dashboard_state.get("status") != "ok":
                    raise RuntimeError(
                        f"Read-only dashboard SQLite reader failed: {dashboard_state.get('status')}"
                    )
                report["read_only_dashboard_reader"] = {
                    "status": dashboard_state.get("status"),
                    "venues": dashboard_state.get("venues", []),
                    "latest_book_count": len(dashboard_state.get("latest_books", [])),
                }
                report["status"] = "passed"
                report["completed_at_utc"] = utc_now()
                report["checks"] = {
                    "windows_market_collector_started": True,
                    "websocket_orderbook_live": True,
                    "orderbook_snapshot_persisted": True,
                    "trade_websocket_live_with_recent_message": True,
                    "trade_flow_minute_persisted": True,
                    "sqlite_integrity_ok": True,
                    "sqlite_wal_mode": True,
                    "streamlit_health_ok": True,
                    "dashboard_read_only_sqlite_reader_ok": True,
                    "mt5_or_trade_execution_used": False,
                }
                write_report(report)
                print(json.dumps(report, ensure_ascii=False, indent=2))
                return 0
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
        report["completed_at_utc"] = utc_now()
        report["runtime_state"] = read_runtime_state() if DB_PATH.exists() else {}
        if COLLECTOR_LOG.exists():
            report["collector_log_tail"] = COLLECTOR_LOG.read_text(
                encoding="utf-8", errors="replace"
            )[-12000:]
        if DASHBOARD_LOG.exists():
            report["dashboard_log_tail"] = DASHBOARD_LOG.read_text(
                encoding="utf-8", errors="replace"
            )[-6000:]
        write_report(report)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1
    finally:
        terminate(dashboard)
        terminate(collector)


if __name__ == "__main__":
    raise SystemExit(main())
