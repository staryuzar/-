from __future__ import annotations

import math
from typing import Mapping


DEFAULT_WEIGHTS = {"technical": 0.40, "orderflow": 0.35, "derivatives": 0.25}
REQUIRED_SOURCES = ("spot", "orderflow", "derivatives")


def central_decision(
    *, technical: Mapping[str, object], orderflow: Mapping[str, object],
    derivatives: Mapping[str, object], source_states: Mapping[str, Mapping[str, object]],
    spread_bps: float, reward_risk_ratio: float = 1.5,
    min_abs_score: float = 0.28, max_spread_bps: float = 12.0,
) -> dict:
    """Conservative, explainable central decision. Never returns a win probability."""
    blockers: list[str] = []
    for name in REQUIRED_SOURCES:
        state = source_states.get(name, {})
        if state.get("status") != "fresh":
            blockers.append(f"{name}_not_fresh")
    if technical.get("status") != "ok" or orderflow.get("status") != "ok" or derivatives.get("status") != "ok":
        blockers.append("required_engine_incomplete")
    if not math.isfinite(float(spread_bps)) or spread_bps < 0 or spread_bps > max_spread_bps:
        blockers.append("spread_gate_failed")
    if not math.isfinite(float(reward_risk_ratio)) or reward_risk_ratio < 1.5:
        blockers.append("reward_risk_gate_failed")
    if blockers:
        return {"action": "HOLD", "score": None, "blockers": blockers, "reasons": [], "weights": DEFAULT_WEIGHTS.copy()}

    inputs = {
        "technical": float(technical["score"]),
        "orderflow": float(orderflow["score"]),
        "derivatives": float(derivatives["score"]),
    }
    if any(not math.isfinite(v) or not -1 <= v <= 1 for v in inputs.values()):
        return {"action": "HOLD", "score": None, "blockers": ["invalid_engine_score"], "reasons": [], "weights": DEFAULT_WEIGHTS.copy()}
    strong = [v for v in inputs.values() if abs(v) >= 0.55]
    if any(x > 0 for x in strong) and any(x < 0 for x in strong):
        return {
            "action": "HOLD", "score": None, "blockers": ["strong_cross_domain_conflict"],
            "reasons": [f"{name}:{value:+.2f}" for name, value in inputs.items()],
            "weights": DEFAULT_WEIGHTS.copy(),
        }
    score = sum(inputs[name] * DEFAULT_WEIGHTS[name] for name in DEFAULT_WEIGHTS)
    aligned = sum(1 for value in inputs.values() if value >= 0.15) if score > 0 else sum(1 for value in inputs.values() if value <= -0.15)
    if abs(score) < min_abs_score or aligned < 2:
        action = "HOLD"
        blockers = ["insufficient_cross_domain_confluence"]
    else:
        action = "BUY" if score > 0 else "SELL"
        blockers = []
    return {
        "action": action, "score": round(score, 6), "blockers": blockers,
        "reasons": [f"{name}:{value:+.2f}" for name, value in inputs.items()],
        "aligned_domains": aligned, "weights": DEFAULT_WEIGHTS.copy(),
        "interpretation": "Directional evidence score, not a statistical probability of profit.",
    }
