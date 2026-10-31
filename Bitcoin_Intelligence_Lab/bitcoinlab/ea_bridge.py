from __future__ import annotations

from datetime import datetime, timezone
import math
import os
from pathlib import Path
import time
from typing import Any

from .command_protocol import build_command, publish_command, read_ack
from .scenarios import build_trade_levels


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
    if len(fields) < 9 or fields[0] != "BTCIL1":
        return {"status": "invalid", "reason": "EA status envelope is malformed."}
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
        account_mode = int(fields[13]) if len(fields) > 13 else None
    except ValueError:
        account_mode = None
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
    result = {
        "status": "fresh" if -5 <= age <= max_age_seconds else "stale",
        "age_seconds": age, "symbol": fields[1], "timeframe": fields[2],
        "connection": fields[4], "bid": bid, "ask": ask,
        "open_positions": open_positions, "ea_message": detail,
        "point": point, "stops_level_points": stops_points,
        "trading_ready": trading_ready, "readiness_marker": readiness_marker,
        "account_server": account_server,
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
    return result


def publish_decision_order(
    *, report: dict, common_files: str | Path | None = None,
    volume: float = 0.01, atr_stop_multiple: float = 1.2,
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
    terminal = read_ea_status(directory)
    if terminal.get("status") != "fresh":
        return {"status": "terminal_not_ready", "terminal": terminal}

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
    command = build_command(
        command_id=f"BTC-{bar_key}", action="OPEN", symbol="BTC", side=side,
        volume=float(volume), stop_loss=float(levels["stop_loss"]),
        take_profit=float(levels["take_profit"]), ttl_seconds=ttl_seconds,
    )
    target = publish_command(directory, command)
    return {
        "status": "published", "command_id": command["id"],
        "symbol": terminal["symbol"], "side": side, "volume": volume,
        "levels": levels, "path": str(target),
        "message": "A real demo-trading command was published; wait for the EA acknowledgment and broker deal confirmation.",
    }


def current_ack(common_files: str | Path | None = None) -> dict[str, Any]:
    directory = Path(common_files) if common_files else default_common_files()
    return read_ack(directory)


def read_positions(common_files: str | Path) -> list[dict[str, Any]]:
    path = Path(common_files) / "BitcoinIntelligenceLab" / "positions.tsv"
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    positions: list[dict[str, Any]] = []
    for line in lines[1:]:
        fields = line.split("|")
        if len(fields) != 9:
            continue
        try:
            positions.append({
                "ticket": int(fields[0]), "symbol": fields[1],
                "type": "BUY" if int(fields[2]) == 0 else "SELL",
                "volume": float(fields[3]), "price_open": float(fields[4]),
                "price_current": float(fields[5]), "stop_loss": float(fields[6]),
                "take_profit": float(fields[7]), "profit": float(fields[8]),
            })
        except (ValueError, IndexError):
            continue
    return positions


def publish_close_order(
    *, ticket: int, common_files: str | Path | None = None,
    ttl_seconds: int = 60,
) -> dict[str, Any]:
    directory = Path(common_files) if common_files else default_common_files()
    terminal = read_ea_status(directory)
    if terminal.get("status") != "fresh":
        return {"status": "terminal_not_ready", "terminal": terminal}
    owned = {row["ticket"] for row in read_positions(directory)}
    if int(ticket) not in owned:
        return {"status": "position_not_found", "ticket": int(ticket)}
    command = build_command(
        command_id=f"BTC-CLOSE-{int(ticket)}-{int(time.time())}",
        action="CLOSE", symbol="BTC", position_ticket=int(ticket),
        ttl_seconds=ttl_seconds,
    )
    target = publish_command(directory, command)
    return {
        "status": "published", "command_id": command["id"],
        "ticket": int(ticket), "path": str(target),
        "message": "Close command published; wait for MT5 deal confirmation.",
    }
