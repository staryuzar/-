from __future__ import annotations
import argparse
import time
from pathlib import Path
from typing import Any
from .config import CHART_DIR,CHART_METADATA_PATH,COLLECT_INTERVAL_SECONDS,SNAPSHOT_PATH,STATUS_PATH,MARKET_MAX_AGE_SECONDS,CHART_MAX_AGE_SECONDS,ENABLE_ORDER_PUBLISH
from .engines.market import MarketEngine
from .engines.chart import analyze_chart_image
from .engines.decision import DecisionEngine
from .engines.mt5_bridge import MT5BridgeEngine
from .storage import save_market_snapshot,write_json_atomic,read_json

def _chart_file()->Path|None:
 if not CHART_DIR.exists(): return None
 files=[p for p in CHART_DIR.iterdir() if p.is_file() and p.suffix.lower() in {".png",".jpg",".jpeg",".webp"}]
 return max(files,key=lambda p:p.stat().st_mtime) if files else None

def collect_once(market_engine:MarketEngine|None=None,bridge_engine:MT5BridgeEngine|None=None)->dict[str,Any]:
 started=int(time.time()*1000)
 market=(market_engine or MarketEngine()).collect()
 save_market_snapshot(market)
 write_json_atomic(SNAPSHOT_PATH,market)
 image=_chart_file()
 metadata=read_json(CHART_METADATA_PATH,{})
 if image:
  chart=analyze_chart_image(image,metadata,expected_symbol=market.get("symbol"))
  saved_at=int(metadata.get("saved_at_ms",0) or 0)
  chart_age=max(0,(int(time.time()*1000)-saved_at)/1000) if saved_at else None
  chart["input_age_seconds"]=round(chart_age,2) if chart_age is not None else None
  if chart_age is None or chart_age>CHART_MAX_AGE_SECONDS:
   chart["decision_eligible"]=False
   chart["status"]="STALE"
   chart["stale_reason"]="Chart screenshot metadata is missing or older than the configured freshness limit."
 else:
  chart={"engine":"engine_2_chart_visual_analysis","status":"WAITING_FOR_IMAGE",
   "decision_eligible":False,"ai_used":False,
   "message":"Upload a real chart screenshot and enter its price-axis scale."}
 bridge=(bridge_engine or MT5BridgeEngine()).inspect()
 decision=DecisionEngine().analyze(market,chart,bridge)
 command_publish={"status":"NOT_READY","message":"No command-ready BUY/SELL decision."}
 if decision.get("command_ready") and ENABLE_ORDER_PUBLISH:
  command_publish=(bridge_engine or MT5BridgeEngine()).publish_decision(decision,bridge)
 elif decision.get("command_ready"):
  command_publish={"status":"PUBLISH_DISABLED","message":"Decision is sized but the bridge command switch is disabled."}
 now=int(time.time()*1000)
 age=max(0,(now-int(market.get("captured_at_ms",now)))/1000)
 market_status=market.get("status","OFFLINE")
 if age>MARKET_MAX_AGE_SECONDS: market_status="STALE"
 readiness={
  "engine_1_market":market_status=="LIVE",
  "engine_2_chart":bool(chart.get("decision_eligible")),
  "engine_3_mt5_bridge":bridge.get("status")=="CONNECTED",
  "engine_4_decision":decision.get("status")=="READY",
 }
 overall="FULLY_OPERATIONAL" if all(readiness.values()) else "PARTIAL_OR_WAITING"
 engine_states={
  "engine_1_market":market_status,"engine_2_chart":chart.get("status","NOT_STARTED"),
  "engine_3_mt5_bridge":bridge.get("status","NOT_STARTED"),
  "engine_4_decision":decision.get("status","NOT_STARTED"),
 }
 report={
  "project":"Mirsad BTC","version":"0.2.0","heartbeat_at_ms":now,
  "cycle_started_at_ms":started,"market_age_seconds":round(age,2),
  "overall_status":overall,"readiness":readiness,"engines":engine_states,
  "market":{"symbol":market.get("symbol"),"price":market.get("price"),
   "primary_venue":market.get("primary_venue"),"venue_count":market.get("venue_count"),
   "status":market_status,
   "venues":{n:{"status":v.get("status"),"latency_ms":v.get("latency_ms"),
    "error":v.get("error"),"timeframe_count":len(v.get("candles_by_tf",{})),
    "orderflow":v.get("orderflow")} for n,v in market.get("venues",{}).items()}},
  "chart":chart,"bridge":bridge,"decision":decision,"command_publish":command_publish,
  "wiring":{"engine_1_to_engine_4":True,"engine_2_to_engine_4":True,
   "engine_3_to_engine_4":True,
   "engine_4_to_engine_3_command_envelope":"implemented_idempotent_disabled_by_default",
   "expert_connection":"pending_next_phase"},
  "notices":[
   "Engine 1: actual public market feeds. Engine 2: classical chart vision. Engine 3: MT5 bridge. Engine 4: central decision and risk.",
   "Engine 3 never classifies account type and never computes risk.",
   "Engine 4 owns every decision, stop, target and volume calculation.",
   "No market simulation or simulated order is used.",
   "The expert is not yet built; command publishing is disabled until its protocol and live integration are verified."
  ],
 }
 write_json_atomic(STATUS_PATH,report)
 return report

def run_forever(interval:int=COLLECT_INTERVAL_SECONDS)->None:
 print("Mirsad BTC runtime: Engine 1 + Engine 2 + Engine 3 -> Engine 4. No trading orders are sent.")
 while True:
  try:
   report=collect_once()
   print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} | overall={report['overall_status']} | engines={report['engines']} | BTC={report['market'].get('price')}")
  except Exception as exc:
   print(f"Runtime cycle error: {type(exc).__name__}: {exc}")
   write_json_atomic(STATUS_PATH,{"project":"Mirsad BTC","heartbeat_at_ms":int(time.time()*1000),
    "overall_status":"ERROR","engines":{"runtime":"ERROR"},"runtime_error":f"{type(exc).__name__}: {exc}"})
  time.sleep(max(5,int(interval)))

def main()->None:
 parser=argparse.ArgumentParser(description="Mirsad BTC live runtime")
 parser.add_argument("--once",action="store_true")
 parser.add_argument("--interval",type=int,default=COLLECT_INTERVAL_SECONDS)
 args=parser.parse_args()
 if args.once:
  report=collect_once()
  print({"overall_status":report["overall_status"],"engines":report["engines"],
   "decision":report["decision"].get("action"),"command_ready":report["decision"].get("command_ready")})
 else: run_forever(args.interval)
if __name__=="__main__": main()
