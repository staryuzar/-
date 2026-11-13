from __future__ import annotations

import math
from typing import Any

from .decision_coordinator import DIRECTIONS, ENGINE_SHARES


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def validate_decision_integrity(
    coordinator: dict[str, Any] | None,
    decision: dict[str, Any] | None,
) -> dict[str, Any]:
    """Validate allocation arithmetic and Engine-4 command intent before publication."""
    coordinator = coordinator if isinstance(coordinator, dict) else {}
    decision = decision if isinstance(decision, dict) else {}
    errors: list[str] = []

    candidate = str(decision.get("candidate_action", "WAIT")).upper()
    action = str(decision.get("action", "WAIT")).upper()
    coordinator_action = str(coordinator.get("action", "WAIT")).upper()
    requires_directional_coordinator = (
        candidate in {"BUY", "SELL"} or action in {"BUY", "SELL"}
    )

    # Missing Engine 1/2/3 inputs are an expected WAIT state, not a corrupt
    # execution command. The complete 100% allocation is mandatory only when
    # Engine 4 proposes new directional exposure.
    if requires_directional_coordinator:
        if coordinator.get("schema") != "MIR-DECISION-COORDINATOR-1":
            errors.append("COORDINATOR_SCHEMA_INVALID")
        if (
            coordinator.get("status") != "READY"
            or coordinator.get("all_engine_decisions_received") is not True
        ):
            errors.append("ENGINE_DECISIONS_INCOMPLETE")

    configured = coordinator.get("configured_shares")
    if not isinstance(configured, dict):
        if requires_directional_coordinator:
            errors.append("CONFIGURED_SHARES_MISSING")
    else:
        for name, expected in ENGINE_SHARES.items():
            actual = _finite(configured.get(name))
            if actual is None or abs(actual - expected) > 1e-9:
                errors.append("CONFIGURED_SHARE_MISMATCH:" + name)
        if abs(sum(_finite(configured.get(name)) or 0.0 for name in ENGINE_SHARES) - 1.0) > 1e-9:
            errors.append("CONFIGURED_SHARES_DO_NOT_TOTAL_100_PERCENT")

    distribution = coordinator.get("directional_shares_percent")
    if not isinstance(distribution, dict):
        if requires_directional_coordinator:
            errors.append("DIRECTIONAL_DISTRIBUTION_MISSING")
        distribution = {}
    values = {name: _finite(distribution.get(name)) for name in DIRECTIONS}
    if requires_directional_coordinator:
        if any(value is None or value < 0 for value in values.values()):
            errors.append("DIRECTIONAL_DISTRIBUTION_INVALID")
        elif abs(sum(float(values[name]) for name in DIRECTIONS) - 100.0) > 0.02:
            errors.append("DIRECTIONAL_DISTRIBUTION_DOES_NOT_TOTAL_100_PERCENT")
    if candidate in {"BUY", "SELL"} and coordinator_action != candidate:
        errors.append("CANDIDATE_DIRECTION_DIFFERS_FROM_COORDINATOR")
    if action in {"BUY", "SELL"} and (
        action != candidate or action != coordinator_action
    ):
        errors.append("OPEN_ACTION_DIFFERS_FROM_COORDINATOR")

    if action in {"BUY", "SELL"}:
        risk = decision.get("risk_plan") if isinstance(decision.get("risk_plan"), dict) else {}
        volume = _finite(risk.get("volume"))
        entry = _finite(decision.get("entry_reference"))
        stop = _finite(decision.get("stop_loss"))
        target = _finite(decision.get("take_profit"))
        if risk.get("status") != "READY" or volume is None or volume <= 0:
            errors.append("OPEN_RISK_PLAN_INVALID")
        if any(value is None or value <= 0 for value in (entry, stop, target)):
            errors.append("OPEN_PRICE_PLAN_INVALID")
        elif action == "BUY" and not stop < entry < target:
            errors.append("BUY_PRICE_ORDER_INVALID")
        elif action == "SELL" and not target < entry < stop:
            errors.append("SELL_PRICE_ORDER_INVALID")

    if action == "CLOSE":
        try:
            ticket = int(decision.get("position_ticket", 0))
        except (TypeError, ValueError, OverflowError):
            ticket = 0
        risk = decision.get("risk_plan") if isinstance(decision.get("risk_plan"), dict) else {}
        volume = _finite(risk.get("volume"))
        if ticket <= 0 or volume is None or volume <= 0:
            errors.append("CLOSE_TARGET_OR_VOLUME_INVALID")

    return {
        "schema": "MIR-DECISION-INTEGRITY-1",
        "status": "PASS" if not errors else "BLOCKED",
        "valid": not errors,
        "errors": errors,
        "coordinator_action": coordinator_action,
        "candidate_action": candidate,
        "engine4_action": action,
        "coordinator_complete": coordinator.get("all_engine_decisions_received") is True,
        "risk_plan_checked": action in {"BUY", "SELL", "CLOSE"},
        "execution_eligible": bool(not errors and decision.get("command_ready") is True),
        "scope": "DECISION_CONTRACT_AND_MIR1_COMMAND_PLAN_NOT_MARKET_PROFITABILITY",
    }


__all__ = ["validate_decision_integrity"]
