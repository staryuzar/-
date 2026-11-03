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



def _read_json_array(path: Path) -> list[Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else None
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None


def _read_jsonl_tail(path: Path, *, limit: int = 100, max_bytes: int = 131072) -> list[dict[str, Any]]:
    """Read a bounded tail of the EA event journal without loading an unbounded file."""
    try:
        with path.open("rb") as stream:
            stream.seek(0, os.SEEK_END)
            size = stream.tell()
            start = max(0, size - max_bytes)
            stream.seek(start)
            payload = stream.read(max_bytes)
        lines = payload.decode("utf-8", errors="replace").splitlines()
        if start > 0 and lines:
            lines = lines[1:]
        rows: list[dict[str, Any]] = []
        for line in lines[-max(1, limit):]:
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                rows.append(item)
        return rows
    except OSError:
        return []


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
        # Telemetry is an external file boundary. Malformed fields must make
        # Engine 5 stale rather than raising and aborting the entire runtime cycle.
        now_ms = int(time.time() * 1000)
        try:
            heartbeat = int(payload.get("heartbeat_at_ms", 0) or 0)
        except (TypeError, ValueError, OverflowError):
            heartbeat = 0
        age = (now_ms - heartbeat) / 1000 if heartbeat > 0 else None

        quote_value = payload.get("quote")
        quote = quote_value if isinstance(quote_value, dict) else {}
        try:
            quote_time = int(quote.get("time_ms", 0) or 0)
        except (TypeError, ValueError, OverflowError):
            quote_time = 0
        quote_age = (now_ms - quote_time) / 1000 if quote_time > 0 else None

        account_value = payload.get("account")
        account = account_value if isinstance(account_value, dict) else {}
        spec_value = payload.get("symbol_spec")
        symbol_spec = spec_value if isinstance(spec_value, dict) else {}
        positions_value = payload.get("positions")
        positions = positions_value if isinstance(positions_value, list) else []
        schema_ok = payload.get("schema") == "MIR1"
        alive = (
            payload.get("terminal_connected") is True and schema_ok
            and age is not None and 0 <= age <= MT5_HEARTBEAT_MAX_AGE_SECONDS
        )
        ack = _read_object(self.root / "ack.json")
        command = _read_object(self.root / "command.json")
        reconciliation = self._reconcile_ack_with_positions(
            ack, command, positions, heartbeat
        )
        execution_value = payload.get("execution_enabled")
        execution_enabled = execution_value if isinstance(execution_value, bool) else None
        positions_file = _read_json_array(self.root / "positions.json")
        positions_file_valid = positions_file is not None and all(isinstance(item, dict) for item in positions_file)
        event_log = _read_jsonl_tail(self.root / "events.jsonl")
        files = {
            "status.json": (self.root / "status.json").is_file(),
            "command.json": (self.root / "command.json").is_file(),
            "ack.json": (self.root / "ack.json").is_file(),
            "positions.json": (self.root / "positions.json").is_file(),
            "events.jsonl": (self.root / "events.jsonl").is_file(),
        }
        return {
            **base, "status": "CONNECTED" if alive else "STALE",
            "schema": payload.get("schema"),
            "terminal_connected": payload.get("terminal_connected") is True,
            "execution_enabled": execution_enabled,
            "heartbeat_at_ms": heartbeat if heartbeat > 0 else None,
            "heartbeat_age_seconds": round(age, 2) if age is not None else None,
            "quote_age_seconds": round(quote_age, 2) if quote_age is not None else None,
            "account": account,
            "symbol": payload.get("symbol"),
            "market_symbol": payload.get("market_symbol"),
            "magic_number": payload.get("magic_number"),
            "quote": quote,
            "symbol_spec": symbol_spec,
            "positions": positions,
            "positions_file_valid": positions_file_valid,
            "current_command": command,
            "last_order_ack": ack,
            "position_reconciliation": reconciliation,
            "event_log": event_log,
            "common_files_directory": str(self.root),
            "common_files_files": files,
            "message": "Fresh EA telemetry received." if alive else "EA heartbeat missing, stale or protocol schema mismatch.",
            "account_type_classification": "NOT_PERFORMED",
            "risk_calculation": "OWNED_BY_ENGINE_4",
        }

    @staticmethod
    def _reconcile_ack_with_positions(
        ack: dict[str, Any],
        command: dict[str, Any],
        positions: list[dict[str, Any]],
        heartbeat_at_ms: int,
    ) -> dict[str, Any]:
        """Confirm a FILLED MIR1 acknowledgement against a later MT5 position snapshot.

        A broker return code alone is not treated as proof that the requested
        exposure/protective change is visible in the terminal's position state.
        """
        def outcome(status: str, reason: str, **extra: Any) -> dict[str, Any]:
            return {
                "status": status,
                "decision_eligible": False,
                "command_id": ack.get("command_id"),
                "reason": reason,
                **extra,
            }

        command_id = str(command.get("command_id", ""))
        if not command_id:
            return outcome("NO_PENDING_COMMAND", "No current MIR1 command is available.")
        if ack.get("command_id") != command_id:
            return outcome(
                "ACK_COMMAND_MISMATCH",
                "The latest ACK does not belong to the current command file.",
                expected_command_id=command_id,
            )

        state = str(ack.get("state", "")).upper()
        if state in {"RECEIVED", "SUBMITTED", "PARTIAL", "UNKNOWN"}:
            return outcome(
                "ACK_PENDING",
                "The broker outcome is not final; retain the command and do not replace it.",
                ack_state=state,
            )
        if state in {"REJECTED", "CANCELLED", "EXPIRED"}:
            return outcome("TERMINAL_NOT_FILLED", "The EA reported a terminal non-fill state.", ack_state=state)
        if state != "FILLED":
            return outcome("ACK_STATE_INVALID", "The ACK state is missing or unsupported.", ack_state=state)

        try:
            ack_at = int(ack.get("ack_at_ms", 0) or 0)
            heartbeat = int(heartbeat_at_ms or 0)
        except (TypeError, ValueError, OverflowError):
            ack_at = heartbeat = 0
        if ack_at <= 0 or heartbeat <= 0:
            return outcome("ACK_TIMESTAMP_INVALID", "ACK and heartbeat timestamps are required for reconciliation.")
        # MQL5's UTC millisecond helper is second-resolution. Equality can
        # therefore mean "telemetry was written immediately before the ACK".
        # Require a strictly later second to prove a post-ACK position read.
        if heartbeat <= ack_at:
            return outcome(
                "AWAITING_POST_ACK_TELEMETRY",
                "The current MT5 heartbeat is not strictly later than the FILLED ACK; wait for a newer positions snapshot.",
                ack_at_ms=ack_at,
                heartbeat_at_ms=heartbeat,
            )

        try:
            magic = int(command.get("magic_number", 0) or 0)
            tick_size = float(command.get("tick_size", 0) or 0)
            volume_step = float(command.get("volume_step", 0) or 0)
            action = str(command.get("action", "")).upper()
            symbol = str(command.get("symbol", "")).upper()
            ticket = int(command.get("position_ticket", 0) or 0)
            requested_volume = float(command.get("volume", 0) or 0)
            filled_volume = float(ack.get("filled_volume", 0) or 0)
        except (TypeError, ValueError, OverflowError):
            return outcome("COMMAND_FIELDS_INVALID", "Command/ACK reconciliation fields are not numeric.")
        if magic <= 0 or not symbol or action not in {"BUY", "SELL", "CLOSE", "MODIFY"}:
            return outcome("BASELINE_MISSING", "The command lacks a valid Mirsad magic number, symbol or action.")
        tolerance = max(1e-8, volume_step * 0.5 if math.isfinite(volume_step) and volume_step > 0 else 1e-8)
        before_raw = command.get("position_snapshot_before")
        if not isinstance(before_raw, list):
            return outcome("BASELINE_MISSING", "The command has no pre-request position snapshot.")
        def normalise(rows: list[Any]) -> list[dict[str, Any]]:
            cleaned = []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                try:
                    item = {
                        "ticket": int(row.get("ticket", 0) or 0),
                        "symbol": str(row.get("symbol", "")).upper(),
                        "type": int(row.get("type", -1)),
                        "magic": int(row.get("magic", -1)),
                        "volume": float(row.get("volume", 0) or 0),
                        "stop_loss": float(row.get("stop_loss", 0) or 0),
                        "take_profit": float(row.get("take_profit", 0) or 0),
                    }
                except (TypeError, ValueError, OverflowError):
                    continue
                if (
                    item["ticket"] > 0 and item["symbol"] and item["type"] in (0, 1)
                    and item["magic"] == magic
                    and all(math.isfinite(item[key]) for key in ("volume", "stop_loss", "take_profit"))
                    and item["volume"] > 0
                ):
                    cleaned.append(item)
            return cleaned

        before = normalise(before_raw)
        after = normalise(positions if isinstance(positions, list) else [])
        if action in {"BUY", "SELL"}:
            side_type = 0 if action == "BUY" else 1
            before_volume = sum(
                item["volume"] for item in before
                if item["symbol"] == symbol and item["type"] == side_type
            )
            after_volume = sum(
                item["volume"] for item in after
                if item["symbol"] == symbol and item["type"] == side_type
            )
            delta = max(0.0, after_volume - before_volume)
            expected = filled_volume if math.isfinite(filled_volume) and filled_volume > 0 else requested_volume
            if expected <= 0 or not math.isfinite(expected):
                return outcome("COMMAND_FIELDS_INVALID", "A positive requested/filled volume is required.")
            if delta + tolerance >= expected:
                return outcome(
                    "CONFIRMED", "The later MT5 snapshot contains the filled Mirsad position volume.",
                    action=action, expected_volume=expected, observed_volume_delta=round(delta, 8),
                )
            status = "PARTIAL_POSITION_CHANGE" if delta > tolerance else "AWAITING_POSITION_UPDATE"
            return outcome(
                status,
                "The later MT5 snapshot does not yet contain the full acknowledged position volume.",
                action=action, expected_volume=expected, observed_volume_delta=round(delta, 8),
            )

        baseline = next(
            (item for item in before if item["ticket"] == ticket and item["symbol"] == symbol),
            None,
        )
        current = next(
            (item for item in after if item["ticket"] == ticket and item["symbol"] == symbol),
            None,
        )
        if baseline is None:
            return outcome("BASELINE_MISSING", "The target Mirsad position was not present in the command's pre-request snapshot.")
        if action == "CLOSE":
            current_volume = current["volume"] if current else 0.0
            reduced = max(0.0, baseline["volume"] - current_volume)
            expected = filled_volume if math.isfinite(filled_volume) and filled_volume > 0 else requested_volume
            if expected <= 0 or not math.isfinite(expected):
                return outcome("COMMAND_FIELDS_INVALID", "A positive close/filled volume is required.")
            if reduced + tolerance >= expected:
                return outcome(
                    "CONFIRMED", "The target position volume has reduced by the acknowledged close amount.",
                    action=action, position_ticket=ticket, expected_reduction=expected,
                    observed_reduction=round(reduced, 8),
                )
            status = "PARTIAL_POSITION_CHANGE" if reduced > tolerance else "AWAITING_POSITION_UPDATE"
            return outcome(
                status, "The target position has not yet reflected the acknowledged close amount.",
                action=action, position_ticket=ticket, expected_reduction=expected,
                observed_reduction=round(reduced, 8),
            )

        if current is None:
            return outcome("POSITION_MISSING", "The target position disappeared before its protective update could be verified.")
        try:
            requested_sl = float(command.get("stop_loss", 0) or 0)
            requested_tp = float(command.get("take_profit", 0) or 0)
        except (TypeError, ValueError, OverflowError):
            return outcome("COMMAND_FIELDS_INVALID", "MODIFY protective prices are invalid.")
        price_tolerance = max(1e-8, tick_size * 0.51 if math.isfinite(tick_size) and tick_size > 0 else 1e-8)
        sl_matches = requested_sl > 0 and abs(current["stop_loss"] - requested_sl) <= price_tolerance
        tp_matches = abs(current["take_profit"] - requested_tp) <= price_tolerance
        tp_preserved = abs(current["take_profit"] - baseline["take_profit"]) <= price_tolerance
        if sl_matches and tp_matches and tp_preserved:
            return outcome(
                "CONFIRMED", "The target position shows the requested protective stop and unchanged take-profit.",
                action=action, position_ticket=ticket,
                observed_stop_loss=current["stop_loss"], observed_take_profit=current["take_profit"],
            )
        return outcome(
            "AWAITING_POSITION_UPDATE",
            "The target position does not yet show the requested stop with its original take-profit unchanged.",
            action=action, position_ticket=ticket,
            observed_stop_loss=current["stop_loss"], observed_take_profit=current["take_profit"],
        )

    @staticmethod
    def _validate_decision(decision: dict[str, Any]) -> dict[str, Any]:
        action = str(decision.get("action", "WAIT")).upper()
        if action not in {"BUY", "SELL", "CLOSE", "MODIFY"}:
            raise ValueError("Only BUY, SELL, CLOSE or MODIFY commands can be published.")
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
        elif action == "MODIFY":
            if risk.get("status") != "READY":
                raise ValueError("Engine 4 has not completed the protective-stop management plan.")
            try:
                position_ticket = int(decision.get("position_ticket", 0))
                stop_loss = float(decision.get("stop_loss", 0))
                take_profit = float(decision.get("take_profit", 0))
            except (TypeError, ValueError, OverflowError):
                raise ValueError("MODIFY ticket or protective price fields are invalid.")
            if position_ticket <= 0:
                raise ValueError("MODIFY requires a valid position ticket.")
            if not math.isfinite(stop_loss) or stop_loss <= 0:
                raise ValueError("MODIFY stop-loss must be finite and positive.")
            if not math.isfinite(take_profit) or take_profit < 0:
                raise ValueError("MODIFY take-profit must be finite and non-negative.")
            envelope.update({
                "position_ticket": position_ticket,
                "stop_loss": stop_loss,
                "take_profit": take_profit,
            })
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
            return {"status": "BLOCKED", "message": "A fresh Engine 5 bridge heartbeat is required."}
        if bridge_state.get("terminal_connected") is not True:
            return {
                "status": "TERMINAL_NOT_CONNECTED",
                "message": "The latest MIR1 telemetry does not prove that the MT5 terminal is connected.",
            }
        if bridge_state.get("execution_enabled") is not True:
            status = "EXECUTION_DISABLED" if bridge_state.get("execution_enabled") is False else "EXECUTION_STATE_UNKNOWN"
            message = (
                "The MT5 EA InpAllowExecution switch is false; no MIR1 command was written."
                if status == "EXECUTION_DISABLED"
                else "The EA execution_enabled telemetry is missing or invalid; no MIR1 command was written."
            )
            return {"status": status, "message": message}

        self.root.mkdir(parents=True, exist_ok=True)
        ack = _read_object(self.root / "ack.json")
        settled_failure_states = {"REJECTED", "CANCELLED", "EXPIRED"}
        active_states = {"RECEIVED", "SUBMITTED", "PARTIAL", "UNKNOWN"}
        if ack.get("command_id") == envelope["command_id"] and (
            ack.get("state") in (settled_failure_states | active_states | {"FILLED"})
        ):
            reconciliation = bridge_state.get("position_reconciliation")
            return {
                "status": (
                    "ALREADY_ACKNOWLEDGED"
                    if ack.get("state") != "FILLED" or (
                        isinstance(reconciliation, dict)
                        and reconciliation.get("command_id") == envelope["command_id"]
                        and reconciliation.get("status") == "CONFIRMED"
                    )
                    else "ACK_POSITION_RECONCILIATION_PENDING"
                ),
                "command_id": envelope["command_id"],
                "ack_state": ack.get("state"),
                "position_reconciliation": reconciliation if isinstance(reconciliation, dict) else None,
            }

        target = self.root / "command.json"
        current = _read_object(target)
        if current.get("command_id") == envelope["command_id"]:
            return {"status": "ALREADY_PUBLISHED", "command_id": envelope["command_id"]}
        current_id = current.get("command_id")
        if current_id:
            current_ack = _read_object(self.root / "ack.json")
            ack_matches = current_ack.get("command_id") == current_id
            ack_state = str(current_ack.get("state", "")).upper() if ack_matches else "MISSING"
            reconciliation = bridge_state.get("position_reconciliation")
            position_confirmed = (
                isinstance(reconciliation, dict)
                and reconciliation.get("command_id") == current_id
                and reconciliation.get("status") == "CONFIRMED"
            )
            settled = ack_matches and (
                ack_state in settled_failure_states
                or (ack_state == "FILLED" and position_confirmed)
            )
            if not settled:
                return {
                    "status": "PENDING_COMMAND_BLOCKED",
                    "pending_command_id": current_id,
                    "ack_state": ack_state,
                    "position_reconciliation": (
                        reconciliation if isinstance(reconciliation, dict) else None
                    ),
                    "message": "Existing command must reach a terminal ACK and, when FILLED, match the later MT5 position snapshot before replacement.",
                }

        # Preserve the exact pre-request exposure so a later FILLED ACK can be
        # reconciled against an MT5 heartbeat written after that ACK.
        positions_before = []
        raw_positions = bridge_state.get("positions")
        for item in raw_positions if isinstance(raw_positions, list) else []:
            if not isinstance(item, dict):
                continue
            snapshot = {}
            for key in ("ticket", "symbol", "type", "magic", "volume", "price_open", "stop_loss", "take_profit"):
                if key in item:
                    snapshot[key] = item[key]
            if snapshot:
                positions_before.append(snapshot)
        symbol_spec = bridge_state.get("symbol_spec") if isinstance(bridge_state.get("symbol_spec"), dict) else {}
        try:
            envelope["magic_number"] = int(bridge_state.get("magic_number", 0) or 0)
            envelope["tick_size"] = float(symbol_spec.get("tick_size", 0) or 0)
            envelope["volume_step"] = float(symbol_spec.get("volume_step", 0) or 0)
        except (TypeError, ValueError, OverflowError):
            envelope["magic_number"] = 0
            envelope["tick_size"] = 0.0
            envelope["volume_step"] = 0.0
        envelope["position_snapshot_before"] = positions_before

        now = int(time.time() * 1000)
        envelope.update({"created_at_ms": now, "expires_at_ms": now + 60000})
        temp = self.root / ("command." + envelope["command_id"] + ".tmp")
        temp.write_text(json.dumps(envelope, separators=(",", ":")), encoding="utf-8")
        os.replace(temp, target)
        return {
            "status": "PUBLISHED", "command_id": envelope["command_id"],
            "message": "MIR1 command envelope written; wait for the matching EA acknowledgement.",
        }
