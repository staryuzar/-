from __future__ import annotations

import math
import os
from pathlib import Path
import tempfile
import time
from typing import Any, Mapping

COMMAND_FOLDER = "BitcoinIntelligenceLab"
COMMAND_FILENAME = "trade_command.txt"
ACK_FILENAME = "trade_command_ack.txt"
SCHEMA_VERSION = "BTCIL1"


def build_command(
    *, command_id: str, action: str, symbol: str, side: str = "NONE",
    volume: float = 0.0, stop_loss: float = 0.0, take_profit: float = 0.0,
    position_ticket: int = 0, ttl_seconds: int = 60, now: int | None = None,
) -> dict[str, Any]:
    if not command_id or any(not (ch.isalnum() or ch in "-_") for ch in command_id):
        raise ValueError("command_id must contain only letters, digits, hyphens or underscores.")
    if symbol != "BTC":
        raise ValueError("The BTC executor accepts only the broker's exact BTC symbol.")
    action, side = action.upper(), side.upper()
    if action not in {"OPEN", "CLOSE"}:
        raise ValueError("Unsupported command action.")
    if action == "OPEN":
        if side not in {"BUY", "SELL"}:
            raise ValueError("OPEN requires BUY or SELL.")
        if not math.isfinite(volume) or volume <= 0:
            raise ValueError("OPEN requires finite positive volume.")
        if not math.isfinite(stop_loss) or not math.isfinite(take_profit) or stop_loss <= 0 or take_profit <= 0:
            raise ValueError("OPEN requires positive stop-loss and take-profit levels.")
        if position_ticket != 0:
            raise ValueError("OPEN does not accept a position ticket.")
    else:
        if position_ticket <= 0:
            raise ValueError("CLOSE requires a positive position ticket.")
        if volume != 0 or stop_loss != 0 or take_profit != 0:
            raise ValueError("CLOSE cannot contain new sizing or price levels.")
        side = "NONE"
    if isinstance(ttl_seconds, bool) or not 5 <= int(ttl_seconds) <= 300:
        raise ValueError("Command TTL must be between 5 and 300 seconds.")
    issued = int(time.time()) if now is None else int(now)
    return {
        "schema": SCHEMA_VERSION, "id": command_id, "issued_at": issued,
        "expires_at": issued + int(ttl_seconds), "symbol": symbol,
        "action": action, "side": side, "volume": float(volume),
        "stop_loss": float(stop_loss), "take_profit": float(take_profit),
        "position_ticket": int(position_ticket),
    }


def serialize_command(command: Mapping[str, Any]) -> str:
    fields = (
        command["schema"], command["id"], str(int(command["issued_at"])),
        str(int(command["expires_at"])), command["symbol"], command["action"],
        command["side"], format(float(command["volume"]), ".8f"),
        format(float(command["stop_loss"]), ".8f"),
        format(float(command["take_profit"]), ".8f"),
        str(int(command["position_ticket"])),
    )
    if any("|" in str(value) or "\n" in str(value) or "\r" in str(value) for value in fields):
        raise ValueError("Command contains an unsafe delimiter.")
    return "|".join(str(value) for value in fields) + "\n"


def publish_command(common_files: str | Path, command: Mapping[str, Any]) -> Path:
    root = Path(common_files) / COMMAND_FOLDER
    root.mkdir(parents=True, exist_ok=True)
    target = root / COMMAND_FILENAME
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="ascii", newline="\n", dir=root,
            prefix=COMMAND_FILENAME + ".", suffix=".tmp", delete=False,
        ) as handle:
            temp_name = handle.name
            handle.write(serialize_command(command))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, target)
    except (OSError, UnicodeError, ValueError) as exc:
        if temp_name:
            try:
                os.unlink(temp_name)
            except OSError:
                pass
        raise RuntimeError("Could not atomically publish BTC trade command.") from exc
    return target


def read_ack(common_files: str | Path) -> dict[str, Any]:
    import json
    path = Path(common_files) / COMMAND_FOLDER / ACK_FILENAME
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}
