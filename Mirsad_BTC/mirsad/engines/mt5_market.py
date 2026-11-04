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

VENUE_NAME = "MT5 Broker"
MARKET_SCHEMA = "MIR-MT5-MARKET-2"
MAX_TICK_ROWS = 512


class MT5MarketDataEngine:
    """Engine 5 support: broker quote/microstructure telemetry for execution safety.

    This adapter does not collect Engine 1 intelligence, calendars, charts or indicators.
    """

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

    def _blocked(
        self,
        status: str,
        reason: str,
        *,
        captured_at_ms: int | None = None,
        feed_health: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "engine": "engine_5_execution_quote_feed",
            "source": "MT5_TERMINAL",
            "status": status,
            "symbol": self.symbol,
            "price": None,
            "captured_at_ms": captured_at_ms,
            "primary_venue": None,
            "venue_count": 0,
            "venues": {
                VENUE_NAME: {
                    "status": status,
                    "error": reason,
                    "price": None,
                    "bid": None,
                    "ask": None,
                    "microstructure": {},
                }
            },
            "market_context": {
                "microstructure": {"status": "NOT_AVAILABLE"},
            },
            "feed_health": feed_health or {},
            "reason": reason,
        }

    def _parse_ticks(
        self, raw_ticks: Any, *, captured_at_ms: int
    ) -> tuple[list[dict[str, Any]], str]:
        if not isinstance(raw_ticks, list):
            return [], "UNAVAILABLE"
        if len(raw_ticks) > MAX_TICK_ROWS:
            return [], "INVALID"
        ticks: list[dict[str, Any]] = []
        previous_time = 0
        for index, raw in enumerate(raw_ticks):
            if not isinstance(raw, dict):
                return [], "INVALID"
            stamp = self._finite(raw.get("time_utc_ms"))
            bid = self._finite(raw.get("bid"))
            ask = self._finite(raw.get("ask"))
            last = self._finite(raw.get("last"))
            volume = self._finite(raw.get("volume"))
            volume_real = self._finite(raw.get("volume_real"))
            flags_raw = raw.get("flags", 0)
            try:
                flags = int(flags_raw)
            except (TypeError, ValueError, OverflowError):
                return [], "INVALID"
            if (
                stamp is None or stamp <= 0 or flags < 0
                or (bid is not None and bid < 0)
                or (ask is not None and ask < 0)
                or (last is not None and last < 0)
                or (volume is not None and volume < 0)
                or (volume_real is not None and volume_real < 0)
            ):
                return [], "INVALID"
            bid_value = bid or 0.0
            ask_value = ask or 0.0
            last_value = last or 0.0
            volume_value = volume or 0.0
            volume_real_value = volume_real or 0.0
            # MqlTick keeps the previous Bid/Ask values on Last/Volume-only
            # events. Count a quote update only when the corresponding flags
            # explicitly state that Bid or Ask changed.
            quote_changed = bool(flags & (2 | 4))
            quote_valid = quote_changed and bid_value > 0 and ask_value >= bid_value
            last_valid = bool(flags & 8) and last_value > 0
            volume_valid = bool(flags & 16) and (volume_value > 0 or volume_real_value > 0)
            if not (quote_valid or last_valid or volume_valid):
                return [], "INVALID"
            time_ms = int(stamp)
            if (
                time_ms < previous_time
                or time_ms > captured_at_ms + 2_000
                or time_ms < captured_at_ms - 120_000
            ):
                return [], "INVALID"
            item: dict[str, Any] = {
                "time_utc_ms": float(time_ms),
                "bid": bid_value,
                "ask": ask_value,
                "last": last_value,
                "volume": volume_value,
                "volume_real": volume_real_value,
                "flags": flags,
                "quote_valid": quote_valid,
                "last_valid": last_valid,
                "volume_valid": volume_valid,
            }
            ticks.append(item)
            previous_time = time_ms
        quote_count = sum(1 for tick in ticks if tick["quote_valid"])
        return ticks, "READY" if quote_count >= 2 else "INSUFFICIENT"

    def _microstructure(
        self,
        ticks: list[dict[str, float]],
        bid: float,
        ask: float,
        tick_window_seconds: float,
        tick_status: str,
    ) -> dict[str, Any]:
        midpoint = (bid + ask) / 2.0
        spread = ask - bid
        spread_pct = spread / midpoint if midpoint > 0 else None
        quote_ticks = [
            row for row in ticks
            if bool(row.get("quote_valid", float(row.get("bid", 0.0)) > 0
                          and float(row.get("ask", 0.0)) >= float(row.get("bid", 0.0))))
        ]
        mids = [(row["bid"] + row["ask"]) / 2.0 for row in quote_ticks]
        spreads = [
            (row["ask"] - row["bid"]) / ((row["ask"] + row["bid"]) / 2.0)
            for row in quote_ticks if row["bid"] > 0
        ]
        changes = [right - left for left, right in zip(mids[:-1], mids[1:])]
        upticks = sum(1 for value in changes if value > 0)
        downticks = sum(1 for value in changes if value < 0)
        unchanged = sum(1 for value in changes if value == 0)
        directional_count = upticks + downticks
        direction_balance = (
            (upticks - downticks) / directional_count if directional_count else None
        )
        drift_pct = (
            (mids[-1] - mids[0]) / mids[0] * 100.0
            if len(mids) >= 2 and mids[0] > 0 else None
        )
        # MT5 trade-related tick fields are broker supplied and flagged
        # separately from ordinary Bid/Ask quote updates (LAST=8,VOLUME=16,
        # BUY=32,SELL=64). They are not a consolidated exchange tape.
        last_updates = [
            row for row in ticks
            if int(row.get("flags", 0)) & 8 and float(row.get("last", 0.0)) > 0
        ]
        volume_updates = [
            row for row in ticks
            if int(row.get("flags", 0)) & 16
            and (float(row.get("volume_real", 0.0)) > 0 or float(row.get("volume", 0.0)) > 0)
        ]
        buy_updates = sum(1 for row in ticks if int(row.get("flags", 0)) & 32)
        sell_updates = sum(1 for row in ticks if int(row.get("flags", 0)) & 64)
        reported_volume = sum(
            float(row.get("volume_real", 0.0) or row.get("volume", 0.0) or 0.0)
            for row in volume_updates
        )
        window = max(1.0, min(120.0, tick_window_seconds))
        return {
            "status": tick_status,
            "scope": "MT5 broker quote updates; Last/Volume and Buy/Sell flags are exposed separately when supplied and are not a consolidated exchange tape.",
            "reported_last_price_tick_count": len(last_updates),
            "latest_reported_last_price": last_updates[-1].get("last") if last_updates else None,
            "reported_volume_update_count": len(volume_updates),
            "reported_volume_sum": round(reported_volume, 8) if volume_updates else None,
            "reported_buy_flag_count": buy_updates,
            "reported_sell_flag_count": sell_updates,
            "window_seconds": window,
            "tick_count": len(ticks),
            "quote_tick_count": len(quote_ticks),
            "tick_rate_per_minute": round(len(ticks) * 60.0 / window, 3),
            "quote_tick_rate_per_minute": round(len(quote_ticks) * 60.0 / window, 3),
            "upticks": upticks,
            "downticks": downticks,
            "unchanged_mid_updates": unchanged,
            "quote_direction_balance": round(direction_balance, 4) if direction_balance is not None else None,
            "midpoint_change_pct": round(drift_pct, 6) if drift_pct is not None else None,
            "current_spread": round(spread, 10),
            "current_spread_pct": round(spread_pct * 100.0, 6) if spread_pct is not None else None,
            "mean_observed_spread_pct": round(sum(spreads) / len(spreads) * 100.0, 6) if spreads else None,
            "max_observed_spread_pct": round(max(spreads) * 100.0, 6) if spreads else None,
        }

    def _market_depth(self, raw: Any) -> dict[str, Any]:
        if not isinstance(raw, dict):
            return {
                "status": "NOT_AVAILABLE",
                "source": "MT5_MARKET_BOOK",
                "levels": [],
                "reason": "The MT5 observer did not publish a market-book snapshot.",
            }
        status = str(raw.get("status", "UNAVAILABLE")).upper()
        if status != "AVAILABLE":
            return {
                "status": "NOT_AVAILABLE" if status in {"UNAVAILABLE", "DISABLED"} else status,
                "source": "MT5_MARKET_BOOK",
                "subscribed": bool(raw.get("subscribed", False)),
                "error_code": raw.get("error_code"),
                "levels": [],
                "reason": (
                    "The broker/MT5 symbol does not expose Depth of Market, or the subscription is unavailable."
                    if status != "DISABLED" else "Depth of Market collection is disabled."
                ),
            }
        raw_levels = raw.get("levels")
        if not isinstance(raw_levels, list) or len(raw_levels) > 200:
            return {"status": "INVALID", "source": "MT5_MARKET_BOOK", "levels": []}
        levels: list[dict[str, Any]] = []
        for item in raw_levels:
            if not isinstance(item, dict):
                return {"status": "INVALID", "source": "MT5_MARKET_BOOK", "levels": []}
            side = str(item.get("side", "")).upper()
            price = self._finite(item.get("price"))
            volume = self._finite(item.get("volume"))
            volume_real = self._finite(item.get("volume_real"))
            if (
                side not in {"BUY", "SELL", "BUY_MARKET", "SELL_MARKET"}
                or price is None or volume is None or price <= 0 or volume < 0
                or (volume_real is not None and volume_real < 0)
            ):
                return {"status": "INVALID", "source": "MT5_MARKET_BOOK", "levels": []}
            levels.append({
                "side": side,
                "price": price,
                "volume": volume,
                "volume_real": volume_real,
            })
        bids = [item for item in levels if item["side"] in {"BUY", "BUY_MARKET"}]
        asks = [item for item in levels if item["side"] in {"SELL", "SELL_MARKET"}]
        return {
            "status": "AVAILABLE" if levels else "EMPTY",
            "source": "MT5_MARKET_BOOK",
            "scope": "Broker-provided MT5 Depth of Market; not guaranteed to represent a consolidated multi-venue book.",
            "captured_at_ms": raw.get("captured_at_utc_ms"),
            "level_count": len(levels),
            "bid_level_count": len(bids),
            "ask_level_count": len(asks),
            "bid_volume": round(sum(item["volume_real"] or item["volume"] for item in bids), 8),
            "ask_volume": round(sum(item["volume_real"] or item["volume"] for item in asks), 8),
            "levels": levels,
        }

    def collect(self, bridge: dict[str, Any] | None = None) -> dict[str, Any]:
        if self.root is None:
            return self._blocked(
                "NOT_CONFIGURED",
                "MIRSAD_MT5_COMMON_FILES is not configured; Engine 5 execution quote telemetry requires the user's MT5 Common Files feed.",
            )
        path = self.root / "market.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return self._blocked("OFFLINE", "MT5 market.json has not been published by the read-only Chart Observer.")
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            return self._blocked("INVALID", f"MT5 market.json could not be read: {type(exc).__name__}.")

        if not isinstance(payload, dict) or payload.get("schema") != MARKET_SCHEMA:
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
        if payload.get("time_basis") != "UTC_NORMALIZED_FROM_MT5_SERVER_TIME":
            return self._blocked("INVALID", "MT5 market snapshot time basis is missing or unsupported.", captured_at_ms=captured_at_ms)

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
        if (
            bid is None or ask is None or tick_age is None
            or bid <= 0 or ask < bid or tick_age < 0
            or tick_age > self.quote_max_age_seconds
        ):
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
            if (
                bridge_bid is None or bridge_ask is None or bridge_age is None
                or bridge_bid <= 0 or bridge_ask < bridge_bid or bridge_age < 0
                or bridge_age > self.quote_max_age_seconds
            ):
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

        ticks, tick_status = self._parse_ticks(payload.get("ticks"), captured_at_ms=captured_at_ms)
        tick_window = self._finite(payload.get("tick_window_seconds")) or 30.0
        microstructure = self._microstructure(ticks, bid, ask, tick_window, tick_status)
        # Embedded Observer economic_calendar data is intentionally ignored by this quote adapter.
        order_book = self._market_depth(payload.get("depth_of_market"))
        price = (bid + ask) / 2.0
        venue = {
            "status": "LIVE",
            "price": price,
            "bid": bid,
            "ask": ask,
            "latency_ms": round(age_seconds * 1000, 2),
            "broker_symbol": broker_symbol,
            "account_server": server,
            "tick_age_seconds": tick_age,
            "microstructure": microstructure,
            "order_book": order_book,
            "error": None,
        }
        return {
            "engine": "engine_5_execution_quote_feed",
            "source": "MT5_TERMINAL",
            "status": "LIVE",
            "symbol": self.symbol,
            "price": price,
            "captured_at_ms": captured_at_ms,
            "primary_venue": VENUE_NAME,
            "venue_count": 1,
            "venues": {VENUE_NAME: venue},
            "market_context": {
                "microstructure": microstructure,
                    "order_book": order_book,
            },
            "feed_health": {
                "terminal_connected": True,
                "quote_fresh": True,
                "snapshot_age_seconds": round(age_seconds, 3),
                "tick_age_seconds": tick_age,
                "tick_history_status": tick_status,
                "account_server": server,
                "broker_symbol": broker_symbol,
                "bridge_quote_check": bridge_check,
                "candle_data_owner": "engine_2_chart",
            },
            "reason": None,
        }
