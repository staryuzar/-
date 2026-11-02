from __future__ import annotations

import json
import math
import os
import re
import time
from pathlib import Path
from typing import Any

from ..config import ENABLE_ORDER_PUBLISH, MT5_COMMON_FILES, MT5_HEARTBEAT_MAX_AGE_SECONDS


def _read_object(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}


class MT5BridgeEngine:
    """Engine 5: bidirectional program/EA bridge. No direction or risk computation."""

    def __init__(self, common_files: str | None = None):
        configured = common_files if common_files is not None else MT5_COMMON_FILES
        self.root = Path(configured).expanduser() / "MirsadBTC" if configured else None

    def inspect(self) -> dict[str, Any]:
        base = {"engine": "engine_5_communication_bridge", "direction": "bidirectional_program_to_expert"}
        if self.root is None:
            return {**base, "status": "NOT_CONFIGURED",
                    "message": "Set MIRSAD_MT5_COMMON_FILES to the terminal Common\\\\Files directory."}
        payload = _read_object(self.root / "status.json")
        if not payload:
            return {**base, "status": "WAITING_FOR_EXPERT", "message": "No EA heartbeat file received yet."}
        heartbeat = int(payload.get("heartbeat_at_ms", 0) or 0)
        age = (int(time.time() * 1000) - heartbeat) / 1000 if heartbeat else None
        quote = payload.get("quote", {})
        quote_time = int(quote.get("time_ms", 0) or 0)
        quote_age = (int(time.time() * 1000) - quote_time) / 1000 if quote_time else None
        schema_ok = payload.get("schema") == "MIR1"
        alive = (
            bool(payload.get("terminal_connected")) and schema_ok
            and age is not None and 0 <= age <= MT5_HEARTBEAT_MAX_AGE_SECONDS
        )
        return {
            **base, "status": "CONNECTED" if alive else "STALE",
            "heartbeat_age_seconds": round(age, 2) if age is not None else None,
            "quote_age_seconds": round(quote_age, 2) if quote_age is not None else None,
            "account": payload.get("account", {}),
            "symbol": payload.get("symbol"),
            "market_symbol": payload.get("market_symbol"),
            "magic_number": payload.get("magic_number"),
            "quote": quote,
            "symbol_spec": payload.get("symbol_spec", {}),
            "positions": payload.get("positions", []),
            "last_order_ack": _read_object(self.root / "ack.json"),
            "message": "Fresh EA telemetry received." if alive else "EA heartbeat missing, stale or protocol schema mismatch.",
            "account_type_classification": "NOT_PERFORMED",
            "risk_calculation": "OWNED_BY_ENGINE_4",
        }

    @staticmethod
    def _validate_decision(decision: dict[str, Any]) -> dict[str, Any]:
        action = str(decision.get("action", "WAIT")).upper()
        if action not in {"BUY", "SELL", "CLOSE"}:
            raise ValueError("Only BUY, SELL or CLOSE commands can be published.")
        if decision.get("status") != "READY" or not decision.get("command_ready"):
            raise ValueError("Engine 4 has not marked this command ready.")
        symbol = str(decision.get("symbol", ""))
        market_symbol = str(decision.get("market_symbol", ""))
        command_id = str(decision.get("signal_id", ""))
        if not re.fullmatch(r"MIR-[A-Fa-f0-9]{24}", command_id):
            raise ValueError("Decision signal ID is missing or invalid.")
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,32}", symbol):
            raise ValueError("Invalid broker symbol.")
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,32}", market_symbol):
            raise ValueError("Invalid market symbol mapping.")
        risk = decision.get("risk_plan", {})
        try:
            volume = float(risk.get("volume", 0))
        except (TypeError, ValueError, OverflowError):
            raise ValueError("Command volume is invalid.")
        if not math.isfinite(volume) or volume <= 0:
            raise ValueError("Command volume must be finite and positive.")

        envelope: dict[str, Any] = {
            "schema": "MIR1", "command_id": command_id, "action": action,
            "symbol": symbol, "market_symbol": market_symbol, "volume": volume,
            "entry_reference": 0.0, "stop_loss": 0.0, "take_profit": 0.0,
            "position_ticket": 0,
        }
        if action in {"BUY", "SELL"}:
            if risk.get("status") != "READY":
                raise ValueError("Engine 4 has not completed risk-based position sizing.")
            try:
                entry = float(decision.get("entry_reference", 0))
                sl = float(decision.get("stop_loss", 0))
                tp = float(decision.get("take_profit", 0))
            except (TypeError, ValueError, OverflowError):
                raise ValueError("Order prices are invalid.")
            if not all(math.isfinite(x) and x > 0 for x in (entry, sl, tp)):
                raise ValueError("Order prices must be finite and positive.")
            if action == "BUY" and not sl < entry < tp:
                raise ValueError("BUY stop-loss/entry/take-profit levels are inconsistent.")
            if action == "SELL" and not tp < entry < sl:
                raise ValueError("SELL stop-loss/entry/take-profit levels are inconsistent.")
            envelope.update({"entry_reference": entry, "stop_loss": sl, "take_profit": tp})
        else:
            try:
                position_ticket = int(decision.get("position_ticket", 0))
            except (TypeError, ValueError, OverflowError):
                position_ticket = 0
            if position_ticket <= 0:
                raise ValueError("CLOSE requires a valid position ticket.")
            envelope["position_ticket"] = position_ticket
        return envelope

    def publish_decision(self, decision: dict[str, Any], bridge_state: dict[str, Any]) -> dict[str, Any]:
        try:
            envelope = self._validate_decision(decision)
        except (TypeError, ValueError, OverflowError) as exc:
            return {"status": "REJECTED", "reason": str(exc)}
        if not ENABLE_ORDER_PUBLISH:
            return {
                "status": "PUBLISH_DISABLED", "command_id": None,
                "message": "Publishing disabled; no command file or broker order was sent.",
            }
        if self.root is None or bridge_state.get("status") != "CONNECTED":
            return {"status": "BLOCKED", "message": "A fresh Engine 3 bridge heartbeat is required."}

        self.root.mkdir(parents=True, exist_ok=True)
        ack = _read_object(self.root / "ack.json")
        settled_states = {"REJECTED", "FILLED", "CANCELLED", "EXPIRED"}
        active_states = {"RECEIVED", "SUBMITTED", "PARTIAL", "UNKNOWN"}
        if ack.get("command_id") == envelope["command_id"] and ack.get("state") in (settled_states | active_states):
            return {
                "status": "ALREADY_ACKNOWLEDGED", "command_id": envelope["command_id"],
                "ack_state": ack.get("state"),
            }

        target = self.root / "command.json"
        current = _read_object(target)
        if current.get("command_id") == envelope["command_id"]:
            return {"status": "ALREADY_PUBLISHED", "command_id": envelope["command_id"]}
        current_id = current.get("command_id")
        if current_id:
            current_ack = _read_object(self.root / "ack.json")
            ack_matches = current_ack.get("command_id") == current_id
            settled = ack_matches and current_ack.get("state") in settled_states
            if not settled:
                return {
                    "status": "PENDING_COMMAND_BLOCKED", "pending_command_id": current_id,
                    "ack_state": current_ack.get("state") if ack_matches else "MISSING",
                    "message": "Existing command must be acknowledged/reconciled before a new command can replace it.",
                }

        now = int(time.time() * 1000)
        envelope.update({"created_at_ms": now, "expires_at_ms": now + 60000})
        temp = self.root / ("command." + envelope["command_id"] + ".tmp")
        temp.write_text(json.dumps(envelope, separators=(",", ":")), encoding="utf-8")
        os.replace(temp, target)
        return {
            "status": "PUBLISHED", "command_id": envelope["command_id"],
            "message": "MIR1 command envelope written; wait for the matching EA acknowledgement.",
        }
