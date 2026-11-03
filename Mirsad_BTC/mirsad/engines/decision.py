from __future__ import annotations

import hashlib
import math
from typing import Any

from ..config import (RISK_PER_TRADE, MT5_QUOTE_MAX_AGE_SECONDS, MT5_MARKET_DIVERGENCE_MAX_PCT, MT5_MAX_SPREAD_PCT)

from .indicators import IndicatorsEngine, TIMEFRAME_WEIGHTS, _ema, _rsi, _atr, _timeframe_trend
from .position_management import plan_atr_stop_update


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
    if raw < volume_min - 1e-12:
        return {
            "status": "BLOCKED", "reason": "Risk-calculated volume is below broker minimum.",
            "risk_cash": risk_cash, "unrounded_volume": raw,
        }
    steps = math.floor((min(raw, volume_max) - volume_min + 1e-12) / volume_step)
    volume = round(volume_min + max(0, steps) * volume_step, 8)
    if volume > volume_max + 1e-9:
        volume = round(volume_min + math.floor((volume_max - volume_min) / volume_step) * volume_step, 8)
    return {
        "status": "READY", "volume": volume, "risk_cash": risk_cash,
        "risk_fraction": risk_fraction, "loss_per_lot": loss_per_lot,
        "estimated_loss": loss_per_lot * volume,
        "tick_value_basis": "loss-side tick value reported by MT5 in account currency",
    }


def _signal_id(*parts: Any) -> str:
    raw = "|".join(str(part) for part in parts)
    return "MIR-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _price_to_tick(price: float, tick_size: float, digits: int, direction: str) -> float:
    if not math.isfinite(price) or not math.isfinite(tick_size) or tick_size <= 0:
        raise ValueError("Invalid price or tick size.")
    units = price / tick_size
    if direction == "UP":
        ticks = math.ceil(units - 1e-10)
    elif direction == "DOWN":
        ticks = math.floor(units + 1e-10)
    else:
        ticks = round(units)
    return round(ticks * tick_size, max(0, min(10, int(digits))))


def _matching_positions(bridge: dict[str, Any], broker_symbol: str) -> list[dict[str, Any]]:
    result = []
    try:
        expected_magic = int(bridge.get("magic_number", 0))
    except (TypeError, ValueError, OverflowError):
        expected_magic = 0
    if expected_magic <= 0:
        return result
    for item in bridge.get("positions", []) or []:
        if str(item.get("symbol", "")).upper() != broker_symbol.upper():
            continue
        try:
            ticket = int(item.get("ticket", 0))
            side_code = int(item.get("type", -1))
            volume = float(item.get("volume", 0))
            magic = int(item.get("magic", -1))
        except (TypeError, ValueError, OverflowError):
            continue
        if ticket > 0 and side_code in (0, 1) and magic == expected_magic and math.isfinite(volume) and volume > 0:
            result.append({**item, "ticket": ticket, "type": side_code, "magic": magic, "volume": volume,
                           "side": "BUY" if side_code == 0 else "SELL"})
    return result


CHART_DECISION_WEIGHT = 0.80
MARKET_CONFIRMATION_WEIGHT = 0.20
DIRECTIONAL_SCORE_THRESHOLD = 0.40
MIN_CHART_SCORE = 0.30
MIN_CHART_CONFIDENCE = 0.55


def _weighted_direction_score(chart_score: float, market_score: float) -> float:
    """Engine 2 owns 80% of direction; Engine 1 contributes 20% confirmation."""
    chart_value = float(chart_score)
    market_value = float(market_score)
    if not math.isfinite(chart_value) or not math.isfinite(market_value):
        raise ValueError("Directional scores must be finite.")
    if not -1.0 <= chart_value <= 1.0 or not -1.0 <= market_value <= 1.0:
        raise ValueError("Directional scores must be between -1 and 1.")
    return max(-1.0, min(1.0,
        CHART_DECISION_WEIGHT * chart_value
        + MARKET_CONFIRMATION_WEIGHT * market_value
    ))


def _market_confirmation_score(indicator_trend_score: float, market: dict[str, Any]) -> tuple[float, dict[str, Any]]:
    """Blend Engine 3 candle indicators with Engine 1 quote-update microstructure."""
    trend = float(indicator_trend_score)
    if not math.isfinite(trend) or not -1.0 <= trend <= 1.0:
        raise ValueError("Indicator trend score must be finite and normalized.")
    context = market.get("market_context") if isinstance(market.get("market_context"), dict) else {}
    pulse = context.get("microstructure") if isinstance(context.get("microstructure"), dict) else {}
    quote_balance = None
    if pulse.get("status") == "READY":
        try:
            value = float(pulse.get("quote_direction_balance"))
        except (TypeError, ValueError, OverflowError):
            value = float("nan")
        if math.isfinite(value) and -1.0 <= value <= 1.0:
            quote_balance = value
    score = trend if quote_balance is None else 0.80 * trend + 0.20 * quote_balance
    return max(-1.0, min(1.0, score)), {
        "engine_3_indicator_trend": round(trend, 4),
        "engine_1_quote_update_balance": round(quote_balance, 4) if quote_balance is not None else None,
        "quote_pulse_status": pulse.get("status", "NOT_AVAILABLE"),
        "quote_pulse_scope": "bid/ask quote updates, not executed trades",
    }


class DecisionEngine:
    """Engine 4. Combines Engine 1 market context, Engine 2 chart/candles and Engine 3 indicators.
    Engine 5 supplies execution/account facts and transports MIR1 commands.
    """

    def analyze(
        self, market: dict[str, Any], chart: dict[str, Any] | None,
        bridge: dict[str, Any] | None, indicators: dict[str, Any] | None = None,
        engine2_price_action: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        base = {
            "engine": "engine_4_decision_trade_monitor", "method": "rules_only",
            "direction_inputs": ["engine_1_market", "engine_2_chart", "engine_3_indicators"],
            "calculation_inputs": ["engine_3_indicators"],
            "bridge_role": "engine_5 transports commands and supplies live quote/account/specifications only",
            "risk_owner": "Mirsad_BTC_program",
        }
        bridge = bridge or {}
        chart = chart if isinstance(chart, dict) else {}
        price_action = engine2_price_action if isinstance(engine2_price_action, dict) else {}
        price_action_summary = (
            price_action.get("summary")
            if isinstance(price_action.get("summary"), dict) else {}
        )
        price_action_context = {
            "status": price_action.get("status", "NOT_PROVIDED"),
            "direction": price_action.get("direction", "UNKNOWN"),
            "structure_score": price_action.get("structure_score"),
            "as_of_utc_ms": price_action.get("as_of_utc_ms"),
            "eligible_timeframes": price_action_summary.get("eligible_timeframes", []),
            "timeframe_alignment": price_action_summary.get("timeframe_alignment", "NOT_AVAILABLE"),
            "latest_candle_pattern_alignment": price_action_summary.get(
                "latest_candle_pattern_alignment", "NO_DIRECTIONAL_CANDLE_PATTERN"
            ),
            "bullish_pattern_timeframes": price_action_summary.get("bullish_pattern_timeframes", []),
            "bearish_pattern_timeframes": price_action_summary.get("bearish_pattern_timeframes", []),
            "mixed_pattern_timeframes": price_action_summary.get("mixed_pattern_timeframes", []),
            "decision_eligible": False,
            "gate": "NOT_EVALUATED",
            "role": "NON_DIRECTIONAL_SAFETY_GATE_ONLY",
        }
        base["engine_2_native_price_action_context"] = price_action_context
        source = str(market.get("source", "")).upper()
        mt5_native_source = source == "MT5_TERMINAL"
        minimum_venues = 1 if mt5_native_source else 2
        feed_health = market.get("feed_health") if isinstance(market.get("feed_health"), dict) else {}
        mt5_health_ok = (
            not mt5_native_source
            or (
                feed_health.get("terminal_connected") is True
                and feed_health.get("quote_fresh") is True
            )
        )
        if (
            market.get("status") != "LIVE"
            or int(market.get("venue_count", 0) or 0) < minimum_venues
            or not market.get("primary_venue")
            or not mt5_health_ok
        ):
            reason = (
                "Engine 1 MT5 quote feed is missing, stale, or failed its terminal/quote checks."
                if mt5_native_source
                else "Engine 1 requires a live MT5 feed, or at least two independent public venues for non-MT5 sources."
            )
            return {**base, "status": "NOT_READY", "action": "WAIT", "candidate_action": "WAIT",
                    "reason": reason}

        indicator_data = indicators if isinstance(indicators, dict) else IndicatorsEngine().analyze(chart.get("candle_history") or {})
        timeframe_data = indicator_data.get("timeframes") or {}
        indicator_values = indicator_data.get("values") or {}
        if indicator_data.get("status") != "READY":
            return {**base, "status": "NOT_READY", "action": "WAIT", "candidate_action": "WAIT",
                    "timeframes": timeframe_data, "indicators": indicator_values,
                    "engine_3_indicator_status": indicator_data.get("status", "NOT_READY"),
                    "reason": indicator_data.get("reason") or "Engine 3 indicators are not ready."}

        # Engine 4 accepts only the explicit Engine 3 contract produced from
        # Engine 2's validated closed-candle history. A READY label alone is
        # insufficient: reject missing provenance, timestamps, or bad values.
        if (
            indicator_data.get("engine") != "engine_3_indicators"
            or indicator_data.get("source") != "engine_2_chart_candles"
        ):
            return {**base, "status": "NOT_READY", "action": "WAIT", "candidate_action": "WAIT",
                    "timeframes": timeframe_data, "indicators": indicator_values,
                    "engine_3_indicator_status": "INVALID_PROVENANCE",
                    "reason": "Engine 3 provenance must identify indicators calculated from Engine 2 candle history."}

        required_indicator_values = ("ema20_1m", "ema50_1m", "rsi14_1m", "atr14_1m", "atr14_5m")
        try:
            normalized_values = {name: float(indicator_values[name]) for name in required_indicator_values}
            trend_score = float(indicator_data["trend_score"])
            last_closed_candle_time_ms = int(indicator_data["last_closed_candle_time_ms"])
        except (KeyError, TypeError, ValueError, OverflowError):
            normalized_values = {}
            trend_score = float("nan")
            last_closed_candle_time_ms = 0
        if (
            len(normalized_values) != len(required_indicator_values)
            or any(not math.isfinite(value) for value in normalized_values.values())
            or not math.isfinite(trend_score) or not -1.0 <= trend_score <= 1.0
            or last_closed_candle_time_ms <= 0
            or not 0.0 <= normalized_values.get("rsi14_1m", -1.0) <= 100.0
            or normalized_values.get("atr14_1m", 0.0) <= 0.0
            or normalized_values.get("atr14_5m", 0.0) <= 0.0
        ):
            return {**base, "status": "NOT_READY", "action": "WAIT", "candidate_action": "WAIT",
                    "timeframes": timeframe_data, "indicators": indicator_values,
                    "engine_3_indicator_status": "INVALID_INDICATOR_PAYLOAD",
                    "reason": "Engine 3 required values, normalized trend score, or last closed-candle timestamp are missing or invalid."}

        fast = normalized_values["ema20_1m"]
        slow = normalized_values["ema50_1m"]
        rsi = normalized_values["rsi14_1m"]
        atr1 = normalized_values["atr14_1m"]
        atr5 = normalized_values["atr14_5m"]
        market_context = market.get("market_context") if isinstance(market.get("market_context"), dict) else {}
        microstructure = market_context.get("microstructure") if isinstance(market_context.get("microstructure"), dict) else {}
        orderflow = {"status": "NOT_PROVIDED", "reason": "Engine 1 quote updates are not treated as executed trade flow or taker volume."}
        chart_eligible = bool(chart.get("decision_eligible")) and chart.get("status") == "READY"
        visual_bias = chart.get("visual_bias", "NEUTRAL")
        try:
            chart_score = float(chart.get("analysis_score", 0.0))
            chart_confidence = float(chart.get("analysis_confidence", 0.0))
        except (TypeError, ValueError, OverflowError):
            chart_score = chart_confidence = 0.0
        if not math.isfinite(chart_score) or not math.isfinite(chart_confidence):
            chart_score = chart_confidence = 0.0
        chart_score = max(-1.0, min(1.0, chart_score))
        chart_confidence = max(0.0, min(1.0, chart_confidence))
        market_score, market_score_parts = _market_confirmation_score(trend_score, market)
        combined_score = _weighted_direction_score(chart_score, market_score)

        candidate = "WAIT"
        chart_quality_ok = chart_eligible and chart_confidence >= MIN_CHART_CONFIDENCE
        if chart_quality_ok:
            if (
                chart_score >= MIN_CHART_SCORE
                and combined_score >= DIRECTIONAL_SCORE_THRESHOLD
                and visual_bias == "BULLISH"
            ):
                candidate = "BUY"
            elif (
                chart_score <= -MIN_CHART_SCORE
                and combined_score <= -DIRECTIONAL_SCORE_THRESHOLD
                and visual_bias == "BEARISH"
            ):
                candidate = "SELL"

        # Native OHLC price action is not a separate directional vote. It is a
        # fail-closed confluence gate: when runtime supplies it, Engine 4 only
        # keeps a visual BUY/SELL candidate if the independently analysed
        # closed-candle structure is READY and aligned in the same direction.
        native_pa_gate = "NOT_PROVIDED"
        native_pa_allows_candidate = True
        if engine2_price_action is not None:
            native_pa_status = str(price_action.get("status", "NOT_READY"))
            native_pa_direction = str(price_action.get("direction", "UNKNOWN"))
            native_pa_alignment = str(price_action_summary.get("timeframe_alignment", "NOT_AVAILABLE"))
            candle_pattern_alignment = str(
                price_action_summary.get(
                    "latest_candle_pattern_alignment", "NO_DIRECTIONAL_CANDLE_PATTERN"
                )
            )
            if native_pa_status != "READY":
                native_pa_gate = "NOT_READY"
                native_pa_allows_candidate = False
            elif (
                native_pa_direction == "BULLISH"
                and native_pa_alignment == "BULLISH_STRUCTURE_CONFLUENCE"
            ):
                native_pa_gate = "BULLISH_CONFLUENCE"
            elif (
                native_pa_direction == "BEARISH"
                and native_pa_alignment == "BEARISH_STRUCTURE_CONFLUENCE"
            ):
                native_pa_gate = "BEARISH_CONFLUENCE"
            else:
                native_pa_gate = "MIXED_OR_NO_CONFLUENCE"
                native_pa_allows_candidate = False

            # Directional candle patterns are a veto-only confirmation layer:
            # mixed or opposite latest-pattern evidence cannot overturn the
            # multi-timeframe OHLC structure or become a standalone vote.
            if native_pa_allows_candidate:
                if candle_pattern_alignment == "MIXED_CANDLE_PATTERN_EVIDENCE":
                    native_pa_gate = "MIXED_CANDLE_PATTERN_EVIDENCE"
                    native_pa_allows_candidate = False
                elif (
                    native_pa_direction == "BULLISH"
                    and candle_pattern_alignment == "BEARISH_CANDLE_PATTERN_EVIDENCE"
                ) or (
                    native_pa_direction == "BEARISH"
                    and candle_pattern_alignment == "BULLISH_CANDLE_PATTERN_EVIDENCE"
                ):
                    native_pa_gate = "CANDLE_PATTERN_DIRECTION_CONFLICT"
                    native_pa_allows_candidate = False

            if candidate in {"BUY", "SELL"}:
                expected_native_direction = "BULLISH" if candidate == "BUY" else "BEARISH"
                if not native_pa_allows_candidate or native_pa_direction != expected_native_direction:
                    native_pa_gate = (
                        "DIRECTION_CONFLICT"
                        if native_pa_status == "READY" and native_pa_allows_candidate
                        else native_pa_gate
                    )
                    candidate = "WAIT"
            price_action_context["gate"] = native_pa_gate

        aligned_signal = candidate
        chart_gate = "NOT_CALIBRATED"
        if not chart_eligible:
            aligned_signal = "WAIT"
            chart_gate = "WAITING_FOR_ENGINE_2_CALIBRATION"
        elif chart_confidence < MIN_CHART_CONFIDENCE:
            aligned_signal = "WAIT"
            chart_gate = "INSUFFICIENT_ANALYSIS_CONFIDENCE"
        elif candidate == "WAIT" and native_pa_gate in {
            "MIXED_CANDLE_PATTERN_EVIDENCE", "CANDLE_PATTERN_DIRECTION_CONFLICT"
        }:
            chart_gate = "WAITING_FOR_ENGINE_2_CANDLE_PATTERN_CONFLUENCE"
        elif candidate == "WAIT" and native_pa_gate not in {
            "NOT_PROVIDED", "BULLISH_CONFLUENCE", "BEARISH_CONFLUENCE"
        }:
            chart_gate = "WAITING_FOR_ENGINE_2_PRICE_ACTION_CONFLUENCE"
        elif candidate == "WAIT":
            chart_gate = "80_20_SCORE_BELOW_THRESHOLD_OR_CONFLICT"
        else:
            chart_gate = "80_20_ANALYSIS_CONFIRMED"

        market_entry = float(market["price"])
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
            broker_mid = (bid + ask) / 2.0
            price_divergence = abs(broker_mid - market_entry) / market_entry if market_entry > 0 else float("inf")
            spread_pct = (ask - bid) / broker_mid if broker_mid > 0 else float("inf")
            quote_ok = (
                bridge.get("status") == "CONNECTED"
                and str(bridge.get("market_symbol", "")).upper() == market_symbol.upper()
                and bool(broker_symbol) and 0 < bid <= ask
                and math.isfinite(bid) and math.isfinite(ask)
                and math.isfinite(quote_age) and math.isfinite(tick_age)
                and 0 <= quote_age <= MT5_QUOTE_MAX_AGE_SECONDS
                and 0 <= tick_age <= MT5_QUOTE_MAX_AGE_SECONDS
                and math.isfinite(price_divergence)
                and price_divergence <= MT5_MARKET_DIVERGENCE_MAX_PCT
                and math.isfinite(spread_pct)
                and spread_pct <= MT5_MAX_SPREAD_PCT
            )
        except (TypeError, ValueError, OverflowError):
            quote_ok = False
            bid = ask = 0.0
            price_divergence = spread_pct = None

        # Protect existing positions before evaluating any new entry. This
        # path needs a fresh broker quote and Engine 3 closed-candle ATR, but
        # deliberately does not wait for Engine 2 visual chart calibration.
        positions = _matching_positions(bridge, broker_symbol)
        if quote_ok and positions:
            try:
                management_tick_size = float(specs.get("tick_size", 0) or 0)
                management_point = float(specs.get("point", management_tick_size) or management_tick_size)
                management_digits = int(specs.get("digits", 2) or 2)
                management_stops = int(specs.get("stops_level_points", 0) or 0)
                management_freeze = int(specs.get("freeze_level_points", 0) or 0)
                management_plan = plan_atr_stop_update(
                    positions, broker_symbol=broker_symbol, bid=bid, ask=ask, atr=atr5,
                    tick_size=management_tick_size, point=management_point,
                    digits=management_digits, stops_level_points=management_stops,
                    freeze_level_points=management_freeze,
                )
            except (TypeError, ValueError, OverflowError):
                management_plan = {"status": "NOT_REQUIRED", "reason": "Broker management inputs are invalid."}
            if management_plan.get("status") == "READY":
                managed_ticket = int(management_plan["ticket"])
                managed_sl = float(management_plan["stop_loss"])
                managed_tp = float(management_plan["take_profit"])
                management_id = _signal_id(
                    "MODIFY", market_symbol, managed_ticket,
                    round(managed_sl, management_digits), round(managed_tp, management_digits),
                )
                return {
                    **base, "status": "READY", "action": "MODIFY",
                    "candidate_action": "WAIT", "aligned_signal": "WAIT",
                    "signal_id": management_id, "command_ready": True,
                    "position_ticket": managed_ticket,
                    "chart_gate": "POSITION_MANAGEMENT_PRIORITY",
                    "chart_visual_bias": visual_bias,
                    "open_block_reason": "New entries are deferred while a protective stop update is pending.",
                    "as_of_ms": market.get("captured_at_ms"),
                    "market_symbol": market_symbol, "symbol": broker_symbol,
                    "market_price_reference": market.get("price"),
                    "broker_quote": quote,
                    "broker_market_price_divergence_pct": round(price_divergence * 100, 4),
                    "broker_spread_pct": round(spread_pct * 100, 4),
                    "entry_reference": 0.0, "stop_loss": managed_sl, "take_profit": managed_tp,
                    "trend_score": round(trend_score, 4), "timeframes": timeframe_data,
                    "decision_scores": {
                        "chart_score": round(chart_score, 4),
                        "chart_confidence": round(chart_confidence, 4),
                        "market_score": round(market_score, 4),
                        "market_components": market_score_parts,
                        "combined_score": round(combined_score, 4),
                        "threshold": DIRECTIONAL_SCORE_THRESHOLD,
                    },
                    "indicators": indicator_values,
                    "engine_3_indicator_status": indicator_data.get("status"),
                    "risk_plan": {
                        "status": "READY", "volume": float(management_plan["volume"]),
                        "purpose": "protective_stop_update",
                    },
                    "position_management": {
                        "action": "MODIFY", "ticket": managed_ticket,
                        "stage": management_plan.get("management_stage"),
                        "protective_stop_only": True,
                    },
                    "management_plan": management_plan,
                    "engine_inputs": {
                        "market_context_from_engine_1": market.get("status"),
                        "chart_and_candles_from_engine_2": chart.get("status", "NOT_READY"),
                        "indicators_from_engine_3": indicator_data.get("status"),
                        "engine_5_bridge_for_quote_account_specs_and_transport": bridge.get("status"),
                        "protective_management_does_not_require_visual_chart": True,
                    },
                    "reason": management_plan.get("reason"),
                }

        entry = ask if aligned_signal == "BUY" and quote_ok else (
            bid if aligned_signal == "SELL" and quote_ok else float(market["price"])
        )
        stop_loss = take_profit = None
        tick_size = float(specs.get("tick_size", 0) or 0)
        point = float(specs.get("point", tick_size) or tick_size)
        digits = int(specs.get("digits", 2) or 2)
        stops_level_points = int(specs.get("stops_level_points", 0) or 0)
        minimum_stop_gap = max(0, stops_level_points) * point + tick_size if tick_size > 0 else 0.0
        if aligned_signal in {"BUY", "SELL"} and quote_ok and tick_size > 0:
            entry = _price_to_tick(entry, tick_size, digits, "NEAREST")
            stop_gap = max(1.5 * atr5, minimum_stop_gap)
            target_gap = max(3.0 * atr5, minimum_stop_gap)
            if aligned_signal == "BUY":
                stop_loss = _price_to_tick(entry - stop_gap, tick_size, digits, "DOWN")
                take_profit = _price_to_tick(entry + target_gap, tick_size, digits, "UP")
            else:
                stop_loss = _price_to_tick(entry + stop_gap, tick_size, digits, "UP")
                take_profit = _price_to_tick(entry - target_gap, tick_size, digits, "DOWN")
        elif aligned_signal == "BUY":
            stop_loss, take_profit = entry - 1.5 * atr5, entry + 3.0 * atr5
        elif aligned_signal == "SELL":
            stop_loss, take_profit = entry + 1.5 * atr5, entry - 3.0 * atr5

        signal_id = _signal_id(
            market_symbol, aligned_signal,
            last_closed_candle_time_ms or 0,
            chart.get("image", ""),
        ) if aligned_signal in {"BUY", "SELL"} else None

        size: dict[str, Any] = {
            "status": "WAITING_FOR_ENGINE_5_QUOTE",
            "reason": "Engine 5 must provide a fresh mapped MT5 quote and live account/symbol specifications.",
        }
        if aligned_signal in {"BUY", "SELL"}:
            spec_fields = ("tick_size", "tick_value_loss", "volume_min", "volume_step", "volume_max")
            if not quote_ok:
                size = {"status": "BLOCKED",
                        "reason": "No fresh MT5 quote or broker symbol mapping does not match the market instrument."}
            elif "equity" not in account or not all(key in specs for key in spec_fields):
                size = {"status": "UNAVAILABLE",
                        "reason": "Engine 5 account equity or loss/volume specifications are incomplete."}
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
                                       last_closed_candle_time_ms or 0,
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
            "broker_market_price_divergence_pct": round(price_divergence * 100, 4) if price_divergence is not None else None,
            "broker_spread_pct": round(spread_pct * 100, 4) if spread_pct is not None else None,
            "entry_reference": entry if action in {"BUY", "SELL"} else 0.0,
            "stop_loss": stop_loss if action in {"BUY", "SELL"} else 0.0,
            "take_profit": take_profit if action in {"BUY", "SELL"} else 0.0,
            "trend_score": round(trend_score, 4), "timeframes": timeframe_data,
            "decision_weights": {
                "engine_2_chart": CHART_DECISION_WEIGHT,
                "engine_3_indicators": round(MARKET_CONFIRMATION_WEIGHT * 0.80, 4),
                "engine_1_market_quote_pulse": round(MARKET_CONFIRMATION_WEIGHT * 0.20, 4),
            },
            "decision_scores": {
                "chart_score": round(chart_score, 4),
                "chart_confidence": round(chart_confidence, 4),
                "market_score": round(market_score, 4),
                "market_components": market_score_parts,
                "combined_score": round(combined_score, 4),
                "threshold": DIRECTIONAL_SCORE_THRESHOLD,
            },
            "indicators": indicator_values,
            "engine_3_indicator_status": indicator_data.get("status"),
            "orderflow": orderflow,
            "market_microstructure": microstructure,
            "economic_calendar": market_context.get("economic_calendar", {"status": "NOT_AVAILABLE", "events": []}),
            "risk_plan": size,
            "position_management": {
                "matching_positions": len(positions),
                "opposite_positions": sum(1 for p in positions if aligned_signal in {"BUY", "SELL"} and p["side"] != aligned_signal),
                "action": action,
                "close_ticket": close_ticket,
            },
            "engine_inputs": {
                "market_context_from_engine_1": market.get("status"),
                "chart_and_candles_from_engine_2": "READY" if chart_eligible else chart.get("status", "NOT_READY"),
                "indicators_from_engine_3": indicator_data.get("status"),
                "engine_5_bridge_for_quote_account_specs_and_transport": bridge.get("status", "NOT_CONFIGURED"),
                "broker_market_price_divergence_pct": round(price_divergence * 100, 4) if price_divergence is not None else None,
                "broker_spread_pct": round(spread_pct * 100, 4) if spread_pct is not None else None,
            },
            "reason": (
                "BUY/SELL combines Engine 2 calibrated chart analysis, Engine 3 indicators calculated from Engine 2 candle history, and Engine 1 quote-update context. "
                "Engine 1 does not read or analyze candles; quote updates are not represented as executed trade flow. Engine 5 supplies execution and account facts only."
            ),
        }
