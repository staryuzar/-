from __future__ import annotations

import json
import math
import time
from pathlib import Path
from typing import Any

from ..config import MT5_COMMON_FILES, MT5_MARKET_DATA_MAX_AGE_SECONDS

TIMEFRAMES = ("1m", "5m", "15m", "1h", "4h", "1d")
REQUIRED_TIMEFRAMES = ("1m", "5m", "15m")
CANDLE_SCHEMA = "MIR-ENGINE2-CANDLES-1"


class MT5ChartCandleHistory:
    """Engine 2 native candle inbox, paired with the real chart Observer.

    This module owns the OHLC history contract consumed by Engine 3. Engine 1
    never reads this file and never receives candle arrays.
    """

    def __init__(
        self,
        common_files: str | None = None,
        *,
        symbol: str = "BTCUSDT",
        max_age_seconds: int = MT5_MARKET_DATA_MAX_AGE_SECONDS,
    ) -> None:
        configured = common_files if common_files is not None else MT5_COMMON_FILES
        self.path = Path(configured).expanduser() / "MirsadBTC" / "observer" / "candles.json" if configured else None
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
            "engine": "engine_2_chart_candles",
            "source": "MT5_CHART_OBSERVER",
            "status": status,
            "decision_eligible": False,
            "symbol": self.symbol,
            "candles_by_tf": {},
            "timeframes": {},
            "feed_health": {},
            "reason": reason,
            **extra,
        }

    def _parse_frame(self, name: str, raw: Any) -> tuple[list[dict[str, Any]] | None, str | None]:
        if not isinstance(raw, dict):
            return None, f"Engine 2 candle snapshot is missing the {name} timeframe."
        bars = raw.get("bars")
        try:
            copied = int(raw.get("copied", -1))
            error_code = int(raw.get("error_code", -1))
        except (TypeError, ValueError, OverflowError):
            return None, f"Engine 2 {name} timeframe count/error metadata is invalid."
        if not isinstance(bars, list) or copied != len(bars) or error_code != 0:
            return None, f"Engine 2 {name} CopyRates count or error code is inconsistent."
        if len(bars) < 2:
            return None, f"Engine 2 {name} timeframe contains fewer than two candles."

        result: list[dict[str, Any]] = []
        previous_time = 0
        for index, raw_bar in enumerate(bars):
            if not isinstance(raw_bar, dict):
                return None, f"Engine 2 {name} candle {index} is not an object."
            try:
                stamp = int(raw_bar["open_time_ms"])
                open_price = float(raw_bar["open"])
                high = float(raw_bar["high"])
                low = float(raw_bar["low"])
                close = float(raw_bar["close"])
                volume = float(raw_bar.get("volume", 0.0))
                closed = raw_bar["closed"]
            except (KeyError, TypeError, ValueError, OverflowError):
                return None, f"Engine 2 {name} candle {index} is missing numeric OHLC/time data."
            values = (open_price, high, low, close, volume)
            if stamp <= previous_time or not all(math.isfinite(value) for value in values):
                return None, f"Engine 2 {name} candles have non-finite values or non-monotonic times."
            if min(open_price, high, low, close) <= 0 or volume < 0:
                return None, f"Engine 2 {name} candle contains non-positive prices or negative volume."
            if high < max(open_price, close, low) or low > min(open_price, close, high):
                return None, f"Engine 2 {name} candle has inconsistent OHLC geometry."
            if not isinstance(closed, bool):
                return None, f"Engine 2 {name} candle is missing its closed/forming flag."
            if index < len(bars) - 1 and not closed:
                return None, f"Engine 2 {name} history has a forming candle before the final row."
            if index == len(bars) - 1 and closed:
                return None, f"Engine 2 {name} history does not end with the current forming candle."
            result.append({
                "open_time_ms": stamp,
                "open": open_price,
                "high": high,
                "low": low,
                "close": close,
                "volume": volume,
                "closed": closed,
            })
            previous_time = stamp
        return result, None

    def collect(
        self,
        *,
        bridge: dict[str, Any] | None = None,
        market: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if self.path is None:
            return self._blocked(
                "NOT_CONFIGURED",
                "MIRSAD_MT5_COMMON_FILES is not configured for the Engine 2 candle inbox.",
            )
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return self._blocked("OFFLINE", "Engine 2 candles.json has not been published by the MT5 Chart Observer.")
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            return self._blocked("INVALID", f"Engine 2 candles.json could not be read: {type(exc).__name__}.")

        if not isinstance(payload, dict) or payload.get("schema") != CANDLE_SCHEMA:
            return self._blocked("INVALID", "Engine 2 candle snapshot schema is missing or unsupported.")
        try:
            captured_at_ms = int(payload["captured_at_utc_ms"])
        except (KeyError, TypeError, ValueError, OverflowError):
            return self._blocked("INVALID", "Engine 2 candle snapshot capture time is missing or invalid.")
        age_seconds = (int(time.time() * 1000) - captured_at_ms) / 1000.0
        if not math.isfinite(age_seconds) or age_seconds < -2 or age_seconds > self.max_age_seconds:
            return self._blocked(
                "STALE",
                "Engine 2 candle snapshot is future-dated or older than its freshness limit.",
                captured_at_ms=captured_at_ms,
                age_seconds=round(age_seconds, 3),
            )
        if payload.get("time_basis") != "UTC_NORMALIZED_FROM_MT5_SERVER_TIME":
            return self._blocked("INVALID", "Engine 2 candle snapshot time basis is missing or unsupported.")

        account = payload.get("account") if isinstance(payload.get("account"), dict) else {}
        server = str(account.get("server", "")).strip()
        broker_symbol = str(payload.get("broker_symbol", "")).strip()
        market_symbol = str(payload.get("market_symbol", "")).strip().upper()
        if payload.get("terminal_connected") is not True or not server:
            return self._blocked(
                "OFFLINE",
                "Engine 2 candle source terminal/server identity is unavailable.",
                source_terminal_connected=payload.get("terminal_connected"),
                source_account_server_present=bool(server),
                source_broker_symbol_present=bool(broker_symbol),
                snapshot_captured_at_ms=captured_at_ms,
            )
        if market_symbol != self.symbol or not broker_symbol:
            return self._blocked("SYMBOL_MISMATCH", "Engine 2 broker symbol is not mapped to the configured market symbol.")

        if not isinstance(account, dict):
            account = {}
        if isinstance(market, dict) and market.get("status") == "LIVE":
            if str(market.get("symbol", "")).strip().upper() != market_symbol:
                return self._blocked("MARKET_IDENTITY_MISMATCH", "Engine 1 and Engine 2 market-symbol mappings differ.")
            market_feed = market.get("feed_health") if isinstance(market.get("feed_health"), dict) else {}
            if str(market_feed.get("broker_symbol", "")).strip() != broker_symbol:
                return self._blocked("MARKET_IDENTITY_MISMATCH", "Engine 1 and Engine 2 broker symbols differ.")
            if str(market_feed.get("account_server", "")).strip().casefold() != server.casefold():
                return self._blocked("MARKET_IDENTITY_MISMATCH", "Engine 1 and Engine 2 account servers differ.")

        if isinstance(bridge, dict) and bridge.get("status") == "CONNECTED":
            bridge_account = bridge.get("account") if isinstance(bridge.get("account"), dict) else {}
            if (
                str(bridge.get("symbol", "")).strip() != broker_symbol
                or str(bridge.get("market_symbol", "")).strip().upper() != self.symbol
                or str(bridge_account.get("server", "")).strip().casefold() != server.casefold()
            ):
                return self._blocked("BRIDGE_IDENTITY_MISMATCH", "Engine 2 candles and Engine 5 do not identify the same MT5 symbol/account.")

        frames_payload = payload.get("timeframes")
        if not isinstance(frames_payload, dict):
            return self._blocked("INVALID", "Engine 2 multi-timeframe candle history is missing.")
        candles_by_tf: dict[str, list[dict[str, Any]]] = {}
        for timeframe in TIMEFRAMES:
            bars, error = self._parse_frame(timeframe, frames_payload.get(timeframe))
            if error:
                return self._blocked("INVALID_HISTORY", error)
            assert bars is not None
            candles_by_tf[timeframe] = bars

        missing = [
            timeframe for timeframe in REQUIRED_TIMEFRAMES
            if sum(1 for candle in candles_by_tf[timeframe] if candle["closed"]) < 50
        ]
        if missing:
            return self._blocked(
                "INSUFFICIENT_HISTORY",
                "Engine 2 completed candle history is insufficient for Engine 3 in: " + ", ".join(missing),
                missing_required_timeframes=missing,
            )

        return {
            "engine": "engine_2_chart_candles",
            "source": "MT5_CHART_OBSERVER",
            "status": "READY",
            "decision_eligible": True,
            "symbol": market_symbol,
            "broker_symbol": broker_symbol,
            "account_server": server,
            "captured_at_ms": captured_at_ms,
            "age_seconds": round(age_seconds, 3),
            "candles_by_tf": candles_by_tf,
            "timeframes": {name: len(rows) for name, rows in candles_by_tf.items()},
            "closed_candles": {
                name: sum(1 for row in rows if row["closed"])
                for name, rows in candles_by_tf.items()
            },
            "feed_health": {
                "terminal_connected": True,
                "snapshot_fresh": True,
                "symbol_mapped": True,
                "account_server_matched": True,
                "required_timeframes_ready": True,
            },
            "reason": None,
        }
