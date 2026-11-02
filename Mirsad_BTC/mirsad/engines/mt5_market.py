from __future__ import annotations

import json
import math
import time
from pathlib import Path
from typing import Any

from ..config import (
    MT5_MARKET_DATA_MAX_AGE_SECONDS,
    MT5_MARKET_DIVERGENCE_MAX_PCT,
    MT5_QUOTE_MAX_AGE_SECONDS,
    MT5_COMMON_FILES,
    SYMBOL,
)

TIMEFRAMES = ("1m", "5m", "15m", "1h", "4h", "1d")
REQUIRED_TIMEFRAMES = ("1m", "5m", "15m")
VENUE_NAME = "MT5 Broker"


class MT5MarketDataEngine:
    """Engine 1 live adapter: read-only market data published by the user's MT5 terminal."""

    def __init__(
        self,
        common_files: str | None = None,
        *,
        symbol: str = SYMBOL,
        max_age_seconds: int = MT5_MARKET_DATA_MAX_AGE_SECONDS,
        quote_max_age_seconds: int = MT5_QUOTE_MAX_AGE_SECONDS,
    ) -> None:
        configured = common_files if common_files is not None else MT5_COMMON_FILES
        self.root = Path(configured).expanduser() / "MirsadBTC" if configured else None
        self.symbol = str(symbol).strip().upper()
        self.max_age_seconds = max(3, int(max_age_seconds))
        self.quote_max_age_seconds = max(1, int(quote_max_age_seconds))

    @staticmethod
    def _finite(value: Any) -> float | None:
        try:
            result = float(value)
        except (TypeError, ValueError, OverflowError):
            return None
        return result if math.isfinite(result) else None

    def _blocked(self, status: str, reason: str, *, captured_at_ms: int | None = None,
                 feed_health: dict[str, Any] | None = None) -> dict[str, Any]:
        return {
            "engine": "engine_1_market", "source": "MT5_TERMINAL", "status": status,
            "symbol": self.symbol, "price": None, "captured_at_ms": captured_at_ms,
            "primary_venue": None, "venue_count": 0,
            "venues": {VENUE_NAME: {
                "status": status, "error": reason, "candles": [], "candles_by_tf": {},
                "trades": [], "orderbook": None, "orderflow": None, "latency_ms": None,
            }},
            "feed_health": feed_health or {}, "reason": reason, "timeframes": list(TIMEFRAMES),
        }

    @staticmethod
    def _parse_timeframe(name: str, payload: Any) -> tuple[list[dict[str, Any]] | None, str | None]:
        if not isinstance(payload, dict):
            return None, f"MT5 snapshot is missing the {name} timeframe object."
        raw_bars = payload.get("bars")
        if not isinstance(raw_bars, list) or len(raw_bars) < 2:
            return None, f"MT5 {name} timeframe has fewer than two bars."
        bars: list[dict[str, Any]] = []
        previous_time = 0
        for index, raw in enumerate(raw_bars):
            if not isinstance(raw, dict):
                return None, f"MT5 {name} bar {index} is not an object."
            try:
                stamp = int(raw["open_time_ms"])
                open_price, high = float(raw["open"]), float(raw["high"])
                low, close = float(raw["low"]), float(raw["close"])
                volume = float(raw.get("volume", 0.0))
            except (KeyError, TypeError, ValueError, OverflowError):
                return None, f"MT5 {name} bar {index} is missing numeric OHLC/time data."
            numbers = (open_price, high, low, close, volume)
            if stamp <= previous_time or not all(math.isfinite(value) for value in numbers):
                return None, f"MT5 {name} candles contain non-finite values or non-monotonic timestamps."
            if min(open_price, high, low, close) <= 0 or volume < 0:
                return None, f"MT5 {name} candle contains non-positive prices or negative volume."
            if high < max(open_price, close, low) or low > min(open_price, close, high):
                return None, f"MT5 {name} candle has inconsistent OHLC geometry."
            closed = raw.get("closed")
            if not isinstance(closed, bool):
                return None, f"MT5 {name} candle is missing its closed/forming flag."
            if index < len(raw_bars) - 1 and not closed:
                return None, f"MT5 {name} history contains a forming candle before the final bar."
            if index == len(raw_bars) - 1 and closed:
                return None, f"MT5 {name} history does not end with the current forming candle."
            bars.append({
                "open_time_ms": stamp, "open": open_price, "high": high,
                "low": low, "close": close, "volume": volume, "closed": closed,
            })
            previous_time = stamp
        return bars, None

    def collect(self, bridge: dict[str, Any] | None = None) -> dict[str, Any]:
        if self.root is None:
            return self._blocked(
                "NOT_CONFIGURED",
                "MIRSAD_MT5_COMMON_FILES is not configured; Engine 1 requires the user's MT5 Common Files feed.",
            )
        path = self.root / "market.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return self._blocked("OFFLINE", "MT5 market.json has not been published by the read-only Chart Observer.")
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            return self._blocked("INVALID", f"MT5 market.json could not be read: {type(exc).__name__}.")

        if not isinstance(payload, dict) or payload.get("schema") != "MIR-MT5-MARKET-1":
            return self._blocked("INVALID", "MT5 market snapshot schema is missing or unsupported.")
        try:
            captured_at_ms = int(payload["captured_at_utc_ms"])
        except (KeyError, TypeError, ValueError, OverflowError):
            return self._blocked("INVALID", "MT5 market snapshot capture time is missing or invalid.")
        age_seconds = (int(time.time() * 1000) - captured_at_ms) / 1000.0
        if not math.isfinite(age_seconds) or age_seconds < -2 or age_seconds > self.max_age_seconds:
            return self._blocked(
                "STALE", "MT5 market snapshot is future-dated or older than the configured freshness limit.",
                captured_at_ms=captured_at_ms,
                feed_health={"snapshot_age_seconds": round(age_seconds, 3)},
            )

        account = payload.get("account") if isinstance(payload.get("account"), dict) else {}
        server = str(account.get("server", "")).strip()
        broker_symbol = str(payload.get("broker_symbol", "")).strip()
        market_symbol = str(payload.get("market_symbol", "")).strip().upper()
        if payload.get("terminal_connected") is not True or not server:
            return self._blocked(
                "OFFLINE", "MT5 terminal connection or broker account-server identity is unavailable.",
                captured_at_ms=captured_at_ms,
            )
        if market_symbol != self.symbol or not broker_symbol:
            return self._blocked(
                "SYMBOL_MISMATCH", "MT5 broker symbol is not mapped to the configured Mirsad market symbol.",
                captured_at_ms=captured_at_ms,
            )

        quote = payload.get("quote") if isinstance(payload.get("quote"), dict) else {}
        bid, ask = self._finite(quote.get("bid")), self._finite(quote.get("ask"))
        tick_age = self._finite(quote.get("tick_age_seconds"))
        if bid is None or ask is None or tick_age is None or bid <= 0 or ask < bid or tick_age < 0 or tick_age > self.quote_max_age_seconds:
            return self._blocked(
                "STALE_QUOTE", "MT5 bid/ask quote is invalid, crossed or older than the configured tick limit.",
                captured_at_ms=captured_at_ms,
                feed_health={"snapshot_age_seconds": round(age_seconds, 3), "tick_age_seconds": tick_age},
            )

        bridge_check: dict[str, Any] = {"status": "NOT_CHECKED"}
        if isinstance(bridge, dict) and bridge.get("status") == "CONNECTED":
            bridge_account = bridge.get("account") if isinstance(bridge.get("account"), dict) else {}
            bridge_quote = bridge.get("quote") if isinstance(bridge.get("quote"), dict) else {}
            bridge_bid, bridge_ask = self._finite(bridge_quote.get("bid")), self._finite(bridge_quote.get("ask"))
            bridge_age = self._finite(bridge.get("quote_age_seconds"))
            same_identity = (
                str(bridge.get("symbol", "")).strip() == broker_symbol
                and str(bridge.get("market_symbol", "")).strip().upper() == self.symbol
                and str(bridge_account.get("server", "")).strip().casefold() == server.casefold()
            )
            if not same_identity:
                return self._blocked(
                    "BRIDGE_IDENTITY_MISMATCH",
                    "MT5 market feed and execution bridge do not identify the same broker symbol, market mapping and account server.",
                    captured_at_ms=captured_at_ms,
                )
            if bridge_bid is None or bridge_ask is None or bridge_age is None or bridge_bid <= 0 or bridge_ask < bridge_bid or bridge_age < 0 or bridge_age > self.quote_max_age_seconds:
                return self._blocked(
                    "BRIDGE_QUOTE_STALE", "Execution bridge quote is invalid or stale; MT5 feed cannot be cross-checked.",
                    captured_at_ms=captured_at_ms,
                )
            market_mid, bridge_mid = (bid + ask) / 2.0, (bridge_bid + bridge_ask) / 2.0
            divergence = abs(market_mid - bridge_mid) / market_mid if market_mid > 0 else math.inf
            bridge_check = {
                "status": "MATCHED" if divergence <= MT5_MARKET_DIVERGENCE_MAX_PCT else "DIVERGENT",
                "mid_divergence_pct": round(divergence * 100, 5),
            }
            if not math.isfinite(divergence) or divergence > MT5_MARKET_DIVERGENCE_MAX_PCT:
                return self._blocked(
                    "QUOTE_DIVERGENCE",
                    "The read-only MT5 market quote and Engine 5 terminal quote exceed the permitted divergence.",
                    captured_at_ms=captured_at_ms, feed_health=bridge_check,
                )

        frames_payload = payload.get("timeframes")
        if not isinstance(frames_payload, dict):
            return self._blocked("INVALID", "MT5 multi-timeframe history object is missing.", captured_at_ms=captured_at_ms)
        candles_by_tf: dict[str, list[dict[str, Any]]] = {}
        for timeframe in TIMEFRAMES:
            bars, error = self._parse_timeframe(timeframe, frames_payload.get(timeframe))
            if error:
                return self._blocked("INVALID_HISTORY", error, captured_at_ms=captured_at_ms)
            assert bars is not None
            candles_by_tf[timeframe] = bars
        missing = [
            timeframe for timeframe in REQUIRED_TIMEFRAMES
            if sum(1 for bar in candles_by_tf[timeframe] if bar["closed"]) < 50
        ]
        if missing:
            return self._blocked(
                "INSUFFICIENT_HISTORY", "MT5 completed history is insufficient for Engine 3 in: " + ", ".join(missing),
                captured_at_ms=captured_at_ms,
                feed_health={"missing_required_timeframes": missing},
            )

        price = (bid + ask) / 2.0
        venue = {
            "status": "LIVE", "price": price, "bid": bid, "ask": ask,
            "latency_ms": round(age_seconds * 1000, 2),
            "candles": candles_by_tf["1m"], "candles_by_tf": candles_by_tf,
            "orderbook": None, "orderflow": None, "trades": [],
            "broker_symbol": broker_symbol, "account_server": server,
            "tick_age_seconds": tick_age, "error": None,
        }
        return {
            "engine": "engine_1_market", "source": "MT5_TERMINAL", "status": "LIVE",
            "symbol": self.symbol, "price": price, "captured_at_ms": captured_at_ms,
            "primary_venue": VENUE_NAME, "venue_count": 1, "venues": {VENUE_NAME: venue},
            "feed_health": {
                "terminal_connected": True, "quote_fresh": True, "timeframes_ready": True,
                "snapshot_age_seconds": round(age_seconds, 3), "tick_age_seconds": tick_age,
                "account_server": server, "broker_symbol": broker_symbol,
                "bridge_quote_check": bridge_check,
            },
            "reason": None, "timeframes": list(TIMEFRAMES),
        }
