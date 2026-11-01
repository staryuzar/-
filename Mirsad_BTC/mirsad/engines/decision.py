from __future__ import annotations

import hashlib
import math
from typing import Any

from ..config import RISK_PER_TRADE, MT5_QUOTE_MAX_AGE_SECONDS

TIMEFRAME_WEIGHTS = {"1m": 1.0, "5m": 2.0, "15m": 3.0, "1h": 4.0, "4h": 5.0, "1d": 5.0}


def _ema(values: list[float], period: int) -> float | None:
    if period < 2 or len(values) < period:
        return None
    alpha = 2.0 / (period + 1)
    value = sum(values[:period]) / period
    for item in values[period:]:
        value = alpha * item + (1 - alpha) * value
    return value


def _rsi(values: list[float], period: int = 14) -> float | None:
    if period < 2 or len(values) <= period:
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
        return 50.0 if avg_gain == 0 else 100.0
    return 100.0 - (100.0 / (1.0 + avg_gain / avg_loss))


def _atr(candles: list[dict[str, Any]], period: int = 14) -> float | None:
    if period < 2 or len(candles) <= period:
        return None
    ranges = []
    for previous, current in zip(candles[:-1], candles[1:]):
        ranges.append(max(
            float(current["high"]) - float(current["low"]),
            abs(float(current["high"]) - float(previous["close"])),
            abs(float(current["low"]) - float(previous["close"])),
        ))
    return sum(ranges[-period:]) / period


def _timeframe_trend(candles: list[dict[str, Any]]) -> dict[str, Any]:
    closed = [c for c in candles if c.get("closed")]
    closes = [float(c["close"]) for c in closed]
    fast, slow = _ema(closes, 20), _ema(closes, 50)
    if fast is None or slow is None:
        return {"status": "INSUFFICIENT", "trend": "UNKNOWN", "closed_candles": len(closes)}
    last = closes[-1]
    trend = "BULLISH" if fast > slow and last > fast else (
        "BEARISH" if fast < slow and last < fast else "NEUTRAL"
    )
    return {
        "status": "READY", "trend": trend, "ema20": fast, "ema50": slow,
        "last_close": last, "closed_candles": len(closes),
    }


def _aggregate_orderflow(venues: dict[str, Any]) -> dict[str, Any]:
    buy = 0.0
    sell = 0.0
    count = 0
    contributors = []
    for name, row in venues.items():
        flow = row.get("orderflow") or {}
        if row.get("status") != "LIVE" or flow.get("unit") != "BTC":
            continue
        b = float(flow.get("taker_buy_quantity", 0))
        s = float(flow.get("taker_sell_quantity", 0))
        if b < 0 or s < 0 or not math.isfinite(b + s):
            continue
        buy += b
        sell += s
        count += int(flow.get("trade_count", 0))
        contributors.append(name)
    total = buy + sell
    return {
        "trade_count": count, "taker_buy_quantity": buy, "taker_sell_quantity": sell,
        "signed_quantity_delta": buy - sell, "taker_buy_ratio": buy / total if total else None,
        "unit": "BTC", "venues": contributors,
        "scope": "recent public spot trade samples by venue",
    }


def calculate_volume(
    *, equity: float, entry: float, stop_loss: float, tick_size: float,
    tick_value_loss: float, volume_min: float, volume_step: float,
    volume_max: float, risk_fraction: float = RISK_PER_TRADE,
) -> dict[str, Any]:
    values = (
        equity, entry, stop_loss, tick_size, tick_value_loss,
        volume_min, volume_step, volume_max, risk_fraction,
    )
    try:
        nums = [float(value) for value in values]
    except (TypeError, ValueError, OverflowError):
        return {"status": "UNAVAILABLE", "reason": "Live account/specification fields are not numeric."}
    if any(not math.isfinite(value) for value in nums):
        return {"status": "UNAVAILABLE", "reason": "Live account/specification fields contain a non-finite value."}
    if equity <= 0 or entry <= 0 or stop_loss <= 0 or tick_size <= 0 or tick_value_loss <= 0:
        return {"status": "UNAVAILABLE", "reason": "Live equity or loss-side tick data is missing."}
    if not 0 < risk_fraction < 1:
        return {"status": "UNAVAILABLE", "reason": "Risk fraction must be between 0 and 1."}
    if volume_min <= 0 or volume_step <= 0 or volume_max < volume_min:
        return {"status": "UNAVAILABLE", "reason": "Broker volume limits are inconsistent."}
    risk_cash = equity * risk_fraction
    loss_per_lot = abs(entry - stop_loss) / tick_size * tick_value_loss
    if not math.isfinite(loss_per_lot) or loss_per_lot <= 0:
        return {"status": "UNAVAILABLE", "reason": "Cannot calculate loss per lot."}
    raw = risk_cash / loss_per_lot
    volume = round(min(math.floor((raw + 1e-12) / volume_step) * volume_step, volume_max), 8)
    if volume < volume_min:
        return {
            "status": "BLOCKED", "reason": "Risk-calculated volume is below broker minimum.",
            "risk_cash": risk_cash, "unrounded_volume": raw,
        }
    return {
        "status": "READY", "volume": volume, "risk_cash": risk_cash,
        "risk_fraction": risk_fraction, "loss_per_lot": loss_per_lot,
        "estimated_loss": loss_per_lot * volume,
        "tick_value_basis": "loss-side tick value reported by MT5 in account currency",
    }


def _signal_id(*parts: Any) -> str:
    raw = "|".join(str(part) for part in parts)
    return "MIR-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _matching_positions(bridge: dict[str, Any], broker_symbol: str) -> list[dict[str, Any]]:
    result = []
    for item in bridge.get("positions", []) or []:
        if str(item.get("symbol", "")).upper() != broker_symbol.upper():
            continue
        try:
            ticket = int(item.get("ticket", 0))
            side_code = int(item.get("type", -1))
            volume = float(item.get("volume", 0))
        except (TypeError, ValueError, OverflowError):
            continue
        if ticket > 0 and side_code in (0, 1) and math.isfinite(volume) and volume > 0:
            result.append({**item, "ticket": ticket, "type": side_code, "volume": volume,
                           "side": "BUY" if side_code == 0 else "SELL"})
    return result


class DecisionEngine:
    """Engine 4. Direction comes only from Engines 1 and 2.
    Engine 3 supplies execution/account facts and transports MIR1 commands.
    """

    def analyze(
        self, market: dict[str, Any], chart: dict[str, Any] | None,
        bridge: dict[str, Any] | None,
    ) -> dict[str, Any]:
        base = {
            "engine": "engine_4_decision_and_risk", "method": "rules_only",
            "direction_inputs": ["engine_1_market", "engine_2_chart"],
            "bridge_role": "engine_3 transports commands and supplies live quote/account/specifications only",
            "risk_owner": "Mirsad_BTC_program",
        }
        bridge = bridge or {}
        if market.get("status") not in {"LIVE", "PARTIAL"} or not market.get("primary_venue"):
            return {**base, "status": "NOT_READY", "action": "WAIT", "candidate_action": "WAIT",
                    "reason": "Engine 1 has no current public market feed."}

        primary = market["venues"][market["primary_venue"]]
        candle_sets = primary.get("candles_by_tf") or {"1m": primary.get("candles", [])}
        timeframe_data = {tf: _timeframe_trend(candle_sets.get(tf, [])) for tf in TIMEFRAME_WEIGHTS}
        required = ("1m", "5m", "15m")
        missing = [tf for tf in required if timeframe_data[tf]["status"] != "READY"]
        if missing:
            return {**base, "status": "NOT_READY", "action": "WAIT", "candidate_action": "WAIT",
                    "timeframes": timeframe_data,
                    "reason": "Engine 1 lacks completed candles for " + ", ".join(missing)}

        one = [c for c in candle_sets.get("1m", []) if c.get("closed")]
        five = [c for c in candle_sets.get("5m", []) if c.get("closed")]
        closes = [float(c["close"]) for c in one]
        fast, slow = _ema(closes, 20), _ema(closes, 50)
        rsi, atr1, atr5 = _rsi(closes), _atr(one), _atr(five)
        if None in (fast, slow, rsi, atr1, atr5) or atr5 <= 0:
            return {**base, "status": "NOT_READY", "action": "WAIT", "candidate_action": "WAIT",
                    "timeframes": timeframe_data,
                    "reason": "Completed candle data is insufficient for technical calculations."}

        weighted = 0.0
        weight_total = 0.0
        for tf, weight in TIMEFRAME_WEIGHTS.items():
            row = timeframe_data[tf]
            if row["status"] != "READY":
                continue
            weight_total += weight
            weighted += weight * (1 if row["trend"] == "BULLISH" else -1 if row["trend"] == "BEARISH" else 0)
        trend_score = weighted / weight_total if weight_total else 0.0
        orderflow = _aggregate_orderflow(market.get("venues", {}))
        buy_ratio = orderflow.get("taker_buy_ratio")

        candidate = "WAIT"
        if (
            timeframe_data["1m"]["trend"] == "BULLISH"
            and timeframe_data["5m"]["trend"] == "BULLISH"
            and timeframe_data["15m"]["trend"] == "BULLISH"
            and trend_score >= 0.35 and 50 < rsi < 72
            and buy_ratio is not None and buy_ratio >= 0.52
        ):
            candidate = "BUY"
        elif (
            timeframe_data["1m"]["trend"] == "BEARISH"
            and timeframe_data["5m"]["trend"] == "BEARISH"
            and timeframe_data["15m"]["trend"] == "BEARISH"
            and trend_score <= -0.35 and 28 < rsi < 50
            and buy_ratio is not None and buy_ratio <= 0.48
        ):
            candidate = "SELL"

        chart = chart or {}
        chart_eligible = bool(chart.get("decision_eligible")) and chart.get("status") == "READY"
        visual_bias = chart.get("visual_bias", "NEUTRAL")
        aligned_signal = candidate
        chart_gate = "NOT_CALIBRATED"
        if not chart_eligible:
            aligned_signal = "WAIT"
            chart_gate = "WAITING_FOR_ENGINE_2_CALIBRATION"
        elif candidate in {"BUY", "SELL"}:
            expected = "BULLISH" if candidate == "BUY" else "BEARISH"
            if visual_bias != expected:
                aligned_signal = "WAIT"
                chart_gate = "VISUAL_CONFLICT_OR_NEUTRAL"
            else:
                chart_gate = "CONFIRMED"
        else:
            chart_gate = "NO_MARKET_SETUP"

        broker_symbol = str(bridge.get("symbol", ""))
        market_symbol = str(market.get("symbol", ""))
        quote = bridge.get("quote", {})
        account = bridge.get("account", {})
        specs = bridge.get("symbol_spec", {})
        try:
            bid = float(quote.get("bid", 0))
            ask = float(quote.get("ask", 0))
            quote_age = float(bridge.get("quote_age_seconds", float("inf")))
            tick_age = float(quote.get("tick_age_seconds", float("inf")))
            quote_ok = (
                bridge.get("status") == "CONNECTED"
                and str(bridge.get("market_symbol", "")).upper() == market_symbol.upper()
                and bool(broker_symbol) and 0 < bid <= ask
                and math.isfinite(bid) and math.isfinite(ask)
                and math.isfinite(quote_age) and math.isfinite(tick_age)
                and 0 <= quote_age <= MT5_QUOTE_MAX_AGE_SECONDS
                and 0 <= tick_age <= MT5_QUOTE_MAX_AGE_SECONDS
            )
        except (TypeError, ValueError, OverflowError):
            quote_ok = False
            bid = ask = 0.0

        entry = ask if aligned_signal == "BUY" and quote_ok else (
            bid if aligned_signal == "SELL" and quote_ok else float(market["price"])
        )
        stop_loss = take_profit = None
        if aligned_signal == "BUY":
            stop_loss, take_profit = entry - 1.5 * atr5, entry + 3.0 * atr5
        elif aligned_signal == "SELL":
            stop_loss, take_profit = entry + 1.5 * atr5, entry - 3.0 * atr5

        signal_id = _signal_id(
            market_symbol, aligned_signal,
            one[-1].get("open_time_ms") if one else 0,
            chart.get("image", ""),
        ) if aligned_signal in {"BUY", "SELL"} else None

        size: dict[str, Any] = {
            "status": "WAITING_FOR_ENGINE_3_QUOTE",
            "reason": "Engine 3 must provide a fresh mapped MT5 quote and live account/symbol specifications.",
        }
        if aligned_signal in {"BUY", "SELL"}:
            spec_fields = ("tick_size", "tick_value_loss", "volume_min", "volume_step", "volume_max")
            if not quote_ok:
                size = {"status": "BLOCKED",
                        "reason": "No fresh MT5 quote or broker symbol mapping does not match the market instrument."}
            elif "equity" not in account or not all(key in specs for key in spec_fields):
                size = {"status": "UNAVAILABLE",
                        "reason": "Engine 3 account equity or loss/volume specifications are incomplete."}
            else:
                size = calculate_volume(
                    equity=account["equity"], entry=entry, stop_loss=stop_loss,
                    tick_size=specs["tick_size"], tick_value_loss=specs["tick_value_loss"],
                    volume_min=specs["volume_min"], volume_step=specs["volume_step"],
                    volume_max=specs["volume_max"],
                )

        # Position management: close one opposite position first, and never stack
        # another same-direction position in the same symbol by accident.
        positions = _matching_positions(bridge, broker_symbol)
        action = aligned_signal
        close_ticket = None
        open_block_reason = None
        close_volume = None
        if aligned_signal in {"BUY", "SELL"} and quote_ok:
            opposite = [p for p in positions if p["side"] != aligned_signal]
            same = [p for p in positions if p["side"] == aligned_signal]
            if opposite:
                target = sorted(opposite, key=lambda p: p["ticket"])[0]
                action = "CLOSE"
                close_ticket = target["ticket"]
                close_volume = target["volume"]
                size = {
                    "status": "READY", "volume": close_volume,
                    "purpose": "close_existing_opposite_position",
                    "reason": "Engine 1 and Engine 2 confirmed a direction opposite to an existing position; close first before considering a reversal.",
                }
                signal_id = _signal_id("CLOSE", market_symbol, close_ticket, round(close_volume, 8),
                                       one[-1].get("open_time_ms") if one else 0,
                                       chart.get("image", ""))
            elif same:
                action = "HOLD"
                open_block_reason = "A same-direction position is already open; duplicate entry is suppressed."
                size = {"status": "NOT_REQUIRED", "reason": open_block_reason}

        command_ready = bool(
            bridge.get("status") == "CONNECTED" and quote_ok
            and (
                (action in {"BUY", "SELL"} and size.get("status") == "READY")
                or (action == "CLOSE" and close_ticket is not None and close_volume is not None)
            )
        )

        return {
            **base,
            "status": "READY" if chart_eligible else "WAITING_FOR_ENGINE_2",
            "action": action, "candidate_action": candidate, "aligned_signal": aligned_signal,
            "signal_id": signal_id, "command_ready": command_ready,
            "position_ticket": close_ticket, "chart_gate": chart_gate,
            "chart_visual_bias": visual_bias, "open_block_reason": open_block_reason,
            "as_of_ms": market.get("captured_at_ms"),
            "market_symbol": market_symbol, "symbol": broker_symbol if quote_ok else market_symbol,
            "market_price_reference": market.get("price"),
            "broker_quote": quote if quote_ok else None,
            "entry_reference": entry if action in {"BUY", "SELL"} else 0.0,
            "stop_loss": stop_loss if action in {"BUY", "SELL"} else 0.0,
            "take_profit": take_profit if action in {"BUY", "SELL"} else 0.0,
            "trend_score": round(trend_score, 4), "timeframes": timeframe_data,
            "indicators": {
                "ema20_1m": fast, "ema50_1m": slow, "rsi14_1m": rsi,
                "atr14_1m": atr1, "atr14_5m": atr5,
            },
            "orderflow": orderflow,
            "risk_plan": size,
            "position_management": {
                "matching_positions": len(positions),
                "opposite_positions": sum(1 for p in positions if aligned_signal in {"BUY", "SELL"} and p["side"] != aligned_signal),
                "action": action,
                "close_ticket": close_ticket,
            },
            "engine_inputs": {
                "direction_from_engine_1_market": market.get("status"),
                "direction_from_engine_2_chart": "READY" if chart_eligible else chart.get("status", "NOT_READY"),
                "engine_3_bridge_for_quote_account_specs_and_transport": bridge.get("status", "NOT_CONFIGURED"),
            },
            "reason": (
                "BUY/SELL is derived only from Engine 1 market data and Engine 2 calibrated chart analysis. "
                "Engine 3 supplies execution and account facts only; it does not vote on direction."
            ),
        }
