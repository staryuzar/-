from __future__ import annotations

import math
from typing import Any

from ..config import RISK_PER_TRADE

def _ema(values: list[float], period: int) -> float | None:
    if len(values) < period:
        return None
    alpha = 2.0 / (period + 1)
    value = sum(values[:period]) / period
    for item in values[period:]:
        value = alpha * item + (1 - alpha) * value
    return value

def _rsi(values: list[float], period: int = 14) -> float | None:
    if len(values) <= period:
        return None
    changes = [values[i] - values[i - 1] for i in range(1, len(values))]
    gains = [max(x, 0.0) for x in changes]
    losses = [max(-x, 0.0) for x in changes]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for gain, loss in zip(gains[period:], losses[period:]):
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
    if avg_loss == 0:
        return 100.0
    return 100.0 - (100.0 / (1.0 + avg_gain / avg_loss))

def _atr(candles: list[dict[str, Any]], period: int = 14) -> float | None:
    if len(candles) <= period:
        return None
    ranges = []
    for previous, current in zip(candles[:-1], candles[1:]):
        ranges.append(max(
            float(current["high"]) - float(current["low"]),
            abs(float(current["high"]) - float(previous["close"])),
            abs(float(current["low"]) - float(previous["close"])),
        ))
    return sum(ranges[-period:]) / period

def calculate_volume(
    *, equity: float, entry: float, stop_loss: float,
    tick_size: float, tick_value: float,
    volume_min: float, volume_step: float, volume_max: float,
    risk_fraction: float = RISK_PER_TRADE,
) -> dict[str, Any]:
    values = (equity, entry, stop_loss, tick_size, tick_value, volume_min, volume_step, volume_max)
    if any(not math.isfinite(float(x)) for x in values):
        return {"status": "UNAVAILABLE", "reason": "Broker account/specifications are not finite."}
    if equity <= 0 or entry <= 0 or stop_loss <= 0 or tick_size <= 0 or tick_value <= 0 or volume_step <= 0:
        return {"status": "UNAVAILABLE", "reason": "Live account or symbol specifications are missing."}
    risk_cash = equity * risk_fraction
    per_lot_loss = abs(entry - stop_loss) / tick_size * tick_value
    if per_lot_loss <= 0:
        return {"status": "UNAVAILABLE", "reason": "Cannot calculate cash risk per lot."}
    raw = risk_cash / per_lot_loss
    rounded = math.floor((raw + 1e-12) / volume_step) * volume_step
    rounded = min(rounded, volume_max)
    rounded = round(rounded, 8)
    if rounded < volume_min:
        return {"status": "BLOCKED", "reason": "Calculated size is below broker minimum volume.",
                "risk_cash": round(risk_cash, 8), "raw_volume": raw}
    return {
        "status": "READY", "volume": rounded, "risk_cash": round(risk_cash, 8),
        "risk_fraction": risk_fraction, "loss_per_lot": round(per_lot_loss, 8),
        "raw_volume": raw,
    }

class DecisionEngine:
    """Combines measured market evidence and keeps all sizing/risk logic in the program."""
    def analyze(self, market: dict[str, Any], chart: dict[str, Any] | None,
                mt5_state: dict[str, Any] | None) -> dict[str, Any]:
        base = {"engine": "decision_and_risk", "risk_owner": "Mirsad_BTC_program"}
        if market.get("status") not in {"LIVE", "PARTIAL"} or not market.get("primary_venue"):
            return {**base, "status": "NOT_READY", "action": "WAIT",
                    "reason": "No current market feed is available."}
        primary = market["venues"][market["primary_venue"]]
        candles = [c for c in primary.get("candles", []) if c.get("closed")]
        closes = [float(c["close"]) for c in candles]
        if len(closes) < 55:
            return {**base, "status": "NOT_READY", "action": "WAIT",
                    "reason": "At least 55 completed one-minute candles are required."}
        fast, slow = _ema(closes, 20), _ema(closes, 50)
        rsi, atr = _rsi(closes), _atr(candles)
        last = closes[-1]
        if None in (fast, slow, rsi, atr) or atr <= 0:
            return {**base, "status": "NOT_READY", "action": "WAIT",
                    "reason": "Indicator calculation lacks sufficient valid input."}
        action = "WAIT"
        if fast > slow and last > fast and 52 <= rsi < 75:
            action = "BUY"
        elif fast < slow and last < fast and 25 < rsi <= 48:
            action = "SELL"
        entry = float(market["price"])
        stop_loss = take_profit = None
        if action == "BUY":
            stop_loss, take_profit = entry - 1.5 * atr, entry + 3.0 * atr
        elif action == "SELL":
            stop_loss, take_profit = entry + 1.5 * atr, entry - 3.0 * atr

        size_plan: dict[str, Any] = {"status": "WAITING_FOR_LIVE_MT5_SPECS"}
        if action in {"BUY", "SELL"} and stop_loss is not None and mt5_state:
            account = mt5_state.get("account", {})
            specs = mt5_state.get("symbol_spec", {})
            needed = ("equity", "tick_size", "tick_value", "volume_min", "volume_step", "volume_max")
            if all(k in account or k in specs for k in needed):
                size_plan = calculate_volume(
                    equity=float(account.get("equity", 0)), entry=entry, stop_loss=stop_loss,
                    tick_size=float(specs.get("tick_size", 0)),
                    tick_value=float(specs.get("tick_value", 0)),
                    volume_min=float(specs.get("volume_min", 0)),
                    volume_step=float(specs.get("volume_step", 0)),
                    volume_max=float(specs.get("volume_max", 0)),
                )
        chart_note = "no_chart_image"
        if chart and chart.get("status") == "READY":
            chart_note = f"visual evidence available ({chart.get('detected_bar_count', 0)} bars); candidate patterns are not used as a standalone trigger"
        return {
            **base, "status": "READY", "action": action,
            "as_of_ms": market["captured_at_ms"], "symbol": market["symbol"],
            "entry_reference": entry, "stop_loss": stop_loss, "take_profit": take_profit,
            "indicators": {"ema20": fast, "ema50": slow, "rsi14": rsi, "atr14": atr},
            "risk_plan": size_plan, "chart_context": chart_note,
            "reason": "Rules-only technical calculation over completed live candles; no AI or predictive certainty.",
        }
