from __future__ import annotations
import argparse, hashlib, json, math, sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
from mirsad.engines.chart import analyze_chart_image
from mirsad.engines.mt5_observer import MT5ChartObserverInbox

SUPPORTED = {"1m", "5m", "15m", "1h", "4h", "1d", "1w"}

def analyze(observer_root: Path, market_symbol: str, broker_symbol: str) -> dict:
    capture = MT5ChartObserverInbox(observer_root, max_age_seconds=120).inspect_latest()
    chart = capture.get("chart") if isinstance(capture.get("chart"), dict) else {}
    def blocked(code: str, reason: str) -> dict:
        return {
            "schema": "MIR-ENGINE2-OBSERVER-SMOKE-1",
            "capture_id": capture.get("capture_id"),
            "capture": {
                "source_width_px": chart.get("source_width_px"),
                "source_main_window_height_px": chart.get("source_main_window_height_px"),
                "visible_bars": chart.get("visible_bars"),
                "windows_total": chart.get("windows_total"),
                "chart_autoscroll": chart.get("chart_autoscroll"),
                "source_dimensions_usable": chart.get("source_dimensions_usable"),
            },
            "decision_eligible": False,
            "engine2": {"status": code, "visual_eligible": False, "reason": reason,
                        "detected_bars": 0, "confirmed_bars": 0,
                        "reference_calibration_status": "NOT_ATTEMPTED", "quality_gates": {}},
            "safety": {"read_only": True, "decision_eligible": False}
        }
    if capture.get("status") != "READY_FOR_ENGINE_2_VALIDATION":
        return blocked("CAPTURE_NOT_READY", str(capture.get("reason") or capture.get("status")))
    bars = capture.get("bars") if isinstance(capture.get("bars"), list) else []
    timeframe = str(chart.get("timeframe", "")).lower()
    if chart.get("symbol") != broker_symbol:
        return blocked("SYMBOL_MISMATCH", "Broker symbol differs from the explicit input.")
    if timeframe not in SUPPORTED:
        return blocked("TIMEFRAME_UNSUPPORTED", "Observer timeframe is unsupported.")
    if not capture.get("visual_calibration_eligible") or not chart.get("source_dimensions_usable"):
        return blocked("VIEWPORT_UNSUITABLE", "Original MT5 viewport is below the calibration threshold.")
    if int(chart.get("source_width_px", 0)) < 320 or int(chart.get("source_main_window_height_px", 0)) < 160:
        return blocked("VIEWPORT_UNSUITABLE", "Original MT5 viewport is too small.")
    if chart.get("chart_autoscroll") is not True or int(chart.get("windows_total", 0)) != 1:
        return blocked("LAYOUT_UNVERIFIED", "AutoScroll must be enabled and the chart must have one calibrated window.")
    if int(chart.get("visible_bars", 0)) < 21 or len(bars) < 21:
        return blocked("HISTORY_INSUFFICIENT", "Need 20 closed candles and one forming candle.")
    if capture.get("rates_status") != "AVAILABLE" or int(capture.get("rates_error_code", -1)) != 0:
        return blocked("OHLC_UNAVAILABLE", "CopyRates did not provide a valid OHLC snapshot.")
    if any(x.get("is_closed") is not True for x in bars[:-1]) or bars[-1].get("is_closed") is not False:
        return blocked("BAR_STATE_INVALID", "Exactly the last OHLC bar must be forming.")
    try:
        age = float(capture.get("age_seconds", math.inf))
        skew = int(capture.get("capture_data_skew_ms", -1))
        pmin, pmax = float(chart["price_min"]), float(chart["price_max"])
        low, high = float(bars[-1]["low"]), float(bars[-1]["high"])
    except (TypeError, ValueError, KeyError, OverflowError):
        return blocked("METADATA_INVALID", "Capture timing or visible price range is missing.")
    if not all(math.isfinite(x) for x in (age, pmin, pmax, low, high)) or age > 120 or age < 0 or not 0 <= skew <= 2000:
        return blocked("CAPTURE_NOT_SYNCHRONIZED", "Image and OHLC timing exceeds the allowed two seconds.")
    if not 0 < pmin < pmax or low < pmin or high > pmax:
        return blocked("PRICE_RANGE_MISMATCH", "Latest MT5 candle is outside the visible chart range.")
    image = Path(str(capture.get("image_path", "")))
    if not image.is_file():
        return blocked("IMAGE_MISSING", "Validated PNG is no longer available.")
    digest = hashlib.sha256(image.read_bytes()).hexdigest()
    if digest != str(capture.get("image_sha256", "")).lower():
        return blocked("IMAGE_CHANGED", "PNG hash changed after inbox verification.")
    if not market_symbol or len(market_symbol) > 32:
        return blocked("MARKET_MAPPING_INVALID", "Explicit Mirsad market symbol is invalid.")
    metadata = {
        "symbol": market_symbol, "timeframe": timeframe,
        "price_scale_type": str(chart.get("price_scale_type", "linear")).lower(),
        "last_candle_closed": False, "auto_axis_ocr": False,
        "reference_last_candle_ohlc": {k: float(bars[-1][k]) for k in ("open", "high", "low", "close")}
    }
    result = analyze_chart_image(image, metadata, expected_symbol=market_symbol)
    reference = result.get("reference_calibration") or {}
    anchor = (result.get("calibration", {}).get("source") == "reference_last_candle_ohlc"
              and reference.get("status") == "READY"
              and result.get("reference_ohlc_override_applied") is True)
    eligible = bool(result.get("decision_eligible")) and anchor
    return {
        "schema": "MIR-ENGINE2-OBSERVER-SMOKE-1",
        "capture_id": capture.get("capture_id"),
        "broker_symbol": broker_symbol, "market_symbol": market_symbol, "timeframe": timeframe,
        "capture": {"age_seconds": round(age, 2), "capture_data_skew_ms": skew,
                    "image_sha256": digest, "native_ohlc_bars": len(bars),
                    "source_width_px": int(chart["source_width_px"]),
                    "source_height_px": int(chart["source_main_window_height_px"])},
        "engine2": {
            "status": result.get("status") if anchor else "REFERENCE_NOT_VERIFIED",
            "visual_eligible": eligible, "visual_bias": result.get("visual_bias", "NEUTRAL"),
            "analysis_score": result.get("analysis_score", 0),
            "analysis_confidence": result.get("analysis_confidence", 0),
            "detected_bars": result.get("detected_bar_count", 0),
            "confirmed_bars": result.get("confirmed_bar_count", 0),
            "reference_calibration_status": reference.get("status", "NOT_VERIFIED"),
            "quality_gates": result.get("quality_gates", {}),
            "reason": None if eligible else "Visual quality or native OHLC anchor did not pass."
        },
        "decision_eligible": False,
        "safety": {"read_only": True, "decision_eligible": False,
                   "reason": "Engine 2 diagnostic only. No order is created or authorized."}
    }

def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--observer-root", type=Path, required=True)
    p.add_argument("--market-symbol", required=True)
    p.add_argument("--expected-broker-symbol", required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    result = analyze(a.observer_root, a.market_symbol.strip().upper(), a.expected_broker_symbol.strip())
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["engine2"]["status"],
                      "visual_eligible": result["engine2"]["visual_eligible"],
                      "decision_eligible": False}))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
