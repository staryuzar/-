from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Callable, Mapping

from .market_store import MarketDataStore
from .trade_analytics import ensure_trade_footprint_schema, record_trade_batch
from .trade_flow import (
    normalize_binance_usdm_agg_trade,
    normalize_bybit_public_trades,
    normalize_okx_spot_trades,
)

LOG = logging.getLogger("bitcoinlab.trade_stream")

BINANCE_USDM_TRADE_WS = "wss://fstream.binance.com/market/ws/{symbol}@aggTrade"
BYBIT_LINEAR_TRADE_WS = "wss://stream.bybit.com/v5/public/linear"
OKX_SPOT_TRADE_WS = "wss://ws.okx.com/ws/v5/public"


async def _application_ping(ws: Any, payload: str, interval: float = 20.0) -> None:
    while True:
        await asyncio.sleep(interval)
        await ws.send(payload)


async def _feed_heartbeat(
    store: MarketDataStore,
    *,
    venue: str,
    symbol: str,
    reconnects: int,
) -> None:
    """Keep connection health independent from the arrival rate of trade events."""
    while True:
        await asyncio.sleep(10)
        now = int(time.time() * 1000)
        store.record_status(
            venue=venue, symbol=symbol, status="live",
            updated_at_ms=now, reconnects=reconnects,
        )


def _record_trade_batch(
    store: MarketDataStore,
    *,
    status_venue: str,
    symbol: str,
    events: list[dict[str, Any]],
    received_at_ms: int,
    reconnects: int,
    last_status_write: float,
) -> float:
    if events:
        record_trade_batch(store, events=events, received_at_ms=received_at_ms)
    now_monotonic = time.monotonic()
    if now_monotonic - last_status_write >= 2.0:
        store.record_status(
            venue=status_venue, symbol=symbol, status="live",
            updated_at_ms=received_at_ms,
            last_message_ms=received_at_ms if events else None,
            reconnects=reconnects,
        )
        return now_monotonic
    return last_status_write


async def _run_binance_trades(store: MarketDataStore, symbol: str) -> None:
    from websockets.asyncio.client import connect

    status_venue = "binance_usdm_trades"
    reconnects, backoff = 0, 1
    while True:
        now = int(time.time() * 1000)
        store.record_status(venue=status_venue, symbol=symbol, status="connecting", updated_at_ms=now, reconnects=reconnects)
        try:
            async with connect(
                BINANCE_USDM_TRADE_WS.format(symbol=symbol.lower()),
                ping_interval=20, ping_timeout=20, close_timeout=5, max_size=2_000_000,
            ) as ws:
                backoff = 1
                heartbeat = asyncio.create_task(_feed_heartbeat(
                    store, venue=status_venue, symbol=symbol, reconnects=reconnects,
                ))
                try:
                    last_status_write = 0.0
                    while True:
                        raw = await asyncio.wait_for(ws.recv(), timeout=65)
                        payload = json.loads(raw)
                        event = normalize_binance_usdm_agg_trade(payload)
                        received = int(time.time() * 1000)
                        last_status_write = _record_trade_batch(
                            store, status_venue=status_venue, symbol=symbol,
                            events=[event], received_at_ms=received, reconnects=reconnects,
                            last_status_write=last_status_write,
                        )
                finally:
                    heartbeat.cancel()
                    await asyncio.gather(heartbeat, return_exceptions=True)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            reconnects += 1
            now = int(time.time() * 1000)
            store.record_status(
                venue=status_venue, symbol=symbol, status="reconnecting",
                updated_at_ms=now, reconnects=reconnects,
                last_error=f"{type(exc).__name__}: {exc}",
            )
            LOG.warning("Binance USDⓈ-M BTC trade feed disconnected: %s", exc)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30)


async def _run_bybit_trades(store: MarketDataStore, symbol: str) -> None:
    from websockets.asyncio.client import connect

    status_venue = "bybit_linear_trades"
    reconnects, backoff = 0, 1
    while True:
        now = int(time.time() * 1000)
        store.record_status(venue=status_venue, symbol=symbol, status="connecting", updated_at_ms=now, reconnects=reconnects)
        try:
            async with connect(
                BYBIT_LINEAR_TRADE_WS, ping_interval=20, ping_timeout=20,
                close_timeout=5, max_size=2_000_000,
            ) as ws:
                await ws.send(json.dumps({"op": "subscribe", "args": [f"publicTrade.{symbol}"]}))
                ping_task = asyncio.create_task(_application_ping(ws, json.dumps({"op": "ping"})))
                heartbeat = asyncio.create_task(_feed_heartbeat(
                    store, venue=status_venue, symbol=symbol, reconnects=reconnects,
                ))
                backoff = 1
                try:
                    last_status_write = 0.0
                    while True:
                        raw = await asyncio.wait_for(ws.recv(), timeout=65)
                        if raw == "pong":
                            continue
                        payload = json.loads(raw)
                        if isinstance(payload, Mapping) and (
                            payload.get("op") == "pong" or payload.get("ret_msg") == "pong"
                        ):
                            continue
                        if isinstance(payload, Mapping) and payload.get("op") == "subscribe":
                            if payload.get("success") is False:
                                raise RuntimeError(str(payload.get("ret_msg", "Bybit trade subscription rejected.")))
                            continue
                        if isinstance(payload, Mapping) and payload.get("success") is False:
                            raise RuntimeError(str(payload.get("ret_msg", "Bybit trade feed error.")))
                        events = normalize_bybit_public_trades(payload)
                        if not events:
                            continue
                        received = int(time.time() * 1000)
                        last_status_write = _record_trade_batch(
                            store, status_venue=status_venue, symbol=symbol,
                            events=events, received_at_ms=received, reconnects=reconnects,
                            last_status_write=last_status_write,
                        )
                finally:
                    ping_task.cancel()
                    heartbeat.cancel()
                    await asyncio.gather(ping_task, heartbeat, return_exceptions=True)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            reconnects += 1
            now = int(time.time() * 1000)
            store.record_status(
                venue=status_venue, symbol=symbol, status="reconnecting",
                updated_at_ms=now, reconnects=reconnects,
                last_error=f"{type(exc).__name__}: {exc}",
            )
            LOG.warning("Bybit linear BTC trade feed disconnected: %s", exc)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30)


async def _run_okx_trades(store: MarketDataStore, symbol: str) -> None:
    from websockets.asyncio.client import connect

    status_venue = "okx_spot_trades"
    reconnects, backoff = 0, 1
    while True:
        now = int(time.time() * 1000)
        store.record_status(venue=status_venue, symbol=symbol, status="connecting", updated_at_ms=now, reconnects=reconnects)
        try:
            async with connect(
                OKX_SPOT_TRADE_WS, ping_interval=20, ping_timeout=20,
                close_timeout=5, max_size=2_000_000,
            ) as ws:
                await ws.send(json.dumps({
                    "op": "subscribe",
                    "args": [{"channel": "trades", "instId": "BTC-USDT"}],
                }))
                ping_task = asyncio.create_task(_application_ping(ws, "ping"))
                heartbeat = asyncio.create_task(_feed_heartbeat(
                    store, venue=status_venue, symbol=symbol, reconnects=reconnects,
                ))
                backoff = 1
                try:
                    last_status_write = 0.0
                    while True:
                        raw = await asyncio.wait_for(ws.recv(), timeout=65)
                        if raw == "pong":
                            continue
                        payload = json.loads(raw)
                        if isinstance(payload, Mapping) and payload.get("event") == "error":
                            raise RuntimeError(str(payload.get("msg", "OKX trade subscription rejected.")))
                        if isinstance(payload, Mapping) and payload.get("event") == "subscribe":
                            continue
                        events = normalize_okx_spot_trades(payload)
                        if not events:
                            continue
                        received = int(time.time() * 1000)
                        last_status_write = _record_trade_batch(
                            store, status_venue=status_venue, symbol=symbol,
                            events=events, received_at_ms=received, reconnects=reconnects,
                            last_status_write=last_status_write,
                        )
                finally:
                    ping_task.cancel()
                    heartbeat.cancel()
                    await asyncio.gather(ping_task, heartbeat, return_exceptions=True)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            reconnects += 1
            now = int(time.time() * 1000)
            store.record_status(
                venue=status_venue, symbol=symbol, status="reconnecting",
                updated_at_ms=now, reconnects=reconnects,
                last_error=f"{type(exc).__name__}: {exc}",
            )
            LOG.warning("OKX spot BTC trade feed disconnected: %s", exc)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30)


async def run_trade_streams(
    store: MarketDataStore,
    *,
    symbol: str = "BTCUSDT",
    venues: tuple[str, ...] = ("binance", "bybit", "okx"),
) -> None:
    """Run three read-only public trade streams using venue-specific normalizers."""
    symbol = symbol.upper().strip()
    if symbol != "BTCUSDT":
        raise ValueError("The first trade-stream release is restricted to BTCUSDT.")
    allowed = {"binance", "bybit", "okx"}
    if not venues or set(venues) - allowed:
        raise ValueError(f"venues must be selected from {sorted(allowed)}.")
    ensure_trade_footprint_schema(store)
    tasks: list[Callable[[], Any]] = []
    if "binance" in venues:
        tasks.append(lambda: _run_binance_trades(store, symbol))
    if "bybit" in venues:
        tasks.append(lambda: _run_bybit_trades(store, symbol))
    if "okx" in venues:
        tasks.append(lambda: _run_okx_trades(store, symbol))
    await asyncio.gather(*(task() for task in tasks))
