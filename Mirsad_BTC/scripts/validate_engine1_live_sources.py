from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from mirsad.engines.market_intelligence import MarketIntelligenceEngine


def _status(value: Any) -> str:
    return str(value or "NOT_REPORTED").upper()


def _number(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if math.isfinite(parsed) else None


def _acceptance_findings(report: dict[str, Any], *, now_ms: int | None = None) -> tuple[list[str], list[str]]:
    """Strict operational acceptance for the required standalone Engine 1 inputs.

    Trading Economics is intentionally optional: ShowMyTrades and Forex Factory
    are the required independent public calendars. This gate validates source
    readiness and provenance, not trading accuracy or profitability.
    """
    captured = _number(report.get("captured_at_ms"))
    now = int(datetime.now(timezone.utc).timestamp() * 1000) if now_ms is None else int(now_ms)
    blockers: list[str] = []
    warnings: list[str] = []

    if report.get("overall_status") != "READY":
        blockers.append(f"Engine 1 composite status is {report.get('overall_status')}, not READY.")
    if str(report.get("symbol") or "").upper() != "BTCUSDT":
        blockers.append("Engine 1 report symbol is missing or is not BTCUSDT.")
    if captured is None:
        blockers.append("Engine 1 collection timestamp is missing or invalid.")
    else:
        age = (now - captured) / 1000.0
        if age < -2 or age > 120:
            blockers.append(f"Engine 1 collection snapshot is not fresh (age={age:.1f}s; maximum=120s).")

    direction = str(report.get("direction") or "UNKNOWN").upper()
    score = _number(report.get("directional_score"))
    confidence = _number(report.get("confidence"))
    coverage = _number(report.get("evidence_coverage"))
    if direction not in {"BULLISH", "BEARISH", "NEUTRAL"} or score is None or not -1.0 <= score <= 1.0:
        blockers.append("Engine 1 directional context is missing or outside its valid range.")
    if confidence is None or not 0.0 <= confidence <= 1.0:
        blockers.append("Engine 1 confidence is missing or outside [0, 1].")
    if coverage is None or coverage < 0.55 or coverage > 1.0:
        blockers.append("Engine 1 evidence coverage is below the configured READY threshold.")
    if int(report.get("usable_directional_component_count") or 0) < 3:
        blockers.append("Full Engine 1 acceptance requires all 3 configured directional components to contribute.")

    providers = report.get("provider_statuses") if isinstance(report.get("provider_statuses"), dict) else {}
    for key in ("news", "fear_greed", "global_metrics", "derivatives"):
        if str(providers.get(key, "NOT_REPORTED")).upper() != "READY":
            blockers.append(f"Required Engine 1 provider group {key} is {providers.get(key, 'NOT_REPORTED')}.")

    news = report.get("news") if isinstance(report.get("news"), dict) else {}
    news_sources = news.get("feed_statuses") if isinstance(news.get("feed_statuses"), dict) else {}
    ready_news_sources = [name for name, status in news_sources.items() if str(status).upper() == "READY"]
    if news.get("status") != "READY" or news.get("sentiment_status") != "READY":
        blockers.append("News collection and headline sentiment must both be READY.")
    if int(news.get("fresh_72h") or 0) < 3 or int(news.get("headline_sources") or 0) < 3 or len(ready_news_sources) < 3:
        blockers.append("Full news acceptance needs at least 3 fresh headlines and 3 independent RSS publishers.")
    freshest_age = _number(news.get("freshest_age_seconds"))
    if freshest_age is None or freshest_age < -120 or freshest_age > 72 * 60 * 60:
        blockers.append("News freshest-publication age is missing, future-dated or older than 72 hours.")

    fear = report.get("fear_greed") if isinstance(report.get("fear_greed"), dict) else {}
    fear_age = _number(fear.get("age_seconds"))
    fear_value = _number(fear.get("value"))
    if fear.get("status") != "READY" or fear_age is None or fear_age < -120 or fear_age > 129600 or fear_value is None or not 0 <= fear_value <= 100:
        blockers.append("Fear & Greed must contain a valid value and a provider observation no older than 36 hours.")

    global_metrics = report.get("global_metrics") if isinstance(report.get("global_metrics"), dict) else {}
    global_age = _number(global_metrics.get("age_seconds"))
    usable_global_metrics = global_metrics.get("metrics") if isinstance(global_metrics.get("metrics"), dict) else {}
    if global_metrics.get("status") != "READY" or global_metrics.get("freshness_status") != "FRESH" or global_age is None or global_age < -120 or global_age > 86400 or not any(_number(v) is not None for v in usable_global_metrics.values()):
        blockers.append("Global market metrics must be present and provider-fresh within 24 hours.")

    derivatives = report.get("derivatives") if isinstance(report.get("derivatives"), dict) else {}
    venue_rows = derivatives.get("venues") if isinstance(derivatives.get("venues"), dict) else {}
    fresh_venues = [
        name for name, row in venue_rows.items()
        if isinstance(row, dict)
        and row.get("provider_status") == "READY"
        and row.get("directional_status") == "FRESH"
        and _number(row.get("age_seconds")) is not None
        and -120 <= float(row.get("age_seconds")) <= 900
    ]
    derivative_score = _number(derivatives.get("score"))
    if derivatives.get("status") != "READY" or derivative_score is None or not -1.0 <= derivative_score <= 1.0 or len(fresh_venues) < 3:
        blockers.append("Full derivatives acceptance needs at least 3 independent venues with fresh, timestamped directional inputs.")
    if int(derivatives.get("stale_venue_count") or 0) > 0:
        warnings.append(f"{derivatives.get('stale_venue_count')} derivatives venues contained stale factors; only individually fresh factors may vote.")

    calendar = report.get("economic_calendar") if isinstance(report.get("economic_calendar"), dict) else {}
    calendar_sources = calendar.get("source_statuses") if isinstance(calendar.get("source_statuses"), dict) else {}
    required_calendars = ("showmytrades", "forex_factory")
    for provider in required_calendars:
        if str(calendar_sources.get(provider, "NOT_REPORTED")).upper() not in {"READY", "EMPTY"}:
            blockers.append(f"Independent economic calendar {provider} is {calendar_sources.get(provider, 'NOT_REPORTED')}.")
    if calendar.get("status") != "READY":
        blockers.append("Merged independent public economic calendar is not READY.")

    risk = report.get("market_risk_assessment") if isinstance(report.get("market_risk_assessment"), dict) else {}
    if risk.get("status") != "READY":
        blockers.append("Engine 1 contextual market-risk assessment is not READY.")

    if providers.get("trading_economics") == "NOT_CONFIGURED" or providers.get("trading_economics_calendar") == "NOT_CONFIGURED":
        warnings.append("Trading Economics is optional and is not configured; ShowMyTrades and Forex Factory are both checked independently.")
    warnings.append("Headline sentiment is a transparent RSS keyword heuristic, not article fact-checking or a calibrated forecast.")
    warnings.append("Engine 1 operational readiness does not establish profitable predictive performance; out-of-sample validation remains separate.")
    return blockers, warnings


def build_report(result: dict[str, Any], *, now_ms: int | None = None) -> dict[str, Any]:
    news = result.get("news") if isinstance(result.get("news"), dict) else {}
    news_sentiment = news.get("sentiment") if isinstance(news.get("sentiment"), dict) else {}
    fear = result.get("fear_greed") if isinstance(result.get("fear_greed"), dict) else {}
    global_metrics = result.get("global_metrics") if isinstance(result.get("global_metrics"), dict) else {}
    derivatives = result.get("derivatives") if isinstance(result.get("derivatives"), dict) else {}
    venues = derivatives.get("venues") if isinstance(derivatives.get("venues"), dict) else {}
    venue_scores = derivatives.get("venue_scores") if isinstance(derivatives.get("venue_scores"), dict) else {}
    calendar = result.get("economic_calendar") if isinstance(result.get("economic_calendar"), dict) else {}
    risk = result.get("market_risk_assessment") if isinstance(result.get("market_risk_assessment"), dict) else {}
    providers = result.get("source_statuses") if isinstance(result.get("source_statuses"), dict) else {}
    components = result.get("components") if isinstance(result.get("components"), dict) else {}

    venue_report: dict[str, Any] = {}
    for name, raw in venues.items():
        if not isinstance(raw, dict):
            continue
        diagnostic = venue_scores.get(name) if isinstance(venue_scores.get(name), dict) else {}
        venue_report[name] = {
            "provider_status": _status(raw.get("status")),
            "reason": raw.get("reason"),
            "endpoint_statuses": raw.get("endpoint_statuses", {}),
            "endpoint_errors": raw.get("endpoint_errors", {}),
            "directional_status": _status(diagnostic.get("directional_status")),
            "age_seconds": diagnostic.get("age_seconds"),
            "funding_directional_status": diagnostic.get("funding_directional_status"),
            "long_short_directional_status": diagnostic.get("long_short_directional_status"),
            "funding_rate": raw.get("funding_rate"),
            "funding_timestamp_basis": raw.get("funding_timestamp_basis"),
            "long_short_ratio": raw.get("long_short_ratio"),
            "long_short_ratio_scope": raw.get("long_short_ratio_scope"),
            "top_trader_long_short_account_ratio": raw.get("top_trader_long_short_account_ratio"),
            "top_trader_long_short_position_ratio": raw.get("top_trader_long_short_position_ratio"),
            "taker_long_short_ratio": raw.get("taker_long_short_ratio"),
            "open_interest_change_pct_35m": raw.get("open_interest_change_pct_35m"),
            "timestamp_basis": raw.get("timestamp_basis"),
        }

    captured_ms = result.get("captured_at_ms")
    try:
        captured_iso = datetime.fromtimestamp(float(captured_ms) / 1000.0, tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OverflowError, OSError):
        captured_iso = datetime.now(timezone.utc).isoformat()

    responsive = sum(
        1 for name, value in providers.items()
        if name not in {"trading_economics_calendar", "mt5_broker_calendar"}
        and _status(value) in {"READY", "PARTIAL", "STALE", "EMPTY"}
    )
    usable_directional_components = sum(
        1 for value in components.values()
        if isinstance(value, dict) and value.get("contributes") is True
    )
    report = {
        "schema": "MIR-ENGINE1-LIVE-SOURCE-PREFLIGHT-1",
        "captured_at_ms": captured_ms,
        "captured_at_utc": captured_iso,
        "symbol": result.get("symbol"),
        "overall_status": _status(result.get("status")),
        "direction": result.get("direction"),
        "directional_score": result.get("directional_score"),
        "confidence": result.get("confidence"),
        "evidence_coverage": result.get("evidence_coverage"),
        "provider_statuses": providers,
        "provider_response_count": responsive,
        "usable_directional_component_count": usable_directional_components,
        "news": {
            "status": _status(news.get("status")),
            "items": news.get("count", 0),
            "fresh_72h": news.get("fresh_count_72h", 0),
            "headline_sources": news.get("headline_source_count", 0),
            "freshest_age_seconds": news.get("freshest_age_seconds"),
            "feed_statuses": news.get("sources", {}),
            "sentiment_status": _status(news_sentiment.get("status")),
            "sentiment_score": news_sentiment.get("score"),
        },
        "fear_greed": {
            "status": _status(fear.get("status")),
            "value": fear.get("value"),
            "classification": fear.get("classification"),
            "age_seconds": fear.get("freshness_age_seconds"),
            "score": fear.get("score"),
        },
        "global_metrics": {
            "status": _status(global_metrics.get("status")),
            "freshness_status": _status(global_metrics.get("freshness_status")),
            "age_seconds": global_metrics.get("freshness_age_seconds"),
            "metrics": global_metrics.get("metrics", {}),
        },
        "derivatives": {
            "status": _status(derivatives.get("status")),
            "score": derivatives.get("score"),
            "confidence": derivatives.get("confidence"),
            "venue_count": derivatives.get("venue_count", 0),
            "stale_venue_count": derivatives.get("stale_venue_count", 0),
            "maximum_age_seconds": derivatives.get("freshness_max_age_seconds"),
            "venues": venue_report,
        },
        "economic_calendar": {
            "status": _status(calendar.get("status")),
            "source_statuses": calendar.get("sources", {}),
            "countries_covered": calendar.get("countries_covered", []),
            "events": calendar.get("event_count", 0),
            "next_24h_high_impact_events": calendar.get("next_24h_high_impact_events", []),
            "high_impact_window_active": calendar.get("high_impact_window_active", False),
            "trading_economics_configured": providers.get("trading_economics") not in {None, "NOT_CONFIGURED"},
        },
        "market_risk_assessment": {
            "status": _status(risk.get("status")),
            "level": risk.get("level"),
            "drivers": risk.get("drivers", []),
            "automatic_entry_block": risk.get("automatic_entry_block", False),
        },
        "scope": "Read-only standalone public-provider diagnostic for Engine 1. No MT5 quote, account, broker-calendar or other-engine payload is consumed; no orders or position operations are sent. Provider outages are diagnostic warnings, not model evidence.",
    }
    blockers, warnings = _acceptance_findings(report, now_ms=now_ms)
    report["acceptance"] = {
        "status": "PASS" if not blockers else "FAIL",
        "blockers": blockers,
        "warnings": warnings,
        "required_calendar_providers": ["showmytrades", "forex_factory"],
        "trading_economics_required": False,
        "scope": "Operational source-coverage gate only; not strategy-performance validation.",
    }
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only live diagnostics for Mirsad Engine 1 providers.")
    parser.add_argument("--output", default="engine1-live-source-report.json")
    args = parser.parse_args()

    # Engine 1 is standalone: this diagnostic only samples its public providers.
    # MT5 quotes, account identity, broker calendar and other-engine payloads
    # belong to the separate Engine 5 feed and are never passed into this collector.
    result = MarketIntelligenceEngine().collect()
    report = build_report(result)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))

    acceptance = report["acceptance"]
    if acceptance["status"] != "PASS":
        print("FAIL: Engine 1 strict operational acceptance did not pass.", file=sys.stderr)
        for blocker in acceptance["blockers"]:
            print(f" - {blocker}", file=sys.stderr)
        return 2
    print(
        "PASS: Engine 1 strict source acceptance passed: "
        f"{report['usable_directional_component_count']} directional components, "
        f"{len([v for v in report['derivatives']['venues'].values() if v['directional_status'] == 'FRESH'])} fresh derivatives venues, "
        "two independent public calendars, fresh news/sentiment/global metrics."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

