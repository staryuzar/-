from __future__ import annotations

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
) -> dict[str, Any]:
    """Join independently observed components into one honest system state.

    This is a read-only status aggregator. It never publishes, changes, or
    authorizes a broker command; the execution loop and EA enforce that contract.
    """
    report = _mapping(snapshot)
    ea = _mapping(terminal)
    loop = _mapping(execution_loop)
    pending = _mapping(pending_command)
    decision = _mapping(report.get("decision"))
    sources = _mapping(report.get("source_states"))
    market_stream = _mapping(report.get("market_stream"))

    core_domains = ("spot", "technical", "orderflow", "derivatives")
    fresh_core = [
        name for name in core_domains
        if _mapping(sources.get(name)).get("status") == "fresh"
    ]
    missing_core = [name for name in core_domains if name not in fresh_core]

    stream_venues = market_stream.get("venues", [])
    if not isinstance(stream_venues, list):
        stream_venues = []
    live_stream_venues = [
        row for row in stream_venues
        if _mapping(row).get("status") in {"live", "connected", "connected_quiet_ok"}
    ]
    stream_status = (
        "live" if market_stream.get("status") == "ok" and live_stream_venues
        else ("partial" if market_stream.get("status") == "ok" else "unavailable")
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
    pending_now = bool(pending.get("pending"))
    execution_pipeline_ready = terminal_ready and execution_loop_ready

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
            "live_orderbook_venues": len(live_stream_venues),
            "orderbook_venues": [
                str(_mapping(row).get("venue", "unknown"))
                for row in live_stream_venues
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
        "headway_mt5": {
            "status": "ready" if terminal_ready else str(ea.get("status", "unavailable")),
            "symbol": symbol or None,
            "server": ea.get("account_server"),
            "age_seconds": ea.get("age_seconds"),
            "trading_ready": bool(ea.get("trading_ready")),
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
            and not pending_now
        ),
        "blockers": list(dict.fromkeys(blockers)),
        "interpretation": (
            "Execution components are fresh; a new entry still requires a current "
            "unblocked BUY/SELL decision and no unconfirmed command."
            if execution_pipeline_ready else
            "Market analysis and trade execution are separate readiness stages. "
            "A working dashboard does not mean the MT5 execution loop is active."
        ),
    }
