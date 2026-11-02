from __future__ import annotations
import argparse
import time
import hashlib
from pathlib import Path
from typing import Any
from .config import CHART_DIR,CHART_METADATA_PATH,COLLECT_INTERVAL_SECONDS,SNAPSHOT_PATH,STATUS_PATH,MARKET_MAX_AGE_SECONDS,CHART_MAX_AGE_SECONDS,ENABLE_ORDER_PUBLISH,MT5_COMMON_FILES
from .engines.market import MarketEngine
from .engines.chart import analyze_chart_image
from .engines.chart_multi_timeframe import analyze_stored_multi_timeframe_structure
from .engines.indicators import IndicatorsEngine
from .engines.decision import DecisionEngine
from .engines.mt5_bridge import MT5BridgeEngine
from .engines.mt5_observer import MT5ChartObserverInbox
from .storage import save_market_snapshot,write_json_atomic,read_json

def _chart_file()->Path|None:
 if not CHART_DIR.exists(): return None
 files=[p for p in CHART_DIR.iterdir() if p.is_file() and p.suffix.lower() in {".png",".jpg",".jpeg",".webp"}]
 return max(files,key=lambda p:p.stat().st_mtime) if files else None

def _inspect_mt5_chart_observer(now_ms:int|None=None)->dict[str,Any]:
 if not MT5_COMMON_FILES:
  return {"engine":"mt5_chart_observer_inbox","status":"NOT_CONFIGURED",
   "decision_eligible":False,
   "message":"Set MIRSAD_MT5_COMMON_FILES to MT5 Terminal\\Common\\Files to inspect MT5 chart captures."}
 try:
  inbox=MT5ChartObserverInbox.from_common_files(MT5_COMMON_FILES)
  return inbox.inspect_latest(now_ms=now_ms)
 except Exception as exc:
  return {"engine":"mt5_chart_observer_inbox","status":"ERROR",
   "decision_eligible":False,"reason":f"{type(exc).__name__}: {exc}"}


def collect_once(market_engine:MarketEngine|None=None,bridge_engine:MT5BridgeEngine|None=None)->dict[str,Any]:
 started=int(time.time()*1000)
 market=(market_engine or MarketEngine()).collect()
 save_market_snapshot(market)
 write_json_atomic(SNAPSHOT_PATH,market)
 image=_chart_file()
 metadata=read_json(CHART_METADATA_PATH,{})
 if not isinstance(metadata,dict):
  metadata={}
 if image:
  expected_hash=str(metadata.get("source_sha256","")).strip().lower()
  actual_hash=hashlib.sha256(image.read_bytes()).hexdigest()
  if expected_hash and expected_hash!=actual_hash:
   chart={
    "engine":"engine_2_chart_visual_analysis","status":"IMAGE_METADATA_MISMATCH",
    "decision_eligible":False,
    "error":"The saved calibration metadata belongs to a different image file.",
   }
  else:
   chart=analyze_chart_image(image,metadata,expected_symbol=market.get("symbol"))
  now_ms=int(time.time()*1000)
  try:
   saved_at=int(metadata.get("saved_at_ms",0) or 0)
  except (TypeError,ValueError,OverflowError):
   saved_at=0
  chart_age=(now_ms-saved_at)/1000 if saved_at else None
  chart["input_age_seconds"]=round(chart_age,2) if chart_age is not None else None
  if chart_age is None or chart_age< -60 or chart_age>CHART_MAX_AGE_SECONDS:
   chart["decision_eligible"]=False
   chart["status"]="STALE"
   chart["stale_reason"]="Chart metadata is missing, future-dated or older than the configured freshness limit."
 else:
  chart={"engine":"engine_2_chart_visual_analysis","status":"WAITING_FOR_IMAGE",
   "decision_eligible":False,"ai_used":False,
   "message":"Upload a real chart screenshot and enter its price-axis scale."}
 # Engine 2 reads Engine 1's stored OHLCV through a read-only, venue-specific adapter.
 # This descriptive confluence report is not fed into Engine 4 sizing or scoring.
 try:
  chart["stored_multi_timeframe_structure"]=analyze_stored_multi_timeframe_structure(
   symbol=str(market.get("symbol","BTCUSDT")),
   venue=market.get("primary_venue"),
   as_of_ms=int(market.get("captured_at_ms",started)),
  )
 except Exception as exc:
  chart["stored_multi_timeframe_structure"]={
   "status":"ERROR","source":"market_candles_sqlite",
   "errors":{"runtime":f"{type(exc).__name__}: {exc}"},
   "alignment":"INSUFFICIENT_TIMEFRAME_CONFLUENCE",
   "does_not_affect_decision_engine":True,
  }
 # The read-only chart observer is surfaced independently. Its capture has
 # no effect on chart eligibility, Engine 4 scoring, or MIR1 order publication.
 chart_observer=_inspect_mt5_chart_observer(now_ms=int(time.time()*1000))
 indicators=IndicatorsEngine().analyze(market)
 bridge_adapter=bridge_engine or MT5BridgeEngine()
 bridge=bridge_adapter.inspect()
 decision=DecisionEngine().analyze(market,chart,bridge,indicators)
 command_publish={"status":"NOT_READY","message":"No command-ready OPEN/CLOSE instruction from Engine 4."}
 if decision.get("command_ready") and ENABLE_ORDER_PUBLISH:
  command_publish=bridge_adapter.publish_decision(decision,bridge)
 elif decision.get("command_ready"):
  command_publish={"status":"PUBLISH_DISABLED","message":"Decision is sized but the bridge command switch is disabled."}
 now=int(time.time()*1000)
 age=max(0,(now-int(market.get("captured_at_ms",now)))/1000)
 market_status=market.get("status","OFFLINE")
 if age>MARKET_MAX_AGE_SECONDS: market_status="STALE"
 readiness={
  "engine_1_market":market_status=="LIVE",
  "engine_2_chart":bool(chart.get("decision_eligible")),
  "engine_3_indicators":indicators.get("status")=="READY",
  "engine_4_decision":decision.get("status")=="READY",
  "engine_5_communication_bridge":bridge.get("status")=="CONNECTED",
 }
 overall="FULLY_OPERATIONAL" if all(readiness.values()) else "PARTIAL_OR_WAITING"
 engine_states={
  "engine_1_market":market_status,"engine_2_chart":chart.get("status","NOT_STARTED"),
  "engine_3_indicators":indicators.get("status","NOT_STARTED"),
  "engine_4_decision":decision.get("status","NOT_STARTED"),
  "engine_5_communication_bridge":bridge.get("status","NOT_STARTED"),
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
  "chart":chart,"chart_observer":chart_observer,"indicators":indicators,
  "bridge":bridge,"decision":decision,"command_publish":command_publish,
  "wiring":{"engine_1_to_engine_3":True,"engine_2_to_engine_4":True,
   "engine_3_to_engine_4":True,
   "engine_4_to_engine_5_command_envelope":"implemented_idempotent_user_authorized",
   "engine_5_to_engine_4_ack_and_positions":"read_from_common_files",
   "expert_connection":bridge.get("status","NOT_CONFIGURED")},
  "notices":[
   "Engine 1: actual public market feeds. Engine 2: classical chart vision. Engine 3: technical indicator calculations. Engine 4: central decision and trade monitoring. Engine 5: MT5 communication bridge.",
   "Engine 3 calculates from Engine 1 completed candles and does not create an independent directional vote.",
   "Engine 5 never classifies direction or computes risk; it supplies execution/account facts and transports MIR1.",
   "Engine 4 owns every decision, stop, target, volume calculation and position-management instruction.",
   "No market simulation or simulated order is used.",
   "The MT5 Chart Observer is a read-only capture source; its raw capture is not decision-eligible until Engine 2 validates the visual and temporal alignment.",
   "A directional decision requires at least two live public venues.",
   "A broker quote must be fresh, close to the spot reference and within the configured spread threshold.",
   "The MQL5 expert accepts Engine 4 MIR1 BUY/SELL/CLOSE instructions through Engine 5; a command is sent only when Engine 4 marks it ready and the live bridge is connected."
  ],
 }
 write_json_atomic(STATUS_PATH,report)
 return report

def run_forever(interval:int=COLLECT_INTERVAL_SECONDS)->None:
 print("Mirsad BTC runtime: Engine 1 + Engine 2 + Engine 3 -> Engine 4 -> Engine 5 -> MT5 EA. Commands execute only when Engine 4 marks them ready.")
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
