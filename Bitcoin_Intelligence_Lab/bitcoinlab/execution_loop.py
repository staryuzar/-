from __future__ import annotations

import argparse
import json
import os
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .ea_bridge import (
    default_common_files,
    pending_command_state,
    PositionSnapshotError,
    publish_close_order,
    publish_decision_order,
    read_ea_status,
    read_positions,
)
from .snapshot_runtime import read_latest_snapshot
from .position_manager import next_position_action


def _finish_cycle(directory: Path, result: dict[str, Any]) -> dict[str, Any]:
    """Publish a small heartbeat for the dashboard without exposing credentials."""
    folder = directory / "BitcoinIntelligenceLab"
    folder.mkdir(parents=True, exist_ok=True)
    command = result.get("command", {})
    previous: dict[str, Any] = {}
    try:
        previous = json.loads((folder / "execution_loop_status.json").read_text(encoding="utf-8"))
        if not isinstance(previous, dict):
            previous = {}
    except (OSError, UnicodeError, json.JSONDecodeError):
        previous = {}
    last_command_id = command.get("command_id") or previous.get("last_command_id") or previous.get("command_id")
    decision_action = (
        result.get("decision", {}).get("action")
        or previous.get("decision_action")
    )
    risk_sizing = command.get("risk_sizing") or previous.get("last_risk_sizing")
    levels = command.get("levels") or {
        "stop_loss": previous.get("last_stop_loss"),
        "take_profit": previous.get("last_take_profit"),
    }
    last_command_side = command.get("side") or previous.get("last_command_side")
    last_command_volume = command.get("volume") or previous.get("last_command_volume")
    last_command_status = command.get("status") or previous.get("last_command_status")
    payload = {
        "schema": "BTCIL-EXEC1",
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": result.get("status"),
        "plan": result.get("plan", {}),
        "command_id": last_command_id,
        "last_command_id": last_command_id,
        "last_command_status": last_command_status,
        "last_command_side": last_command_side,
        "last_command_volume": last_command_volume,
        "last_risk_sizing": risk_sizing,
        "last_stop_loss": levels.get("stop_loss") if isinstance(levels, dict) else None,
        "last_take_profit": levels.get("take_profit") if isinstance(levels, dict) else None,
        "decision_action": decision_action,
    }
    target = folder / "execution_loop_status.json"
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=folder,
            prefix="execution_loop_status.", suffix=".tmp", delete=False,
        ) as handle:
            temp_path = Path(handle.name)
            json.dump(payload, handle, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, target)
    except OSError:
        if temp_path is not None:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass
    return result


def execute_once(
    *,
    common_files: str | Path | None = None,
    report: dict[str, Any] | None = None,
    report_builder: Callable[[], dict[str, Any]] | None = None,
    snapshot_path: str | Path | None = None,
    max_snapshot_age_seconds: int = 90,
    volume: float = 0.01,
) -> dict[str, Any]:
    """
    Run one central-decision -> EA command cycle.

    This module only publishes an expiring command to MT5 Common\\Files.
    The EA validates broker permissions, price protection, broker volume,
    and the 0.5% equity-risk cap before sending an order to the terminal.
    """
    directory = Path(common_files) if common_files is not None else default_common_files()
    pending = pending_command_state(directory)
    if pending.get("pending"):
        return _finish_cycle(directory, {
            "status": "command_pending",
            "plan": {
                "action": "HOLD",
                "reason": "previous_broker_command_not_final",
            },
            "command": {
                "command_id": pending.get("command_id"),
                "status": pending.get("status"),
                "ack_status": pending.get("ack_status"),
            },
            "pending_command": pending,
        })
    if not 5 <= max_snapshot_age_seconds <= 900:
        raise ValueError("max_snapshot_age_seconds must be between 5 and 900.")
    try:
        snapshot = (
            report if report is not None
            else (
                report_builder() if report_builder is not None
                else read_latest_snapshot(snapshot_path, max_age_seconds=max_snapshot_age_seconds)
            )
        )
        observed = datetime.fromisoformat(
            str(snapshot.get("as_of_utc", "")).replace("Z", "+00:00")
        ).astimezone(timezone.utc)
        age_seconds = (datetime.now(timezone.utc) - observed).total_seconds()
    except Exception as exc:
        return _finish_cycle(directory, {
            "status": "snapshot_unavailable",
            "plan": {"action": "HOLD", "reason": "shared_market_snapshot_unavailable"},
            "decision": {"action": "HOLD", "blockers": ["shared_market_snapshot_unavailable"]},
            "error": f"{type(exc).__name__}: {str(exc)[:300]}",
            "orders_sent": False,
        })
    if age_seconds < -5 or age_seconds > max_snapshot_age_seconds:
        return _finish_cycle(directory, {
            "status": "snapshot_stale",
            "plan": {"action": "HOLD", "reason": "shared_market_snapshot_stale"},
            "decision": {"action": "HOLD", "blockers": ["shared_market_snapshot_stale"]},
            "snapshot_age_seconds": round(age_seconds, 2),
            "max_snapshot_age_seconds": max_snapshot_age_seconds,
            "orders_sent": False,
        })
    terminal = read_ea_status(directory)
    if terminal.get("status") != "fresh":
        return _finish_cycle(directory, {
            "status": "terminal_not_ready",
            "terminal": terminal,
            "action": "HOLD",
        })

    try:
        positions = read_positions(directory)
    except PositionSnapshotError as exc:
        return _finish_cycle(directory, {
            "status": "positions_unavailable",
            "plan": {"action": "HOLD", "reason": "managed_position_snapshot_unavailable"},
            "decision": snapshot.get("decision", {}),
            "error": str(exc)[:300],
            "orders_sent": False,
        })
    plan = next_position_action(snapshot.get("decision", {}), positions)
    action = str(plan.get("action", "HOLD")).upper()

    if action == "OPEN":
        published = publish_decision_order(
            report=snapshot,
            common_files=directory,
            volume=volume,
        )
        return _finish_cycle(directory, {
            "status": published.get("status", "unknown"),
            "plan": plan,
            "command": published,
            "decision": snapshot.get("decision", {}),
        })

    if action == "CLOSE":
        published = publish_close_order(
            ticket=int(plan["ticket"]),
            common_files=directory,
        )
        return _finish_cycle(directory, {
            "status": published.get("status", "unknown"),
            "plan": plan,
            "command": published,
            "decision": snapshot.get("decision", {}),
        })

    return _finish_cycle(directory, {
        "status": "no_command",
        "plan": plan,
        "decision": snapshot.get("decision", {}),
        "positions": positions,
    })


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Persistent Bitcoin Intelligence Lab -> MT5 shared-file executor."
    )
    parser.add_argument("--interval-seconds", type=int, default=30)
    parser.add_argument("--volume", type=float, default=0.01)
    parser.add_argument("--snapshot-path", default=None)
    parser.add_argument("--max-snapshot-age-seconds", type=int, default=90)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()

    if not 15 <= args.interval_seconds <= 300:
        parser.error("interval-seconds must be between 15 and 300.")
    if not 0 < args.volume <= 100:
        parser.error("volume must be greater than zero and at most 100.")
    if not 5 <= args.max_snapshot_age_seconds <= 900:
        parser.error("max-snapshot-age-seconds must be between 5 and 900.")
    if os.environ.get("BTCIL_ENABLE_EXECUTION") != "1":
        print(json.dumps({
            "status": "blocked",
            "reason": "Set BTCIL_ENABLE_EXECUTION=1 only when the Headway MT5 terminal is intentionally running.",
            "orders_sent": False,
        }, ensure_ascii=False))
        return 2

    try:
        while True:
            try:
                result = execute_once(
                    volume=args.volume,
                    snapshot_path=args.snapshot_path,
                    max_snapshot_age_seconds=args.max_snapshot_age_seconds,
                )
                print(json.dumps(result, ensure_ascii=False, default=str), flush=True)
            except Exception as exc:
                error_result = {
                    "status": "cycle_error",
                    "plan": {"action": "HOLD", "reason": "execution_cycle_exception"},
                    "decision": {"action": "HOLD", "blockers": ["execution_cycle_exception"]},
                    "reason": f"{type(exc).__name__}: {str(exc)[:300]}",
                    "orders_sent": False,
                }
                try:
                    error_result = _finish_cycle(default_common_files(), error_result)
                except Exception:
                    pass
                print(json.dumps(error_result, ensure_ascii=False, default=str), flush=True)
            if args.once:
                return 0
            time.sleep(args.interval_seconds)
    except KeyboardInterrupt:
        print(json.dumps({
            "status": "stopped",
            "reason": "Execution loop stopped by operator; open positions remain protected by broker-side SL/TP.",
        }, ensure_ascii=False))
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
