from __future__ import annotations

import json
import math
import os
import re
import time
from pathlib import Path
from typing import Any

from ..config import (
    ENABLE_ORDER_PUBLISH,
    MT5_COMMON_FILES,
    MT5_HEARTBEAT_MAX_AGE_SECONDS,
    MT5_QUOTE_MAX_AGE_SECONDS,
)


def _read_json_snapshot(path: Path) -> Any:
    """Read one complete JSON snapshot, tolerating a brief rename/lock race."""
    for attempt in range(6):
        try:
            raw = path.read_text(encoding="utf-8-sig")
            if not raw.strip():
                raise json.JSONDecodeError("empty snapshot", raw, 0)
            return json.loads(raw)
        except (OSError, UnicodeError, json.JSONDecodeError):
            if attempt < 5:
                # Bounded consistency retry only; heartbeat age is still checked
                # against the original strict MT5_HEARTBEAT_MAX_AGE_SECONDS.
                time.sleep(0.015 * (attempt + 1))
    return None


def _read_object(path: Path) -> dict[str, Any]:
    data = _read_json_snapshot(path)
    return data if isinstance(data, dict) else {}


def _read_json_array(path: Path) -> list[Any] | None:
    data = _read_json_snapshot(path)
    return data if isinstance(data, list) else None


def _validate_positions_snapshot(raw: Any) -> tuple[list[dict[str, Any]], bool, str | None]:
    """Validate the complete position list before treating an empty list as no exposure."""
    if not isinstance(raw, list):
        return [], False, "MIR1 status positions must be a JSON array."

    required = (
        "ticket", "position_id", "symbol", "type", "magic", "volume",
        "price_open", "stop_loss", "take_profit", "profit",
    )
    validated: list[dict[str, Any]] = []
    seen_tickets: set[int] = set()
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            return [], False, f"MIR1 position {index} is not an object."
        if any(name not in item for name in required):
            return [], False, f"MIR1 position {index} is missing required ownership or price fields."
        try:
            ticket = int(item["ticket"])
            position_id = int(item["position_id"])
            side = int(item["type"])
            magic = int(item["magic"])
            volume = float(item["volume"])
            price_open = float(item["price_open"])
            stop_loss = float(item["stop_loss"])
            take_profit = float(item["take_profit"])
            profit = float(item["profit"])
        except (TypeError, ValueError, OverflowError):
            return [], False, f"MIR1 position {index} has invalid numeric fields."
        symbol = str(item.get("symbol", "")).strip()
        numeric = (volume, price_open, stop_loss, take_profit, profit)
        if (
            ticket <= 0 or position_id <= 0 or side not in (0, 1) or magic < 0
            or not symbol or ticket in seen_tickets
            or any(not math.isfinite(value) for value in numeric)
            or volume <= 0 or price_open <= 0 or stop_loss < 0 or take_profit < 0
        ):
            return [], False, f"MIR1 position {index} failed identity, ownership, volume or price validation."
        seen_tickets.add(ticket)
        validated.append(item)
    return validated, True, None


def _read_mt5_deal_history(
    path: Path,
    *,
    expected_symbol: str,
    expected_magic: int,
) -> dict[str, Any]:
    """Read and strictly validate the bounded MIR1 broker-deal history file."""
    payload = _read_object(path)
    if not payload:
        return {
            "status": "NOT_REPORTED",
            "deals": [],
            "reason": "The MT5 execution EA has not published deals.json yet.",
        }
    if payload.get("schema") != "MIR1-DEALS-1":
        return {
            "status": "INVALID",
            "deals": [],
            "reason": "The MT5 deal-history schema is not supported.",
        }
    producer_status = str(payload.get("status", "")).upper()
    if producer_status == "UNAVAILABLE":
        return {
            "status": "UNAVAILABLE",
            "deals": [],
            "reason": f"MT5 HistorySelect is unavailable (error={payload.get('history_error', 'unknown')}).",
        }
    if producer_status != "READY":
        return {
            "status": "INVALID",
            "deals": [],
            "reason": "The MT5 deal-history producer status is not valid.",
        }
    try:
        queried_at = int(payload["queried_at_utc_ms"])
        window_start = int(payload["window_start_server_ms"])
        window_end = int(payload["window_end_server_ms"])
        server_utc_offset = int(payload["server_utc_offset_seconds_at_query"])
        history_total = int(payload["history_total_selected"])
        start_index = int(payload["history_start_index"])
        returned_count = int(payload["returned_count"])
        history_matching_total = int(payload.get("history_matching_total", returned_count))
        magic = int(payload["magic"])
    except (KeyError, TypeError, ValueError, OverflowError):
        return {"status": "INVALID", "deals": [], "reason": "Deal-history metadata is incomplete."}
    current_ms = int(time.time() * 1000)
    age_seconds = (current_ms - queried_at) / 1000.0
    if not math.isfinite(age_seconds) or age_seconds < -2 or age_seconds > 180:
        return {
            "status": "STALE",
            "deals": [],
            "queried_at_utc_ms": queried_at,
            "age_seconds": round(age_seconds, 3) if math.isfinite(age_seconds) else None,
            "reason": "MT5 broker deal-history snapshot is future-dated or older than 180 seconds.",
        }
    symbol = str(payload.get("symbol", "")).strip()
    raw_deals = payload.get("deals")
    if (
        queried_at <= 0 or window_start <= 0 or window_end < window_start
        or history_total < 0 or start_index < 0 or returned_count < 0
        or history_matching_total < returned_count
        or not isinstance(raw_deals, list) or returned_count != len(raw_deals)
        or server_utc_offset < -86400 or server_utc_offset > 86400
        or magic <= 0 or magic != expected_magic
        or symbol.casefold() != expected_symbol.casefold()
        or payload.get("time_basis") != "MT5_SERVER_TIME"
    ):
        return {
            "status": "INVALID",
            "deals": [],
            "reason": "Deal-history identity, time window, count or time basis is inconsistent.",
        }

    validated: list[dict[str, Any]] = []
    seen: set[str] = set()
    numeric_fields = (
        "volume", "price", "profit", "commission", "swap", "fee", "net_cashflow"
    )
    for index, raw in enumerate(raw_deals):
        if not isinstance(raw, dict):
            return {"status": "INVALID", "deals": [], "reason": f"Deal {index} is not an object."}
        try:
            ticket = str(int(raw["deal_ticket"]))
            order_ticket = str(int(raw.get("order_ticket", 0) or 0))
            position_id = str(int(raw["position_id"]))
            row_magic = int(raw["magic"])
            deal_time = int(raw["time_server_ms"])
            deal_type = int(raw["type"])
            deal_entry = int(raw["entry"])
            deal_reason = int(raw.get("reason", 0) or 0)
            values = {name: float(raw[name]) for name in numeric_fields}
        except (KeyError, TypeError, ValueError, OverflowError):
            return {"status": "INVALID", "deals": [], "reason": f"Deal {index} has missing or invalid fields."}
        row_symbol = str(raw.get("symbol", "")).strip()
        currency = str(raw.get("currency", "")).strip()
        if (
            int(ticket) <= 0 or int(position_id) <= 0 or row_magic != magic
            or row_symbol.casefold() != symbol.casefold()
            or deal_time < window_start or deal_time > window_end
            or not currency or ticket in seen
            or any(not math.isfinite(value) for value in values.values())
            or values["volume"] < 0 or values["price"] < 0
            or abs(values["net_cashflow"] - (
                values["profit"] + values["commission"] + values["swap"] + values["fee"]
            )) > 0.02
        ):
            return {
                "status": "INVALID",
                "deals": [],
                "reason": f"Deal {index} failed identity, numeric, time-window or net-cashflow validation.",
            }
        seen.add(ticket)
        validated.append({
            "deal_ticket": ticket,
            "order_ticket": order_ticket,
            "position_id": position_id,
            "magic": row_magic,
            "symbol": row_symbol,
            "type": deal_type,
            "entry": deal_entry,
            "reason": deal_reason,
            "time_server_ms": deal_time,
            **values,
            "currency": currency,
            "comment": str(raw.get("comment", "")),
        })
    if returned_count > history_total or history_matching_total > history_total or start_index > history_total:
        return {"status": "INVALID", "deals": [], "reason": "Deal-history pagination counters are inconsistent."}
    if "history_matching_total" in payload and bool(payload.get("truncated")) != (history_matching_total > returned_count):
        return {"status": "INVALID", "deals": [], "reason": "Deal-history truncation flag does not match filtered Mirsad deal counts."}
    return {
        **payload,
        "status": "READY",
        "server_utc_offset_seconds_at_query": server_utc_offset,
        "symbol": symbol,
        "magic": magic,
        "deals": validated,
        "history_matching_total": history_matching_total,
        "truncated": bool(payload.get("truncated")),
        "age_seconds": round(age_seconds, 3),
        "reason": None,
    }


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
        status_path = self.root / "status.json"
        payload = _read_object(status_path)
        if not payload:
            exists = status_path.is_file()
            try:
                size_bytes = status_path.stat().st_size if exists else 0
            except OSError:
                size_bytes = None
            return {
                **base,
                "status": "WAITING_FOR_EXPERT",
                "status_file_exists": exists,
                "status_file_size_bytes": size_bytes,
                "bridge_diagnostics": {
                    "status_file_state": "INVALID_OR_PARTIAL_JSON" if exists else "MISSING",
                    "status_file_path": str(status_path),
                    "json_read_retries": 6,
                },
                "message": (
                    "MIR1 status file exists but did not yield complete JSON after bounded read retries."
                    if exists else "No EA heartbeat file received yet."
                ),
            }
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
        quote_snapshot_age = (
            (now_ms - quote_time) / 1000 if quote_time > 0 else None
        )
        # The EA refreshes status.json on every timer cycle, so quote.time_ms
        # is the telemetry publication time, not the time of the last broker
        # tick. Use the EA's tick_age_seconds for true market-quote freshness.
        try:
            quote_age = float(quote.get("tick_age_seconds"))
        except (TypeError, ValueError, OverflowError):
            quote_age = None
        if quote_age is not None and (not math.isfinite(quote_age) or quote_age < 0):
            quote_age = None
        quote_fresh = (
            quote_age is not None and quote_age <= MT5_QUOTE_MAX_AGE_SECONDS
        )

        account_value = payload.get("account")
        account = account_value if isinstance(account_value, dict) else {}
        spec_value = payload.get("symbol_spec")
        symbol_spec = spec_value if isinstance(spec_value, dict) else {}
        positions_value = payload.get("positions")
        positions, positions_snapshot_valid, positions_snapshot_reason = (
            _validate_positions_snapshot(positions_value)
        )
        schema_ok = payload.get("schema") == "MIR1"
        terminal_connected = payload.get("terminal_connected") is True
        heartbeat_fresh = (
            age is not None and 0 <= age <= MT5_HEARTBEAT_MAX_AGE_SECONDS
        )
        if not schema_ok:
            connection_reason = "MIR1 schema mismatch."
        elif not terminal_connected:
            connection_reason = "MT5 terminal_connected is false in the latest EA heartbeat."
        elif age is None:
            connection_reason = "Heartbeat timestamp is missing or invalid."
        elif age < 0:
            connection_reason = "Heartbeat timestamp is in the future."
        elif age > MT5_HEARTBEAT_MAX_AGE_SECONDS:
            connection_reason = (
                f"Heartbeat is stale ({age:.2f}s; maximum {MT5_HEARTBEAT_MAX_AGE_SECONDS}s)."
            )
        elif not positions_snapshot_valid:
            connection_reason = positions_snapshot_reason or "Position snapshot is invalid."
        else:
            connection_reason = None
        alive = (
            terminal_connected and schema_ok and heartbeat_fresh
            and positions_snapshot_valid
        )
        ack = _read_object(self.root / "ack.json")
        command = _read_object(self.root / "command.json")
        reconciliation = self._reconcile_ack_with_positions(
            ack, command, positions, heartbeat
        )
        execution_value = payload.get("execution_enabled")
        execution_enabled = execution_value if isinstance(execution_value, bool) else None
        input_value = payload.get("execution_input_enabled")
        execution_input_enabled = input_value if isinstance(input_value, bool) else None
        permissions_value = payload.get("trade_permissions_available")
        trade_permissions_available = permissions_value if isinstance(permissions_value, bool) else None
        positions_file = _read_json_array(self.root / "positions.json")
        positions_file_valid = positions_file is not None and all(isinstance(item, dict) for item in positions_file)
        event_log = _read_jsonl_tail(self.root / "events.jsonl")
        try:
            expected_magic = int(payload.get("magic_number", 0) or 0)
        except (TypeError, ValueError, OverflowError):
            expected_magic = 0
        deal_history = _read_mt5_deal_history(
            self.root / "deals.json",
            expected_symbol=str(payload.get("symbol", "")),
            expected_magic=expected_magic,
        ) if expected_magic > 0 and payload.get("symbol") else {
            "status": "INVALID",
            "deals": [],
            "reason": "MIR1 heartbeat is missing the configured symbol or magic number.",
        }
        if (
            alive
            and positions_snapshot_valid
            and reconciliation.get("status") == "ACK_PENDING"
            and str(ack.get("state", "")).upper() == "UNKNOWN"
        ):
            deal_reconciliation = self._reconcile_unknown_close_from_deal_history(
                ack, command, positions, deal_history, heartbeat
            )
            if deal_reconciliation is not None:
                reconciliation = deal_reconciliation
        if (
            alive
            and positions_snapshot_valid
            and reconciliation.get("status") == "POSITION_MISSING"
            and str(ack.get("state", "")).upper() == "FILLED"
            and str(command.get("action", "")).upper() == "MODIFY"
        ):
            closed_position_reconciliation = self._reconcile_filled_modify_after_later_close(
                ack, command, positions, deal_history, heartbeat
            )
            if closed_position_reconciliation is not None:
                reconciliation = closed_position_reconciliation
        files = {
            "status.json": (self.root / "status.json").is_file(),
            "command.json": (self.root / "command.json").is_file(),
            "ack.json": (self.root / "ack.json").is_file(),
            "positions.json": (self.root / "positions.json").is_file(),
            "events.jsonl": (self.root / "events.jsonl").is_file(),
            "deals.json": (self.root / "deals.json").is_file(),
        }
        return {
            **base, "status": "CONNECTED" if alive else "STALE",
            "schema": payload.get("schema"),
            "terminal_connected": terminal_connected,
            "bridge_diagnostics": {
                "status_file_state": "VALID_JSON",
                "schema_valid": schema_ok,
                "heartbeat_age_seconds": round(age, 3) if age is not None else None,
                "heartbeat_max_age_seconds": MT5_HEARTBEAT_MAX_AGE_SECONDS,
                "heartbeat_fresh": heartbeat_fresh,
                "quote_tick_age_seconds": round(quote_age, 3) if quote_age is not None else None,
                "quote_snapshot_age_seconds": round(quote_snapshot_age, 3) if quote_snapshot_age is not None else None,
                "quote_max_age_seconds": MT5_QUOTE_MAX_AGE_SECONDS,
                "quote_fresh": quote_fresh,
                "positions_snapshot_valid": positions_snapshot_valid,
                "positions_file_valid": positions_file_valid,
                "execution_enabled": execution_enabled,
                "execution_input_enabled": execution_input_enabled,
                "trade_permissions_available": trade_permissions_available,
                "reason": connection_reason,
            },
            "execution_enabled": execution_enabled,
            "execution_input_enabled": execution_input_enabled,
            "trade_permissions_available": trade_permissions_available,
            "heartbeat_at_ms": heartbeat if heartbeat > 0 else None,
            "heartbeat_age_seconds": round(age, 2) if age is not None else None,
            # quote_age_seconds means the age of the last broker tick, not
            # the age of the freshly rewritten status.json heartbeat.
            "quote_age_seconds": round(quote_age, 2) if quote_age is not None else None,
            "quote_snapshot_age_seconds": round(quote_snapshot_age, 2) if quote_snapshot_age is not None else None,
            "quote_fresh": quote_fresh,
            "account": account,
            "symbol": payload.get("symbol"),
            "market_symbol": payload.get("market_symbol"),
            "magic_number": payload.get("magic_number"),
            "quote": quote,
            "symbol_spec": symbol_spec,
            "positions": positions,
            "positions_snapshot_valid": positions_snapshot_valid,
            "positions_snapshot_reason": positions_snapshot_reason,
            "positions_file_valid": positions_file_valid,
            "current_command": command,
            "last_order_ack": ack,
            "position_reconciliation": reconciliation,
            "event_log": event_log,
            "deal_history": deal_history,
            "common_files_directory": str(self.root),
            "common_files_files": files,
            "message": (
                "Fresh EA telemetry received." if alive
                else connection_reason or "EA heartbeat missing, stale or protocol schema mismatch."
            ),
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
        if state in {"RECEIVED", "SUBMITTED", "UNKNOWN"}:
            return outcome(
                "ACK_PENDING",
                "The broker outcome is not final; retain the command and do not replace it.",
                ack_state=state,
            )
        if state in {"REJECTED", "CANCELLED", "EXPIRED"}:
            return outcome("TERMINAL_NOT_FILLED", "The EA reported a terminal non-fill state.", ack_state=state)
        if state not in {"FILLED", "PARTIAL"}:
            return outcome("ACK_STATE_INVALID", "The ACK state is missing or unsupported.", ack_state=state)

        try:
            ack_at = int(ack.get("ack_at_ms", 0) or 0)
            heartbeat = int(heartbeat_at_ms or 0)
        except (TypeError, ValueError, OverflowError):
            ack_at = heartbeat = 0
        if ack_at <= 0 or heartbeat <= 0:
            if state == "PARTIAL":
                return outcome(
                    "ACK_PENDING",
                    "The partial execution does not yet have valid ACK/heartbeat timestamps; keep waiting for broker reconciliation.",
                    ack_state=state,
                )
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
        if state == "PARTIAL" and (not math.isfinite(filled_volume) or filled_volume <= 0):
            return outcome("ACK_PENDING", "The EA reported a partial state without a confirmed positive filled volume.", ack_state=state)
        if state == "PARTIAL" and action == "MODIFY":
            return outcome("ACK_PENDING", "A partial MODIFY acknowledgement cannot be reconciled as an exposure change.", ack_state=state)
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
                    "CONFIRMED_PARTIAL" if state == "PARTIAL" else "CONFIRMED",
                    "The later MT5 snapshot contains the broker-confirmed filled Mirsad position volume.",
                    action=action, expected_volume=expected, observed_volume_delta=round(delta, 8),
                    ack_state=state,
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
                    "CONFIRMED_PARTIAL" if state == "PARTIAL" else "CONFIRMED",
                    "The target position volume has reduced by the broker-confirmed close amount.",
                    action=action, position_ticket=ticket, expected_reduction=expected,
                    observed_reduction=round(reduced, 8), ack_state=state,
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
    def _reconcile_filled_modify_after_later_close(
        ack: dict[str, Any],
        command: dict[str, Any],
        positions: list[dict[str, Any]],
        deal_history: dict[str, Any],
        heartbeat_at_ms: int,
    ) -> dict[str, Any] | None:
        """Settle a FILLED MODIFY only when complete broker history proves later full closure.

        A protective update is no longer pending when the exact target position
        was subsequently closed. Absence from the live position list alone is
        never sufficient: require a complete, validated, correctly owned exit
        deal sequence after the MODIFY ACK and before the fresh MT5 heartbeat.
        """
        command_id = str(command.get("command_id", "")).strip()
        if (
            not command_id
            or str(ack.get("command_id", "")).strip() != command_id
            or str(ack.get("state", "")).upper() != "FILLED"
            or str(command.get("action", "")).upper() != "MODIFY"
            or str(deal_history.get("status", "")).upper() != "READY"
            or deal_history.get("truncated") is not False
        ):
            return None

        raw_deals = deal_history.get("deals")
        if not isinstance(raw_deals, list):
            return None
        try:
            returned_count = int(deal_history.get("returned_count", -1))
            history_matching_total = int(deal_history.get("history_matching_total", -1))
            magic = int(command.get("magic_number", 0) or 0)
            ticket = int(command.get("position_ticket", 0) or 0)
            volume_step = float(command.get("volume_step", 0) or 0)
            ack_at = int(ack.get("ack_at_ms", 0) or 0)
            heartbeat = int(heartbeat_at_ms or 0)
            server_utc_offset = int(deal_history.get("server_utc_offset_seconds_at_query", 0))
        except (TypeError, ValueError, OverflowError):
            return None

        symbol = str(command.get("symbol", "")).strip().upper()
        if (
            returned_count != len(raw_deals)
            or history_matching_total != returned_count
            or magic <= 0 or ticket <= 0 or not symbol
            or not math.isfinite(volume_step) or volume_step <= 0
            or ack_at <= 0 or heartbeat <= ack_at
            or not -86400 <= server_utc_offset <= 86400
        ):
            return None

        before_rows = command.get("position_snapshot_before")
        if not isinstance(before_rows, list):
            return None
        baseline_rows = []
        for row in before_rows:
            if not isinstance(row, dict):
                continue
            try:
                item = {
                    "ticket": int(row.get("ticket", 0) or 0),
                    "symbol": str(row.get("symbol", "")).strip().upper(),
                    "type": int(row.get("type", -1)),
                    "magic": int(row.get("magic", -1)),
                    "volume": float(row.get("volume", 0) or 0),
                }
            except (TypeError, ValueError, OverflowError):
                continue
            if (
                item["ticket"] == ticket and item["symbol"] == symbol
                and item["magic"] == magic and item["type"] in (0, 1)
                and math.isfinite(item["volume"]) and item["volume"] > 0
            ):
                baseline_rows.append(item)
        if len(baseline_rows) != 1:
            return None
        baseline = baseline_rows[0]

        # A still-open target must be reconciled against its protective prices,
        # not treated as closed merely because some exit deals exist.
        for row in positions if isinstance(positions, list) else []:
            if not isinstance(row, dict):
                continue
            try:
                same_target = (
                    int(row.get("ticket", 0) or 0) == ticket
                    and int(row.get("magic", -1)) == magic
                    and str(row.get("symbol", "")).strip().upper() == symbol
                    and float(row.get("volume", 0) or 0) > 0
                )
            except (TypeError, ValueError, OverflowError):
                same_target = False
            if same_target:
                return None

        tolerance = max(1e-8, volume_step * 0.5)
        expected_exit_type = 1 if baseline["type"] == 0 else 0
        matching_exits: list[dict[str, Any]] = []
        later_entries: list[int] = []
        for row in raw_deals:
            if not isinstance(row, dict):
                continue
            try:
                row_magic = int(row.get("magic", -1))
                row_ticket = int(row.get("position_id", 0) or 0)
                row_type = int(row.get("type", -1))
                row_entry = int(row.get("entry", -1))
                row_deal_ticket = int(row.get("deal_ticket", 0) or 0)
                row_order_ticket = int(row.get("order_ticket", 0) or 0)
                row_volume = float(row.get("volume", 0) or 0)
                row_server_time = int(row.get("time_server_ms", 0) or 0)
            except (TypeError, ValueError, OverflowError):
                continue
            if (
                row_magic != magic or row_ticket != ticket
                or str(row.get("symbol", "")).strip().upper() != symbol
                or row_server_time <= 0
            ):
                continue
            deal_time_utc_ms = row_server_time - server_utc_offset * 1000
            if deal_time_utc_ms <= ack_at or deal_time_utc_ms >= heartbeat:
                continue
            if row_entry in (0, 2):
                later_entries.append(deal_time_utc_ms)
            if (
                row_type == expected_exit_type
                and row_entry in (1, 3)
                and row_deal_ticket > 0 and row_order_ticket > 0
                and math.isfinite(row_volume) and row_volume > 0
            ):
                matching_exits.append({
                    "deal_ticket": row_deal_ticket,
                    "order_ticket": row_order_ticket,
                    "volume": row_volume,
                    "time_utc_ms": deal_time_utc_ms,
                    "reason": int(row.get("reason", -1) or -1),
                    "price": float(row.get("price", 0) or 0),
                })

        closed_volume = sum(row["volume"] for row in matching_exits)
        if (
            not matching_exits
            or any(entry_time > max(row["time_utc_ms"] for row in matching_exits) for entry_time in later_entries)
            or abs(closed_volume - baseline["volume"]) > tolerance
        ):
            return None

        close_reasons = sorted({row["reason"] for row in matching_exits})
        if 5 in close_reasons:
            close_kind = "TAKE_PROFIT"
        elif 4 in close_reasons:
            close_kind = "STOP_LOSS"
        else:
            close_kind = "BROKER_CONFIRMED_EXIT"
        return {
            "status": "POSITION_CLOSED_AFTER_MODIFY",
            "decision_eligible": False,
            "command_id": command_id,
            "ack_state": "FILLED",
            "action": "MODIFY",
            "position_ticket": ticket,
            "closed_volume": round(closed_volume, 8),
            "close_kind": close_kind,
            "close_reason_codes": close_reasons,
            "deal_tickets": [str(row["deal_ticket"]) for row in matching_exits],
            "order_tickets": [str(row["order_ticket"]) for row in matching_exits],
            "final_exit_time_utc_ms": max(row["time_utc_ms"] for row in matching_exits),
            "confirmation_source": "COMPLETE_VALIDATED_MT5_DEAL_HISTORY_AND_EMPTY_LIVE_POSITION_SNAPSHOT",
            "reason": (
                "The FILLED protective MODIFY is settled: complete validated MT5 history "
                "confirms that the exact Mirsad position was fully closed afterward, "
                "and the current live position snapshot confirms no remaining exposure."
            ),
        }

    @staticmethod
    def _reconcile_unknown_close_from_deal_history(
        ack: dict[str, Any],
        command: dict[str, Any],
        positions: list[dict[str, Any]],
        deal_history: dict[str, Any],
        heartbeat_at_ms: int,
    ) -> dict[str, Any] | None:
        """Confirm an UNKNOWN duplicate CLOSE only from an exact broker-deal match.

        The EA may return UNKNOWN after finding a command ID in its persistent
        ledger, in order to prevent duplicate OrderSend calls. For CLOSE only,
        a fresh validated broker deal can independently confirm the outcome
        when its comment is the exact MIR1 command ID, its position/symbol/magic
        and exit side match the pre-command position, its volume equals the
        request, and the later live positions snapshot reflects that reduction.
        The original ACK file is never rewritten or promoted to FILLED.
        """
        command_id = str(command.get("command_id", "")).strip()
        if (
            not command_id
            or str(ack.get("command_id", "")).strip() != command_id
            or str(ack.get("state", "")).upper() != "UNKNOWN"
            or str(command.get("action", "")).upper() != "CLOSE"
            or str(deal_history.get("status", "")).upper() != "READY"
            or "persistent ledger" not in str(ack.get("message", "")).casefold()
            or "will not be resent" not in str(ack.get("message", "")).casefold()
        ):
            return None

        try:
            magic = int(command.get("magic_number", 0) or 0)
            ticket = int(command.get("position_ticket", 0) or 0)
            requested_volume = float(command.get("volume", 0) or 0)
            volume_step = float(command.get("volume_step", 0) or 0)
            command_created_at = int(command.get("created_at_ms", 0) or 0)
            command_expires_at = int(command.get("expires_at_ms", 0) or 0)
            server_utc_offset = int(deal_history.get("server_utc_offset_seconds_at_query", 0))
            heartbeat_at_ms = int(heartbeat_at_ms)
        except (TypeError, ValueError, OverflowError):
            return None
        symbol = str(command.get("symbol", "")).strip().upper()
        if (
            magic <= 0 or ticket <= 0 or not symbol
            or not math.isfinite(requested_volume) or requested_volume <= 0
            or command_created_at <= 0 or command_expires_at <= command_created_at
            or heartbeat_at_ms <= 0
            or server_utc_offset < -86400 or server_utc_offset > 86400
        ):
            return None

        before_rows = command.get("position_snapshot_before")
        if not isinstance(before_rows, list):
            return None
        baseline = None
        for row in before_rows:
            if not isinstance(row, dict):
                continue
            try:
                row_ticket = int(row.get("ticket", 0) or 0)
                row_magic = int(row.get("magic", -1))
                row_type = int(row.get("type", -1))
                row_volume = float(row.get("volume", 0) or 0)
            except (TypeError, ValueError, OverflowError):
                continue
            if (
                row_ticket == ticket
                and row_magic == magic
                and str(row.get("symbol", "")).strip().upper() == symbol
                and row_type in (0, 1)
                and math.isfinite(row_volume)
                and row_volume > 0
            ):
                baseline = {"type": row_type, "volume": row_volume}
                break
        if baseline is None:
            return None

        tolerance = max(
            1e-8,
            volume_step * 0.5 if math.isfinite(volume_step) and volume_step > 0 else 1e-8,
        )
        if requested_volume > baseline["volume"] + tolerance:
            return None
        expected_close_type = 1 if baseline["type"] == 0 else 0
        matching_deals: list[dict[str, Any]] = []
        raw_deals = deal_history.get("deals")
        for row in raw_deals if isinstance(raw_deals, list) else []:
            if not isinstance(row, dict):
                continue
            try:
                row_magic = int(row.get("magic", -1))
                position_id = int(row.get("position_id", 0) or 0)
                deal_type = int(row.get("type", -1))
                deal_entry = int(row.get("entry", -1))
                deal_volume = float(row.get("volume", 0) or 0)
                deal_ticket = int(row.get("deal_ticket", 0) or 0)
                order_ticket = int(row.get("order_ticket", 0) or 0)
                deal_time_server_ms = int(row.get("time_server_ms", 0) or 0)
            except (TypeError, ValueError, OverflowError):
                continue
            deal_time_utc_ms = deal_time_server_ms - server_utc_offset * 1000
            if (
                str(row.get("comment", "")).strip() == command_id
                and str(row.get("symbol", "")).strip().upper() == symbol
                and row_magic == magic
                and position_id == ticket
                and deal_type == expected_close_type
                and deal_entry in (1, 3)  # OUT or OUT_BY; never count an opening deal.
                and deal_ticket > 0 and order_ticket > 0
                and math.isfinite(deal_volume) and deal_volume > 0
                and deal_time_utc_ms >= command_created_at - 2_000
                and deal_time_utc_ms <= command_expires_at + 2_000
                and deal_time_utc_ms < heartbeat_at_ms
            ):
                matching_deals.append(row)

        broker_closed_volume = sum(float(row["volume"]) for row in matching_deals)
        if (
            not matching_deals
            or abs(broker_closed_volume - requested_volume) > tolerance
            or broker_closed_volume - baseline["volume"] > tolerance
        ):
            return None

        after_volume = 0.0
        for row in positions if isinstance(positions, list) else []:
            if not isinstance(row, dict):
                continue
            try:
                row_ticket = int(row.get("ticket", 0) or 0)
                row_magic = int(row.get("magic", -1))
                row_volume = float(row.get("volume", 0) or 0)
            except (TypeError, ValueError, OverflowError):
                continue
            if (
                row_ticket == ticket and row_magic == magic
                and str(row.get("symbol", "")).strip().upper() == symbol
                and math.isfinite(row_volume) and row_volume > 0
            ):
                after_volume = row_volume
                break
        observed_reduction = max(0.0, baseline["volume"] - after_volume)
        if observed_reduction + tolerance < requested_volume:
            return None

        return {
            "status": "CONFIRMED_FROM_DEAL_HISTORY",
            "decision_eligible": False,
            "command_id": command_id,
            "reason": (
                "ACK is UNKNOWN because the EA protected its persistent command ledger; "
                "the exact command comment, Mirsad magic, symbol, target position, exit side, "
                "broker order/deal tickets and full close volume match fresh MT5 deal history, "
                "and the later positions snapshot confirms the same exposure reduction."
            ),
            "confirmation_source": "FRESH_VALIDATED_MT5_DEAL_HISTORY_AND_LATER_POSITIONS",
            "ack_state": "UNKNOWN",
            "action": "CLOSE",
            "position_ticket": ticket,
            "expected_reduction": requested_volume,
            "observed_reduction": round(observed_reduction, 8),
            "broker_closed_volume": round(broker_closed_volume, 8),
            "deal_tickets": [str(row["deal_ticket"]) for row in matching_deals],
            "order_tickets": [str(row["order_ticket"]) for row in matching_deals],
        }

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
        if bridge_state.get("execution_input_enabled") is not True:
            status = (
                "EXECUTION_INPUT_DISABLED"
                if bridge_state.get("execution_input_enabled") is False
                else "EXECUTION_INPUT_STATE_UNKNOWN"
            )
            return {
                "status": status,
                "message": "The latest MIR1 heartbeat must explicitly confirm that the EA execution input is enabled.",
            }
        if bridge_state.get("trade_permissions_available") is not True:
            status = (
                "TRADE_PERMISSIONS_UNAVAILABLE"
                if bridge_state.get("trade_permissions_available") is False
                else "TRADE_PERMISSIONS_STATE_UNKNOWN"
            )
            return {
                "status": status,
                "message": "The latest MIR1 heartbeat must explicitly confirm terminal, MQL, account and Expert Advisor trading permissions.",
            }

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
                        and reconciliation.get("status") in {"CONFIRMED", "POSITION_CLOSED_AFTER_MODIFY"}
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
                and reconciliation.get("status") in {
                    "CONFIRMED", "CONFIRMED_PARTIAL", "CONFIRMED_FROM_DEAL_HISTORY",
                    "POSITION_CLOSED_AFTER_MODIFY",
                }
            )
            settled = ack_matches and (
                ack_state in settled_failure_states
                or (ack_state in {"FILLED", "PARTIAL"} and position_confirmed)
                or (
                    ack_state == "UNKNOWN"
                    and isinstance(reconciliation, dict)
                    and reconciliation.get("status") == "CONFIRMED_FROM_DEAL_HISTORY"
                )
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

