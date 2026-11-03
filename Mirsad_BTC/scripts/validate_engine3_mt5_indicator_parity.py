from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from mirsad.engines.indicators import _calculate_timeframe_indicators

TIMEFRAMES = ("1m", "5m", "15m", "1h", "4h", "1d")
TOLERANCES = {
    "ema20": 0.10, "ema50": 0.10, "rsi14": 0.35, "atr14": 0.50,
    "macd_main": 0.10, "macd_signal": 0.10, "osma": 0.10,
    "bollinger_middle": 0.10, "bollinger_upper": 0.10, "bollinger_lower": 0.10,
    "stochastic_k": 0.75, "stochastic_d": 0.75,
    "adx14": 1.00, "plus_di14": 1.00, "minus_di14": 1.00,
    "cci20": 3.00, "mfi14": 1.00, "momentum14": 0.20, "wpr14": 1.00,
    "obv_delta": 0.01,
}
INDICATORS = tuple(name for name in TOLERANCES if name != "obv_delta")


def _finite(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def _obv_delta(candles: list[dict[str, Any]]) -> float | None:
    closed = [row for row in candles if row.get("closed") is True]
    if len(closed) < 2:
        return None
    previous, current = closed[-2], closed[-1]
    close_before = _finite(previous.get("close"))
    close_now = _finite(current.get("close"))
    volume = _finite(current.get("volume", current.get("tick_volume")))
    if close_before is None or close_now is None or volume is None or volume < 0:
        return None
    if close_now > close_before:
        return volume
    if close_now < close_before:
        return -volume
    return 0.0


def validate(candles_payload: dict[str, Any], native_payload: dict[str, Any]) -> dict[str, Any]:
    failures: list[str] = []
    frames_out: dict[str, Any] = {}
    if candles_payload.get("schema") != "MIR-ENGINE2-CANDLES-1":
        failures.append("Unsupported Engine 2 candle snapshot schema.")
    if native_payload.get("schema") != "MIR-MT5-INDICATORS-1":
        failures.append("Unsupported native MT5 indicator snapshot schema.")
    if candles_payload.get("broker_symbol") != native_payload.get("broker_symbol"):
        failures.append("Broker symbol differs between Engine 2 candles and native indicators.")
    if str(candles_payload.get("market_symbol", "")).upper() != str(native_payload.get("market_symbol", "")).upper():
        failures.append("Mirsad market symbol differs between Engine 2 candles and native indicators.")
    candle_server = str((candles_payload.get("account") or {}).get("server", "")).strip().casefold()
    native_server = str((native_payload.get("account") or {}).get("server", "")).strip().casefold()
    if not candle_server or not native_server or candle_server != native_server:
        failures.append("Broker account/server identity is missing or differs between Engine 2 candles and native indicators.")
    if candles_payload.get("time_basis") != "UTC_NORMALIZED_FROM_MT5_SERVER_TIME" or native_payload.get("time_basis") != "UTC_NORMALIZED_FROM_MT5_SERVER_TIME":
        failures.append("Both snapshots must use the same UTC-normalized MT5 server-time basis.")

    candle_frames = candles_payload.get("timeframes") or {}
    native_frames = native_payload.get("timeframes") or {}
    for timeframe in TIMEFRAMES:
        candle_frame = candle_frames.get(timeframe) or {}
        bars = candle_frame.get("bars") or []
        native_frame = native_frames.get(timeframe) or {}
        frame_failures: list[str] = []
        if not isinstance(bars, list) or len(bars) < 3:
            frame_failures.append("Insufficient OHLC bars for closed-bar parity.")
            frames_out[timeframe] = {"status": "FAIL", "failures": frame_failures, "metrics": {}}
            failures.extend(f"{timeframe}: {item}" for item in frame_failures)
            continue
        closed_bars = [bar for bar in bars if isinstance(bar, dict) and bar.get("closed") is True]
        if len(closed_bars) < 2:
            frame_failures.append("At least two closed bars are required.")
            expected_closed_time = 0
        else:
            try:
                expected_closed_time = int(closed_bars[-1]["open_time_ms"])
                native_closed_time = int(native_frame.get("closed_bar_time_utc_ms", 0))
                expected_forming_time = int(bars[-1]["open_time_ms"])
                native_forming_time = int(native_frame.get("forming_bar_time_utc_ms", 0))
            except (KeyError, TypeError, ValueError, OverflowError):
                expected_closed_time = native_closed_time = 0
            if expected_closed_time <= 0 or expected_closed_time != native_closed_time:
                frame_failures.append(
                    f"Closed-bar timestamp mismatch: Engine2={expected_closed_time}, MT5={native_closed_time}."
                )
            if expected_forming_time <= 0 or expected_forming_time != native_forming_time:
                frame_failures.append(
                    f"Forming-bar timestamp mismatch: Engine2={expected_forming_time}, MT5={native_forming_time}."
                )

        calculated = _calculate_timeframe_indicators(bars)
        native_values = native_frame.get("values") or {}
        metrics: dict[str, Any] = {}
        for name in INDICATORS:
            local_value = _finite(calculated.get(name))
            native_item = native_values.get(name) or {}
            native_value = _finite(native_item.get("closed")) if native_item.get("status") == "READY" else None
            tolerance = TOLERANCES[name]
            if local_value is None or native_value is None:
                metrics[name] = {
                    "status": "MISSING", "engine3": local_value,
                    "mt5": native_value, "tolerance": tolerance,
                }
                frame_failures.append(f"{name}: Engine 3 or MT5 closed-bar value is unavailable.")
                continue
            error = abs(local_value - native_value)
            passed = error <= tolerance
            metrics[name] = {
                "status": "PASS" if passed else "FAIL",
                "engine3": local_value, "mt5": native_value,
                "absolute_error": error, "tolerance": tolerance,
            }
            if not passed:
                frame_failures.append(f"{name}: absolute error {error:.8g} exceeds tolerance {tolerance}.")

        # OBV is cumulative and its absolute origin depends on loaded history.
        # Compare the last closed-bar increment, not the cumulative offset.
        obv_item = native_values.get("obv") or {}
        native_obv_delta = None
        if obv_item.get("status") == "READY":
            previous = _finite(obv_item.get("previous_closed"))
            latest = _finite(obv_item.get("closed"))
            if previous is not None and latest is not None:
                native_obv_delta = latest - previous
        local_obv_delta = _obv_delta(bars)
        if native_obv_delta is None or local_obv_delta is None:
            metrics["obv_delta"] = {
                "status": "MISSING", "engine3": local_obv_delta,
                "mt5": native_obv_delta, "tolerance": TOLERANCES["obv_delta"],
            }
            frame_failures.append("OBV delta: previous-closed MT5 value or OHLC tick volume is unavailable.")
        else:
            error = abs(local_obv_delta - native_obv_delta)
            passed = error <= TOLERANCES["obv_delta"]
            metrics["obv_delta"] = {
                "status": "PASS" if passed else "FAIL",
                "engine3": local_obv_delta, "mt5": native_obv_delta,
                "absolute_error": error, "tolerance": TOLERANCES["obv_delta"],
            }
            if not passed:
                frame_failures.append(
                    f"OBV delta: absolute error {error:.8g} exceeds tolerance {TOLERANCES['obv_delta']}."
                )

        frame_status = "PASS" if not frame_failures else "FAIL"
        frames_out[timeframe] = {
            "status": frame_status,
            "closed_bars": len(closed_bars),
            "closed_bar_time_utc_ms": expected_closed_time or None,
            "metrics": metrics,
            "failures": frame_failures,
        }
        failures.extend(f"{timeframe}: {item}" for item in frame_failures)

    passed_metrics = sum(
        1 for frame in frames_out.values()
        for metric in (frame.get("metrics") or {}).values()
        if metric.get("status") == "PASS"
    )
    total_metrics = sum(len(frame.get("metrics") or {}) for frame in frames_out.values())
    return {
        "schema": "MIR-ENGINE3-MT5-INDICATOR-PARITY-1",
        "status": "PASS" if not failures else "FAIL",
        "method": "same closed Engine2 OHLC bars versus native MT5 CopyBuffer values",
        "timeframes": frames_out,
        "passed_metrics": passed_metrics,
        "total_metrics": total_metrics,
        "failures": failures,
        "decision_eligible": False,
        "obv_method": "compare last closed-bar OBV delta; cumulative absolute OBV offsets are history-origin dependent",
        "tolerances": TOLERANCES,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare Engine 3 indicators with MT5 native CopyBuffer on identical closed bars.")
    parser.add_argument("--candles", type=Path, required=True)
    parser.add_argument("--native-indicators", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        candles_payload = json.loads(args.candles.read_text(encoding="utf-8"))
        native_payload = json.loads(args.native_indicators.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        print(f"Unable to read parity inputs: {type(exc).__name__}", file=sys.stderr)
        return 2
    report = validate(candles_payload, native_payload)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": report["status"],
        "passed_metrics": report["passed_metrics"],
        "total_metrics": report["total_metrics"],
        "failures": report["failures"][:20],
    }, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
