from __future__ import annotations
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from mirsad.runtime import collect_once
from mirsad.config import DB_PATH
from mirsad.storage import connect

def main()->int:
    print("Mirsad BTC end-to-end live connection check. Actual public data only; order execution is not invoked.")
    report=collect_once()
    for name,row in report["market"]["venues"].items():
        print(f"{name}: {row['status']} | latency_ms={row.get('latency_ms')} | error={row.get('error')}")
    if report["market"].get("price") is None or report["market"].get("venue_count",0)<1:
        print("FAIL: no live BTC/USDT venue was reachable.")
        return 1
    conn=connect(DB_PATH)
    try:
        saved=conn.execute("SELECT COUNT(*) FROM market_snapshots").fetchone()[0]
        candles=conn.execute("SELECT COUNT(*) FROM candles").fetchone()[0]
        trades=conn.execute("SELECT COUNT(*) FROM public_trades").fetchone()[0]
    finally:
        conn.close()
    if saved<1 or candles<1:
        print("FAIL: live snapshot/candles were not persisted to SQLite.")
        return 1
    print(f"PASS: {report['market']['venue_count']} actual venue(s); SQLite snapshots={saved}, candles={candles}, trades={trades}.")
    print("No fake data, no paper-trading, no simulated orders, and no order was sent.")
    return 0
if __name__=="__main__":
    raise SystemExit(main())
