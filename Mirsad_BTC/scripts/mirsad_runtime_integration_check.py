from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any

from mirsad import runtime
from mirsad.engines.mt5_bridge import MT5BridgeEngine


def read_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Cannot read required MT5 feed {path.name}: {exc}") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"MT5 feed {path.name} must contain a JSON object.")
    return value


def read_shared_feeds(common_root: Path) -> dict[str, dict[str, Any]]:
    mirsad = common_root / "MirsadBTC"
    observer = mirsad / "observer"
    paths = {
        "execution_status": mirsad / "status.json",
        "broker_market": mirsad / "market.json",
        "native_candles": observer / "candles.json",
        "native_indicators": observer / "indicators.json",
    }
    snapshots: dict[str, dict[str, Any]] = {}
    for name, path in paths.items():
        if not path.is_file() or path.stat().st_size <= 0:
            raise RuntimeError(f"Shared Common Files feed is missing or empty: {path}")
        snapshots[name] = read_object(path)
    return snapshots


def evaluate_engine4_runtime(decision: dict[str, Any]) -> dict[str, Any]:
    """Distinguish a completed safe WAIT from an eligible directional entry."""
    action = str(decision.get("action", "UNKNOWN")).upper()
    candidate = str(decision.get("candidate_action", "WAIT")).upper()
    status = str(decision.get("status", "NOT_READY")).upper()
    command_ready = decision.get("command_ready") is True
    context = decision.get("engine_2_native_price_action_context")
    context = context if isinstance(context, dict) else {}
    entry_eligible = context.get("decision_eligible") is True
    gate = str(
        decision.get("chart_gate", "NOT_EVALUATED")
        if status == "WAITING_FOR_ENGINE_3_PARITY"
        else context.get("gate", decision.get("chart_gate", "NOT_EVALUATED"))
    ).upper()

    cycle_completed = action in {"BUY", "SELL", "WAIT", "CLOSE", "MODIFY"} and status in {
        "READY", "WAITING_FOR_ENGINE_2", "WAITING_FOR_ENGINE_3_PARITY"
    }
    safe_wait = (
        action == "WAIT"
        and candidate == "WAIT"
        and not command_ready
        and (
            (entry_eligible and status == "READY")
            or (
                not entry_eligible
                and status in {"WAITING_FOR_ENGINE_2", "WAITING_FOR_ENGINE_3_PARITY"}
                and gate in {
                    "NOT_READY",
                    "MIXED_OR_NO_CONFLUENCE",
                    "BULLISH_CONFLUENCE",
                    "BEARISH_CONFLUENCE",
                    "CANDLE_PATTERN_DIRECTION_CONFLICT",
                    "MIXED_CANDLE_PATTERN_EVIDENCE",
                    "NOT_EVALUATED",
                    "NATIVE_OHLC_NOT_PROVIDED",
                    "WAITING_FOR_ENGINE_3_NATIVE_PARITY",
                }
            )
        )
    )
    protective_action = action in {"CLOSE", "MODIFY"}
    directional_entry = action in {"BUY", "SELL"}
    gate_consistent = (
        (protective_action and cycle_completed)
        or (directional_entry and entry_eligible and status == "READY")
        or safe_wait
    )

    if directional_entry and entry_eligible and status == "READY":
        readiness = "DIRECTIONAL_ENTRY_ELIGIBLE"
    elif protective_action:
        readiness = "POSITION_PROTECTION_ACTION"
    elif safe_wait and not entry_eligible:
        readiness = "SAFE_WAIT_NO_ENGINE2_DIRECTION"
    elif safe_wait:
        readiness = "SAFE_WAIT_COMPOSITE_SCORE_OR_OTHER_GATE"
    else:
        readiness = "INCONSISTENT_OR_INCOMPLETE"

    return {
        "cycle_completed": cycle_completed,
        "gate_consistent": gate_consistent,
        "safe_wait": safe_wait,
        "entry_eligible": entry_eligible,
        "readiness": readiness,
        "engine2_gate": gate,
        "engine4_status": status,
        "action": action,
        "candidate_action": candidate,
        "command_ready": command_ready,
    }


def run(common_root: Path, output: Path) -> dict[str, Any]:
    if runtime.ENABLE_ORDER_PUBLISH is not True:
        raise RuntimeError("MIRSAD_ENABLE_ORDER_PUBLISH must remain enabled for this integrated runtime check.")
    if os.environ.get("MIRSAD_ENABLE_ORDER_PUBLISH", "1").strip().lower() not in {"1", "true", "yes", "on"}:
        raise RuntimeError("Order publishing environment setting is not enabled.")

    common_root = common_root.resolve()
    feeds = read_shared_feeds(common_root)
    bridge = MT5BridgeEngine(common_files=str(common_root))
    captured_commands: list[dict[str, Any]] = []

    def capture_validated_command(
        self: MT5BridgeEngine,
        decision: dict[str, Any],
        bridge_state: dict[str, Any],
    ) -> dict[str, Any]:
        envelope = self._validate_decision(decision)
        captured_commands.append({
            "command_id": envelope["command_id"],
            "action": envelope["action"],
            "symbol": envelope["symbol"],
            "market_symbol": envelope["market_symbol"],
            "volume": envelope["volume"],
            "stop_loss": envelope["stop_loss"],
            "take_profit": envelope["take_profit"],
            "position_ticket": envelope["position_ticket"],
            "bridge_state": bridge_state.get("status"),
        })
        return {
            "status": "INTEGRATION_CAPTURED_VALID_MIR1",
            "command_id": envelope["command_id"],
            "message": "MIR1 envelope passed the production validator; the integration harness did not submit a second broker order.",
        }

    original_publish = MT5BridgeEngine.publish_decision
    MT5BridgeEngine.publish_decision = capture_validated_command
    try:
        report = runtime.collect_once(bridge_engine=bridge)
    finally:
        MT5BridgeEngine.publish_decision = original_publish

    bridge_state = report.get("bridge") or {}
    market = report.get("market") or {}
    candles = report.get("engine_2_candles") or {}
    indicators = report.get("indicators") or {}
    native_indicators = report.get("mt5_native_indicators") or {}
    price_action = report.get("engine_2_price_action") or {}
    intelligence = report.get("market_intelligence") or {}
    decision = report.get("decision") or {}
    controls = report.get("execution_controls") or {}
    readiness = report.get("readiness") or {}

    decision_context = decision.get("engine_2_native_price_action_context")
    if not isinstance(decision_context, dict):
        decision_context = {}

    engine4_runtime = evaluate_engine4_runtime(decision)
    engine2_summary = price_action.get("summary")
    if not isinstance(engine2_summary, dict):
        engine2_summary = {}

    checks = {
        "engine5_bridge_connected": bridge_state.get("status") == "CONNECTED",
        "mt5_terminal_connected": bridge_state.get("terminal_connected") is True,
        "mt5_execution_permissions_enabled": (
            bridge_state.get("execution_enabled") is True
            and bridge_state.get("execution_input_enabled") is True
            and bridge_state.get("trade_permissions_available") is True
        ),
        "order_publishing_enabled": controls.get("order_publish_enabled") is True,
        "engine5_command_gate_ready": (
            controls.get("order_execution_ready") is True
            and readiness.get("engine_5_command_execution_gate") is True
        ),
        "broker_quote_live": (
            market.get("status") == "LIVE"
            and readiness.get("engine_5_execution_quote_feed") is True
        ),
        "engine2_native_ohlc_ready": (
            candles.get("status") == "READY"
            and readiness.get("engine_2_candles") is True
        ),
        "engine2_price_action_processed": price_action.get("status") == "READY",
        "engine3_calculated_indicators_ready": (
            indicators.get("status") == "READY"
            and readiness.get("engine_3_indicators") is True
        ),
        "engine3_native_mt5_buffers_ready": (
            native_indicators.get("status") == "READY"
            and readiness.get("mt5_native_indicator_feed") is True
        ),
        "engine3_numeric_parity_pass": (
            (indicators.get("mt5_native_parity") or {}).get("status") == "PASS"
            and readiness.get("engine_3_mt5_numeric_parity") is True
        ),
        "daily_risk_policy_consistent": readiness.get("engine_4_daily_risk_guard") is True,
        "engine4_decision_cycle_completed": engine4_runtime["cycle_completed"],
        "engine4_decision_gate_consistent": engine4_runtime["gate_consistent"],
    }

    summary = {
        "schema": "MIRSAD-LIVE-RUNTIME-INTEGRATION-1",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "captured_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "common_files_root": str(common_root),
        "checks": checks,
        "source_feeds": {
            "market_schema": feeds["broker_market"].get("schema"),
            "execution_schema": feeds["execution_status"].get("schema"),
            "candles_schema": feeds["native_candles"].get("schema"),
            "indicators_schema": feeds["native_indicators"].get("schema"),
            "shared_feed_count": len(feeds),
        },
        "engines": {
            "engine1": {
                "status": intelligence.get("status"),
                "direction": intelligence.get("direction"),
                "evidence_coverage": intelligence.get("evidence_coverage"),
            },
            "engine2": {
                "status": price_action.get("status"),
                "direction": price_action.get("direction"),
                "decision_eligible": decision_context.get("decision_eligible"),
                "structure_score": price_action.get("structure_score"),
                "timeframe_alignment": engine2_summary.get("timeframe_alignment"),
                "eligible_timeframes": engine2_summary.get("eligible_timeframes", []),
                "timeframe_weight_coverage": engine2_summary.get("timeframe_weight_coverage"),
                "directional_structure_agreement": engine2_summary.get("directional_structure_agreement"),
                "latest_candle_pattern_alignment": engine2_summary.get("latest_candle_pattern_alignment"),
            },
            "engine3": {
                "calculated_status": indicators.get("status"),
                "native_status": native_indicators.get("status"),
                "signal_score": indicators.get("signal_score"),
                "signal_quality": indicators.get("signal_quality"),
                "numeric_parity_status": (indicators.get("mt5_native_parity") or {}).get("status"),
                "numeric_parity_passed_metrics": (indicators.get("mt5_native_parity") or {}).get("passed_metrics"),
                "numeric_parity_total_metrics": (indicators.get("mt5_native_parity") or {}).get("total_metrics"),
            },
            "engine4": {
                "status": decision.get("status"),
                "action": decision.get("action"),
                "command_ready": decision.get("command_ready"),
                "reason": decision.get("reason"),
                "chart_gate": decision.get("chart_gate"),
                "engine2_gate": engine4_runtime["engine2_gate"],
                "decision_readiness": engine4_runtime["readiness"],
                "entry_eligible": engine4_runtime["entry_eligible"],
                "candidate_action": engine4_runtime["candidate_action"],
            },
            "engine5": {
                "status": bridge_state.get("status"),
                "execution_enabled": bridge_state.get("execution_enabled"),
                "execution_input_enabled": bridge_state.get("execution_input_enabled"),
                "trade_permissions_available": bridge_state.get("trade_permissions_available"),
                "quote_age_seconds": bridge_state.get("quote_age_seconds"),
            },
        },
        "validated_mir1_envelopes": captured_commands,
        "decision_readiness": engine4_runtime["readiness"],
        "directional_entry_eligible": engine4_runtime["entry_eligible"],
        "overall_runtime_status": report.get("overall_status"),
        "notes": [
            "All five engines were evaluated in one runtime.collect_once cycle against one live MT5 Common Files directory.",
            "Production order publishing and MT5 expert execution permissions remained enabled.",
            "Any command-ready MIR1 envelope was checked by the production validator and observed by the harness; this diagnostic did not create an extra broker order.",
            "A safe WAIT caused by mixed or insufficient Engine 2 structure is a successful completed decision cycle, but it is explicitly not a directional entry or a claim of trade readiness.",
            "PASS means the five-engine live data/decision pipeline completed consistently; directional entry eligibility is reported separately.",
            "The independent broker BUY/CLOSE acceptance transaction is validated by the separate MT5 execution workflow.",
            "Engine 1 provider reachability is reported as observed and is not assumed to be complete from a hosted runner.",
            "Engine 3 directional votes are accepted by Engine 4 only after 120/120 numeric MT5 CopyBuffer parity metrics pass on the same closed Engine 2 bars.",
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    if summary["status"] != "PASS":
        raise RuntimeError("Integrated runtime cycle or decision gate was inconsistent: " + json.dumps(checks, ensure_ascii=False))
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--common-files", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = run(args.common_files, args.report)
    except Exception as exc:
        payload = {
            "schema": "MIRSAD-LIVE-RUNTIME-INTEGRATION-1",
            "status": "FAIL",
            "error": f"{type(exc).__name__}: {exc}",
        }
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(payload, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
