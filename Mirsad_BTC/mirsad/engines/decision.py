from __future__ import annotations

import hashlib
import math
import time
from typing import Any

from ..config import (RISK_PER_TRADE, MT5_QUOTE_MAX_AGE_SECONDS, MT5_MARKET_DIVERGENCE_MAX_PCT, MT5_MAX_SPREAD_PCT, MT5_MARKET_DATA_MAX_AGE_SECONDS)

from .indicators import (
    IndicatorsEngine, TIMEFRAME_WEIGHTS, MIN_INDICATOR_SIGNAL_QUALITY,
    _ema, _rsi, _atr, _timeframe_trend,
)
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


def _protective_position_management_decision(
    bridge: dict[str, Any],
    indicator_data: dict[str, Any],
    market: dict[str, Any],
) -> dict[str, Any] | None:
    """Build one protective MODIFY command from Engine 3 ATR and fresh Engine 5 facts.

    This safety path is deliberately independent of Engine 1's standalone public
    intelligence report and Engine 2's visual image eligibility. It cannot create
    BUY/SELL commands; it only tightens the stop of an existing Mirsad-owned
    position using the broker's own fresh quote.
    """
    if bridge.get("status") != "CONNECTED":
        return None
    if (
        indicator_data.get("status") != "READY"
        or indicator_data.get("engine") != "engine_3_indicators"
        or indicator_data.get("source") != "engine_2_chart_candles"
    ):
        return None

    values = indicator_data.get("values")
    if not isinstance(values, dict):
        return None
    try:
        atr5 = float(values["atr14_5m"])
        closed_at = int(indicator_data["last_closed_candle_time_ms"])
        capture_at = int(indicator_data["source_capture_at_ms"])
        capture_age = (time.time() * 1000.0 - capture_at) / 1000.0
    except (KeyError, TypeError, ValueError, OverflowError):
        return None
    if (
        not math.isfinite(atr5) or atr5 <= 0
        or closed_at <= 0
        or not math.isfinite(capture_age)
        or capture_age < 0
        or capture_age > MT5_MARKET_DATA_MAX_AGE_SECONDS
    ):
        return None

    broker_symbol = str(bridge.get("symbol", "")).strip()
    market_symbol = str(bridge.get("market_symbol", "")).strip()
    if not broker_symbol or not market_symbol:
        return None

    quote = bridge.get("quote") if isinstance(bridge.get("quote"), dict) else {}
    specs = bridge.get("symbol_spec") if isinstance(bridge.get("symbol_spec"), dict) else {}
    try:
        bid = float(quote["bid"])
        ask = float(quote["ask"])
        quote_age = float(bridge["quote_age_seconds"])
        tick_age = float(quote["tick_age_seconds"])
        midpoint = (bid + ask) / 2.0
        spread_pct = (ask - bid) / midpoint if midpoint > 0 else float("inf")
    except (KeyError, TypeError, ValueError, OverflowError):
        return None
    if (
        not all(math.isfinite(value) for value in (bid, ask, quote_age, tick_age, spread_pct))
        or bid <= 0 or ask < bid
        or quote_age < 0 or quote_age > MT5_QUOTE_MAX_AGE_SECONDS
        or tick_age < 0 or tick_age > MT5_QUOTE_MAX_AGE_SECONDS
        or midpoint <= 0
        or spread_pct > MT5_MAX_SPREAD_PCT
    ):
        return None

    positions = _matching_positions(bridge, broker_symbol)
    if not positions:
        return None
    try:
        tick_size = float(specs.get("tick_size", 0) or 0)
        point = float(specs.get("point", tick_size) or tick_size)
        digits = int(specs.get("digits", 2) or 2)
        stops_level = int(specs.get("stops_level_points", 0) or 0)
        freeze_level = int(specs.get("freeze_level_points", 0) or 0)
        plan = plan_atr_stop_update(
            positions,
            broker_symbol=broker_symbol,
            bid=bid,
            ask=ask,
            atr=atr5,
            tick_size=tick_size,
            point=point,
            digits=digits,
            stops_level_points=stops_level,
            freeze_level_points=freeze_level,
        )
    except (TypeError, ValueError, OverflowError):
        return None
    if plan.get("status") != "READY":
        return None

    ticket = int(plan["ticket"])
    stop_loss = float(plan["stop_loss"])
    take_profit = float(plan["take_profit"])
    command_id = _signal_id(
        "MODIFY", market_symbol, ticket,
        round(stop_loss, digits), round(take_profit, digits),
    )
    return {
        "status": "READY",
        "action": "MODIFY",
        "candidate_action": "WAIT",
        "aligned_signal": "WAIT",
        "signal_id": command_id,
        "command_ready": True,
        "position_ticket": ticket,
        "symbol": broker_symbol,
        "market_symbol": market_symbol,
        "entry_reference": 0.0,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "chart_gate": "POSITION_MANAGEMENT_PRIORITY",
        "open_block_reason": "New entries are deferred while a protective stop update is pending.",
        "risk_plan": {
            "status": "READY",
            "volume": float(plan["volume"]),
            "purpose": "protective_stop_update",
        },
        "position_management": {
            "action": "MODIFY",
            "ticket": ticket,
            "stage": plan.get("management_stage"),
            "protective_stop_only": True,
            "market_feed_independent": True,
        },
        "management_plan": plan,
        "broker_quote": quote,
        "broker_spread_pct": round(spread_pct * 100.0, 4),
        "engine_inputs": {
            "engine_5_execution_quote_feed": market.get("status", "UNAVAILABLE"),
            "engine_1_intelligence_required_for_protective_management": False,
            "engine_2_chart": "NOT_REQUIRED_FOR_PROTECTIVE_MANAGEMENT",
            "engine_3_indicators": "READY",
            "engine_5_bridge": "CONNECTED",
            "protective_management_quote_source": "MT5_BROKER_BID_ASK",
        },
        "reason": plan.get("reason"),
    }

# Engine 4's fixed baseline decision mix. Evidence quality may reduce a
# component's effective contribution; the remaining valid weights are
# re-normalized to 100% rather than silently filling missing evidence with zero.
ENGINE1_DECISION_WEIGHT = 0.20
ENGINE2_DECISION_WEIGHT = 0.50
ENGINE3_DECISION_WEIGHT = 0.30

# Engine 2 owns both native OHLC price structure and calibrated image analysis.
# Native OHLC is the primary sub-input; image analysis is supporting evidence.
ENGINE2_NATIVE_OHLC_WEIGHT = 0.70
ENGINE2_VISUAL_WEIGHT = 0.30

DIRECTIONAL_SCORE_THRESHOLD = 0.40
MIN_ENGINE2_DIRECTION_SCORE = 0.20
MIN_ENGINE2_TIMEFRAME_COVERAGE = 0.65
MIN_ENGINE2_DIRECTIONAL_AGREEMENT = 0.60
MIN_CHART_CONFIDENCE = 0.55


def _market_intelligence_signal(intelligence: dict[str, Any] | None) -> tuple[float | None, float, dict[str, Any]]:
    """Accept only Engine 1's independent report; do not blend broker quote telemetry."""
    intelligence = intelligence if isinstance(intelligence, dict) else {}
    score = _finite_intelligence_score(intelligence)
    confidence = _finite_value(intelligence.get("confidence"))
    coverage = _finite_value(intelligence.get("evidence_coverage"))
    # A rejected/missing score must contribute zero weight, even when its
    # raw metadata contains a nonzero confidence or evidence-coverage value.
    quality = (
        min(confidence, coverage)
        if score is not None and confidence is not None and coverage is not None
        else 0.0
    )
    quality = max(0.0, min(1.0, quality))
    return score, quality, {
        "score": round(score, 4) if score is not None else None,
        "quality": round(quality, 4),
        "source": "ENGINE1_STANDALONE_REPORT" if score is not None else "UNAVAILABLE",
        "intelligence_status": intelligence.get("status", "NOT_AVAILABLE"),
        "intelligence_confidence": confidence,
        "evidence_coverage": coverage,
        "only_engine1_report_used": True,
    }


def _weighted_three_engine_score(
    *,
    engine1_score: float | None,
    engine2_score: float | None,
    engine3_score: float | None,
    engine1_quality: float,
    engine2_quality: float,
    engine3_quality: float,
) -> tuple[float | None, dict[str, float]]:
    """Quality-adjust the 20/50/30 baseline and normalize the active weights."""
    configured = {
        "engine_1_market_intelligence": ENGINE1_DECISION_WEIGHT,
        "engine_2_price_action": ENGINE2_DECISION_WEIGHT,
        "engine_3_indicators": ENGINE3_DECISION_WEIGHT,
    }
    supplied = {
        "engine_1_market_intelligence": (engine1_score, engine1_quality),
        "engine_2_price_action": (engine2_score, engine2_quality),
        "engine_3_indicators": (engine3_score, engine3_quality),
    }
    effective: dict[str, float] = {}
    valid_scores: dict[str, float] = {}
    for name, (raw_score, raw_quality) in supplied.items():
        score = _finite_value(raw_score)
        quality = _finite_value(raw_quality)
        quality = max(0.0, min(1.0, quality if quality is not None else 0.0))
        if score is None or not -1.0 <= score <= 1.0 or quality <= 0.0:
            effective[name] = 0.0
            continue
        valid_scores[name] = score
        effective[name] = configured[name] * quality

    total = sum(effective.values())
    if total <= 0.0:
        return None, {name: 0.0 for name in configured}
    normalized = {name: value / total for name, value in effective.items()}
    combined = sum(valid_scores[name] * normalized[name] for name in valid_scores)
    return max(-1.0, min(1.0, combined)), {
        name: round(weight, 8) for name, weight in normalized.items()
    }


def _finite_intelligence_score(intelligence: dict[str, Any]) -> float | None:
    status = str(intelligence.get("status", "")).upper()
    confidence = _finite_value(intelligence.get("confidence"))
    score = _finite_value(intelligence.get("directional_score"))
    if status not in {"READY", "PARTIAL"} or score is None or confidence is None:
        return None
    coverage = _finite_value(intelligence.get("evidence_coverage"))
    if (
        not 0.0 <= confidence <= 1.0 or confidence < 0.25
        or coverage is None or not 0.55 <= coverage <= 1.0
        or not -1.0 <= score <= 1.0
    ):
        return None
    return score


def _finite_value(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None


class DecisionEngine:
    """Engine 4. Combines Engine 1 market context, Engine 2 chart/candles and Engine 3 indicators.
    Engine 5 supplies execution/account facts and transports MIR1 commands.
    """

    def analyze(
        self, market: dict[str, Any], chart: dict[str, Any] | None,
        bridge: dict[str, Any] | None, indicators: dict[str, Any] | None = None,
        engine2_price_action: dict[str, Any] | None = None,
        market_intelligence: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        base = {
            "engine": "engine_4_decision_trade_monitor", "method": "rules_only",
            "direction_inputs": ["engine_1_market_intelligence", "engine_2_price_action_and_calibrated_visual", "engine_3_indicators"],
            "calculation_inputs": ["engine_1_market_intelligence", "engine_2_native_ohlc_price_action", "engine_3_indicators"],
            "engine_1_input_contract": "standalone report only; no Engine 2, 3 or 5 data is blended into Engine 1",
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
            "role": "PRIMARY_ENGINE_2_DIRECTIONAL_INPUT_WITH_OPTIONAL_CALIBRATED_VISUAL_CONFIRMATION",
        }
        base["engine_2_native_price_action_context"] = price_action_context
        indicator_data = indicators if isinstance(indicators, dict) else IndicatorsEngine().analyze(
            chart.get("candle_history") or {}
        )
        protective_decision = _protective_position_management_decision(
            bridge, indicator_data, market if isinstance(market, dict) else {}
        )
        if protective_decision is not None:
            return {**base, **protective_decision}

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
                "Engine 5 MT5 broker quote feed is missing, stale, or failed its terminal/quote checks."
                if mt5_native_source
                else "Engine 5 broker quote checks require a live MT5 feed; Engine 4 also requires at least two independent public venues for non-MT5 price sources."
            )
            return {**base, "status": "NOT_READY", "action": "WAIT", "candidate_action": "WAIT",
                    "reason": reason}

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
            signal_score = float(indicator_data["signal_score"])
            signal_quality = float(indicator_data["signal_quality"])
            last_closed_candle_time_ms = int(indicator_data["last_closed_candle_time_ms"])
        except (KeyError, TypeError, ValueError, OverflowError):
            normalized_values = {}
            trend_score = float("nan")
            signal_score = float("nan")
            signal_quality = 0.0
            last_closed_candle_time_ms = 0
        if (
            len(normalized_values) != len(required_indicator_values)
            or any(not math.isfinite(value) for value in normalized_values.values())
            or not math.isfinite(trend_score) or not -1.0 <= trend_score <= 1.0
            or not math.isfinite(signal_score) or not -1.0 <= signal_score <= 1.0
            or not math.isfinite(signal_quality)
            or not MIN_INDICATOR_SIGNAL_QUALITY <= signal_quality <= 1.0
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
        orderflow = {"status": "NOT_PROVIDED", "reason": "Engine 5 Bid/Ask quote updates are not executed trades, taker flow or consolidated order-book volume."}

        chart_eligible = bool(chart.get("decision_eligible")) and chart.get("status") == "READY"
        visual_bias = str(chart.get("visual_bias", "NEUTRAL")).upper()
        try:
            chart_score = float(chart.get("analysis_score", 0.0))
            chart_confidence = float(chart.get("analysis_confidence", 0.0))
        except (TypeError, ValueError, OverflowError):
            chart_score = chart_confidence = 0.0
        if not math.isfinite(chart_score) or not math.isfinite(chart_confidence):
            chart_score = chart_confidence = 0.0
        chart_score = max(-1.0, min(1.0, chart_score))
        chart_confidence = max(0.0, min(1.0, chart_confidence))
        visual_evidence_usable = chart_eligible and chart_confidence >= MIN_CHART_CONFIDENCE

        # Engine 1 contributes only its standalone public-intelligence report.
        # Engine 5 quote telemetry is checked separately for price/execution safety
        # and is never blended into the Engine 1 directional score.
        intelligence = market_intelligence if isinstance(market_intelligence, dict) else {}
        engine1_score, engine1_quality, engine1_parts = _market_intelligence_signal(intelligence)
        market_score = engine1_score
        market_score_parts = engine1_parts

        # Engine 2: native multi-timeframe OHLC structure is the primary vote.
        # A calibrated image contributes only as supporting evidence; an
        # uncalibrated/mismatched image is omitted, never used as a fake score.
        native_pa_gate = "NOT_PROVIDED"
        native_pa_allows_candidate = True
        engine2_direction = "UNKNOWN"
        engine2_structure_score = None
        engine2_visual_used = False
        engine2_visual_weight = 0.0
        engine2_score = None
        engine2_quality = 0.0
        engine2_decision_eligible = False
        engine2_source = "NOT_READY"
        if engine2_price_action is not None:
            native_pa_status = str(price_action.get("status", "NOT_READY")).upper()
            native_pa_direction = str(price_action.get("direction", "UNKNOWN")).upper()
            native_pa_alignment = str(price_action_summary.get("timeframe_alignment", "NOT_AVAILABLE")).upper()
            engine2_structure_score = _finite_value(price_action.get("structure_score"))
            timeframe_coverage = _finite_value(price_action_summary.get("timeframe_weight_coverage"))
            directional_agreement = _finite_value(price_action_summary.get("directional_structure_agreement"))
            if (
                native_pa_status == "READY"
                and native_pa_direction == "BULLISH"
                and native_pa_alignment == "BULLISH_STRUCTURE_CONFLUENCE"
            ):
                native_pa_gate = "BULLISH_CONFLUENCE"
            elif (
                native_pa_status == "READY"
                and native_pa_direction == "BEARISH"
                and native_pa_alignment == "BEARISH_STRUCTURE_CONFLUENCE"
            ):
                native_pa_gate = "BEARISH_CONFLUENCE"
            elif native_pa_status != "READY":
                native_pa_gate = "NOT_READY"
                native_pa_allows_candidate = False
            else:
                native_pa_gate = "MIXED_OR_NO_CONFLUENCE"
                native_pa_allows_candidate = False

            candle_pattern_alignment = str(
                price_action_summary.get(
                    "latest_candle_pattern_alignment", "NO_DIRECTIONAL_CANDLE_PATTERN"
                )
            ).upper()
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

            structure_valid = (
                engine2_structure_score is not None
                and -1.0 <= engine2_structure_score <= 1.0
                and timeframe_coverage is not None
                and MIN_ENGINE2_TIMEFRAME_COVERAGE <= timeframe_coverage <= 1.0
                and directional_agreement is not None
                and MIN_ENGINE2_DIRECTIONAL_AGREEMENT <= directional_agreement <= 1.0
                and (
                    (native_pa_direction == "BULLISH" and engine2_structure_score >= MIN_ENGINE2_DIRECTION_SCORE)
                    or (native_pa_direction == "BEARISH" and engine2_structure_score <= -MIN_ENGINE2_DIRECTION_SCORE)
                )
            )
            engine2_decision_eligible = bool(
                native_pa_status == "READY"
                and native_pa_allows_candidate
                and structure_valid
            )
            if engine2_decision_eligible:
                engine2_direction = native_pa_direction
                engine2_visual_used = visual_evidence_usable
                if engine2_visual_used:
                    engine2_visual_weight = ENGINE2_VISUAL_WEIGHT
                    engine2_score = (
                        ENGINE2_NATIVE_OHLC_WEIGHT * float(engine2_structure_score)
                        + ENGINE2_VISUAL_WEIGHT * chart_score
                    )
                    engine2_quality = (
                        ENGINE2_NATIVE_OHLC_WEIGHT * min(float(timeframe_coverage), float(directional_agreement))
                        + ENGINE2_VISUAL_WEIGHT * chart_confidence
                    )
                    engine2_source = "NATIVE_OHLC_PLUS_CALIBRATED_VISUAL"
                else:
                    engine2_score = float(engine2_structure_score)
                    engine2_quality = min(float(timeframe_coverage), float(directional_agreement))
                    engine2_source = "NATIVE_OHLC_ONLY_VISUAL_NOT_ELIGIBLE"
            price_action_context["decision_eligible"] = engine2_decision_eligible
            price_action_context["gate"] = native_pa_gate
            price_action_context["timeframe_weight_coverage"] = timeframe_coverage
            price_action_context["directional_structure_agreement"] = directional_agreement
            price_action_context["visual_evidence_used"] = engine2_visual_used
            price_action_context["visual_evidence_weight_inside_engine_2"] = engine2_visual_weight
        else:
            # Backwards-compatible isolated visual contract for callers that do
            # not yet provide the native Engine 2 price-action report. Runtime
            # always supplies the native report and therefore never takes this
            # fallback in normal operation.
            engine2_direction = (
                "BULLISH" if visual_bias == "BULLISH"
                else "BEARISH" if visual_bias == "BEARISH"
                else "UNKNOWN"
            )
            engine2_decision_eligible = bool(visual_evidence_usable and engine2_direction != "UNKNOWN")
            if engine2_decision_eligible:
                engine2_score = chart_score
                engine2_quality = chart_confidence
                engine2_source = "CALIBRATED_VISUAL_ONLY_COMPATIBILITY"
            price_action_context["gate"] = "NOT_PROVIDED_VISUAL_COMPATIBILITY"

        engine2_score = (
            max(-1.0, min(1.0, float(engine2_score)))
            if engine2_score is not None and math.isfinite(float(engine2_score))
            else None
        )
        engine3_score = signal_score
        engine3_quality = signal_quality
        weighted_score, effective_weights = _weighted_three_engine_score(
            engine1_score=engine1_score,
            engine2_score=engine2_score,
            engine3_score=engine3_score,
            engine1_quality=engine1_quality,
            engine2_quality=engine2_quality,
            engine3_quality=engine3_quality,
        )
        # A composite directional score is not actionable without a valid
        # Engine 2 multi-timeframe directional structure.
        combined_score = weighted_score if engine2_decision_eligible else None

        candidate = "WAIT"
        if (
            engine2_decision_eligible
            and engine2_direction == "BULLISH"
            and engine2_score is not None
            and engine2_score >= MIN_ENGINE2_DIRECTION_SCORE
            and combined_score is not None
            and combined_score >= DIRECTIONAL_SCORE_THRESHOLD
        ):
            candidate = "BUY"
        elif (
            engine2_decision_eligible
            and engine2_direction == "BEARISH"
            and engine2_score is not None
            and engine2_score <= -MIN_ENGINE2_DIRECTION_SCORE
            and combined_score is not None
            and combined_score <= -DIRECTIONAL_SCORE_THRESHOLD
        ):
            candidate = "SELL"

        aligned_signal = candidate
        if native_pa_gate in {"CANDLE_PATTERN_DIRECTION_CONFLICT", "MIXED_CANDLE_PATTERN_EVIDENCE"}:
            chart_gate = "WAITING_FOR_ENGINE_2_CANDLE_PATTERN_CONFLUENCE"
        elif engine2_price_action is not None and not engine2_decision_eligible:
            chart_gate = "WAITING_FOR_ENGINE_2_PRICE_ACTION_CONFLUENCE"
        elif engine2_price_action is None and not engine2_decision_eligible:
            chart_gate = (
                "WAITING_FOR_ENGINE_2_CALIBRATION"
                if not chart_eligible else "INSUFFICIENT_ANALYSIS_CONFIDENCE"
            )
        elif candidate == "WAIT":
            chart_gate = "20_50_30_SCORE_BELOW_THRESHOLD_OR_CONFLICT"
        elif engine2_visual_used:
            chart_gate = "20_50_30_NATIVE_OHLC_AND_VISUAL_CONFIRMED"
        else:
            chart_gate = "20_50_30_NATIVE_OHLC_CONFIRMED_VISUAL_NOT_USED"
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

        daily_risk = bridge.get("daily_risk") if isinstance(bridge.get("daily_risk"), dict) else {}
        daily_risk_required = bridge.get("daily_risk_required") is True
        daily_risk_status = str(daily_risk.get("status", "NOT_CONFIGURED"))
        daily_risk_locked = daily_risk.get("locked") is True
        daily_risk_blocks_entry = (
            daily_risk_required
            and (daily_risk_status != "READY" or daily_risk_locked)
        )
        economic_calendar = intelligence.get("economic_calendar") if isinstance(intelligence.get("economic_calendar"), dict) else {}
        calendar_status = str(economic_calendar.get("status", "NOT_AVAILABLE") or "NOT_AVAILABLE").upper()
        # Only a successful public-calendar response (including a valid empty
        # calendar) can clear the macro gate. Missing, stale, invalid or offline
        # data must never be interpreted as "no high-impact event".
        macro_calendar_verified = calendar_status in {"READY", "EMPTY"}
        macro_event_window_active = economic_calendar.get("high_impact_window_active") is True
        if action in {"BUY", "SELL"} and quote_ok:
            if macro_event_window_active:
                action = "WAIT"
                open_block_reason = "High-importance macro event is inside the configured pre/post-release window; new entry is paused."
                size = {"status": "BLOCKED", "reason": open_block_reason}
            elif not macro_calendar_verified:
                action = "WAIT"
                open_block_reason = (
                    "Economic calendar data is unavailable, stale or invalid; new entries remain paused "
                    "until a verified Engine 1 calendar feed is restored."
                )
                size = {"status": "BLOCKED", "reason": open_block_reason}

        # The daily loss gate applies only to NEW exposure. A protective MODIFY
        # has already returned above; an opposite-position CLOSE is kept intact.
        if action in {"BUY", "SELL"} and quote_ok and daily_risk_blocks_entry:
            action = "WAIT"
            reason = (
                "Daily loss cap reached; new entries are locked for the current UTC day."
                if daily_risk_status == "READY" and daily_risk_locked
                else "Daily risk baseline is unavailable; new entries fail closed."
            )
            open_block_reason = reason
            size = {"status": "BLOCKED", "reason": reason}

        command_ready = bool(
            bridge.get("status") == "CONNECTED" and quote_ok
            and (
                (action in {"BUY", "SELL"} and size.get("status") == "READY")
                or (action == "CLOSE" and close_ticket is not None and close_volume is not None)
            )
        )

        return {
            **base,
            "status": "READY" if engine2_decision_eligible else "WAITING_FOR_ENGINE_2",
            "action": action, "candidate_action": candidate, "aligned_signal": aligned_signal,
            "signal_id": signal_id, "command_ready": command_ready,
            "position_ticket": close_ticket, "chart_gate": chart_gate,
            "chart_visual_bias": visual_bias, "engine_2_direction": engine2_direction,
            "engine_2_score_source": engine2_source, "engine_2_visual_evidence_used": engine2_visual_used,
            "open_block_reason": open_block_reason,
            "as_of_ms": market.get("captured_at_ms"),
            "market_symbol": market_symbol, "symbol": broker_symbol if quote_ok else market_symbol,
            "market_price_reference": market.get("price"),
            "broker_quote": quote if quote_ok else None,
            "broker_market_price_divergence_pct": round(price_divergence * 100, 4) if price_divergence is not None else None,
            "broker_spread_pct": round(spread_pct * 100, 4) if spread_pct is not None else None,
            "entry_reference": entry if action in {"BUY", "SELL"} else 0.0,
            "stop_loss": stop_loss if action in {"BUY", "SELL"} else 0.0,
            "take_profit": take_profit if action in {"BUY", "SELL"} else 0.0,
            "trend_score": round(trend_score, 4),
            "engine_3_signal_score": round(signal_score, 4),
            "engine_3_signal_quality": round(signal_quality, 4),
            "timeframes": timeframe_data,
            "decision_weights": {
                **effective_weights,
                "configured": {
                    "engine_1_market_intelligence": ENGINE1_DECISION_WEIGHT,
                    "engine_2_price_action": ENGINE2_DECISION_WEIGHT,
                    "engine_3_indicators": ENGINE3_DECISION_WEIGHT,
                },
                "engine_2_internal": {
                    "configured": {
                        "native_ohlc_price_action": ENGINE2_NATIVE_OHLC_WEIGHT,
                        "calibrated_visual_chart": ENGINE2_VISUAL_WEIGHT,
                    },
                    "applied": {
                        "native_ohlc_price_action": ENGINE2_NATIVE_OHLC_WEIGHT if engine2_visual_used else 1.0,
                        "calibrated_visual_chart": ENGINE2_VISUAL_WEIGHT if engine2_visual_used else 0.0,
                    },
                },
                "normalization": "configured base weight multiplied by evidence quality, then active weights normalized to 100 percent",
            },
            "decision_scores": {
                "engine_1_market_intelligence": round(engine1_score, 4) if engine1_score is not None else None,
                "engine_1_quality": round(engine1_quality, 4),
                "engine_2_score": round(engine2_score, 4) if engine2_score is not None else None,
                "engine_2_native_ohlc_score": round(float(engine2_structure_score), 4) if engine2_structure_score is not None else None,
                "engine_2_visual_score": round(chart_score, 4) if engine2_visual_used else None,
                "engine_2_quality": round(engine2_quality, 4),
                "engine_3_indicators": round(signal_score, 4),
                "engine_3_ema_trend_score": round(trend_score, 4),
                "engine_3_quality": round(engine3_quality, 4),
                "chart_score": round(chart_score, 4),
                "chart_confidence": round(chart_confidence, 4),
                "market_score": round(market_score, 4) if market_score is not None else None,
                "market_components": market_score_parts,
                "effective_weights": effective_weights,
                "combined_score": round(combined_score, 4) if combined_score is not None else None,
                "threshold": DIRECTIONAL_SCORE_THRESHOLD,
                "minimum_engine_2_direction_score": MIN_ENGINE2_DIRECTION_SCORE,
            },
            "indicators": indicator_values,
            "engine_3_indicator_status": indicator_data.get("status"),
            "orderflow": orderflow,
            "market_microstructure": microstructure,
            "economic_calendar": economic_calendar or {"status": "NOT_AVAILABLE", "events": []},
            "market_intelligence": intelligence,
            "macro_event_gate": {
                "status": "ACTIVE" if macro_event_window_active else "CLEAR" if macro_calendar_verified else "UNKNOWN",
                "calendar_status": calendar_status,
                "calendar_verified": macro_calendar_verified,
                "new_entries_paused": macro_event_window_active or not macro_calendar_verified,
                "active_events": economic_calendar.get("active_high_impact_events", []),
                "reason": (
                    "HIGH_IMPACT_EVENT_WINDOW"
                    if macro_event_window_active else
                    "CALENDAR_UNAVAILABLE_OR_UNVERIFIED"
                    if not macro_calendar_verified else None
                ),
                "policy": "pause_new_entries_on_active_or_unverified_calendar_only_close_and_protective_modify_remain_available",
            },
            "risk_plan": size,
            "daily_risk_gate": {
                "required": daily_risk_required,
                "status": daily_risk_status,
                "locked": daily_risk_locked,
                "new_entry_blocked": daily_risk_blocks_entry,
                "max_daily_loss_fraction": daily_risk.get("max_daily_loss_fraction"),
                "daily_loss_fraction": daily_risk.get("daily_loss_fraction"),
                "day_utc": daily_risk.get("day_utc"),
            },
            "position_management": {
                "matching_positions": len(positions),
                "opposite_positions": sum(1 for p in positions if aligned_signal in {"BUY", "SELL"} and p["side"] != aligned_signal),
                "action": action,
                "close_ticket": close_ticket,
            },
            "engine_inputs": {
                "engine_1_market_intelligence": intelligence.get("status", "NOT_PROVIDED"),
                "engine_5_execution_quote_feed": market.get("status"),
                "chart_and_candles_from_engine_2": "READY" if engine2_decision_eligible else price_action.get("status", chart.get("status", "NOT_READY")) ,
                "indicators_from_engine_3": indicator_data.get("status"),
                "engine_5_bridge_for_quote_account_specs_and_transport": bridge.get("status", "NOT_CONFIGURED"),
                "broker_market_price_divergence_pct": round(price_divergence * 100, 4) if price_divergence is not None else None,
                "broker_spread_pct": round(spread_pct * 100, 4) if spread_pct is not None else None,
            },
            "reason": (
                "BUY/SELL combines Engine 1 market intelligence (20%), Engine 2 native multi-timeframe OHLC price action (50%), and Engine 3 indicators (30%). "
                "Inside Engine 2, native OHLC structure carries 70% and calibrated image analysis may add 30%; when the image is uncalibrated, only native OHLC is used. "
                "Evidence-quality weighting re-normalizes available contributions; the resulting score is not a calibrated probability of profit. Engine 5 supplies execution and account facts only."
            ),
        }
