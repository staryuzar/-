from __future__ import annotations
import argparse
import time
import hashlib
import math
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


def _blocked_observer_chart(observer:dict[str,Any], reason:str, status:str="OBSERVER_VALIDATION_BLOCKED")->dict[str,Any]:
 return {
  "engine":"engine_2_chart_visual_analysis",
  "source":"MT5_OBSERVER",
  "status":status,
  "decision_eligible":False,
  "ai_used":False,
  "observer_capture_id":observer.get("capture_id"),
  "observer_block_reason":reason,
  "message":reason,
 }


def _analyze_mt5_observer_chart(
 observer:dict[str,Any], market:dict[str,Any], bridge:dict[str,Any],
)->dict[str,Any]|None:
 """Feed only a fresh, mapped, readable MT5 capture into Engine 2.

 A None return means no current capture exists and permits the existing
 manually calibrated image path. A READY capture that fails any gate returns
 a blocked chart so stale/manual data cannot silently replace it.
 """
 if observer.get("status")!="READY_FOR_ENGINE_2_VALIDATION":
  return None

 chart_meta=observer.get("chart") if isinstance(observer.get("chart"),dict) else {}
 bars=observer.get("bars") if isinstance(observer.get("bars"),list) else []
 capture_id=observer.get("capture_id")
 if not observer.get("visual_calibration_eligible") or not chart_meta.get("source_dimensions_usable"):
  return _blocked_observer_chart(
   observer,"MT5 source chart viewport is below the visual-calibration threshold; capture is retained for diagnostics only.",
   "OBSERVER_VIEWPORT_UNSUITABLE",
  )
 if int(chart_meta.get("source_width_px",0) or 0)<320 or int(chart_meta.get("source_main_window_height_px",0) or 0)<160:
  return _blocked_observer_chart(observer,"MT5 source chart dimensions are not sufficient for reliable candle geometry.","OBSERVER_VIEWPORT_UNSUITABLE")
 if chart_meta.get("chart_autoscroll") is not True:
  return _blocked_observer_chart(observer,"MT5 chart auto-scroll is not enabled; the screenshot may not show the latest forming candle.","OBSERVER_NOT_AT_LIVE_EDGE")
 if int(chart_meta.get("windows_total",0) or 0)!=1:
  return _blocked_observer_chart(observer,"MT5 chart has indicator subwindows; plot layout must be calibrated before automatic visual analysis.","OBSERVER_LAYOUT_UNVERIFIED")
 if int(chart_meta.get("visible_bars",0) or 0)<21:
  return _blocked_observer_chart(observer,"MT5 chart viewport shows fewer than 21 bars; at least 20 completed candles plus the forming candle are required.","OBSERVER_HISTORY_INSUFFICIENT")
 if observer.get("rates_status")!="AVAILABLE" or int(observer.get("rates_error_code",-1))!=0:
  return _blocked_observer_chart(observer,"MT5 native CopyRates data is unavailable or reported an error.","OBSERVER_OHLC_UNAVAILABLE")
 if len(bars)!=int(observer.get("bar_count",-1)) or len(bars)<21:
  return _blocked_observer_chart(observer,"MT5 OHLC bar count does not meet the visual-analysis minimum.","OBSERVER_HISTORY_INSUFFICIENT")
 if any(not isinstance(item,dict) or item.get("is_closed") is not True for item in bars[:-1]) or bars[-1].get("is_closed") is not False:
  return _blocked_observer_chart(observer,"MT5 must provide closed historical bars followed by exactly one forming bar.","OBSERVER_BAR_STATE_INVALID")
 if bool(observer.get("newest_bar_after_server_clock")):
  return _blocked_observer_chart(observer,"MT5 newest bar timestamp is ahead of the broker server clock.","OBSERVER_CLOCK_MISMATCH")
 try:
  skew=int(observer.get("capture_data_skew_ms",-1))
  age=float(observer.get("age_seconds",float("inf")))
  source_low=float(chart_meta.get("price_min",0))
  source_high=float(chart_meta.get("price_max",0))
  latest_low=float(bars[-1]["low"])
  latest_high=float(bars[-1]["high"])
  latest_close=float(bars[-1]["close"])
  numbers=(age,source_low,source_high,latest_low,latest_high,latest_close)
 except (TypeError,ValueError,KeyError,OverflowError):
  return _blocked_observer_chart(observer,"MT5 capture timing or price-range metadata is incomplete.","OBSERVER_METADATA_INVALID")
 if not all(math.isfinite(value) for value in numbers) or not 0<=skew<=2000 or age<0 or age>120:
  return _blocked_observer_chart(observer,"MT5 capture is stale or its image/OHLC timing skew exceeds 2 seconds.","OBSERVER_CAPTURE_NOT_SYNCHRONIZED")
 if not 0<source_low<source_high or latest_low<source_low or latest_high>source_high:
  return _blocked_observer_chart(observer,"The latest MT5 candle is outside the price range reported for the visible chart.","OBSERVER_PRICE_RANGE_MISMATCH")

 market_symbol=str(market.get("symbol","")).strip().upper()
 observer_symbol=str(chart_meta.get("symbol","")).strip()
 bridge_symbol=str(bridge.get("symbol","")).strip()
 bridge_market_symbol=str(bridge.get("market_symbol","")).strip().upper()
 observer_server=str((observer.get("account") or {}).get("server","")).strip().casefold()
 bridge_server=str((bridge.get("account") or {}).get("server","")).strip().casefold()
 if bridge.get("status")!="CONNECTED":
  return _blocked_observer_chart(observer,"A fresh Engine 5 heartbeat is required to verify the MT5 symbol mapping and account server.")
 if not market_symbol or not observer_symbol or bridge_symbol!=observer_symbol or bridge_market_symbol!=market_symbol:
  return _blocked_observer_chart(observer,"MT5 chart symbol, Engine 5 broker symbol and Engine 1 market-symbol mapping do not match.")
 if not observer_server or not bridge_server or observer_server!=bridge_server:
  return _blocked_observer_chart(observer,"Observer and Engine 5 do not report the same broker server; chart identity is unverified.")
 timeframe=str(chart_meta.get("timeframe","")).strip().lower()
 if timeframe not in {"1m","5m","15m","1h","4h","1d","1w"}:
  return _blocked_observer_chart(observer,"MT5 chart timeframe is not supported by Engine 2.","OBSERVER_TIMEFRAME_UNSUPPORTED")
 venues=market.get("venues") or {}
 primary=venues.get(market.get("primary_venue")) if market.get("primary_venue") else None
 if not isinstance(primary,dict) or primary.get("status")!="LIVE":
  return _blocked_observer_chart(observer,"Engine 1 does not currently have the mapped live market venue.","OBSERVER_MARKET_UNAVAILABLE")
 market_frames=primary.get("candles_by_tf") or {}
 if timeframe not in market_frames:
  return _blocked_observer_chart(observer,"Engine 1 has no matching timeframe for the MT5 chart.","OBSERVER_TIMEFRAME_UNMAPPED")

 image_path=Path(str(observer.get("image_path",""))).expanduser()
 if not image_path.is_file():
  return _blocked_observer_chart(observer,"The validated Observer PNG is no longer available to Engine 2.","OBSERVER_IMAGE_MISSING")
 try:
  image_hash=hashlib.sha256(image_path.read_bytes()).hexdigest()
 except OSError:
  return _blocked_observer_chart(observer,"Engine 2 could not read the validated Observer PNG.","OBSERVER_IMAGE_UNREADABLE")
 if not observer.get("image_sha256") or image_hash.lower()!=str(observer.get("image_sha256")).strip().lower():
  return _blocked_observer_chart(observer,"Observer PNG changed after inbox validation; its verified SHA-256 no longer matches.","OBSERVER_IMAGE_CHANGED")
 metadata={
  "symbol":market_symbol,
  "timeframe":timeframe,
  "price_scale_type":str(chart_meta.get("price_scale_type","linear")).strip().lower(),
  "last_candle_closed":False,
  "auto_axis_ocr":False,
  "reference_last_candle_ohlc":{
   key:float(bars[-1][key]) for key in ("open","high","low","close")
  },
 }
 analysis=analyze_chart_image(image_path,metadata,expected_symbol=market_symbol)
 analysis={
  **analysis,
  "source":"MT5_OBSERVER",
  "observer_capture":{
   "capture_id":capture_id,
   "image_sha256":image_hash,
   "age_seconds":round(age,2),
   "capture_data_skew_ms":skew,
   "native_bar_count":len(bars),
   "forming_bar_used_as_reference":True,
   "broker_symbol":observer_symbol,
   "market_symbol":market_symbol,
   "timeframe":timeframe,
   "source_viewport_width_px":int(chart_meta.get("source_width_px",0) or 0),
   "source_viewport_height_px":int(chart_meta.get("source_main_window_height_px",0) or 0),
  },
 }
 reference=analysis.get("reference_calibration") or {}
 anchor_verified=(
  analysis.get("calibration",{}).get("source")=="reference_last_candle_ohlc"
  and reference.get("status")=="READY"
  and analysis.get("reference_ohlc_override_applied") is True
 )
 if not anchor_verified:
  analysis["decision_eligible"]=False
  if analysis.get("status")=="READY":
   analysis["status"]="OBSERVER_REFERENCE_NOT_VERIFIED"
  analysis["observer_reference_status"]=reference.get("status","NOT_VERIFIED")
  analysis["observer_block_reason"]="The image's latest visible candle did not pass the native MT5 OHLC pixel-geometry anchor check."
 else:
  analysis["observer_reference_status"]="READY"
 return analysis


def collect_once(market_engine:MarketEngine|None=None,bridge_engine:MT5BridgeEngine|None=None)->dict[str,Any]:
 started=int(time.time()*1000)
 market=(market_engine or MarketEngine()).collect()
 save_market_snapshot(market)
 write_json_atomic(SNAPSHOT_PATH,market)
 bridge_adapter=bridge_engine or MT5BridgeEngine()
 bridge=bridge_adapter.inspect()
 chart_observer=_inspect_mt5_chart_observer(now_ms=int(time.time()*1000))
 observer_chart=_analyze_mt5_observer_chart(chart_observer,market,bridge)
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
 indicators=IndicatorsEngine().analyze(market)
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
