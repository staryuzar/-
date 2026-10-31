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
    publish_close_order,
    publish_decision_order,
    read_ea_status,
    read_positions,
)
from .live_snapshot import build_live_snapshot
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
    payload = {
        "schema": "BTCIL-EXEC1",
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": result.get("status"),
        "plan": result.get("plan", {}),
        "command_id": last_command_id,
        "last_command_id": last_command_id,
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
    report_builder: Callable[[], dict[str, Any]] = build_live_snapshot,
    volume: float = 0.01,
) -> dict[str, Any]:
    """
    Run one central-decision -> EA command cycle.

    This module only publishes an expiring command to MT5 Common\Files.
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
    snapshot = report if report is not None else report_builder()
    terminal = read_ea_status(directory)
    if terminal.get("status") != "fresh":
        return _finish_cycle(directory, {
            "status": "terminal_not_ready",
            "terminal": terminal,
            "action": "HOLD",
        })

    positions = read_positions(directory)
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
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()

    if not 15 <= args.interval_seconds <= 300:
        parser.error("interval-seconds must be between 15 and 300.")
    if not 0 < args.volume <= 100:
        parser.error("volume must be greater than zero and at most 100.")
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
                result = execute_once(volume=args.volume)
                print(json.dumps(result, ensure_ascii=False, default=str), flush=True)
            except Exception as exc:
                print(json.dumps({
                    "status": "cycle_error",
                    "reason": f"{type(exc).__name__}: {str(exc)[:300]}",
                    "orders_sent": False,
                }, ensure_ascii=False), flush=True)
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
