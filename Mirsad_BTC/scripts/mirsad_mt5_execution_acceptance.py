"""Standalone MIR1 sizing acceptance helper used by offline unit tests.

This module is intentionally not imported by the live runtime. It exercises
broker-quote freshness, spread, volume-step, notional and stop-risk checks using
a deterministic synthetic stop distance. Live orders must still be produced by
DecisionEngine and validated by MT5BridgeEngine/ExecutionBridge.
"""
from __future__ import annotations

import hashlib
import math
from typing import Any

RISK_FRACTION = 0.005
MAX_NOTIONAL = 1_000.0
MAX_QUOTE_AGE_SECONDS = 10.0
MAX_TICK_AGE_SECONDS = 10.0
MAX_SPREAD_FRACTION = 0.003
COMMISSION_PER_LOT = 25.0
SYNTHETIC_STOP_FRACTION = 0.0015
TARGET_R_MULTIPLE = 2.0


def _number(value: Any, name: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise RuntimeError(f"{name} is missing or not numeric.") from exc
    if not math.isfinite(result):
        raise RuntimeError(f"{name} is not finite.")
    return result


def build_open_decision(state: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build a synthetic BUY acceptance envelope for isolated contract tests.

    The fixture deliberately uses no MT5 connection and sends no commands.
    Its 0.15% stop distance exists only to make sizing assertions reproducible.
    """
    if not isinstance(state, dict) or str(state.get("status", "")).upper() != "CONNECTED":
        raise RuntimeError("MT5 state is not connected.")

    quote = state.get("quote") if isinstance(state.get("quote"), dict) else {}
    spec = state.get("symbol_spec") if isinstance(state.get("symbol_spec"), dict) else {}
    account = state.get("account") if isinstance(state.get("account"), dict) else {}

    quote_age = _number(state.get("quote_age_seconds"), "quote_age_seconds")
    tick_age = _number(quote.get("tick_age_seconds"), "tick_age_seconds")
    bid = _number(quote.get("bid"), "bid")
    ask = _number(quote.get("ask"), "ask")
    if (
        quote_age < 0 or quote_age > MAX_QUOTE_AGE_SECONDS
        or tick_age < 0 or tick_age > MAX_TICK_AGE_SECONDS
        or bid <= 0 or ask < bid
    ):
        raise RuntimeError("MT5 quote is stale or outside the accepted market bounds.")

    midpoint = (bid + ask) / 2.0
    spread_fraction = (ask - bid) / midpoint if midpoint > 0 else math.inf
    if not math.isfinite(spread_fraction) or spread_fraction > MAX_SPREAD_FRACTION:
        raise RuntimeError("MT5 quote is stale or outside the accepted market bounds.")

    equity = _number(account.get("equity"), "account.equity")
    tick_size = _number(spec.get("tick_size"), "symbol_spec.tick_size")
    tick_value_loss = _number(spec.get("tick_value_loss"), "symbol_spec.tick_value_loss")
    volume_min = _number(spec.get("volume_min"), "symbol_spec.volume_min")
    volume_step = _number(spec.get("volume_step"), "symbol_spec.volume_step")
    volume_max = _number(spec.get("volume_max"), "symbol_spec.volume_max")
    digits = int(_number(spec.get("digits", 2), "symbol_spec.digits"))
    if (
        equity <= 0 or tick_size <= 0 or tick_value_loss <= 0
        or volume_min <= 0 or volume_step <= 0 or volume_max < volume_min
        or digits < 0 or digits > 10
    ):
        raise RuntimeError("Account equity or broker symbol specifications are invalid.")

    entry = ask
    if entry * volume_min > MAX_NOTIONAL + 1e-9:
        raise RuntimeError("Broker minimum lot exceeds the independent notional cap.")
    stop_distance = entry * SYNTHETIC_STOP_FRACTION
    stop_loss = round(entry - stop_distance, digits)
    take_profit = round(entry + stop_distance * TARGET_R_MULTIPLE, digits)
    loss_per_lot = (entry - stop_loss) / tick_size * tick_value_loss
    total_loss_per_lot = loss_per_lot + COMMISSION_PER_LOT
    risk_budget = equity * RISK_FRACTION
    if not all(math.isfinite(x) and x > 0 for x in (
        stop_distance, loss_per_lot, total_loss_per_lot, risk_budget
    )):
        raise RuntimeError("Stop-risk calculation is invalid.")

    raw_volume = min(volume_max, risk_budget / total_loss_per_lot)
    if raw_volume < volume_min - 1e-12:
        raise RuntimeError("Risk budget is below broker minimum volume.")
    steps = math.floor((raw_volume - volume_min + 1e-12) / volume_step)
    volume = round(volume_min + max(0, steps) * volume_step, 8)
    if volume <= 0 or volume > volume_max + 1e-9:
        raise RuntimeError("Calculated volume is outside broker limits.")

    estimated_stop_loss = loss_per_lot * volume
    estimated_commission = COMMISSION_PER_LOT * volume
    estimated_loss = estimated_stop_loss + estimated_commission
    estimated_notional = entry * volume
    if estimated_notional > MAX_NOTIONAL + 1e-8:
        capped_volume = math.floor((MAX_NOTIONAL / entry - volume_min + 1e-12) / volume_step)
        capped_volume = volume_min + max(0, capped_volume) * volume_step
        if capped_volume < volume_min - 1e-12:
            raise RuntimeError("Broker minimum lot exceeds the independent notional cap.")
        volume = round(min(volume, capped_volume), 8)
        estimated_stop_loss = loss_per_lot * volume
        estimated_commission = COMMISSION_PER_LOT * volume
        estimated_loss = estimated_stop_loss + estimated_commission
        estimated_notional = entry * volume

    if estimated_loss > risk_budget + 1e-8 or estimated_notional > MAX_NOTIONAL + 1e-8:
        raise RuntimeError("Calculated order exceeds the accepted risk or notional cap.")

    fingerprint = hashlib.sha256(
        f"{state.get('symbol','BTC')}|{entry:.{digits}f}|{volume:.8f}|{stop_loss:.{digits}f}".encode()
    ).hexdigest()[:24]
    sizing = {
        "status": "READY",
        "volume": volume,
        "risk_fraction": RISK_FRACTION,
        "risk_budget": risk_budget,
        "estimated_stop_loss": estimated_stop_loss,
        "estimated_commission": estimated_commission,
        "estimated_loss": estimated_loss,
        "estimated_notional": estimated_notional,
        "commission_per_lot": COMMISSION_PER_LOT,
        "notional_cap": MAX_NOTIONAL,
        "sizing_scope": "OFFLINE_SYNTHETIC_ACCEPTANCE_FIXTURE_ONLY",
    }
    decision = {
        "schema": "MIR1",
        "status": "READY",
        "action": "BUY",
        "candidate_action": "BUY",
        "command_ready": True,
        "signal_id": "MIR-" + fingerprint,
        "symbol": str(state.get("symbol", "BTC")),
        "market_symbol": str(state.get("market_symbol", "BTCUSDT")),
        "entry_reference": entry,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "risk_plan": {
            "status": "READY",
            "volume": volume,
            "risk_fraction": RISK_FRACTION,
            "risk_budget": risk_budget,
            "estimated_loss": estimated_loss,
        },
        "execution_scope": "OFFLINE_TEST_ONLY_NOT_PUBLISHABLE",
    }
    return decision, sizing
