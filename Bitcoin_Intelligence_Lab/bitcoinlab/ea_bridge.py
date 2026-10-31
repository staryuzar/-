from __future__ import annotations

from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import time
from typing import Any

from .command_protocol import (
    COMMAND_FILENAME,
    COMMAND_FOLDER,
    build_command,
    publish_command,
    read_ack,
)
from .scenarios import build_trade_levels
from .risk import calculate_position_size_from_tick_value


class PositionSnapshotError(RuntimeError):
    """The EA position export is missing, malformed, or unsafe to act upon."""


def default_common_files() -> Path:
    configured = os.environ.get("BTCIL_MT5_COMMON_FILES")
    if configured:
        return Path(configured).expanduser()
    appdata = os.environ.get("APPDATA")
    if not appdata:
        raise RuntimeError("Set BTCIL_MT5_COMMON_FILES to the MT5 Common\\Files directory.")
    return Path(appdata) / "MetaQuotes" / "Terminal" / "Common" / "Files"


def read_ea_status(common_files: str | Path, *, now_seconds: int | None = None, max_age_seconds: int = 45) -> dict[str, Any]:
    path = Path(common_files) / "BitcoinIntelligenceLab" / "ea_status.tsv"
    try:
        fields = path.read_text(encoding="utf-8", errors="replace").strip().split("|")
    except OSError as exc:
        return {"status": "unavailable", "reason": f"EA status file unavailable: {exc}"}
    if len(fields) < 15 or fields[0] != "BTCIL1":
        return {"status": "invalid", "reason": "EA status envelope or daily-risk readout is incomplete."}
    try:
        timestamp = int(fields[3])
        bid, ask = float(fields[5]), float(fields[6])
        open_positions = int(fields[7])
        point = float(fields[9]) if len(fields) > 9 else 0.0
        stops_points = int(fields[10]) if len(fields) > 10 else 0
    except (ValueError, IndexError):
        return {"status": "invalid", "reason": "EA status contains invalid numeric fields."}
    now = int(time.time()) if now_seconds is None else int(now_seconds)
    age = now - timestamp
    detail = fields[8]
    readiness_marker = fields[11] if len(fields) > 11 else None
    account_server = fields[12] if len(fields) > 12 else None
    try:
        daily_loss_percent = float(fields[13])
        daily_loss_limit_percent = float(fields[14])
    except ValueError:
        return {"status": "invalid", "reason": "EA daily-risk fields are malformed."}
    if (
        not math.isfinite(daily_loss_percent)
        or daily_loss_percent < 0
        or not math.isfinite(daily_loss_limit_percent)
        or daily_loss_limit_percent <= 0
    ):
        return {"status": "invalid", "reason": "EA daily-risk fields are outside valid bounds."}

    if 15 < len(fields) < 21:
        return {"status": "invalid", "reason": "EA broker risk-specification record is truncated."}
    equity = tick_size = tick_value_loss = volume_min = volume_step = volume_max = None
    risk_specs_ready = False
    if len(fields) >= 21:
        try:
            equity = float(fields[15])
            tick_size = float(fields[16])
            tick_value_loss = float(fields[17])
            volume_min = float(fields[18])
            volume_step = float(fields[19])
            volume_max = float(fields[20])
            risk_specs_ready = (
                all(math.isfinite(value) and value > 0 for value in (
                    equity, tick_size, tick_value_loss,
                    volume_min, volume_step, volume_max,
                ))
                and volume_max >= volume_min
            )
        except ValueError:
            return {"status": "invalid", "reason": "EA broker risk-specification fields are malformed."}
    server_normalized = (account_server or "").lower()
    # Broker identity is verified independently of the account trade mode.
    # Do not inspect or gate execution based on DEMO/LIVE classification.
    headway_server_ok = (
        "headway" in server_normalized
        or "trade-hw.online" in server_normalized
    )
    trading_ready = (
        readiness_marker == "TRADE_READY"
        if readiness_marker is not None
        else "READY:" in detail
    )
    freshness_status = "fresh" if -5 <= age <= max_age_seconds else "stale"
    result = {
        "status": freshness_status,
        "freshness_status": freshness_status,
        "age_seconds": age, "symbol": fields[1], "timeframe": fields[2],
        "connection": fields[4], "bid": bid, "ask": ask,
        "open_positions": open_positions, "ea_message": detail,
        "point": point, "stops_level_points": stops_points,
        "trading_ready": trading_ready, "readiness_marker": readiness_marker,
        "account_server": account_server,
        "daily_loss_percent": daily_loss_percent,
        "daily_loss_limit_percent": daily_loss_limit_percent,
        "account_equity": equity,
        "tick_size": tick_size,
        "tick_value_loss": tick_value_loss,
        "volume_min": volume_min,
        "volume_step": volume_step,
        "volume_max": volume_max,
        "risk_specs_ready": risk_specs_ready,
        "headway_server_ok": headway_server_ok,
        "observed_at_utc": datetime.fromtimestamp(timestamp, timezone.utc).isoformat(),
    }
    symbol = fields[1].upper()
    if "BTC" not in symbol:
        result["status"] = "wrong_symbol"
    elif not headway_server_ok:
        result["status"] = "wrong_broker"
    elif result["connection"] != "CONNECTED" or not trading_ready:
        result["status"] = "not_ready"
    elif not all(math.isfinite(x) and x > 0 for x in (bid, ask)) or ask < bid:
        result["status"] = "invalid_quote"
    elif daily_loss_percent is not None and (
        not math.isfinite(daily_loss_percent) or daily_loss_percent < 0
    ):
        result["status"] = "invalid_risk_status"
    elif daily_loss_limit_percent is not None and (
        not math.isfinite(daily_loss_limit_percent) or daily_loss_limit_percent <= 0
    ):
        result["status"] = "invalid_risk_status"
    return result


def pending_command_state(
    common_files: str | Path,
    *,
    now_seconds: int | None = None,
    expiry_grace_seconds: int = 10,
) -> dict[str, Any]:
    """Prevent a later decision cycle from overwriting a broker command in flight."""
    directory = Path(common_files) / "BitcoinIntelligenceLab"
    command_path = directory / "trade_command.txt"
    try:
        fields = command_path.read_text(encoding="ascii").strip().split("|")
    except FileNotFoundError:
        return {"status": "none", "pending": False}
    except (OSError, UnicodeError) as exc:
        return {
            "status": "unavailable", "pending": True,
            "reason": f"Cannot safely inspect current MT5 command: {type(exc).__name__}",
        }

    if len(fields) != 11 or fields[0] != "BTCIL1":
        return {
            "status": "invalid", "pending": True,
            "reason": "An unrecognized command envelope exists; refusing to overwrite it.",
        }
    now = int(time.time()) if now_seconds is None else int(now_seconds)
    try:
        issued = int(fields[2])
        expires = int(fields[3])
    except (ValueError, TypeError):
        return {
            "status": "invalid", "pending": True,
            "command_id": fields[1],
            "reason": "Current command timestamps are malformed; refusing to overwrite it.",
        }
    ttl_seconds = expires - issued
    if issued > now + 5 or not 5 <= ttl_seconds <= 300:
        return {
            "status": "invalid", "pending": True,
            "command_id": fields[1],
            "reason": "Current command issued/expiry timestamps are inconsistent; refusing to overwrite it.",
        }
    command_id = fields[1]
    acknowledgement = read_ack(Path(common_files))
    ack_matches = acknowledgement.get("id") == command_id
    ack_status = str(acknowledgement.get("status", "")).upper() if ack_matches else ""

    pending_ack_statuses = {
        "SUBMITTED_PENDING",
        "CLOSE_SUBMITTED_PENDING",
        "PARTIAL_FILL_PENDING",
        "FILL_VOLUME_COMPLETE_WAITING_ORDER_FINALITY",
        "CANCEL_REQUESTED",
        "CANCEL_NOT_CONFIRMED",
    }
    if ack_matches and ack_status in pending_ack_statuses:
        return {
            "status": "pending",
            "pending": True,
            "command_id": command_id,
            "ack_status": ack_status,
            "expires_at": expires,
            "ack": acknowledgement,
        }

    if now <= expires + max(0, int(expiry_grace_seconds)):
        # No matching final ACK yet. Keep the exact command intact until its
        # bounded TTL and small scheduling grace have elapsed.
        final_ack_statuses = {
            "OPEN_FILL_CONFIRMED",
            "OPEN_PARTIAL_FILL_CONFIRMED",
            "CLOSE_FILL_CONFIRMED",
            "CLOSE_PARTIAL_FILL_CONFIRMED",
            "ORDER_REJECTED_OR_CANCELLED",
            "REJECTED",
            "FILLED",
            "CLOSED",
        }
        if not ack_matches or ack_status not in final_ack_statuses:
            return {
                "status": "awaiting_ack",
                "pending": True,
                "command_id": command_id,
                "ack_status": ack_status or None,
                "expires_at": expires,
                "seconds_until_safe_retry": max(0, expires + max(0, int(expiry_grace_seconds)) - now),
            }

    expired = now > expires + max(0, int(expiry_grace_seconds))
    if expired and not ack_matches:
        # The terminal persists the last consumed command ID before returning
        # its ACK. If it has consumed this command but its ACK is absent,
        # never replace it: the outcome must be reconciled first.
        last_id_path = directory / "last_command_id.txt"
        try:
            last_consumed_id = last_id_path.read_text(encoding="ascii").strip()
        except FileNotFoundError:
            last_consumed_id = ""
        except (OSError, UnicodeError):
            return {
                "status": "expired_unconfirmed",
                "pending": True,
                "command_id": command_id,
                "reason": "Cannot safely read terminal's last consumed command ID.",
                "requires_reconciliation": True,
            }
        if last_consumed_id == command_id:
            return {
                "status": "expired_unconfirmed",
                "pending": True,
                "command_id": command_id,
                "reason": "The terminal consumed this command but no final ACK is available.",
                "requires_reconciliation": True,
            }

    return {
        "status": "final_or_expired",
        "pending": False,
        "command_id": command_id,
        "ack_status": ack_status or None,
        "expired": expired,
    }


def read_execution_loop_status(
    common_files: str | Path,
    *,
    now_seconds: int | None = None,
    max_age_seconds: int = 90,
) -> dict[str, Any]:
    path = Path(common_files) / "BitcoinIntelligenceLab" / "execution_loop_status.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {"status": "unavailable", "reason": "Execution-loop heartbeat is unavailable."}
    if not isinstance(payload, dict) or payload.get("schema") != "BTCIL-EXEC1":
        return {"status": "invalid", "reason": "Execution-loop heartbeat is malformed."}
    cycle_status = payload.get("status")
    if not isinstance(cycle_status, str) or not cycle_status.strip():
        return {"status": "invalid", "reason": "Execution-loop heartbeat has no valid cycle result."}
    try:
        observed = datetime.fromisoformat(
            str(payload.get("updated_at_utc", "")).replace("Z", "+00:00")
        ).astimezone(timezone.utc)
    except (TypeError, ValueError):
        return {"status": "invalid", "reason": "Execution-loop heartbeat timestamp is invalid."}
    now = datetime.fromtimestamp(
        int(time.time()) if now_seconds is None else int(now_seconds),
        tz=timezone.utc,
    )
    age = (now - observed).total_seconds()
    return {
        **payload,
        "cycle_status": payload.get("status"),
        "status": "fresh" if -5 <= age <= max_age_seconds else "stale",
        "age_seconds": round(max(0.0, age), 2),
    }


def _completed_command_ack(
    common_files: str | Path,
    command_id: str,
) -> dict[str, Any] | None:
    """Return a final matching ACK so a completed signal is not republished."""
    path = Path(common_files) / COMMAND_FOLDER / COMMAND_FILENAME
    try:
        fields = path.read_text(encoding="ascii").strip().split("|")
    except (OSError, UnicodeError):
        return None
    if len(fields) != 11 or fields[0] != "BTCIL1" or fields[1] != command_id:
        return None
    ack = read_ack(common_files)
    if ack.get("id") != command_id:
        return None
    pending_statuses = {
        "SUBMITTED_PENDING",
        "CLOSE_SUBMITTED_PENDING",
        "PARTIAL_FILL_PENDING",
        "FILL_VOLUME_COMPLETE_WAITING_ORDER_FINALITY",
        "CANCEL_REQUESTED",
        "CANCEL_NOT_CONFIRMED",
    }
    status = str(ack.get("status", "")).upper()
    if not status or status in pending_statuses:
        return None
    return ack


def _next_open_command_id(common_files: str | Path, signal_id: str) -> str:
    """
    Keep a stable ID for a signal after a final ACK. If its prior envelope
    expired without being consumed by the EA, issue a distinct retry ID.
    """
    directory = Path(common_files) / COMMAND_FOLDER
    command_path = directory / COMMAND_FILENAME
    try:
        fields = command_path.read_text(encoding="ascii").strip().split("|")
    except (OSError, UnicodeError):
        return signal_id
    if len(fields) != 11 or fields[0] != "BTCIL1":
        return signal_id

    previous_id = fields[1]
    if previous_id != signal_id and not previous_id.startswith(signal_id + "-R"):
        return signal_id

    ack = read_ack(Path(common_files))
    ack_matches = ack.get("id") == previous_id
    final_statuses = {
        "OPEN_FILL_CONFIRMED",
        "OPEN_PARTIAL_FILL_CONFIRMED",
        "CLOSE_FILL_CONFIRMED",
        "CLOSE_PARTIAL_FILL_CONFIRMED",
        "ORDER_REJECTED_OR_CANCELLED",
        "REJECTED",
        "FILLED",
        "CLOSED",
    }
    if ack_matches and str(ack.get("status", "")).upper() in final_statuses:
        return previous_id

    # Only retry after pending_command_state has established that the prior
    # envelope expired and the terminal did not consume its ID.
    last_id_path = directory / "last_command_id.txt"
    try:
        last_consumed_id = last_id_path.read_text(encoding="ascii").strip()
    except (OSError, UnicodeError):
        last_consumed_id = ""
    if last_consumed_id == previous_id:
        return previous_id

    attempt = 1
    if previous_id.startswith(signal_id + "-R"):
        suffix = previous_id[len(signal_id + "-R"):]
        try:
            attempt = max(1, int(suffix) + 1)
        except ValueError:
            attempt = 1
    return f"{signal_id}-R{attempt}"


def publish_decision_order(
    *, report: dict, common_files: str | Path | None = None,
    volume: float = 0.01, risk_fraction: float = 0.0025,
    max_risk_fraction: float = 0.005, atr_stop_multiple: float = 1.2,
    reward_risk: float = 1.8, ttl_seconds: int = 60,
    max_signal_age_seconds: int = 90,
) -> dict[str, Any]:
    """Publish one real command for the current signal to the connected MT5 terminal."""
    decision = report.get("decision", {})
    action = str(decision.get("action", "HOLD")).upper()
    if action not in {"BUY", "SELL"}:
        return {"status": "no_directional_decision", "reason": "The central decision is HOLD."}
    if decision.get("blockers"):
        return {"status": "decision_blocked", "reason": "The central decision has blocking conditions.", "blockers": decision["blockers"]}
    if not 5 <= int(max_signal_age_seconds) <= 600:
        raise ValueError("max_signal_age_seconds must be between 5 and 600.")
    as_of = report.get("as_of_utc")
    try:
        observed_at = datetime.fromisoformat(str(as_of).replace("Z", "+00:00"))
        age = (datetime.now(timezone.utc) - observed_at.astimezone(timezone.utc)).total_seconds()
    except (TypeError, ValueError):
        return {"status": "signal_timestamp_missing", "reason": "A valid report as_of_utc timestamp is required."}
    if age < -5 or age > max_signal_age_seconds:
        return {"status": "signal_stale", "age_seconds": round(age, 2), "max_age_seconds": max_signal_age_seconds}
    if not math.isfinite(float(volume)) or volume <= 0:
        raise ValueError("Volume must be positive.")
    directory = Path(common_files) if common_files else default_common_files()
    pending = pending_command_state(directory)
    if pending.get("pending"):
        return {
            "status": "command_pending",
            "reason": "A previous broker command must be reconciled before another command can be published.",
            "pending_command": pending,
        }
    terminal = read_ea_status(directory)
    if terminal.get("status") != "fresh":
        return {"status": "terminal_not_ready", "terminal": terminal}
    daily_loss = terminal.get("daily_loss_percent")
    daily_limit = terminal.get("daily_loss_limit_percent")
    if (
        daily_loss is None or daily_limit is None
        or not math.isfinite(float(daily_loss))
        or not math.isfinite(float(daily_limit))
        or float(daily_loss) < 0
        or float(daily_limit) <= 0
    ):
        return {
            "status": "daily_risk_status_unavailable",
            "reason": "The EA has not supplied valid daily-loss status; new entries are blocked.",
            "terminal": terminal,
        }
    if float(daily_loss) >= float(daily_limit):
        return {
            "status": "daily_loss_limit_reached",
            "reason": "Daily loss reached the configured Headway limit; new entries are blocked while position management remains available.",
            "daily_loss_percent": float(daily_loss),
            "daily_loss_limit_percent": float(daily_limit),
        }
    if not terminal.get("risk_specs_ready"):
        return {
            "status": "risk_specs_unavailable",
            "reason": "The connected EA has not supplied valid equity, tick-value and broker volume specifications.",
            "terminal": terminal,
        }

    technical = report.get("technical", {})
    atr_value = technical.get("atr14")
    if atr_value is None or not math.isfinite(float(atr_value)) or float(atr_value) <= 0:
        return {"status": "scenario_unavailable", "reason": "Fresh ATR is unavailable."}
    side = action
    entry = float(terminal["ask"] if side == "BUY" else terminal["bid"])
    point = float(terminal.get("point") or 0.0)
    minimum = int(terminal.get("stops_level_points") or 0) * point
    levels = build_trade_levels(
        side=side, entry=entry, atr_value=float(atr_value),
        atr_stop_multiple=atr_stop_multiple, reward_risk=reward_risk,
        broker_min_stop_distance=minimum,
    )
    bar = report.get("spot", {}).get("last_bar") or {}
    bar_key = int(bar.get("close_time_ms") or 0)
    if bar_key <= 0:
        return {"status": "scenario_unavailable", "reason": "Latest completed candle timestamp is missing."}
    sizing = calculate_position_size_from_tick_value(
        equity=float(terminal["account_equity"]),
        risk_fraction=float(risk_fraction),
        entry=entry,
        stop=float(levels["stop_loss"]),
        tick_size=float(terminal["tick_size"]),
        tick_value_loss=float(terminal["tick_value_loss"]),
        volume_min=float(terminal["volume_min"]),
        volume_step=float(terminal["volume_step"]),
        volume_max=float(terminal["volume_max"]),
        max_volume=float(volume),
        max_risk_fraction=float(max_risk_fraction),
    )
    if sizing.get("status") != "calculated":
        return {
            "status": "risk_size_blocked",
            "reason": sizing.get("status"),
            "risk_sizing": sizing,
            "levels": levels,
        }
    sized_volume = float(sizing["volume_lots"])
    command = build_command(
        command_id=_next_open_command_id(directory, f"BTC-{bar_key}"), action="OPEN", symbol="BTC", side=side,
        volume=sized_volume, stop_loss=float(levels["stop_loss"]),
        take_profit=float(levels["take_profit"]), ttl_seconds=ttl_seconds,
    )
    completed_ack = _completed_command_ack(directory, command["id"])
    if completed_ack is not None:
        return {
            "status": "already_processed",
            "command_id": command["id"],
            "ack": completed_ack,
            "message": "The broker has already returned a final acknowledgment for this signal.",
        }
    target = publish_command(directory, command)
    return {
        "status": "published", "command_id": command["id"],
        "symbol": terminal["symbol"], "side": side, "volume": sized_volume,
        "levels": levels, "risk_sizing": sizing, "path": str(target),
        "message": "A real Headway execution command was published; wait for the EA acknowledgment and broker deal confirmation.",
    }


def current_ack(common_files: str | Path | None = None) -> dict[str, Any]:
    directory = Path(common_files) if common_files else default_common_files()
    return read_ack(directory)


def read_positions(
    common_files: str | Path,
    *,
    max_age_seconds: int = 30,
    now_seconds: int | float | None = None,
) -> list[dict[str, Any]]:
    """Read the EA-owned BTC position export; fail closed on missing or malformed data."""
    path = Path(common_files) / "BitcoinIntelligenceLab" / "positions.tsv"
    expected_header = (
        "ticket|symbol|type|volume|price_open|price_current|"
        "stop_loss|take_profit|profit"
    )
    if not 5 <= int(max_age_seconds) <= 180:
        raise ValueError("max_age_seconds must be between 5 and 180.")
    try:
        before = path.stat()
        raw = path.read_text(encoding="utf-8")
        after = path.stat()
    except FileNotFoundError as exc:
        raise PositionSnapshotError(
            "MT5 EA positions.tsv is missing; refusing to assume the account has no managed position."
        ) from exc
    except (OSError, UnicodeError) as exc:
        raise PositionSnapshotError(
            f"MT5 EA positions.tsv cannot be read: {type(exc).__name__}: {exc}"
        ) from exc

    if before.st_mtime_ns != after.st_mtime_ns or before.st_size != after.st_size:
        raise PositionSnapshotError("MT5 EA positions.tsv changed while it was being read.")
    current_time = time.time() if now_seconds is None else float(now_seconds)
    age_seconds = current_time - after.st_mtime
    if age_seconds < -5 or age_seconds > max_age_seconds:
        raise PositionSnapshotError(
            f"MT5 EA positions.tsv is stale ({age_seconds:.1f}s; maximum {max_age_seconds}s)."
        )
    lines = raw.splitlines()
    if not lines or lines[0].strip() != expected_header:
        raise PositionSnapshotError("MT5 EA positions.tsv header is missing or invalid.")

    positions: list[dict[str, Any]] = []
    for line_number, line in enumerate(lines[1:], start=2):
        if not line.strip():
            continue
        fields = line.split("|")
        if len(fields) != 9:
            raise PositionSnapshotError(
                f"MT5 EA positions.tsv row {line_number} has {len(fields)} fields; expected 9."
            )
        try:
            ticket = int(fields[0])
            symbol = fields[1].strip()
            position_type = int(fields[2])
            volume, price_open, price_current = map(float, fields[3:6])
            stop_loss, take_profit, profit = map(float, fields[6:9])
        except (ValueError, TypeError) as exc:
            raise PositionSnapshotError(
                f"MT5 EA positions.tsv row {line_number} contains malformed numeric data."
            ) from exc
        numeric = (volume, price_open, price_current, stop_loss, take_profit, profit)
        if (
            ticket <= 0 or "BTC" not in symbol.upper() or position_type not in {0, 1}
            or any(not math.isfinite(value) for value in numeric)
            or volume <= 0 or price_open <= 0 or price_current <= 0
            or stop_loss < 0 or take_profit < 0
        ):
            raise PositionSnapshotError(
                f"MT5 EA positions.tsv row {line_number} failed ticket/symbol/type/value validation."
            )
        positions.append({
            "ticket": ticket, "symbol": symbol,
            "type": "BUY" if position_type == 0 else "SELL",
            "volume": volume, "price_open": price_open,
            "price_current": price_current, "stop_loss": stop_loss,
            "take_profit": take_profit, "profit": profit,
        })
    return positions

def _next_close_command_id(common_files: str | Path, ticket: int, volume_key: int) -> str:
    """Retry a close only after a final broker rejection or safe expiry."""
    base_id = f"BTC-CLOSE-{int(ticket)}-V{int(volume_key)}"
    command_path = Path(common_files) / COMMAND_FOLDER / COMMAND_FILENAME
    try:
        fields = command_path.read_text(encoding="ascii").strip().split("|")
    except (OSError, UnicodeError):
        return base_id
    if len(fields) != 11 or fields[0] != "BTCIL1":
        return base_id
    previous_id = fields[1]
    if previous_id != base_id and not previous_id.startswith(base_id + "-R"):
        return base_id
    acknowledgement = read_ack(Path(common_files))
    ack_matches = acknowledgement.get("id") == previous_id
    status = str(acknowledgement.get("status", "")).upper() if ack_matches else ""
    if status in {"CLOSE_FILL_CONFIRMED", "CLOSE_PARTIAL_FILL_CONFIRMED", "CLOSED", "FILLED"}:
        return previous_id
    if status not in {"ORDER_REJECTED_OR_CANCELLED", "REJECTED"}:
        # Missing or pending ACKs are never retried here.
        return previous_id
    suffix = previous_id[len(base_id):]
    attempt = 1
    if suffix.startswith("-R"):
        try:
            attempt = max(1, int(suffix[2:]) + 1)
        except ValueError:
            attempt = 1
    return f"{base_id}-R{attempt}"


def publish_close_order(
    *, ticket: int, common_files: str | Path | None = None,
    ttl_seconds: int = 60,
) -> dict[str, Any]:
    directory = Path(common_files) if common_files else default_common_files()
    pending = pending_command_state(directory)
    if pending.get("pending"):
        return {
            "status": "command_pending",
            "reason": "A previous broker command must be reconciled before another command can be published.",
            "pending_command": pending,
        }
    terminal = read_ea_status(directory)
    if terminal.get("status") != "fresh":
        return {"status": "terminal_not_ready", "terminal": terminal}
    owned = {
        int(row["ticket"]): row
        for row in read_positions(directory)
    }
    position = owned.get(int(ticket))
    if position is None:
        return {"status": "position_not_found", "ticket": int(ticket)}
    # Include remaining volume in the id: repeated cycles are idempotent,
    # while a broker-confirmed partial close can target the smaller remainder.
    volume_key = int(round(float(position["volume"]) * 100_000_000))
    command = build_command(
        command_id=_next_close_command_id(directory, int(ticket), volume_key),
        action="CLOSE", symbol="BTC", position_ticket=int(ticket),
        ttl_seconds=ttl_seconds,
    )
    completed_ack = _completed_command_ack(directory, command["id"])
    if completed_ack is not None:
        return {
            "status": "already_processed",
            "command_id": command["id"],
            "ack": completed_ack,
            "message": "The broker has already returned a final acknowledgment for this signal.",
        }
    target = publish_command(directory, command)
    return {
        "status": "published", "command_id": command["id"],
        "ticket": int(ticket), "path": str(target),
        "message": "Close command published; wait for MT5 deal confirmation.",
    }
