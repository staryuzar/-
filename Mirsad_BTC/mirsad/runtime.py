from __future__ import annotations
import argparse
import time
from pathlib import Path
from typing import Any
from .config import CHART_DIR, COLLECT_INTERVAL_SECONDS, SNAPSHOT_PATH, STATUS_PATH, MARKET_MAX_AGE_SECONDS
from .engines.market import MarketEngine
from .engines.chart import analyze_chart_image
from .engines.decision import DecisionEngine
from .engines.mt5_bridge import MT5BridgeEngine
from .storage import save_market_snapshot, write_json_atomic

def _chart_file() -> Path | None:
    if not CHART_DIR.exists():
        return None
    candidates = [p for p in CHART_DIR.iterdir() if p.is_file() and p.suffix.lower() in {".png",".jpg",".jpeg",".webp"}]
    return max(candidates, key=lambda p: p.stat().st_mtime) if candidates else None

def collect_once(market_engine: MarketEngine | None = None, bridge_engine: MT5BridgeEngine | None = None) -> dict[str, Any]:
    started = int(time.time() * 1000)
    market_engine = market_engine or MarketEngine()
    bridge_engine = bridge_engine or MT5BridgeEngine()
    market = market_engine.collect()
    save_market_snapshot(market)
    write_json_atomic(SNAPSHOT_PATH, market)
    chart_path = _chart_file()
    chart = analyze_chart_image(chart_path) if chart_path else {
        "engine":"chart_visual_analysis","status":"WAITING_FOR_IMAGE","ai_used":False,
        "message":"Upload a real chart screenshot from the dashboard."
    }
    mt5 = bridge_engine.inspect()
    decision = DecisionEngine().analyze(market, chart, mt5)
    now_ms = int(time.time() * 1000)
    age = (now_ms - int(market.get("captured_at_ms", now_ms))) / 1000
    market_status = market.get("status", "OFFLINE")
    if age > MARKET_MAX_AGE_SECONDS:
        market_status = "STALE"
    health = {
        "runtime":"RUNNING","market_data":market_status,
        "chart_analysis":chart.get("status","NOT_STARTED"),
        "decision_risk":decision.get("status","NOT_STARTED"),
        "mt5_bridge":mt5.get("status","NOT_STARTED"),
    }
    report = {
        "project":"Mirsad BTC","version":"0.1.0","updated_at_ms":now_ms,
        "runtime_started_at_ms":started,"heartbeat_at_ms":now_ms,"market_age_seconds":round(age,2),
        "engines":health,
        "market":{"symbol":market.get("symbol"),"price":market.get("price"),
            "primary_venue":market.get("primary_venue"),"venue_count":market.get("venue_count"),
            "venues":{name:{"status":item.get("status"),"latency_ms":item.get("latency_ms"),"error":item.get("error")}
                      for name,item in market.get("venues",{}).items()}},
        "chart":chart,"decision":decision,"mt5":mt5,
        "notices":[
            "Market information is read from actual public exchange endpoints.",
            "No simulated market prices or simulated trades are created.",
            "No trade is sent by this runtime. The executable EA is a later project phase.",
            "Risk and position sizing belong to the Mirsad BTC program."
        ],
    }
    write_json_atomic(STATUS_PATH, report)
    return report

def run_forever(interval: int = COLLECT_INTERVAL_SECONDS) -> None:
    print("Mirsad BTC runtime started. Reading actual public market feeds; no orders are sent.")
    while True:
        try:
            status = collect_once()
            e = status["engines"]
            print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} | market={e['market_data']} | chart={e['chart_analysis']} | decision={e['decision_risk']} | mt5={e['mt5_bridge']} | BTC={status['market'].get('price')}")
        except Exception as exc:
            print(f"Runtime cycle error: {type(exc).__name__}: {exc}")
            write_json_atomic(STATUS_PATH, {"project":"Mirsad BTC","heartbeat_at_ms":int(time.time()*1000),
                "engines":{"runtime":"ERROR"},"runtime_error":f"{type(exc).__name__}: {exc}"})
        time.sleep(max(5, int(interval)))

def main() -> None:
    parser=argparse.ArgumentParser(description="Mirsad BTC real-data runtime")
    parser.add_argument("--once",action="store_true",help="Collect one real market snapshot and exit.")
    parser.add_argument("--interval",type=int,default=COLLECT_INTERVAL_SECONDS)
    args=parser.parse_args()
    if args.once:
        report=collect_once()
        print(report["engines"])
    else:
        run_forever(args.interval)

if __name__ == "__main__":
    main()
