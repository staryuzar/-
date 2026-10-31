from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Sequence

from .liquidations import (
    normalize_binance_force_order,
    normalize_bybit_liquidation,
    normalize_okx_liquidation,
)
from .market_store import MarketDataStore


LOG = logging.getLogger("bitcoinlab.liquidations.stream")
BINANCE_FORCE_ORDER_WS = "wss://fstream.binance.com/market/ws/btcusdt@forceOrder"
BYBIT_LINEAR_WS = "wss://stream.bybit.com/v5/public/linear"
OKX_PUBLIC_WS = "wss://ws.okx.com/ws/v5/public"


def _persist_events(
    store: MarketDataStore,
    events: Sequence[dict[str, Any]],
    *,
    received_at_ms: int,
) -> int:
    saved = 0
    for event in events:
        if store.record_liquidation(event=event, received_at_ms=received_at_ms):
            saved += 1
    return saved


async def _app_ping(ws: Any, payload: str, interval: float = 20.0) -> None:
    while True:
        await asyncio.sleep(interval)
        await ws.send(payload)


def _is_bybit_pong(payload: object) -> bool:
    """Recognize Bybit's JSON application-ping replies on public streams."""
    if not isinstance(payload, dict):
        return False
    return (
        str(payload.get("op", "")).lower() == "pong"
        or str(payload.get("ret_msg", payload.get("retMsg", ""))).lower() == "pong"
    )


async def _run_binance(store: MarketDataStore, symbol: str) -> None:
    from websockets.asyncio.client import connect

    venue = "binance_usdm_liquidations"
    reconnects, backoff = 0, 1
    while True:
        now = int(time.time() * 1000)
        store.record_status(
            venue=venue, symbol=symbol, status="connecting",
            updated_at_ms=now, reconnects=reconnects,
        )
        try:
            async with connect(
                BINANCE_FORCE_ORDER_WS, ping_interval=20,
                ping_timeout=20, close_timeout=5, max_size=500_000,
            ) as ws:
                LOG.info("Connected liquidation stream: %s", venue)
                backoff = 1
                connected_at = int(time.time() * 1000)
                store.record_status(
                    venue=venue, symbol=symbol, status="connected",
                    updated_at_ms=connected_at, last_message_ms=connected_at,
                    reconnects=reconnects,
                )
                last_status = 0.0
                while True:
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=25)
                    except asyncio.TimeoutError:
                        heartbeat = int(time.time() * 1000)
                        store.record_status(
                            venue=venue, symbol=symbol, status="connected",
                            updated_at_ms=heartbeat, reconnects=reconnects,
                        )
                        continue
                    payload = json.loads(raw)
                    if not isinstance(payload, dict) or payload.get("e") != "forceOrder":
                        continue
                    event = normalize_binance_force_order(payload)
                    received = int(time.time() * 1000)
                    _persist_events(store, [event], received_at_ms=received)
                    if time.monotonic() - last_status >= 5.0:
                        store.record_status(
                            venue=venue, symbol=symbol, status="live",
                            updated_at_ms=received, last_message_ms=received,
                            reconnects=reconnects,
                        )
                        last_status = time.monotonic()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            reconnects += 1
            now = int(time.time() * 1000)
            store.record_status(
                venue=venue, symbol=symbol, status="reconnecting",
                updated_at_ms=now, reconnects=reconnects,
                last_error=f"{type(exc).__name__}: {exc}",
            )
            LOG.warning("%s disconnected: %s", venue, exc)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30)


async def _run_bybit(store: MarketDataStore, symbol: str) -> None:
    from websockets.asyncio.client import connect

    venue = "bybit_linear_liquidations"
    topic = f"allLiquidation.{symbol}"
    reconnects, backoff = 0, 1
    while True:
        now = int(time.time() * 1000)
        store.record_status(
            venue=venue, symbol=symbol, status="connecting",
            updated_at_ms=now, reconnects=reconnects,
        )
        try:
            async with connect(
                BYBIT_LINEAR_WS, ping_interval=20,
                ping_timeout=20, close_timeout=5, max_size=1_000_000,
            ) as ws:
                await ws.send(json.dumps({"op": "subscribe", "args": [topic]}))
                ping_task = asyncio.create_task(_app_ping(ws, json.dumps({"op": "ping"})))
                backoff = 1
                last_status = 0.0
                try:
                    while True:
                        raw = await asyncio.wait_for(ws.recv(), timeout=60)
                        if raw == "pong":
                            heartbeat = int(time.time() * 1000)
                            store.record_status(
                                venue=venue, symbol=symbol, status="connected",
                                updated_at_ms=heartbeat, reconnects=reconnects,
                            )
                            continue
                        payload = json.loads(raw)
                        if _is_bybit_pong(payload):
                            heartbeat = int(time.time() * 1000)
                            store.record_status(
                                venue=venue, symbol=symbol, status="connected",
                                updated_at_ms=heartbeat, reconnects=reconnects,
                            )
                            continue
                        if isinstance(payload, dict) and payload.get("op") == "subscribe":
                            if payload.get("success") is False:
                                raise RuntimeError(str(payload.get("ret_msg", "Bybit liquidation subscription rejected.")))
                            connected_at = int(time.time() * 1000)
                            store.record_status(
                                venue=venue, symbol=symbol, status="connected",
                                updated_at_ms=connected_at, last_message_ms=connected_at,
                                reconnects=reconnects,
                            )
                            continue
                        if not isinstance(payload, dict) or payload.get("topic") != topic:
                            continue
                        events = normalize_bybit_liquidation(payload)
                        received = int(time.time() * 1000)
                        _persist_events(store, events, received_at_ms=received)
                        if events and time.monotonic() - last_status >= 5.0:
                            store.record_status(
                                venue=venue, symbol=symbol, status="live",
                                updated_at_ms=received, last_message_ms=received,
                                reconnects=reconnects,
                            )
                            last_status = time.monotonic()
                finally:
                    ping_task.cancel()
                    await asyncio.gather(ping_task, return_exceptions=True)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            reconnects += 1
            now = int(time.time() * 1000)
            store.record_status(
                venue=venue, symbol=symbol, status="reconnecting",
                updated_at_ms=now, reconnects=reconnects,
                last_error=f"{type(exc).__name__}: {exc}",
            )
            LOG.warning("%s disconnected: %s", venue, exc)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30)


async def _run_okx(store: MarketDataStore, symbol: str) -> None:
    from websockets.asyncio.client import connect

    venue = "okx_swap_liquidations"
    instrument = "BTC-USDT-SWAP"
    reconnects, backoff = 0, 1
    while True:
        now = int(time.time() * 1000)
        store.record_status(
            venue=venue, symbol=symbol, status="connecting",
            updated_at_ms=now, reconnects=reconnects,
        )
        try:
            async with connect(
                OKX_PUBLIC_WS, ping_interval=20,
                ping_timeout=20, close_timeout=5, max_size=1_000_000,
            ) as ws:
                await ws.send(json.dumps({
                    "op": "subscribe",
                    "args": [{"channel": "liquidation-orders", "instType": "SWAP"}],
                }))
                ping_task = asyncio.create_task(_app_ping(ws, "ping"))
                backoff = 1
                last_status = 0.0
                try:
                    while True:
                        raw = await asyncio.wait_for(ws.recv(), timeout=40)
                        if raw == "pong":
                            heartbeat = int(time.time() * 1000)
                            store.record_status(
                                venue=venue, symbol=symbol, status="connected",
                                updated_at_ms=heartbeat, reconnects=reconnects,
                            )
                            continue
                        payload = json.loads(raw)
                        if not isinstance(payload, dict):
                            continue
                        if payload.get("event") == "error":
                            raise RuntimeError(str(payload.get("msg", "OKX liquidation subscription error")))
                        if payload.get("event") == "subscribe":
                            connected_at = int(time.time() * 1000)
                            store.record_status(
                                venue=venue, symbol=symbol, status="connected",
                                updated_at_ms=connected_at, last_message_ms=connected_at,
                                reconnects=reconnects,
                            )
                            continue
                        arg = payload.get("arg")
                        if not isinstance(arg, dict) or arg.get("channel") != "liquidation-orders":
                            continue
                        events = normalize_okx_liquidation(payload)
                        received = int(time.time() * 1000)
                        _persist_events(store, events, received_at_ms=received)
                        if events and time.monotonic() - last_status >= 5.0:
                            store.record_status(
                                venue=venue, symbol=symbol, status="live",
                                updated_at_ms=received, last_message_ms=received,
                                reconnects=reconnects,
                            )
                            last_status = time.monotonic()
                finally:
                    ping_task.cancel()
                    await asyncio.gather(ping_task, return_exceptions=True)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            reconnects += 1
            now = int(time.time() * 1000)
            store.record_status(
                venue=venue, symbol=symbol, status="reconnecting",
                updated_at_ms=now, reconnects=reconnects,
                last_error=f"{type(exc).__name__}: {exc}",
            )
            LOG.warning("%s disconnected: %s", venue, exc)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30)


async def run_liquidation_streams(
    store: MarketDataStore,
    *,
    symbol: str = "BTCUSDT",
    venues: tuple[str, ...] = ("binance", "bybit", "okx"),
) -> None:
    """Collect read-only BTC liquidation events from independent derivatives venues."""
    symbol = symbol.upper().strip()
    if symbol != "BTCUSDT":
        raise ValueError("The first liquidation collector release is restricted to BTCUSDT.")
    supported = {"binance", "bybit", "okx"}
    if not venues or set(venues) - supported:
        raise ValueError(f"Liquidation venues must be selected from {sorted(supported)}.")
    tasks = []
    if "binance" in venues:
        tasks.append(_run_binance(store, symbol))
    if "bybit" in venues:
        tasks.append(_run_bybit(store, symbol))
    if "okx" in venues:
        tasks.append(_run_okx(store, symbol))
    await asyncio.gather(*tasks)
