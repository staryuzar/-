from __future__ import annotations

import math
from typing import Any

ENGINE_SHARES = {
    "engine_1_market_intelligence": 0.20,
    "engine_2_price_action": 0.55,
    "engine_3_indicators": 0.25,
}
DIRECTIONS = ("BUY", "SELL", "NEUTRAL")
SHARE_TOLERANCE_PERCENT = 0.005


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def publish_engine_share(
    engine_name: str,
    *,
    status: str,
    score: Any,
    quality: Any,
    eligible: bool = True,
    source: str | None = None,
) -> dict[str, Any]:
    """Convert one engine's signed score and evidence quality into its fixed share.

    Quality controls the portion that engine is willing to vote. The unused
    portion remains NEUTRAL inside that engine's allocation; it is never
    transferred to another engine. This function performs no market analysis.
    """
    if engine_name not in ENGINE_SHARES:
        raise ValueError(f"Unknown decision engine: {engine_name}")
    base_share = ENGINE_SHARES[engine_name]
    normalized_status = str(status or "UNAVAILABLE").upper()
    signed_score = _finite(score)
    evidence_quality = _finite(quality)

    valid = (
        bool(eligible)
        and normalized_status in {"READY", "PARTIAL"}
        and signed_score is not None
        and -1.0 <= signed_score <= 1.0
        and evidence_quality is not None
        and 0.0 <= evidence_quality <= 1.0
    )
    if not valid:
        return {
            "engine": engine_name,
            "status": normalized_status,
            "received": False,
            "decision_eligible": False,
            "reason": "ENGINE_REPORT_INELIGIBLE_OR_SCORE_QUALITY_INVALID",
            "base_share": base_share,
            "decision_share_distribution_percent": None,
            "source": source,
        }

    active_percent = base_share * evidence_quality * 100.0
    neutral_percent = (base_share * (1.0 - evidence_quality)) * 100.0
    buy_percent = active_percent * (1.0 + signed_score) / 2.0
    sell_percent = active_percent * (1.0 - signed_score) / 2.0
    split = {
        "BUY": round(buy_percent, 8),
        "SELL": round(sell_percent, 8),
        "NEUTRAL": round(neutral_percent, 8),
    }
    expected_percent = base_share * 100.0
    correction = round(expected_percent - sum(split.values()), 8)
    split["NEUTRAL"] = round(split["NEUTRAL"] + correction, 8)
    return {
        "engine": engine_name,
        "status": normalized_status,
        "received": True,
        "decision_eligible": True,
        "reason": None,
        "base_share": base_share,
        "decision_quality": evidence_quality,
        "score": signed_score,
        "direction": (
            "BUY" if signed_score > 0
            else "SELL" if signed_score < 0
            else "NEUTRAL"
        ),
        "decision_share_distribution_percent": split,
        "source": source,
        "quality_policy": "UNUSED_ENGINE_SHARE_REMAINS_NEUTRAL_NO_REDISTRIBUTION",
    }


def _read_engine_decision(
    report: Any,
    *,
    expected_engine: str,
    expected_share: float,
) -> dict[str, Any]:
    data = report if isinstance(report, dict) else {}
    status = str(data.get("status", "UNAVAILABLE")).upper()
    split = data.get("decision_share_distribution_percent")
    if data.get("received") is not True or data.get("decision_eligible") is not True:
        return {"received": False, "reason": data.get("reason") or "ENGINE_DECISION_INELIGIBLE"}
    if status not in {"READY", "PARTIAL"} or not isinstance(split, dict):
        return {"received": False, "reason": "ENGINE_STATUS_OR_DISTRIBUTION_INVALID"}

    values = {direction: _finite(split.get(direction)) for direction in DIRECTIONS}
    if any(value is None or value < 0.0 for value in values.values()):
        return {"received": False, "reason": "INVALID_DIRECTION_SHARE_VALUE"}
    expected_percent = expected_share * 100.0
    received_total = sum(float(values[name]) for name in DIRECTIONS)
    if abs(received_total - expected_percent) > SHARE_TOLERANCE_PERCENT:
        return {
            "received": False,
            "reason": "ENGINE_SHARE_DISTRIBUTION_TOTAL_MISMATCH",
            "expected_share_percent": round(expected_percent, 8),
            "received_share_percent": round(received_total, 8),
        }
    clean = {name: float(values[name]) for name in DIRECTIONS}
    dominant = max(DIRECTIONS, key=lambda name: (clean[name], name == "NEUTRAL"))
    return {
        "received": True,
        "reason": None,
        "engine": expected_engine,
        "status": status,
        "direction": dominant,
        "share_distribution_percent": clean,
        "base_share_percent": round(expected_percent, 8),
        "net_score": round((clean["BUY"] - clean["SELL"]) / expected_percent, 8),
        "source_quality": _finite(data.get("decision_quality")),
        "signed_contribution_percent": round(clean["BUY"] - clean["SELL"], 8),
    }


def build_final_decision(
    engine1: dict[str, Any] | None,
    engine2: dict[str, Any] | None,
    engine3: dict[str, Any] | None,
) -> dict[str, Any]:
    """Add the three already-published engine shares; missing shares are not redistributed."""
    supplied = {
        "engine_1_market_intelligence": engine1,
        "engine_2_price_action": engine2,
        "engine_3_indicators": engine3,
    }
    decisions: dict[str, dict[str, Any]] = {}
    totals = {direction: 0.0 for direction in DIRECTIONS}
    contributions: dict[str, dict[str, Any]] = {}
    pending: list[str] = []
    received_share = 0.0

    for name, base_share in ENGINE_SHARES.items():
        item = _read_engine_decision(
            supplied[name], expected_engine=name, expected_share=base_share
        )
        decisions[name] = item
        if not item["received"]:
            pending.append(name)
            contributions[name] = {
                "base_share": base_share,
                "effective_share": 0.0,
                "eligible": False,
                "reason": item.get("reason"),
                "direction": "UNKNOWN",
                "vote_distribution_percent": None,
                "signed_contribution_percent": 0.0,
            }
            continue

        split = item["share_distribution_percent"]
        received_share += item["base_share_percent"]
        for direction in DIRECTIONS:
            totals[direction] += split[direction]
        contributions[name] = {
            "base_share": base_share,
            "effective_share": base_share,
            "eligible": True,
            "reason": None,
            "direction": item["direction"],
            "vote_distribution_percent": dict(split),
            "signed_contribution_percent": item["signed_contribution_percent"],
            "quality": item.get("source_quality"),
            "quality_preapplied": True,
        }

    complete = not pending
    if not complete:
        action = "WAIT"
    elif totals["BUY"] > totals["SELL"] and totals["BUY"] > totals["NEUTRAL"]:
        action = "BUY"
    elif totals["SELL"] > totals["BUY"] and totals["SELL"] > totals["NEUTRAL"]:
        action = "SELL"
    else:
        action = "WAIT"

    distribution = {name: round(totals[name], 8) for name in DIRECTIONS}
    total_percent = sum(distribution.values())
    decision_rows = [
        {
            "engine_key": name,
            "base_share_percent": round(share * 100.0, 8),
            "buy_percent": decisions[name].get("share_distribution_percent", {}).get("BUY"),
            "sell_percent": decisions[name].get("share_distribution_percent", {}).get("SELL"),
            "neutral_percent": decisions[name].get("share_distribution_percent", {}).get("NEUTRAL"),
            "direction": decisions[name].get("direction", "UNAVAILABLE"),
            "status": decisions[name].get("status", "UNAVAILABLE"),
            "received": decisions[name].get("received") is True,
            "reason": decisions[name].get("reason"),
        }
        for name, share in ENGINE_SHARES.items()
    ]
    decision_rows.append({
        "engine_key": "TOTAL",
        "base_share_percent": 100.0,
        "buy_percent": distribution["BUY"],
        "sell_percent": distribution["SELL"],
        "neutral_percent": distribution["NEUTRAL"],
        "direction": action,
        "status": "READY" if complete else "PARTIAL",
        "received": complete,
        "reason": None if complete else "Missing engine allocation was not redistributed.",
    })
    return {
        "schema": "MIR-DECISION-COORDINATOR-1",
        "engine": "three_engine_decision_coordinator",
        "status": "READY" if complete else "WAITING_FOR_ENGINE_DECISIONS",
        "action": action,
        "decision_direction": action,
        "entry_eligible": bool(complete and action in {"BUY", "SELL"}),
        "all_engine_decisions_received": complete,
        "pending_engines": pending,
        "configured_shares": dict(ENGINE_SHARES),
        "received_share_percent": round(received_share, 8),
        "expected_share_percent": 100.0,
        "directional_shares_percent": distribution,
        "total_reported_share_percent": round(total_percent, 8),
        "contributions": contributions,
        "engine_decisions": decisions,
        "decision_table_rows": decision_rows,
        "decision_rule": "SUM_BUY_VS_SELL_VS_NEUTRAL_ONLY",
        "no_redistribution": True,
    }


__all__ = [
    "ENGINE_SHARES",
    "DIRECTIONS",
    "publish_engine_share",
    "build_final_decision",
]
