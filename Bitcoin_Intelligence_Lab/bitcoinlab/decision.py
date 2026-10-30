from __future__ import annotations

import math
from typing import Mapping


DEFAULT_WEIGHTS = {"technical": 0.40, "orderflow": 0.35, "derivatives": 0.25}


def central_decision(
    *, technical: Mapping[str, object], orderflow: Mapping[str, object],
    derivatives: Mapping[str, object], source_states: Mapping[str, Mapping[str, object]],
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
    }
    valid: dict[str, float] = {}
    unavailable: list[str] = []
    for name, engine in candidates.items():
        if engine.get("status") != "ok":
            unavailable.append(name)
            continue
        if name != "technical" and source_states.get(name, {}).get("status") != "fresh":
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
        return {
            "action": "HOLD", "score": None, "blockers": ["technical_engine_unavailable"],
            "warnings": [f"{name}_unavailable" for name in unavailable],
            "reasons": [], "weights": DEFAULT_WEIGHTS.copy(),
        }
    if len(valid) < minimum_active_domains:
        return {
            "action": "HOLD", "score": None, "blockers": ["insufficient_fresh_evidence_domains"],
            "warnings": [f"{name}_unavailable" for name in unavailable],
            "reasons": [], "weights": DEFAULT_WEIGHTS.copy(),
        }

    active_weights = {name: DEFAULT_WEIGHTS[name] for name in valid}
    total_weight = sum(active_weights.values())
    normalized = {name: weight / total_weight for name, weight in active_weights.items()}
    score = sum(valid[name] * normalized[name] for name in valid)

    warnings = [f"{name}_unavailable_or_stale" for name in unavailable]
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

    return {
        "action": action, "score": round(score, 6), "blockers": [],
        "warnings": warnings,
        "reasons": [f"{name}:{value:+.2f}" for name, value in valid.items()],
        "active_domains": list(valid), "unavailable_domains": unavailable,
        "aligned_domains": max(positive, negative), "weights": normalized,
        "interpretation": "Directional evidence score, not a statistical probability of profit.",
        "execution_filters": "spread and reward/risk are advisory unless explicitly configured.",
    }
