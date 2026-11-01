from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from ..config import ENABLE_ORDER_PUBLISH, MT5_COMMON_FILES

def _read_object(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}

class MT5BridgeEngine:
    """Program-side adapter. It never classifies account type and never calculates risk."""
    def __init__(self, common_files: str | None = None):
        configured = common_files if common_files is not None else MT5_COMMON_FILES
        self.root = Path(configured).expanduser() / "MirsadBTC" if configured else None

    def inspect(self) -> dict[str, Any]:
        if self.root is None:
            return {"engine": "mt5_bridge", "status": "NOT_CONFIGURED",
                    "message": "Set MIRSAD_MT5_COMMON_FILES to the terminal Common\\Files directory."}
        payload = _read_object(self.root / "status.json")
        if not payload:
            return {"engine": "mt5_bridge", "status": "WAITING_FOR_EXPERT",
                    "message": "No EA heartbeat file received yet."}
        heartbeat = int(payload.get("heartbeat_at_ms", 0) or 0)
        age = (int(time.time() * 1000) - heartbeat) / 1000 if heartbeat else None
        alive = bool(payload.get("terminal_connected")) and age is not None and 0 <= age <= 20
        return {
            "engine": "mt5_bridge", "status": "CONNECTED" if alive else "STALE",
            "heartbeat_age_seconds": round(age, 2) if age is not None else None,
            "account": payload.get("account", {}),
            "symbol": payload.get("symbol"),
            "symbol_spec": payload.get("symbol_spec", {}),
            "positions": payload.get("positions", []),
            "last_order_ack": _read_object(self.root / "ack.json"),
            "message": "Live EA telemetry." if alive else "EA heartbeat is missing or stale.",
        }

    def publish(self, command: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
        if not ENABLE_ORDER_PUBLISH:
            return {"status": "PUBLISH_DISABLED", "message": "Command publishing is disabled in configuration."}
        if state.get("status") != "CONNECTED" or self.root is None:
            return {"status": "BLOCKED", "message": "No fresh EA heartbeat; command was not published."}
        if command.get("action") not in {"BUY", "SELL", "CLOSE"}:
            return {"status": "REJECTED", "message": "Unsupported command action."}
        self.root.mkdir(parents=True, exist_ok=True)
        envelope = {
            "schema": "MIR1", "command_id": str(command["command_id"]),
            "created_at_ms": int(time.time() * 1000),
            "expires_at_ms": int(time.time() * 1000) + 60000,
            "symbol": str(command["symbol"]), "action": str(command["action"]),
            "volume": float(command["volume"]),
            "stop_loss": float(command.get("stop_loss") or 0),
            "take_profit": float(command.get("take_profit") or 0),
            "position_ticket": int(command.get("position_ticket") or 0),
        }
        target = self.root / "command.json"
        temp = target.with_suffix(".tmp")
        temp.write_text(json.dumps(envelope, separators=(",", ":")), encoding="utf-8")
        os.replace(temp, target)
        return {"status": "PUBLISHED", "command_id": envelope["command_id"]}
