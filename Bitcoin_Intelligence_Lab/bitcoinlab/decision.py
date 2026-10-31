from __future__ import annotations

import math
from typing import Mapping


DEFAULT_WEIGHTS = {"technical": 0.35, "orderflow": 0.25, "derivatives": 0.20, "market_structure": 0.10, "cross_venue": 0.10}


def central_decision(
    *, technical: Mapping[str, object], orderflow: Mapping[str, object],
    derivatives: Mapping[str, object], source_states: Mapping[str, Mapping[str, object]],
    market_structure: Mapping[str, object] | None = None,
    cross_venue: Mapping[str, object] | None = None,
    liquidation_risk: Mapping[str, object] | None = None,
    event_context: Mapping[str, object] | None = None,
    spread_bps: float | None = None, reward_risk_ratio: float | None = None,
    min_abs_score: float = 0.15, max_spread_bps: float | None = None,
    minimum_active_domains: int = 2,
) -> dict:
    """Flexible research decision engine. Optional execution filters default to observation-only."""
    if not 1 <= minimum_active_domains <= 3:
        raise ValueError("minimum_active_domains must be between one and three.")
    if not math.isfinite(float(min_abs_score)) or not 0 <= min_abs_score <= 1:
        raise ValueError("min_abs_score must be within [0, 1].")

    # Spot price structure is fundamental. A second fresh evidence domain is enough;
    # any unavailable optional domain is reported and its weight is redistributed.
    spot_state = source_states.get("spot", {})
    if spot_state.get("status") != "fresh":
        return {
            "action": "HOLD", "score": None, "blockers": ["spot_not_fresh"],
            "warnings": [], "reasons": [], "weights": DEFAULT_WEIGHTS.copy(),
        }

    candidates = {
        "technical": technical,
        "orderflow": orderflow,
        "derivatives": derivatives,
        "market_structure": market_structure or {"status": "incomplete", "score": None},
        "cross_venue": cross_venue or {"status": "incomplete", "score": None},
    }
    valid: dict[str, float] = {}
    unavailable: list[str] = []
    for name, engine in candidates.items():
        if engine.get("status") != "ok":
            unavailable.append(name)
            continue
        # Every voting domain, including the technical multi-timeframe engine,
        # must carry an explicit fresh source state before its score can vote.
        if source_states.get(name, {}).get("status") != "fresh":
            unavailable.append(name)
            continue
        try:
            value = float(engine["score"])
        except (KeyError, TypeError, ValueError):
            unavailable.append(name)
            continue
        if not math.isfinite(value) or not -1 <= value <= 1:
            unavailable.append(name)
            continue
        valid[name] = value

    if "technical" not in valid:
        technical_state = source_states.get("technical", {})
        blocker = (
            "technical_source_not_fresh"
            if technical_state.get("status") != "fresh"
            else "technical_engine_unavailable"
        )
        return {
            "action": "HOLD", "score": None, "blockers": [blocker],
            "warnings": [f"{name}_unavailable_or_stale" for name in unavailable],
            "reasons": [], "weights": DEFAULT_WEIGHTS.copy(),
        }
    # New auxiliary engines cannot replace the two original independent
    # evidence domains: technical structure plus either trade flow or derivatives.
    core_domains = {"technical", "orderflow", "derivatives"}
    active_core = core_domains.intersection(valid)
    if len(active_core) < minimum_active_domains:
        return {
            "action": "HOLD", "score": None,
            "blockers": ["insufficient_fresh_core_evidence_domains"],
            "warnings": [f"{name}_unavailable" for name in unavailable],
            "reasons": [], "weights": DEFAULT_WEIGHTS.copy(),
            "active_domains": list(valid),
            "core_active_domains": sorted(active_core),
        }

    active_weights = {name: DEFAULT_WEIGHTS[name] for name in valid}
    total_weight = sum(active_weights.values())
    normalized = {name: weight / total_weight for name, weight in active_weights.items()}
    score = sum(valid[name] * normalized[name] for name in valid)

    warnings = [f"{name}_unavailable_or_stale" for name in unavailable]
    if isinstance(liquidation_risk, Mapping):
        warnings.extend(
            str(item) for item in liquidation_risk.get("warnings", [])
        )
    if isinstance(cross_venue, Mapping):
        warnings.extend(
            str(item) for item in cross_venue.get("warnings", [])
        )
    # Cross-venue derivatives are context attached to the derivatives
    # domain; their warnings are surfaced but they add no independent vote.
    if isinstance(derivatives, Mapping):
        derivatives_context = derivatives.get("cross_venue_context_only")
        if isinstance(derivatives_context, Mapping):
            warnings.extend(
                str(item) for item in derivatives_context.get("warnings", [])
            )
    if isinstance(event_context, Mapping):
        warnings.extend(
            str(item) for item in event_context.get("decision_warnings", [])
        )
    if spread_bps is not None:
        if not math.isfinite(float(spread_bps)) or spread_bps < 0:
            warnings.append("spread_data_invalid")
        elif max_spread_bps is not None and spread_bps > max_spread_bps:
            warnings.append("spread_above_optional_threshold")
    if reward_risk_ratio is not None:
        if not math.isfinite(float(reward_risk_ratio)) or reward_risk_ratio <= 0:
            warnings.append("reward_risk_data_invalid")
        elif reward_risk_ratio < 1.5:
            warnings.append("reward_risk_below_optional_reference")

    strong = [value for value in valid.values() if abs(value) >= 0.80]
    if any(value > 0 for value in strong) and any(value < 0 for value in strong):
        return {
            "action": "HOLD", "score": round(score, 6),
            "blockers": ["strong_cross_domain_conflict"],
            "warnings": warnings,
            "reasons": [f"{name}:{value:+.2f}" for name, value in valid.items()],
            "weights": normalized,
        }

    positive = sum(1 for value in valid.values() if value >= 0.10)
    negative = sum(1 for value in valid.values() if value <= -0.10)
    if score >= min_abs_score and positive >= 2:
        action = "BUY"
    elif score <= -min_abs_score and negative >= 2:
        action = "SELL"
    else:
        action = "HOLD"

    blockers = ["insufficient_directional_confluence"] if action == "HOLD" else []
    return {
        "action": action, "score": round(score, 6), "blockers": blockers,
        "warnings": warnings,
        "reasons": [f"{name}:{value:+.2f}" for name, value in valid.items()],
        "active_domains": list(valid), "unavailable_domains": unavailable,
        "core_active_domains": sorted(active_core),
        "aligned_domains": max(positive, negative), "weights": normalized,
        "risk_context_only": (
            liquidation_risk.get("use_in_decision")
            if isinstance(liquidation_risk, Mapping) else None
        ),
        "interpretation": "Directional evidence score, not a statistical probability of profit.",
        "execution_filters": "spread and reward/risk are advisory unless explicitly configured.",
    }
