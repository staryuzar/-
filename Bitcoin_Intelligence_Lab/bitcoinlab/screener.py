from __future__ import annotations

from collections import Counter
import math
from typing import Any, Mapping


DEFAULT_THRESHOLDS = {
    "relative_volume": 2.0,
    "range_expansion": 1.8,
    "book_imbalance_abs": 0.65,
    "spread_warning_bps": 15.0,
}


def _finite(value: object) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if math.isfinite(parsed) else None


def _frame_stamp(frame: Mapping[str, Any]) -> int | None:
    last_bar = frame.get("last_bar")
    if not isinstance(last_bar, Mapping):
        return None
    try:
        stamp = int(last_bar.get("close_time_ms") or 0)
    except (TypeError, ValueError, OverflowError):
        return None
    return stamp if stamp > 0 else None


def build_market_screener(
    *,
    multi_timeframe: Mapping[str, Any],
    market_structure: Mapping[str, Any],
    market_interval: str,
    order_book: Mapping[str, Any] | None = None,
    streamed_trade_flow: Mapping[str, Any] | None = None,
    derivatives: Mapping[str, Any] | None = None,
    cross_venue_derivatives: Mapping[str, Any] | None = None,
    liquidation_risk: Mapping[str, Any] | None = None,
    now_ms: int,
    thresholds: Mapping[str, float] | None = None,
) -> dict[str, Any]:
    """Detect completed-bar and fresh-feed market events. This module never creates trade orders."""
    supplied = dict(thresholds or {})
    unknown = set(supplied) - set(DEFAULT_THRESHOLDS)
    if unknown:
        raise ValueError(f"Unknown screener thresholds: {sorted(unknown)}.")
    params = {**DEFAULT_THRESHOLDS, **supplied}
    for key, value in params.items():
        parsed = _finite(value)
        if parsed is None or parsed < 0:
            raise ValueError(f"Screener threshold {key} must be finite and non-negative.")
        params[key] = parsed
    if params["relative_volume"] <= 0 or params["range_expansion"] <= 0:
        raise ValueError("Volume and range thresholds must be positive.")
    if params["book_imbalance_abs"] <= 0 or params["book_imbalance_abs"] > 1:
        raise ValueError("book_imbalance_abs must be within (0, 1].")
    if params["spread_warning_bps"] <= 0 or params["spread_warning_bps"] > 1000:
        raise ValueError("spread_warning_bps must be within (0, 1000].")

    frames = multi_timeframe.get("frames") or {}
    events: list[dict[str, Any]] = []
    warnings: list[str] = []
    rejected_inputs: list[str] = []
    freshness_used: dict[str, str] = {}

    def emit(
        event_type: str,
        *,
        severity: str,
        direction: str | None,
        timeframe: str,
        observed_at_ms: int | None,
        value: object,
        threshold: object,
        source: str,
        evidence: list[str],
        limitation: str,
    ) -> None:
        if observed_at_ms is None or observed_at_ms <= 0:
            rejected_inputs.append(f"{event_type}:missing_timestamp")
            return
        event_key = f"{event_type}:{timeframe}:{observed_at_ms}:{str(value)}"
        events.append({
            "event_key": event_key,
            "type": event_type,
            "severity": severity,
            "direction": direction,
            "timeframe": timeframe,
            "observed_at_ms": observed_at_ms,
            "value": value,
            "threshold": threshold,
            "source": source,
            "evidence": evidence,
            "limitation": limitation,
            "creates_order": False,
        })

    # 1) Breakouts are detected only from fresh completed candles and the
    # previously calculated closed-bar 20-period breakout field.
    for timeframe in ("1d", "4h", "1h", "15m", "5m", "1m"):
        frame = frames.get(timeframe, {})
        if not isinstance(frame, Mapping) or frame.get("status") != "fresh":
            rejected_inputs.append(f"{timeframe}:frame_not_fresh")
            continue
        stamp = _frame_stamp(frame)
        freshness_used[timeframe] = "fresh"
        breakout = str(frame.get("breakout") or "none").lower()
        if breakout in {"up", "down"}:
            emit(
                "completed_bar_breakout",
                severity="high" if timeframe in {"1d", "4h", "1h"} else "medium",
                direction="BUY" if breakout == "up" else "SELL",
                timeframe=timeframe,
                observed_at_ms=stamp,
                value=breakout,
                threshold="close beyond prior 20 completed-bar high/low",
                source="multi_timeframe.technical_profile",
                evidence=[
                    "latest_bar_is_completed_and_fresh",
                    "close_broke_prior_20_completed_bar_extreme",
                ],
                limitation="A price breakout can fail; the event is not a confirmation of follow-through.",
            )

    # 2) Relative-volume and range expansion are measured on the explicit
    # chart interval; never silently relabel them as a 1m signal.
    structure_bars = market_structure.get("bars") or {}
    relative_volume = _finite(structure_bars.get("relative_volume_20"))
    range_expansion = _finite(structure_bars.get("range_expansion_vs_prior_median"))
    interval_frame = frames.get(market_interval, {})
    interval_stamp = _frame_stamp(interval_frame) if (
        isinstance(interval_frame, Mapping) and interval_frame.get("status") == "fresh"
    ) else None
    if structure_bars.get("status") == "ok" and interval_stamp:
        if relative_volume is not None and relative_volume >= params["relative_volume"]:
            emit(
                "relative_volume_surge",
                severity="high" if relative_volume >= 3.0 else "medium",
                direction=None,
                timeframe=market_interval,
                observed_at_ms=interval_stamp,
                value=round(relative_volume, 4),
                threshold=params["relative_volume"],
                source="market_structure.relative_volume_20",
                evidence=["latest_completed_bar_volume_vs_prior_20_bar_mean"],
                limitation="Volume surge measures activity, not buy/sell direction.",
            )
        if range_expansion is not None and range_expansion >= params["range_expansion"]:
            emit(
                "range_expansion",
                severity="high" if range_expansion >= 2.5 else "medium",
                direction=None,
                timeframe=market_interval,
                observed_at_ms=interval_stamp,
                value=round(range_expansion, 4),
                threshold=params["range_expansion"],
                source="market_structure.range_expansion_vs_prior_median",
                evidence=["latest_completed_bar_true_range_vs_prior_20_bar_median"],
                limitation="Large ranges can reflect news volatility or exhaustion; direction is not inferred.",
            )
    else:
        rejected_inputs.append("market_structure:missing_fresh_interval_bar_or_baseline")

    # 3) Order-book pressure and spread alerts are fresh snapshot observations,
    # not executed-volume signals and not a directional decision.
    book = order_book or {}
    book_imbalance = _finite(book.get("imbalance"))
    spread = _finite(book.get("spread_bps"))
    book_stamp = None
    try:
        raw_stamp = int(book.get("observed_at_ms") or book.get("timestamp_ms") or 0)
        book_stamp = raw_stamp if raw_stamp > 0 else None
    except (TypeError, ValueError, OverflowError):
        book_stamp = None
    book_age = (int(now_ms) - book_stamp) / 1000 if book_stamp else math.inf
    if book_stamp and -5 <= book_age <= 20:
        freshness_used["spot_order_book"] = "fresh"
        if book_imbalance is not None and abs(book_imbalance) >= params["book_imbalance_abs"]:
            emit(
                "extreme_orderbook_imbalance",
                severity="medium",
                direction="BUY" if book_imbalance > 0 else "SELL",
                timeframe="snapshot",
                observed_at_ms=book_stamp,
                value=round(book_imbalance, 4),
                threshold=params["book_imbalance_abs"],
                source="binance_spot_order_book",
                evidence=["normalized_top_depth_imbalance"],
                limitation="Displayed orders may be cancelled, replenished or spoofed; not executed flow.",
            )
        if spread is not None and spread >= params["spread_warning_bps"]:
            emit(
                "wide_spread",
                severity="high" if spread >= 2 * params["spread_warning_bps"] else "medium",
                direction=None,
                timeframe="snapshot",
                observed_at_ms=book_stamp,
                value=round(spread, 4),
                threshold=params["spread_warning_bps"],
                source="binance_spot_order_book",
                evidence=["best_bid_ask_spread_exceeds_reference_threshold"],
                limitation="This is a high-spread condition, not a widening-rate measurement; no rolling baseline is yet used.",
            )
    elif book:
        rejected_inputs.append("spot_order_book:not_fresh_or_missing_timestamp")

    # 4) Multi-venue trade-flow and derivatives differences create alerts
    # only when the upstream modules already validated timestamps/coverage.
    flow = streamed_trade_flow or {}
    if flow.get("status") == "ok":
        spot_score = _finite(flow.get("spot_score"))
        perp_score = _finite(flow.get("perpetual_score"))
        if (
            spot_score is not None and perp_score is not None
            and spot_score * perp_score < 0
            and abs(spot_score - perp_score) >= 0.35
        ):
            stamp = flow.get("last_trade_time_ms")
            emit(
                "spot_perpetual_cvd_disagreement",
                severity="high",
                direction=None,
                timeframe=str(flow.get("timeframe") or "5m"),
                observed_at_ms=int(stamp) if stamp else None,
                value={"spot_cvd": round(spot_score, 4), "perpetual_cvd": round(perp_score, 4)},
                threshold="opposite signs and absolute score gap >= 0.35",
                source="multi_venue_streamed_cvd",
                evidence=["spot_and_linear_perpetual_aggressor_flow_disagree"],
                limitation="Venue samples are not the full market; disagreements can be transient.",
            )
    elif flow:
        rejected_inputs.append("streamed_trade_flow:coverage_incomplete_or_stale")

    cross = cross_venue_derivatives or {}
    for warning in cross.get("warnings", []) if isinstance(cross.get("warnings"), list) else []:
        known = {
            "funding_rate_dispersion_across_venues": ("cross_venue_funding_dispersion", "medium"),
            "perpetual_spot_basis_dispersion_across_venues": ("cross_venue_basis_dispersion", "medium"),
            "mark_index_premium_dispersion_across_venues": ("cross_venue_mark_index_dispersion", "low"),
        }
        if warning not in known:
            continue
        event_type, severity = known[warning]
        venue_stamps = [
            _finite(row.get("observed_at_ms"))
            for row in cross.get("venues", [])
            if isinstance(row, Mapping) and row.get("status") in {"ok", "partial"}
        ]
        observed = int(max((x for x in venue_stamps if x), default=0))
        emit(
            event_type,
            severity=severity,
            direction=None,
            timeframe="snapshot",
            observed_at_ms=observed or None,
            value=warning,
            threshold="cross-venue dispersion threshold from normalized context",
            source="cross_venue_derivatives",
            evidence=[str(warning)],
            limitation="Context-only venue dispersion; it does not imply the next price direction.",
        )

    risk = liquidation_risk or {}
    for warning in risk.get("warnings", []) if isinstance(risk.get("warnings"), list) else []:
        if warning not in {
            "cross_venue_long_liquidation_pressure",
            "cross_venue_short_liquidation_pressure",
        }:
            continue
        # The latest event timestamp is surfaced when available in the stream,
        # but the summary remains the source of the risk warning.
        venue_stamps = [
            _finite(row.get("latest_event_time_ms"))
            for row in risk.get("by_venue", {}).values()
            if isinstance(row, Mapping)
        ] if isinstance(risk.get("by_venue"), Mapping) else []
        observed = int(max((value for value in venue_stamps if value), default=0))
        emit(
            "cross_venue_liquidation_pressure",
            severity="high",
            direction=None,
            timeframe="5m",
            observed_at_ms=observed or None,
            value=warning,
            threshold="at least two venues in the current liquidation-risk summary",
            source="liquidation_risk",
            evidence=[str(warning)],
            limitation="Liquidation feeds are sampled differently across venues; forced flow is not a reversal signal.",
        )

    # Stable deduplication protects a refreshing dashboard from duplicate rows.
    unique: dict[str, dict[str, Any]] = {}
    for event in events:
        unique[event["event_key"]] = event
    events = list(unique.values())
    severity_order = {"high": 0, "medium": 1, "low": 2}
    events.sort(key=lambda event: (
        severity_order.get(event["severity"], 9),
        -int(event["observed_at_ms"]),
        event["type"],
    ))
    counts = Counter(event["severity"] for event in events)

    decision_warnings = sorted({
        event["type"] for event in events
        if event["severity"] in {"high", "medium"}
    })
    if rejected_inputs:
        warnings.append("some_screener_inputs_were_missing_stale_or_incomplete")

    return {
        "status": "ok" if freshness_used else ("partial" if rejected_inputs else "quiet"),
        "event_count": len(events),
        "counts_by_severity": {
            "high": counts.get("high", 0),
            "medium": counts.get("medium", 0),
            "low": counts.get("low", 0),
        },
        "events": events,
        "decision_warnings": decision_warnings,
        "warnings": sorted(set(warnings)),
        "freshness_used": freshness_used,
        "rejected_inputs": sorted(set(rejected_inputs)),
        "thresholds": params,
        "vote_policy": "alerts_are_evidence_context_only_not_an_independent_directional_vote",
        "limitations": [
            "Thresholds are provisional operating references and require calibration against historical BTC data.",
            "Alerts are derived from the supplied current snapshot and completed bars; they are not a continuous all-market scanner.",
            "No alert creates an order or replaces the central decision.",
        ],
    }
