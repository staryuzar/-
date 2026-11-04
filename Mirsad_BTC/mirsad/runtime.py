from __future__ import annotations
import argparse
import time
import hashlib
import math
from pathlib import Path
from typing import Any
from .config import CHART_DIR,CHART_METADATA_PATH,COLLECT_INTERVAL_SECONDS,SNAPSHOT_PATH,STATUS_PATH,MARKET_MAX_AGE_SECONDS,CHART_MAX_AGE_SECONDS,ENABLE_ORDER_PUBLISH,MT5_COMMON_FILES,DAILY_LOSS_LIMIT_ENABLED,MAX_DAILY_LOSS_FRACTION,RISK_STATE_PATH,SYMBOL
from .engines.market import MarketEngine  # Research/benchmark adapter; not used for live runtime.
from .engines.mt5_market import MT5MarketDataEngine
from .engines.market_intelligence import MarketIntelligenceEngine
from .engines.mt5_chart_candles import MT5ChartCandleHistory
from .engines.mt5_native_indicators import MT5NativeIndicatorHistory
from .engines.mt5_price_action import analyze_mt5_native_price_action
from .engines.chart import analyze_chart_image
from .engines.chart_multi_timeframe import analyze_multi_timeframe_structure
from .engines.indicators import IndicatorsEngine
from .engines.decision import DecisionEngine
from .engines.mt5_bridge import MT5BridgeEngine
from .engines.mt5_chart_pipeline import Engine2MT5ChartImagePipeline
from .storage import save_market_snapshot,save_market_intelligence_snapshot,write_json_atomic,read_json
from .engines.daily_risk import evaluate_daily_risk
from .health import build_component_health,summarize_component_health

def _analyze_engine2_multi_timeframe_structure(candle_history:dict[str,Any])->dict[str,Any]:
 if not isinstance(candle_history,dict) or candle_history.get("status")!="READY":
  return {"engine":"engine_2_multi_timeframe_structure","source":"MT5_CHART_OBSERVER",
   "status":"NOT_READY","alignment":"INSUFFICIENT_TIMEFRAME_CONFLUENCE",
   "available_timeframes":[],"eligible_timeframes":[],
   "reason":"Engine 2 has no validated native MT5 multi-timeframe candle history."}
 frames=candle_history.get("candles_by_tf")
 if not isinstance(frames,dict) or not frames:
  return {"engine":"engine_2_multi_timeframe_structure","source":"MT5_CHART_OBSERVER",
   "status":"NOT_READY","alignment":"INSUFFICIENT_TIMEFRAME_CONFLUENCE",
   "available_timeframes":[],"eligible_timeframes":[],
   "reason":"Engine 2 candle history is missing its timeframe map."}
 try:
  as_of_ms=int(candle_history["captured_at_ms"])
  last_closed={
   timeframe:bool(rows and rows[-1].get("closed"))
   for timeframe,rows in frames.items()
  }
  result=analyze_multi_timeframe_structure(
   frames,as_of_ms=as_of_ms,
   last_candle_closed_by_timeframe=last_closed,
  )
 except (KeyError,TypeError,ValueError,OverflowError) as exc:
  return {"engine":"engine_2_multi_timeframe_structure","source":"MT5_CHART_OBSERVER",
   "status":"ERROR","alignment":"INSUFFICIENT_TIMEFRAME_CONFLUENCE",
   "available_timeframes":[],"eligible_timeframes":[],
   "reason":f"{type(exc).__name__}: {exc}"}
 return {
  **result,
  "engine":"engine_2_multi_timeframe_structure",
  "source":"MT5_CHART_OBSERVER",
  "ownership":"engine_2_native_candles_only",
  "reason":None if result.get("status")=="READY" else "Fewer than two fresh timeframes have complete confirmed price structure.",
 }

def _chart_file()->Path|None:
 if not CHART_DIR.exists(): return None
 files=[p for p in CHART_DIR.iterdir() if p.is_file() and p.suffix.lower() in {".png",".jpg",".jpeg",".webp"}]
 return max(files,key=lambda p:p.stat().st_mtime) if files else None

def _inspect_mt5_chart_observer(now_ms:int|None=None)->dict[str,Any]:
 pipeline=Engine2MT5ChartImagePipeline(common_files=MT5_COMMON_FILES)
 return pipeline.inspect_latest(now_ms=now_ms)


def _analyze_mt5_observer_chart(
 observer:dict[str,Any], bridge:dict[str,Any],
)->dict[str,Any]|None:
 return Engine2MT5ChartImagePipeline(
  image_analyzer=analyze_chart_image,
 ).analyze_capture(observer,bridge)


def collect_once(market_engine:Any=None,bridge_engine:MT5BridgeEngine|None=None)->dict[str,Any]:
 started=int(time.time()*1000)
 bridge_adapter=bridge_engine or MT5BridgeEngine()
 bridge=bridge_adapter.inspect()
 risk_previous=read_json(RISK_STATE_PATH,{})
 if not isinstance(risk_previous,dict):
  risk_previous={}
 risk_evaluation=evaluate_daily_risk(
  bridge.get("account") if isinstance(bridge.get("account"),dict) else {},
  risk_previous,
  max_daily_loss_fraction=MAX_DAILY_LOSS_FRACTION,
  enabled=DAILY_LOSS_LIMIT_ENABLED,
  now_ms=started,
 )
 bridge["daily_risk"]=risk_evaluation["report"]
 bridge["daily_risk_required"]=True
 if risk_evaluation["report"].get("status")=="READY":
  write_json_atomic(RISK_STATE_PATH,risk_evaluation["state"])
 # Broker quote telemetry is the Engine 5 execution feed, separate from intelligence.
 market=(market_engine.collect() if market_engine is not None
         else MT5MarketDataEngine().collect(bridge=bridge))
 # Engine 1 independently collects its public sources and accepts no engine payload.
 try:
  market_intelligence=MarketIntelligenceEngine().collect()
 except Exception as exc:
  market_intelligence={"engine":"engine_1_market_intelligence","status":"OFFLINE",
   "direction":"UNKNOWN","directional_score":None,"confidence":0.0,
   "reason":f"{type(exc).__name__}: {exc}","source_statuses":{}}
 save_market_intelligence_snapshot(market_intelligence)
 save_market_snapshot(market)
 write_json_atomic(SNAPSHOT_PATH,market)
 chart_observer=_inspect_mt5_chart_observer(now_ms=int(time.time()*1000))
 observer_chart=_analyze_mt5_observer_chart(chart_observer,bridge)
 if observer_chart is not None:
  chart=observer_chart
 else:
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
    chart=analyze_chart_image(image,metadata,expected_symbol=bridge.get("market_symbol") or SYMBOL)
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
 # Engine 2 multi-timeframe structure is calculated below from its own MT5 candle inbox.

 # A fresh Observer capture is consumed by Engine 2 above as an image/market-data
 # evidence input. It never authorizes an order by itself: Engine 4 still owns
 # scoring, market-source quorum, position management and all risk gates.
 candle_history=MT5ChartCandleHistory().collect(bridge=bridge)
 engine2_multitimeframe={}
 native_indicators=MT5NativeIndicatorHistory().collect(
  bridge=bridge,candle_history=candle_history,
 )
 engine2_price_action=analyze_mt5_native_price_action(candle_history)
 engine2_multitimeframe=engine2_price_action.get("multi_timeframe_structure",{})
 indicators=IndicatorsEngine().analyze(candle_history)
 indicators["mt5_native"]=native_indicators
 chart["engine_2_candle_history"]={
  "status":candle_history.get("status"),
  "source":candle_history.get("source"),
  "timeframes":candle_history.get("timeframes",{}),
  "closed_candles":candle_history.get("closed_candles",{}),
  "reason":candle_history.get("reason"),
 }
 chart["engine_2_multi_timeframe_structure"]=engine2_multitimeframe
 decision=DecisionEngine().analyze(
  market,chart,bridge,indicators,
  engine2_price_action=engine2_price_action,
  market_intelligence=market_intelligence,
 )
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
  "engine_5_execution_quote_feed":market_status=="LIVE",
  "engine_1_market_intelligence":market_intelligence.get("status")=="READY",
  # Screenshot/image analysis is diagnostic only and is not a readiness gate.
  "engine_2_candles":candle_history.get("status")=="READY",
  "engine_2_multi_timeframe_structure":engine2_multitimeframe.get("status")=="READY",
  "engine_2_price_action":engine2_price_action.get("status")=="READY",
  "engine_3_indicators":indicators.get("status")=="READY",
  "mt5_native_indicator_feed":native_indicators.get("status")=="READY",
  "engine_4_daily_risk_guard":(bridge.get("daily_risk") or {}).get("status")=="READY",
  "engine_4_decision":decision.get("status")=="READY",
  "engine_5_communication_bridge":bridge.get("status")=="CONNECTED",
 }
 overall="FULLY_OPERATIONAL" if all(readiness.values()) else "PARTIAL_OR_WAITING"
 engine_states={
  "engine_5_execution_quote_feed":market_status,"engine_1_market_intelligence":market_intelligence.get("status","NOT_STARTED"),
  "engine_2_chart":chart.get("status","NOT_STARTED"),
  "engine_2_visual_chart":chart.get("status","NOT_STARTED"),
  "engine_2_price_action":engine2_price_action.get("status","NOT_STARTED"),
  "engine_3_indicators":indicators.get("status","NOT_STARTED"),
  "mt5_native_indicator_feed":native_indicators.get("status","NOT_STARTED"),
  "engine_4_daily_risk_guard":("LOCKED" if (bridge.get("daily_risk") or {}).get("locked") is True else ((bridge.get("daily_risk") or {}).get("mode") or (bridge.get("daily_risk") or {}).get("status","NOT_STARTED"))),
  "engine_4_decision":decision.get("status","NOT_STARTED"),
  "engine_5_communication_bridge":bridge.get("status","NOT_STARTED"),
 }
 report={
  "project":"Mirsad BTC","version":"0.2.0","heartbeat_at_ms":now,
  "cycle_started_at_ms":started,"market_age_seconds":round(age,2),
  "overall_status":overall,"readiness":readiness,"engines":engine_states,
  "daily_loss_limit_mode":("ENABLED" if DAILY_LOSS_LIMIT_ENABLED else "DISABLED_FOR_DEVELOPMENT"),
  "execution_controls":{
   "order_publish_enabled":bool(ENABLE_ORDER_PUBLISH),
   "daily_loss_limit_enabled":bool(DAILY_LOSS_LIMIT_ENABLED),
   "terminal_connected":bridge.get("terminal_connected"),
   "expert_execution_enabled":bridge.get("execution_enabled"),
   "expert_execution_telemetry":(
    "REPORTED_ENABLED" if bridge.get("execution_enabled") is True
    else "REPORTED_DISABLED" if bridge.get("execution_enabled") is False
    else "NOT_REPORTED_BY_CURRENT_MIR1_STATUS"
   ),
  },
  "market":{"symbol":market.get("symbol"),"price":market.get("price"),
   "primary_venue":market.get("primary_venue"),"venue_count":market.get("venue_count"),
   "status":market_status,
   "order_book":(market.get("market_context") or {}).get("order_book",{}),
   "venues":{n:{"status":v.get("status"),"latency_ms":v.get("latency_ms"),
    "error":v.get("error"),
    "microstructure":v.get("microstructure",{}),
    "order_book":v.get("order_book",{}),
    "order_book_status":(v.get("order_book") or {}).get("status")} for n,v in market.get("venues",{}).items()}},
  "market_intelligence":market_intelligence,
  "chart":chart,"chart_observer":chart_observer,"engine_2_candles":{
   "status":candle_history.get("status"),"timeframes":candle_history.get("timeframes",{}),
   "closed_candles":candle_history.get("closed_candles",{}),"reason":candle_history.get("reason")},
  "engine_2_multi_timeframe_structure":engine2_multitimeframe,
  "engine_2_price_action":engine2_price_action,
  "engine_2_visual_analysis":{
   "status":chart.get("status","NOT_STARTED"),
   "decision_eligible":bool(chart.get("decision_eligible")),
   "scope":"DEFERRED_UNTIL_CHART_AND_DRAWING_PHASE",
   "required_for_native_direction_analysis":False,
  },
  "indicators":indicators,
  "mt5_native_indicators":native_indicators,
  "bridge":bridge,"daily_risk":bridge.get("daily_risk"),"decision":decision,"command_publish":command_publish,
  "wiring":{"engine_5_execution_quote_feed_to_engine_4":True,"engine_1_standalone_report_to_engine_4":True,
   "engine_2_chart_to_engine_4":True,
   "engine_2_candles_to_engine_3":True,"engine_3_to_engine_4":True,
   "engine_2_price_action_to_engine_4":"fail_closed_confluence_gate_not_an_independent_directional_vote",
   "engine_2_price_action_requires_chart_image":False,
   "mt5_native_indicator_buffers_to_engine_3_report":True,
   "engine_4_daily_risk_guard":"persistent_utc_day_equity_drawdown_gate",
   "engine_4_to_engine_5_command_envelope":"implemented_idempotent_user_authorized",
   "engine_5_to_engine_4_ack_and_positions":"read_from_common_files",
   "expert_connection":bridge.get("status","NOT_CONFIGURED")},
  "notices":[
   "Engine 1: independent market intelligence from multi-publisher crypto news, macro calendar, Fear and Greed, global crypto market context and multi-venue perpetual funding/open-interest/long-short positioning. It does not read images, OHLC candles or technical indicators.",
   "Engine 1 directional context is an explainable evidence score with source coverage, not a calibrated probability or profit forecast. News sentiment is a keyword heuristic; headline risk is exposed for review.",
   "High-importance macro events create a bounded new-entry WAIT window; CLOSE and protective MODIFY management remain available.",
   "Engine 2 price action: determines BTC direction from candle formations and confirmed peaks/troughs, BOS/CHOCH, liquidity-sweep candidates and multi-timeframe structure. It calculates no technical indicators and requires no chart image.",
   "Engine 2 visual chart extraction and drawings are deferred and are not a readiness dependency for the native OHLC direction report.",
   "Engine 2 price-action analysis uses only completed native MT5 OHLC bars at a common snapshot cutoff; stale frames, gaps and forming bars cannot create direction evidence. In Engine 4 it is a fail-closed confluence gate, not a separate directional vote.",
   "Engine 3: EMA/RSI/ATR and multi-timeframe technical measures calculated exclusively from Engine 2 completed candles. Native MT5 CopyBuffer indicator values are separately attached for comparison and validation.",
   "Native MT5 indicator snapshots are read independently from chart images every market-feed cycle; closed-bar and forming-bar values remain separate and are not decision-eligible until independently validated.",
   "Engine 4: central synthesis, decision, position monitoring and risk ownership. Engine 5: MT5 communication bridge.",
   "Engine 5 quote updates describe broker quote movement only; they are not represented as executed trades, taker flow or consolidated order-book depth.",
   "Engine 5 never classifies direction or computes risk; it supplies execution/account facts and transports MIR1.",
   "Engine 4 owns every decision, stop, target, volume calculation and position-management instruction.",
   "Engine 4 daily loss cap is disabled by default for development (MIRSAD_DAILY_LOSS_LIMIT_ENABLED=0); per-trade sizing, account/quote validation, signal-quality gates and protective position management remain active. Re-enable explicitly with MIRSAD_DAILY_LOSS_LIMIT_ENABLED=1 before deployment.",
   "No market simulation or simulated order is used.",
   "Chart-image extraction and pixel calibration are a separate deferred visual track; the native OHLC analysis continues without waiting for chart images.",
   "Engine 5 owns the fresh MT5 broker quote feed and execution bridge. Engine 4 validates broker symbol, account server, quote age, spread and price agreement; Engine 1 independently collects public intelligence and does not consume MT5 or other-engine data.",
   "A broker quote must be fresh, close to the spot reference and within the configured spread threshold.",
   "The MQL5 expert accepts Engine 4 MIR1 BUY/SELL/CLOSE instructions through Engine 5; a command is sent only when Engine 4 marks it ready and the live bridge is connected."
  ],
 }
 report["component_health"]=build_component_health(report,now_ms=now)
 report["component_health_summary"]=summarize_component_health(report["component_health"])
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
