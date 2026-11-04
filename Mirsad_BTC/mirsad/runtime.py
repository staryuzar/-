from __future__ import annotations
import argparse
import time
import math
from typing import Any
from .config import COLLECT_INTERVAL_SECONDS,SNAPSHOT_PATH,STATUS_PATH,MARKET_MAX_AGE_SECONDS,ENABLE_ORDER_PUBLISH,DAILY_LOSS_LIMIT_ENABLED,MAX_DAILY_LOSS_FRACTION,RISK_STATE_PATH
from .engines.mt5_market import MT5MarketDataEngine
from .engines.market_intelligence import MarketIntelligenceEngine
from .engines.mt5_chart_candles import MT5ChartCandleHistory
from .engines.mt5_native_indicators import MT5NativeIndicatorHistory
from .engines.mt5_price_action import analyze_mt5_native_price_action
from .engines.indicators import IndicatorsEngine
from .engines.decision import DecisionEngine
from .engines.mt5_bridge import MT5BridgeEngine
from .storage import (
 save_market_snapshot,save_market_intelligence_snapshot,save_mt5_deal_history,
 write_json_atomic,read_json,
)
from .engines.daily_risk import evaluate_daily_risk
from .engines.position_ledger import build_position_management_history
from .health import build_component_health,summarize_component_health

def _daily_risk_guard_ready(report:Any)->bool:
 """Return whether the configured daily-risk policy is internally consistent.

 An explicitly disabled development cap is ready as configured; when enabled,
 it must have a valid persistent UTC-day equity baseline.
 """
 if not isinstance(report,dict) or report.get("status")!="READY":
  return False
 if report.get("enabled") is False and report.get("mode")=="DISABLED_FOR_DEVELOPMENT":
  return report.get("locked") is False and report.get("new_entries_blocked") is False
 if report.get("enabled") is not True or report.get("mode")!="ENABLED":
  return False
 try:
  starting_equity=float(report.get("starting_equity"))
  baseline_at=int(report.get("baseline_at_ms",0) or 0)
  cap=float(report.get("max_daily_loss_fraction"))
 except (TypeError,ValueError,OverflowError):
  return False
 return (
  math.isfinite(starting_equity) and starting_equity>0
  and baseline_at>0 and math.isfinite(cap) and 0<cap<0.5
 )


def collect_once(market_engine:Any=None,bridge_engine:MT5BridgeEngine|None=None)->dict[str,Any]:
 started=int(time.time()*1000)
 bridge_adapter=bridge_engine or MT5BridgeEngine()
 bridge=bridge_adapter.inspect()
 deal_history_snapshot=bridge.get("deal_history")
 deal_ledger_persistence=save_mt5_deal_history(deal_history_snapshot)
 bridge["position_management_history"]=build_position_management_history(
  deal_history_snapshot.get("deals") if isinstance(deal_history_snapshot,dict) else None,
  bridge.get("positions") if isinstance(bridge.get("positions"),list) else [],
  expected_magic=bridge.get("magic_number",0),
  history_status=str(deal_history_snapshot.get("status","") if isinstance(deal_history_snapshot,dict) else ""),
  truncated=deal_history_snapshot.get("truncated",True) if isinstance(deal_history_snapshot,dict) else True,
  queried_at_utc_ms=deal_history_snapshot.get("queried_at_utc_ms",0) if isinstance(deal_history_snapshot,dict) else 0,
  now_ms=int(time.time()*1000),
 )
 bridge["deal_ledger_persistence"]=deal_ledger_persistence
 if isinstance(deal_history_snapshot,dict):
  bridge["deal_history"]={
   key:value for key,value in deal_history_snapshot.items() if key!="deals"
  } | {"deal_count":len(deal_history_snapshot.get("deals",[]))
       if isinstance(deal_history_snapshot.get("deals"),list) else 0}
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
 if (
  risk_evaluation["state"].get("schema")=="MIR-DAILY-RISK-1"
  and risk_evaluation["state"].get("day_utc")
 ):
  # Persist both a verified baseline and a fail-closed pending marker. This
  # prevents a process restart from silently inventing a new midday baseline.
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
 # Engine 2 consumes only native MT5 CopyRates in the live cycle.
 candle_history=MT5ChartCandleHistory().collect(bridge=bridge)
 chart={
  "engine":"engine_2_native_price_action",
  "source":"NATIVE_MT5_OHLC",
  "status":candle_history.get("status","NOT_READY"),
  "candle_history":candle_history,
 }
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
 execution_ready=(
  bool(ENABLE_ORDER_PUBLISH)
  and bridge.get("status")=="CONNECTED"
  and bridge.get("terminal_connected") is True
  and bridge.get("execution_enabled") is True
  and bridge.get("execution_input_enabled") is True
  and bridge.get("trade_permissions_available") is True
 )
 readiness={
  "engine_5_execution_quote_feed":market_status=="LIVE",
  "engine_1_market_intelligence":market_intelligence.get("status")=="READY",
  # Engine 2 native OHLC price action must be ready before a directional entry is eligible.
  "engine_2_candles":candle_history.get("status")=="READY",
  "engine_2_multi_timeframe_structure":engine2_multitimeframe.get("status")=="READY",
  "engine_2_price_action":engine2_price_action.get("status")=="READY",
  "engine_3_indicators":indicators.get("status")=="READY",
  "mt5_native_indicator_feed":native_indicators.get("status")=="READY",
  "engine_4_daily_risk_guard":_daily_risk_guard_ready(bridge.get("daily_risk")),
  "engine_4_decision":decision.get("status")=="READY",
  "engine_5_communication_bridge":bridge.get("status")=="CONNECTED",
  "engine_5_command_execution_gate":execution_ready,
 }
 overall="FULLY_OPERATIONAL" if all(readiness.values()) else "PARTIAL_OR_WAITING"
 engine_states={
  "engine_5_execution_quote_feed":market_status,"engine_1_market_intelligence":market_intelligence.get("status","NOT_STARTED"),
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
   "order_execution_ready":execution_ready,
   "daily_loss_limit_enabled":bool(DAILY_LOSS_LIMIT_ENABLED),
   "terminal_connected":bridge.get("terminal_connected"),
   "expert_execution_enabled":bridge.get("execution_enabled"),
   "expert_execution_input_enabled":bridge.get("execution_input_enabled"),
   "expert_trade_permissions_available":bridge.get("trade_permissions_available"),
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
  "engine_2_candles":{
   "status":candle_history.get("status"),"timeframes":candle_history.get("timeframes",{}),
   "closed_candles":candle_history.get("closed_candles",{}),"reason":candle_history.get("reason")},
  "engine_2_multi_timeframe_structure":engine2_multitimeframe,
  "engine_2_price_action":engine2_price_action,
  "indicators":indicators,
  "mt5_native_indicators":native_indicators,
  "bridge":bridge,"mt5_deal_ledger":deal_ledger_persistence,
  "daily_risk":bridge.get("daily_risk"),"decision":decision,"command_publish":command_publish,
  "wiring":{"engine_5_execution_quote_feed_to_engine_4":True,"engine_1_standalone_report_to_engine_4":True,
   "engine_2_native_price_action_to_engine_4":True,
   "engine_2_candles_to_engine_3":True,"engine_3_to_engine_4":True,
   "engine_2_price_action_to_engine_4":"weighted_directional_vote_50_percent_after_native_ohlc_quality_gates",
   "mt5_native_indicator_buffers_to_engine_3_report":True,
   "engine_4_daily_risk_guard":"persistent_utc_day_equity_drawdown_gate",
   "engine_4_to_engine_5_command_envelope":"implemented_idempotent_user_authorized",
   "engine_5_to_engine_4_ack_and_positions":"read_from_common_files",
   "expert_connection":bridge.get("status","NOT_CONFIGURED")},
  "notices":[
   "Engine 1 directional context is an explainable evidence score with source coverage, not a calibrated probability or profit forecast. News sentiment is a keyword heuristic; headline risk is exposed for review.",
   "High-importance macro events create a bounded new-entry WAIT window; CLOSE and protective MODIFY management remain available.",
   "Engine 2 price action: determines BTC direction from candle formations and confirmed peaks/troughs, BOS/CHOCH, liquidity-sweep candidates and multi-timeframe structure. It calculates no technical indicators and requires no chart image.",
   "Native MT5 OHLC is the sole live input for Engine 2 candle and price-structure analysis; no chart-image capture or pixel extraction is part of the runtime.",
   "Engine 2 price-action analysis uses only completed native MT5 OHLC bars at a common snapshot cutoff; its eligible directional score contributes the configured 50% Engine 4 baseline weight, subject to structure, freshness and multi-timeframe quality gates.",
   "Engine 3: EMA/RSI/ATR and multi-timeframe technical measures calculated exclusively from Engine 2 completed candles. Native MT5 CopyBuffer indicator values are separately attached for comparison and validation.",
   "Native MT5 indicator snapshots are read independently every market-feed cycle; closed-bar and forming-bar values remain separate and are not decision-eligible until independently validated."
   "Engine 4: central synthesis, decision, position monitoring and risk ownership. Engine 5: MT5 communication bridge.",
   "Engine 5 quote updates describe broker quote movement only; they are not represented as executed trades, taker flow or consolidated order-book depth.",
   "Engine 5 never classifies direction or computes risk; it supplies execution/account facts and transports MIR1.",
   "Engine 4 owns every decision, stop, target, volume calculation and position-management instruction.",
   "Engine 4 daily loss cap is intentionally disabled by default during development (MIRSAD_DAILY_LOSS_LIMIT_ENABLED=0); the 2% cap can be re-enabled by configuration. Per-trade sizing, quote validity, signal-quality gates and position protections remain active.",
   "No market simulation or simulated order is used.",
   "Engine 2 direction and score come exclusively from validated native OHLC evidence and cannot be overridden by a visual input.",
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
