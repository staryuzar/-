from __future__ import annotations

import math
from typing import Any, Mapping, Sequence


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def build_system_readiness(
    *,
    snapshot: Mapping[str, Any] | None,
    terminal: Mapping[str, Any] | None,
    execution_loop: Mapping[str, Any] | None,
    positions: Sequence[Mapping[str, Any]] | None = None,
    pending_command: Mapping[str, Any] | None = None,
    snapshot_service: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Join independently observed components into one honest system state.

    This is a read-only status aggregator. It never publishes, changes, or
    authorizes a broker command; the execution loop and EA enforce that contract.
    """
    report = _mapping(snapshot)
    ea = _mapping(terminal)
    loop = _mapping(execution_loop)
    pending = _mapping(pending_command)
    service = _mapping(snapshot_service)
    decision = _mapping(report.get("decision"))
    sources = _mapping(report.get("source_states"))
    data_health = _mapping(report.get("data_health"))
    stream_health_rows = data_health.get("stream_feeds", [])
    if not isinstance(stream_health_rows, list):
        stream_health_rows = []
    live_orderbook_feeds = [
        row for row in stream_health_rows
        if _mapping(row).get("feed_type") == "orderbook"
        and _mapping(row).get("status") == "live"
    ]
    live_trade_feeds = [
        row for row in stream_health_rows
        if _mapping(row).get("feed_type") == "trades"
        and _mapping(row).get("status") == "live"
    ]
    quiet_liquidation_feeds = [
        row for row in stream_health_rows
        if _mapping(row).get("feed_type") == "liquidations"
        and _mapping(row).get("status") == "connected_quiet_ok"
    ]
    degraded_stream_feeds = [
        row for row in stream_health_rows
        if _mapping(row).get("status") in {"stale", "unavailable", "recovering", "error"}
    ]

    core_domains = ("spot", "technical", "orderflow", "derivatives")
    fresh_core = [
        name for name in core_domains
        if _mapping(sources.get(name)).get("status") == "fresh"
    ]
    missing_core = [name for name in core_domains if name not in fresh_core]

    live_orderbook_venues = sorted({
        str(_mapping(row).get("name", "unknown")) for row in live_orderbook_feeds
    })
    live_trade_venues = sorted({
        str(_mapping(row).get("name", "unknown")) for row in live_trade_feeds
    })
    stream_status = (
        "live" if len(live_orderbook_venues) >= 2 and live_trade_venues
        else ("partial" if live_orderbook_venues or live_trade_venues else "unavailable")
    )

    action = str(decision.get("action", "HOLD")).upper()
    decision_blockers = decision.get("blockers", [])
    if not isinstance(decision_blockers, list):
        decision_blockers = ["invalid_decision_blockers"]
    decision_ready = (
        bool(report)
        and action in {"BUY", "SELL", "HOLD"}
        and decision.get("score") is not None
        and not decision_blockers
    )
    decision_state = (
        "direction_ready" if decision_ready and action in {"BUY", "SELL"}
        else ("hold" if report and action == "HOLD" else "unavailable")
    )

    symbol = str(ea.get("symbol", "")).upper()
    terminal_ready = (
        ea.get("status") == "fresh"
        and bool(ea.get("headway_server_ok"))
        and bool(ea.get("trading_ready"))
        and "BTC" in symbol
    )
    execution_loop_ready = loop.get("status") == "fresh"
    risk_specs_ready = bool(ea.get("risk_specs_ready"))
    daily_loss = ea.get("daily_loss_percent")
    daily_loss_limit = ea.get("daily_loss_limit_percent")
    daily_risk_status_ready = (
        isinstance(daily_loss, (int, float))
        and isinstance(daily_loss_limit, (int, float))
        and math.isfinite(float(daily_loss))
        and math.isfinite(float(daily_loss_limit))
        and 0 <= float(daily_loss) < float(daily_loss_limit)
        and float(daily_loss_limit) > 0
    )
    pending_now = bool(pending.get("pending"))
    snapshot_service_ready = (
        service.get("status") == "healthy"
        and service.get("freshness_status") == "fresh"
    )
    execution_pipeline_ready = (
        terminal_ready and execution_loop_ready and snapshot_service_ready
    )

    position_rows = list(positions or [])
    btc_positions = [
        row for row in position_rows
        if "BTC" in str(_mapping(row).get("symbol", "")).upper()
    ]

    blockers: list[str] = []
    if not report:
        blockers.append("market_snapshot_unavailable")
    if missing_core:
        blockers.extend(f"{name}_evidence_not_fresh" for name in missing_core)
    if not decision_ready:
        blockers.extend(str(item) for item in decision_blockers)
        if not decision_blockers and decision_state == "unavailable":
            blockers.append("central_decision_unavailable")
    if not terminal_ready:
        blockers.append(f"headway_terminal_{ea.get('status', 'unavailable')}")
    if not execution_loop_ready:
        blockers.append(f"execution_loop_{loop.get('status', 'unavailable')}")
    if not snapshot_service_ready:
        service_problem = service.get("status", "unavailable")
        if service_problem == "healthy":
            service_problem = service.get("freshness_status", "stale")
        blockers.append(f"snapshot_service_{service_problem}")
    if terminal_ready and not risk_specs_ready:
        blockers.append("mt5_broker_risk_specs_unavailable")
    if terminal_ready and not daily_risk_status_ready:
        blockers.append(
            "mt5_daily_loss_limit_reached"
            if isinstance(daily_loss, (int, float))
            and isinstance(daily_loss_limit, (int, float))
            and float(daily_loss) >= float(daily_loss_limit)
            else "mt5_daily_risk_status_unavailable"
        )
    if pending_now:
        blockers.append("broker_command_pending_acknowledgement")

    return {
        "status": (
            "execution_ready" if execution_pipeline_ready
            else ("analysis_ready" if report and decision_state != "unavailable"
                  else "system_degraded")
        ),
        "market_data": {
            "status": stream_status,
            "live_orderbook_venues": len(live_orderbook_venues),
            "orderbook_venue_names": live_orderbook_venues,
            "live_trade_venues": live_trade_venues,
            "connected_quiet_liquidation_feeds": [
                str(_mapping(row).get("name", "unknown"))
                for row in quiet_liquidation_feeds
            ],
            "non_live_stream_feeds": [
                {
                    "name": _mapping(row).get("name"),
                    "feed_type": _mapping(row).get("feed_type"),
                    "status": _mapping(row).get("status"),
                    "last_error": _mapping(row).get("last_error"),
                }
                for row in degraded_stream_feeds
            ],
            "core_fresh_domains": fresh_core,
            "core_missing_domains": missing_core,
            "snapshot_status": report.get("status", "unavailable"),
        },
        "central_decision": {
            "status": decision_state,
            "action": action,
            "score": decision.get("score"),
            "active_domains": list(decision.get("active_domains", []))
            if isinstance(decision.get("active_domains", []), (list, tuple)) else [],
            "blockers": list(decision_blockers),
            "warnings": list(decision.get("warnings", []))
            if isinstance(decision.get("warnings", []), (list, tuple)) else [],
        },
        "snapshot_service": {
            "status": (
                "healthy" if snapshot_service_ready
                else str(service.get("status", "unavailable"))
            ),
            "freshness_status": service.get("freshness_status", "unavailable"),
            "age_seconds": service.get("age_seconds"),
            "last_success_utc": service.get("last_success_utc"),
            "last_error": service.get("last_error"),
        },
        "headway_mt5": {
            "status": "ready" if terminal_ready else str(ea.get("status", "unavailable")),
            "symbol": symbol or None,
            "server": ea.get("account_server"),
            "age_seconds": ea.get("age_seconds"),
            "trading_ready": bool(ea.get("trading_ready")),
            "risk_sizing_ready": risk_specs_ready,
            "daily_risk_status_ready": daily_risk_status_ready,
            "daily_loss_percent": daily_loss,
            "daily_loss_limit_percent": daily_loss_limit,
            "account_equity": ea.get("account_equity"),
            "tick_size": ea.get("tick_size"),
            "tick_value_loss": ea.get("tick_value_loss"),
            "volume_min": ea.get("volume_min"),
            "volume_step": ea.get("volume_step"),
            "volume_max": ea.get("volume_max"),
        },
        "execution_loop": {
            "status": "active" if execution_loop_ready else str(loop.get("status", "unavailable")),
            "age_seconds": loop.get("age_seconds"),
            "cycle_status": loop.get("cycle_status"),
            "last_command_id": loop.get("last_command_id") or loop.get("command_id"),
        },
        "position_management": {
            "managed_btc_positions": len(btc_positions),
            "pending_command": pending_now,
            "pending_status": pending.get("status", "none"),
            "pending_command_id": pending.get("command_id"),
        },
        "execution_pipeline_ready": execution_pipeline_ready,
        "new_entry_ready": (
            execution_pipeline_ready
            and decision_ready
            and action in {"BUY", "SELL"}
            and risk_specs_ready
            and daily_risk_status_ready
            and not pending_now
        ),
        "blockers": list(dict.fromkeys(blockers)),
        "interpretation": (
            "Execution components are fresh; a new entry still requires a current "
            "unblocked BUY/SELL decision, valid Headway tick-value/volume specifications, and no unconfirmed command."
            if execution_pipeline_ready else
            "Market analysis and trade execution are separate readiness stages. "
            "A working dashboard does not mean the MT5 execution loop is active."
        ),
    }
