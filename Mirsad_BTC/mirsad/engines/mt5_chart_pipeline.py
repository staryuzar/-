from __future__ import annotations

"""Engine 2 input pipeline for MT5 Chart Observer images.

The read-only MT5 capture EA publishes capture_*.json manifests and PNG files
under Common\\Files\\MirsadBTC\\observer\\images. This module owns inbox
inspection, capture validation hand-off, broker identity checks and dispatch
into Engine 2's existing chart-image analyzer. It never sends trading commands.
"""

import hashlib
import math
from pathlib import Path
from typing import Any, Callable

from PIL import Image

from ..config import MT5_COMMON_FILES
from .chart import analyze_chart_image
from .mt5_observer import MT5ChartObserverInbox, recent_reference_candle_candidates
from .mt5_chart_geometry import (
    analyze_native_mt5_ohlc,
    native_geometry_visible_y_max,
    native_geometry_slot_centers,
    validate_mt5_chart_geometry,
)


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


def analyze_mt5_observer_chart(
 observer:dict[str,Any], market:dict[str,Any], bridge:dict[str,Any],
 *, image_analyzer:Callable[...,dict[str,Any]]|None=None,
)->dict[str,Any]|None:
 """Feed only a fresh, mapped, readable MT5 capture into Engine 2.

 A None return means no current capture exists and permits the existing
 manually calibrated image path. A READY capture that fails any gate returns
 a blocked chart so stale/manual data cannot silently replace it.
 """
 capture_status=observer.get("status")
 if capture_status in {"NOT_CONFIGURED","WAITING_FOR_CAPTURE"}:
  return None
 if capture_status!="READY_FOR_ENGINE_2_VALIDATION":
  reason=str(observer.get("reason") or observer.get("message") or
             f"Latest MT5 chart capture is not valid for Engine 2 (status={capture_status}).")
  return _blocked_observer_chart(observer,reason,"OBSERVER_INBOX_VALIDATION_BLOCKED")

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
 visible_bars=int(chart_meta.get("visible_bars",0) or 0)
 if visible_bars<21:
  return _blocked_observer_chart(observer,"MT5 chart viewport shows fewer than 21 bars; at least 20 completed candles plus the forming candle are required.","OBSERVER_HISTORY_INSUFFICIENT")
 try:
  first_visible_bar_shift=int(chart_meta.get("first_visible_bar_shift",-1))
 except (TypeError,ValueError,OverflowError):
  first_visible_bar_shift=-1
 if first_visible_bar_shift<0:
  return _blocked_observer_chart(observer,"MT5 first-visible-bar position is missing; latest-candle alignment cannot be verified.","OBSERVER_VIEWPORT_POSITION_UNKNOWN")
 rightmost_visible_offset=max(0,first_visible_bar_shift-visible_bars+1)
 maximum_allowed_rightmost_offset=max(2,int(math.ceil(visible_bars*0.20)))
 if rightmost_visible_offset>maximum_allowed_rightmost_offset:
  return _blocked_observer_chart(
   observer,
   "MT5 chart is scrolled away from the latest candles; navigate to CHART_END before visual analysis.",
   "OBSERVER_NOT_AT_LIVE_EDGE",
  )
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
  # Engine 2 validates its own chart image and native OHLC. A stale Engine 1
  # quote must not erase valid visual evidence; Engine 4 independently gates
  # any decision on the freshness and health of the live market feed.
 
 image_path=Path(str(observer.get("image_path",""))).expanduser()
 if not image_path.is_file():
  return _blocked_observer_chart(observer,"The validated Observer PNG is no longer available to Engine 2.","OBSERVER_IMAGE_MISSING")
 try:
  image_hash=hashlib.sha256(image_path.read_bytes()).hexdigest()
 except OSError:
  return _blocked_observer_chart(observer,"Engine 2 could not read the validated Observer PNG.","OBSERVER_IMAGE_UNREADABLE")
 if not observer.get("image_sha256") or image_hash.lower()!=str(observer.get("image_sha256")).strip().lower():
  return _blocked_observer_chart(observer,"Observer PNG changed after inbox validation; its verified SHA-256 no longer matches.","OBSERVER_IMAGE_CHANGED")
 reference_candidates=recent_reference_candle_candidates(bars,max_candidates=256,max_lookback=256)
 if not reference_candidates:
  return _blocked_observer_chart(observer,"No recent native MT5 candle has a positive range suitable for visual calibration.","OBSERVER_REFERENCE_CANDLE_UNAVAILABLE")
 reference_candidates_for_chart=[{
  "offset_from_right":item["offset_from_right"],
  "time_server_ms":item.get("time_server_ms"),
  "closed":item.get("closed"),
  "ohlc":item["ohlc"],
 } for item in reference_candidates]
 metadata={
  "symbol":market_symbol,
  "timeframe":timeframe,
  "price_scale_type":str(chart_meta.get("price_scale_type","linear")).strip().lower(),
  "expected_candle_count":int(chart_meta.get("visible_bars",0) or 0),
  "first_visible_bar_shift":int(chart_meta.get("first_visible_bar_shift",0) or 0),
  "allow_reference_anchor_override":True,
  "require_multi_reference_validation":True,
  "last_candle_closed":False,
  "auto_axis_ocr":True,
  "reference_candle_candidates":reference_candidates_for_chart,
  "reference_last_candle_ohlc":reference_candidates_for_chart[0]["ohlc"],
  "reference_candle_offset_from_right":reference_candidates_for_chart[0]["offset_from_right"],
 }
 native_ohlc_analysis=analyze_native_mt5_ohlc(
  bars, symbol=market_symbol, timeframe=timeframe
 )
 with Image.open(image_path) as source_image:
  image_width,image_height=source_image.size
 native_pixel_geometry=validate_mt5_chart_geometry(
  observer.get("pixel_geometry"),bars=bars,chart=chart_meta,
  image_width=image_width,image_height=image_height,
 )
 native_slot_center_result=native_geometry_slot_centers(
  native_pixel_geometry,
  native_bar_count=len(bars),
  visible_bars=visible_bars,
  first_visible_bar_shift=first_visible_bar_shift,
 )
 metadata["native_geometry_slot_centers"]=native_slot_center_result.get("slots",[])
 metadata["native_geometry_slot_center_status"]=native_slot_center_result.get("status")
 native_max_y=native_geometry_visible_y_max(native_pixel_geometry)
 if native_max_y is not None:
  metadata["native_geometry_max_y_image_px"]=native_max_y
 pixel_geometry=observer.get("pixel_geometry") if isinstance(observer.get("pixel_geometry"),dict) else {
  "status":"NOT_AVAILABLE","decision_eligible":False,
  "reason":"Observer inbox did not provide native pixel geometry."
 }
 analysis=(image_analyzer or analyze_chart_image)(image_path,metadata,expected_symbol=market_symbol)
 analysis={
  **analysis,
  "native_ohlc_analysis":native_ohlc_analysis,
  "native_pixel_geometry":native_pixel_geometry,
  "native_pixel_geometry_payload":pixel_geometry,
  "source":"MT5_OBSERVER",
  "observer_capture":{
   "pipeline_component":"engine2_mt5_chart_image_pipeline",
   "capture_directory":str(Path(str(observer.get("image_path",""))).parent),
   "capture_id":capture_id,
   "image_sha256":image_hash,
   "age_seconds":round(age,2),
   "capture_data_skew_ms":skew,
   "native_bar_count":len(bars),
   "forming_bar_used_as_reference":(analysis.get("reference_anchor") or {}).get("offset_from_right")==0,
   "reference_anchor":analysis.get("reference_anchor"),
   "reference_candidates_considered":len(reference_candidates_for_chart),
   "native_pixel_geometry_status":native_pixel_geometry.get("status"),
   "native_pixel_geometry_visible_bars":native_pixel_geometry.get("visible_bars"),
   "native_pixel_geometry_mapping_status":native_pixel_geometry.get("mapping_status"),
   "native_geometry_slot_center_status":native_slot_center_result.get("status"),
   "native_geometry_slot_center_count":native_slot_center_result.get("native_slot_count",0),
   "native_geometry_slot_assignment":analysis.get("native_geometry_slot_assignment"),
   "broker_symbol":observer_symbol,
   "market_symbol":market_symbol,
   "engine_1_quote_freshness_required_for_visual_analysis":False,
   "timeframe":timeframe,
   "source_viewport_width_px":int(chart_meta.get("source_width_px",0) or 0),
   "source_viewport_height_px":int(chart_meta.get("source_main_window_height_px",0) or 0),
  },
 }
 reference=analysis.get("reference_multi_calibration") or {}
 axis_validation=analysis.get("reference_axis_validation") or {}
 anchor_verified=(
  analysis.get("calibration",{}).get("source")=="reference_multi_candle_ohlc"
  and reference.get("status")=="READY"
  and axis_validation.get("status")=="READY"
 )
 if not anchor_verified:
  analysis["decision_eligible"]=False
  if analysis.get("status")=="READY":
   analysis["status"]="OBSERVER_REFERENCE_NOT_VERIFIED"
  analysis["observer_reference_status"]=reference.get("status","NOT_VERIFIED")
  analysis["observer_block_reason"]="The chart did not pass multi-candle native OHLC fit and independent hold-out validation."
 else:
  analysis["observer_reference_status"]="READY"
 return analysis


class Engine2MT5ChartImagePipeline:
    """Engine 2 component that turns an MT5 folder capture into visual evidence."""

    def __init__(
        self,
        *,
        common_files: str | Path | None = None,
        image_analyzer: Callable[..., dict[str, Any]] | None = None,
    ) -> None:
        self.common_files = str(common_files if common_files is not None else MT5_COMMON_FILES).strip()
        self.image_analyzer = image_analyzer or analyze_chart_image

    def inspect_latest(self, *, now_ms: int | None = None) -> dict[str, Any]:
        # Resolve the existing Common\\Files inbox; no second capture agent is created.
        if not self.common_files:
            return {
                "engine": "engine_2_mt5_chart_image_pipeline",
                "status": "NOT_CONFIGURED",
                "decision_eligible": False,
                "message": "Set MIRSAD_MT5_COMMON_FILES to the MT5 Terminal\\Common\\Files folder.",
            }
        try:
            result = MT5ChartObserverInbox.from_common_files(self.common_files).inspect_latest(now_ms=now_ms)
            return {
                **result,
                "pipeline_component": "engine2_mt5_chart_image_pipeline",
                "observer_directory": str(Path(self.common_files) / "MirsadBTC" / "observer"),
                "image_directory": str(Path(self.common_files) / "MirsadBTC" / "observer" / "images"),
            }
        except Exception as exc:
            return {
                "engine": "engine_2_mt5_chart_image_pipeline",
                "status": "ERROR",
                "decision_eligible": False,
                "reason": f"{type(exc).__name__}: {exc}",
            }

    def analyze_capture(
        self,
        observer: dict[str, Any],
        market: dict[str, Any],
        bridge: dict[str, Any],
    ) -> dict[str, Any] | None:
        return analyze_mt5_observer_chart(
            observer,
            market,
            bridge,
            image_analyzer=self.image_analyzer,
        )
