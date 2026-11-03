from __future__ import annotations

import json
import math
import time
from pathlib import Path
from typing import Any

from ..config import MT5_COMMON_FILES, MT5_MARKET_DATA_MAX_AGE_SECONDS

INDICATOR_SCHEMA = "MIR-MT5-INDICATORS-1"
TIMEFRAMES = ("1m", "5m", "15m", "1h", "4h", "1d")
REQUIRED_TIMEFRAMES = ("1m", "5m", "15m")
INDICATORS = (
    "ema20", "ema50", "rsi14", "atr14",
    "macd_main", "macd_signal", "bollinger_middle",
    "bollinger_upper", "bollinger_lower", "stochastic_k",
    "stochastic_d", "adx14", "plus_di14", "minus_di14",
    "cci20", "mfi14", "momentum14", "wpr14", "obv", "osma",
)
REQUIRED_INDICATORS = ("ema20", "ema50", "rsi14", "atr14")


class MT5NativeIndicatorHistory:
    """Read-only consumer for native MT5 CopyBuffer indicator snapshots."""

    def __init__(
        self,
        common_files: str | None = None,
        *,
        symbol: str = "BTCUSDT",
        max_age_seconds: int = MT5_MARKET_DATA_MAX_AGE_SECONDS,
    ) -> None:
        configured = common_files if common_files is not None else MT5_COMMON_FILES
        self.path = (
            Path(configured).expanduser()
            / "MirsadBTC" / "observer" / "indicators.json"
            if configured else None
        )
        self.symbol = str(symbol).strip().upper()
        self.max_age_seconds = max(3, int(max_age_seconds))

    @staticmethod
    def _finite(value: Any) -> float | None:
        try:
            result = float(value)
        except (TypeError, ValueError, OverflowError):
            return None
        return result if math.isfinite(result) else None

    def _blocked(self, status: str, reason: str, **extra: Any) -> dict[str, Any]:
        return {
            "engine": "mt5_native_indicator_history",
            "source": "MT5_COPYBUFFER",
            "status": status,
            "decision_eligible": False,
            "symbol": self.symbol,
            "timeframes": {},
            "reason": reason,
            **extra,
        }

    def _parse_frame(self, name: str, raw: Any) -> dict[str, Any]:
        if not isinstance(raw, dict):
            return {"status": "MISSING", "values": {}, "reason": "Timeframe is absent."}
        try:
            closed_time = int(raw.get("closed_bar_time_utc_ms", 0) or 0)
            forming_time = int(raw.get("forming_bar_time_utc_ms", 0) or 0)
        except (TypeError, ValueError, OverflowError):
            return {"status": "INVALID", "values": {}, "reason": "Bar timestamps are invalid."}
        if closed_time <= 0 or forming_time <= closed_time:
            return {
                "status": "INSUFFICIENT",
                "values": {},
                "closed_bar_time_utc_ms": closed_time or None,
                "forming_bar_time_utc_ms": forming_time or None,
                "reason": "MT5 has not supplied ordered closed/forming bar timestamps.",
            }

        raw_values = raw.get("values")
        if not isinstance(raw_values, dict):
            return {
                "status": "INVALID",
                "values": {},
                "closed_bar_time_utc_ms": closed_time,
                "forming_bar_time_utc_ms": forming_time,
                "reason": "Indicator values map is missing.",
            }

        values: dict[str, dict[str, Any]] = {}
        ready_names: list[str] = []
        for indicator in INDICATORS:
            item = raw_values.get(indicator)
            if not isinstance(item, dict) or str(item.get("status", "")).upper() != "READY":
                source_status = (
                    str(item.get("status", "UNAVAILABLE")).upper()
                    if isinstance(item, dict) else "UNAVAILABLE"
                )
                if source_status not in {"WARMING_UP", "UNAVAILABLE", "INVALID"}:
                    source_status = "UNAVAILABLE"
                values[indicator] = {
                    "status": source_status,
                    "closed": None,
                    "current": None,
                    "error_code": item.get("error_code") if isinstance(item, dict) else None,
                    "copied": item.get("copied") if isinstance(item, dict) else None,
                    "bars_calculated": item.get("bars_calculated") if isinstance(item, dict) else None,
                }
                continue
            previous_closed = self._finite(item.get("previous_closed"))
            closed = self._finite(item.get("closed"))
            current = self._finite(item.get("current"))
            if closed is None or current is None:
                values[indicator] = {
                    "status": "INVALID",
                    "previous_closed": previous_closed,
                    "closed": None,
                    "current": None,
                    "error_code": item.get("error_code"),
                    "copied": item.get("copied"),
                    "bars_calculated": item.get("bars_calculated"),
                }
                continue
            values[indicator] = {
                "status": "READY",
                "previous_closed": previous_closed,
                "closed": closed,
                "current": current,
                "error_code": 0,
            }
            ready_names.append(indicator)

        required_missing = [
            name for name in REQUIRED_INDICATORS
            if values[name]["status"] != "READY"
        ]
        return {
            "status": "READY" if not required_missing else "PARTIAL",
            "closed_bar_time_utc_ms": closed_time,
            "forming_bar_time_utc_ms": forming_time,
            "values": values,
            "ready_indicators": ready_names,
            "ready_indicator_count": len(ready_names),
            "missing_required_indicators": required_missing,
            "reason": None if not required_missing else (
                "Required native MT5 indicator buffers are not ready: "
                + ", ".join(required_missing)
            ),
        }

    def collect(
        self,
        *,
        bridge: dict[str, Any] | None = None,
        candle_history: dict[str, Any] | None = None,
        now_ms: int | None = None,
    ) -> dict[str, Any]:
        if self.path is None:
            return self._blocked(
                "NOT_CONFIGURED",
                "MIRSAD_MT5_COMMON_FILES is not configured for the native MT5 indicator inbox.",
            )
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return self._blocked("OFFLINE", "MT5 observer has not published indicators.json.")
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            return self._blocked(
                "INVALID",
                f"MT5 native indicator snapshot could not be read: {type(exc).__name__}.",
            )

        if not isinstance(payload, dict) or payload.get("schema") != INDICATOR_SCHEMA:
            return self._blocked("INVALID", "Native MT5 indicator snapshot schema is missing or unsupported.")
        try:
            captured_at = int(payload["captured_at_utc_ms"])
        except (KeyError, TypeError, ValueError, OverflowError):
            return self._blocked("INVALID", "Native MT5 indicator capture timestamp is missing or invalid.")

        clock_now = int(time.time() * 1000) if now_ms is None else int(now_ms)
        age_seconds = (clock_now - captured_at) / 1000.0
        if not math.isfinite(age_seconds) or age_seconds < -2 or age_seconds > self.max_age_seconds:
            return self._blocked(
                "STALE",
                "Native MT5 indicator snapshot is future-dated or older than the configured freshness limit.",
                captured_at_ms=captured_at,
                age_seconds=round(age_seconds, 3),
            )
        if payload.get("time_basis") != "UTC_NORMALIZED_FROM_MT5_SERVER_TIME":
            return self._blocked("INVALID", "Native MT5 indicator time basis is missing or unsupported.")

        account = payload.get("account") if isinstance(payload.get("account"), dict) else {}
        server = str(account.get("server", "")).strip()
        broker_symbol = str(payload.get("broker_symbol", "")).strip()
        market_symbol = str(payload.get("market_symbol", "")).strip().upper()
        if payload.get("terminal_connected") is not True or not server:
            return self._blocked("OFFLINE", "MT5 native indicator source is not connected to an identified broker server.")
        if market_symbol != self.symbol or not broker_symbol:
            return self._blocked("SYMBOL_MISMATCH", "Native MT5 indicator broker symbol does not match the configured Mirsad symbol.")

        if isinstance(candle_history, dict) and candle_history.get("status") == "READY":
            if (
                str(candle_history.get("broker_symbol", "")).strip() != broker_symbol
                or str(candle_history.get("account_server", "")).strip().casefold() != server.casefold()
                or str(candle_history.get("symbol", "")).strip().upper() != market_symbol
            ):
                return self._blocked(
                    "CANDLE_IDENTITY_MISMATCH",
                    "Native indicator snapshot and Engine 2 candle history do not identify the same symbol/account.",
                )
        if isinstance(bridge, dict) and bridge.get("status") == "CONNECTED":
            bridge_account = bridge.get("account") if isinstance(bridge.get("account"), dict) else {}
            if (
                str(bridge.get("symbol", "")).strip() != broker_symbol
                or str(bridge.get("market_symbol", "")).strip().upper() != market_symbol
                or str(bridge_account.get("server", "")).strip().casefold() != server.casefold()
            ):
                return self._blocked(
                    "BRIDGE_IDENTITY_MISMATCH",
                    "Native indicator snapshot and MT5 communication bridge do not identify the same account/symbol.",
                )

        frames_raw = payload.get("timeframes")
        if not isinstance(frames_raw, dict):
            return self._blocked("INVALID", "Native MT5 indicator timeframe map is missing.")
        frames = {name: self._parse_frame(name, frames_raw.get(name)) for name in TIMEFRAMES}
        missing_required = [
            name for name in REQUIRED_TIMEFRAMES
            if frames[name]["status"] != "READY"
        ]
        ready_count = sum(frame["status"] == "READY" for frame in frames.values())
        overall = "READY" if not missing_required else "PARTIAL"
        return {
            "engine": "mt5_native_indicator_history",
            "source": "MT5_COPYBUFFER",
            "calculation_source": str(payload.get("calculation_source", "MT5_NATIVE_INDICATOR_BUFFERS")),
            "status": overall,
            "decision_eligible": False,
            "symbol": market_symbol,
            "broker_symbol": broker_symbol,
            "account_server": server,
            "captured_at_ms": captured_at,
            "age_seconds": round(age_seconds, 3),
            "timeframes": frames,
            "ready_timeframe_count": ready_count,
            "required_timeframes_ready": not missing_required,
            "missing_required_timeframes": missing_required,
            "scope": (
                "Native MT5 standard indicator buffers. Each field contains the last closed-bar "
                "value and the forming-bar value separately. Custom iCustom indicators are not "
                "included until their indicator name and input contract are configured."
            ),
            "reason": None if not missing_required else (
                "Native MT5 required indicator buffers are not yet ready for: "
                + ", ".join(missing_required)
            ),
        }


__all__ = [
    "INDICATOR_SCHEMA",
    "TIMEFRAMES",
    "INDICATORS",
    "MT5NativeIndicatorHistory",
]
