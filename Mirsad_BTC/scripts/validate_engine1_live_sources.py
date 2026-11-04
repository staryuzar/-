from __future__ import annotations

import argparse
import json
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


def build_report(result: dict[str, Any]) -> dict[str, Any]:
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
            "long_short_ratio": raw.get("long_short_ratio"),
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
    return {
        "schema": "MIR-ENGINE1-LIVE-SOURCE-PREFLIGHT-1",
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
        "scope": "Read-only live provider diagnostic. No MT5 orders or position operations are sent. Provider outages are diagnostic warnings, not model evidence.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only live diagnostics for Mirsad Engine 1 providers.")
    parser.add_argument("--output", default="engine1-live-source-report.json")
    parser.add_argument(
        "--market-snapshot",
        type=Path,
        default=None,
        help="Optional sanitized MIR-MT5-MARKET-2 JSON snapshot to include the live broker calendar/context.",
    )
    args = parser.parse_args()

    market: dict[str, Any] = {}
    if args.market_snapshot is not None:
        try:
            loaded_market = json.loads(args.market_snapshot.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SystemExit(f"Cannot read MT5 market snapshot: {type(exc).__name__}: {exc}")
        if not isinstance(loaded_market, dict):
            raise SystemExit("MT5 market snapshot must be a JSON object.")
        if loaded_market.get("schema") != "MIR-MT5-MARKET-2":
            raise SystemExit("MT5 market snapshot does not match MIR-MT5-MARKET-2.")
        # The Observer writes the broker calendar at the snapshot root.
        # Runtime's MT5MarketDataEngine nests it under market_context; mirror
        # that normalized shape here so this CLI exercises the same collector.
        market = dict(loaded_market)
        context = market.get("market_context")
        context = dict(context) if isinstance(context, dict) else {}
        if not isinstance(context.get("economic_calendar"), dict):
            root_calendar = loaded_market.get("economic_calendar")
            if isinstance(root_calendar, dict):
                context["economic_calendar"] = root_calendar
        market["market_context"] = context

    result = MarketIntelligenceEngine().collect(market)
    report = build_report(result)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))

    if report["provider_response_count"] == 0:
        print("WARNING: no public Engine 1 provider returned a usable response during this run.", file=sys.stderr)
        return 2
    print(
        "PASS: Engine 1 live-source diagnostic received at least one provider response; "
        f"{report['usable_directional_component_count']} directional components passed their data gates."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
