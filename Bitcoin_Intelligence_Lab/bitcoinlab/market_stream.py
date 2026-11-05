from __future__ import annotations

import argparse
import asyncio
from collections import deque
import json
import logging
from pathlib import Path
import time
from typing import Any

from .market_store import MarketDataStore
from .liquidation_stream import run_liquidation_streams
from .trade_stream import run_trade_streams
from .trade_analytics import prune_trade_footprint
from .orderbook_sync import BinanceOrderBook
from .providers.binance import fetch_spot_depth
from .venue_books import IncrementalOrderBook, apply_bybit_message, apply_okx_message


LOG = logging.getLogger("bitcoinlab.market_stream")
BINANCE_WS = "wss://stream.binance.com:9443/ws/{symbol}@depth@100ms"
BYBIT_WS = "wss://stream.bybit.com/v5/public/linear"
OKX_WS = "wss://ws.okx.com/ws/v5/public"


def _parse_binance_depth(payload: object, expected_symbol: str) -> dict[str, Any]:
    if not isinstance(payload, dict) or payload.get("e") != "depthUpdate":
        raise ValueError("Unexpected Binance depth websocket message.")
    if str(payload.get("s", "")).upper() != expected_symbol.upper():
        raise ValueError("Binance depth websocket symbol mismatch.")
    first_id, final_id = int(payload["U"]), int(payload["u"])
    event_time = int(payload["E"])
    bids, asks = payload.get("b"), payload.get("a")
    if first_id <= 0 or final_id < first_id or event_time <= 0:
        raise ValueError("Invalid Binance depth update IDs or timestamp.")
    if not isinstance(bids, list) or not isinstance(asks, list):
        raise ValueError("Malformed Binance depth levels.")
    return {
        "first_update_id": first_id,
        "final_update_id": final_id,
        "event_time_ms": event_time,
        "bids": bids,
        "asks": asks,
        "raw": payload,
    }


def _install_binance_snapshot(
    book: BinanceOrderBook,
    snapshot: dict[str, Any],
    buffered: list[dict[str, Any]],
) -> bool:
    """Install REST state, then bridge the buffered diff stream in arrival order."""
    book.apply_snapshot(
        last_update_id=int(snapshot["snapshot_id"]),
        bids=snapshot["bids"],
        asks=snapshot["asks"],
    )
    for event in buffered:
        if event["final_update_id"] <= book.last_update_id:
            continue
        result = book.apply_diff(
            first_update_id=event["first_update_id"],
            final_update_id=event["final_update_id"],
            bids=event["bids"],
            asks=event["asks"],
            event_time_ms=event["event_time_ms"],
        )
        if result["status"] == "resync_required":
            return False
    return book.synchronized


def _maybe_save_book(
    store: MarketDataStore,
    *,
    venue: str,
    symbol: str,
    book: Any,
    depth: int,
    received_at_ms: int,
    last_saved_monotonic: float,
) -> float:
    current = time.monotonic()
    if current - last_saved_monotonic < 5.0:
        return last_saved_monotonic
    snapshot = book.top(depth)
    metrics = book.metrics(depth)
    if snapshot.get("status") == "ok" and metrics.get("status") == "ok":
        # Use the exchange event time for freshness gating; local receive time
        # can make a delayed/backlogged snapshot look newer than it really is.
        exchange_event_ms = snapshot.get("last_event_ms")
        observed_at_ms = (
            int(exchange_event_ms)
            if exchange_event_ms is not None and int(exchange_event_ms) > 0
            else received_at_ms
        )
        store.record_snapshot(
            venue=venue,
            symbol=symbol,
            observed_at_ms=observed_at_ms,
            book=snapshot,
            metrics=metrics,
        )
        return current
    return last_saved_monotonic


def _maybe_prune(store: MarketDataStore, *, now_ms: int | None = None) -> dict[str, int]:
    observed = int(time.time() * 1000) if now_ms is None else int(now_ms)
    removed = store.prune(now_ms=observed)
    removed["trade_footprint"] = prune_trade_footprint(store, now_ms=observed)
    return removed


async def _periodic_prune(store: MarketDataStore, interval_seconds: int = 300) -> None:
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            _maybe_prune(store)
        except Exception:
            LOG.exception("SQLite retention cleanup failed.")


def _should_log_event(last_logged: float, event_type: str) -> tuple[bool, float]:
    now = time.monotonic()
    if event_type == "snapshot" or now - last_logged >= 10.0:
        return True, now
    return False, last_logged


async def _ping_application(ws: Any, payload: str, interval: float = 20.0) -> None:
    while True:
        await asyncio.sleep(interval)
        await ws.send(payload)


async def _run_binance(store: MarketDataStore, symbol: str, depth: int) -> None:
    from websockets.asyncio.client import connect

    venue, reconnects, backoff = "binance_spot", 0, 1
    symbol_l = symbol.lower()
    uri = BINANCE_WS.format(symbol=symbol_l)
    while True:
        now = int(time.time() * 1000)
        store.record_status(
            venue=venue, symbol=symbol, status="connecting",
            updated_at_ms=now, reconnects=reconnects,
        )
        try:
            async with connect(
                uri, ping_interval=20, ping_timeout=20,
                close_timeout=5, max_size=2_000_000,
            ) as ws:
                LOG.info("Connected: %s %s", venue, symbol)
                backoff = 1
                book = BinanceOrderBook()
                buffered: deque[dict[str, Any]] = deque(maxlen=20_000)
                snapshot_task: asyncio.Task[Any] | None = asyncio.create_task(
                    asyncio.to_thread(fetch_spot_depth, symbol, 5000)
                )
                reader_task = asyncio.create_task(ws.recv())
                last_saved = 0.0
                last_event_log = 0.0
                synced = False
                last_status_write = 0.0
                try:
                    while True:
                        wait_set = {reader_task}
                        if snapshot_task is not None:
                            wait_set.add(snapshot_task)
                        done, _pending = await asyncio.wait(
                            wait_set, timeout=40, return_when=asyncio.FIRST_COMPLETED,
                        )
                        if not done:
                            raise TimeoutError("Binance depth stream was silent for 40 seconds.")
    
                        if snapshot_task is not None and snapshot_task in done:
                            snapshot = snapshot_task.result()
                            buffered_copy = list(buffered)
                            buffered.clear()
                            synced = _install_binance_snapshot(book, snapshot, buffered_copy)
                            snapshot_task = None
                            if not synced:
                                book.mark_stale("snapshot_buffer_bridge_failed")
                                snapshot_task = asyncio.create_task(
                                    asyncio.to_thread(fetch_spot_depth, symbol, 5000)
                                )
                            else:
                                now_ms = int(time.time() * 1000)
                                store.record_status(
                                    venue=venue, symbol=symbol, status="live",
                                    updated_at_ms=now_ms, last_message_ms=now_ms,
                                    reconnects=reconnects,
                                )
                                last_saved = _maybe_save_book(
                                    store, venue=venue, symbol=symbol, book=book,
                                    depth=depth, received_at_ms=now_ms,
                                    last_saved_monotonic=last_saved,
                                )
    
                        if reader_task in done:
                            raw = reader_task.result()
                            reader_task = asyncio.create_task(ws.recv())
                            payload = json.loads(raw)
                            event = _parse_binance_depth(payload, symbol)
                            received_at = int(time.time() * 1000)
                            should_log, last_event_log = _should_log_event(last_event_log, "delta")
                            if should_log:
                                store.record_event(
                                    venue=venue, symbol=symbol,
                                    event_time_ms=event["event_time_ms"],
                                    received_at_ms=received_at,
                                    event_type="depth_delta_sample",
                                    sequence_id=event["final_update_id"],
                                    payload={
                                        "first_update_id": event["first_update_id"],
                                        "final_update_id": event["final_update_id"],
                                        "bid_level_updates": len(event["bids"]),
                                        "ask_level_updates": len(event["asks"]),
                                    },
                                )
                            if not synced:
                                if len(buffered) == buffered.maxlen:
                                    raise RuntimeError("Binance bootstrap event buffer overflow.")
                                buffered.append(event)
                            else:
                                result = book.apply_diff(
                                    first_update_id=event["first_update_id"],
                                    final_update_id=event["final_update_id"],
                                    bids=event["bids"], asks=event["asks"],
                                    event_time_ms=event["event_time_ms"],
                                )
                                if result["status"] == "resync_required":
                                    synced = False
                                    book.mark_stale(result.get("reason", "sequence_gap"))
                                    buffered.clear()
                                    buffered.append(event)
                                    snapshot_task = asyncio.create_task(
                                        asyncio.to_thread(fetch_spot_depth, symbol, 5000)
                                    )
                                elif result["status"] == "applied":
                                    last_saved = _maybe_save_book(
                                        store, venue=venue, symbol=symbol, book=book,
                                        depth=depth, received_at_ms=received_at,
                                        last_saved_monotonic=last_saved,
                                    )
                            if time.monotonic() - last_status_write >= 5:
                                store.record_status(
                                    venue=venue, symbol=symbol,
                                    status="live" if synced else "synchronizing",
                                    updated_at_ms=received_at,
                                    last_message_ms=received_at,
                                    reconnects=reconnects,
                                    last_error=book.last_error,
                                )
                                last_status_write = time.monotonic()
                finally:
                    cleanup = [task for task in (reader_task, snapshot_task) if task is not None]
                    for task in cleanup:
                        if not task.done():
                            task.cancel()
                    await asyncio.gather(*cleanup, return_exceptions=True)
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
            LOG.warning("%s %s disconnected: %s", venue, symbol, exc)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30)


async def _run_bybit(store: MarketDataStore, symbol: str, depth: int) -> None:
    from websockets.asyncio.client import connect

    venue, reconnects, backoff = "bybit_linear", 0, 1
    topic = f"orderbook.{depth}.{symbol}"
    while True:
        now = int(time.time() * 1000)
        store.record_status(venue=venue, symbol=symbol, status="connecting", updated_at_ms=now, reconnects=reconnects)
        try:
            async with connect(
                BYBIT_WS, ping_interval=20, ping_timeout=20,
                close_timeout=5, max_size=2_000_000,
            ) as ws:
                await ws.send(json.dumps({"op": "subscribe", "args": [topic]}))
                ping_task = asyncio.create_task(_ping_application(ws, json.dumps({"op": "ping"})))
                book = IncrementalOrderBook("Bybit", symbol)
                last_saved, last_status, last_event_log = 0.0, 0.0, 0.0
                backoff = 1
                try:
                    while True:
                        raw = await asyncio.wait_for(ws.recv(), timeout=40)
                        if raw == "pong":
                            continue
                        payload = json.loads(raw)
                        if isinstance(payload, dict) and payload.get("op") == "subscribe" and payload.get("success") is False:
                            raise RuntimeError(str(payload.get("ret_msg", "Bybit subscription was rejected.")))
                        if not isinstance(payload, dict) or "type" not in payload or "data" not in payload:
                            continue
                        event_time = int(payload.get("ts") or time.time() * 1000)
                        data = payload.get("data") or {}
                        update_id = int(data.get("u", 0)) if isinstance(data, dict) else 0
                        received_at = int(time.time() * 1000)
                        event_type = str(payload.get("type", "unknown"))
                        should_log, last_event_log = _should_log_event(last_event_log, event_type)
                        if should_log:
                            store.record_event(
                                venue=venue, symbol=symbol, event_time_ms=event_time,
                                received_at_ms=received_at,
                                event_type=f"orderbook_{event_type}_sample",
                                sequence_id=update_id or None,
                                payload={
                                    "update_id": update_id,
                                    "bid_level_updates": len(data.get("b", [])),
                                    "ask_level_updates": len(data.get("a", [])),
                                },
                            )
                        result = apply_bybit_message(book, payload)
                        if result["status"] == "resync_required":
                            raise RuntimeError(result.get("reason", "Bybit book requires a fresh snapshot."))
                        if result["status"] in {"snapshot", "applied"}:
                            last_saved = _maybe_save_book(
                                store, venue=venue, symbol=symbol, book=book,
                                depth=depth, received_at_ms=received_at,
                                last_saved_monotonic=last_saved,
                            )
                            if time.monotonic() - last_status >= 5:
                                store.record_status(
                                    venue=venue, symbol=symbol, status="live",
                                    updated_at_ms=received_at, last_message_ms=received_at,
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
            book_state = "reconnecting"
            store.record_status(
                venue=venue, symbol=symbol, status=book_state,
                updated_at_ms=now, reconnects=reconnects,
                last_error=f"{type(exc).__name__}: {exc}",
            )
            LOG.warning("%s %s disconnected: %s", venue, symbol, exc)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30)


async def _run_okx(store: MarketDataStore, symbol: str, depth: int) -> None:
    from websockets.asyncio.client import connect

    venue, reconnects, backoff = "okx_spot", 0, 1
    instrument = "BTC-USDT"
    while True:
        now = int(time.time() * 1000)
        store.record_status(venue=venue, symbol=instrument, status="connecting", updated_at_ms=now, reconnects=reconnects)
        try:
            async with connect(
                OKX_WS, ping_interval=20, ping_timeout=20,
                close_timeout=5, max_size=2_000_000,
            ) as ws:
                await ws.send(json.dumps({
                    "op": "subscribe",
                    "args": [{"channel": "books", "instId": instrument}],
                }))
                ping_task = asyncio.create_task(_ping_application(ws, "ping"))
                book = IncrementalOrderBook("OKX", instrument)
                last_saved, last_status, last_event_log = 0.0, 0.0, 0.0
                backoff = 1
                try:
                    while True:
                        raw = await asyncio.wait_for(ws.recv(), timeout=40)
                        if raw == "pong":
                            continue
                        payload = json.loads(raw)
                        if not isinstance(payload, dict) or "action" not in payload:
                            if isinstance(payload, dict) and payload.get("event") == "error":
                                raise RuntimeError(str(payload.get("msg", "OKX subscription error")))
                            continue
                        data = payload.get("data") or []
                        row = data[0] if isinstance(data, list) and data else {}
                        event_time = int(row.get("ts", 0)) if isinstance(row, dict) else 0
                        sequence_id = int(row.get("seqId", 0)) if isinstance(row, dict) else 0
                        received_at = int(time.time() * 1000)
                        event_type = str(payload.get("action", "unknown"))
                        should_log, last_event_log = _should_log_event(last_event_log, event_type)
                        if should_log:
                            store.record_event(
                                venue=venue, symbol=instrument, event_time_ms=event_time or None,
                                received_at_ms=received_at,
                                event_type=f"orderbook_{event_type}_sample",
                                sequence_id=sequence_id or None,
                                payload={
                                    "sequence_id": sequence_id,
                                    "bid_level_updates": len(row.get("bids", [])) if isinstance(row, dict) else 0,
                                    "ask_level_updates": len(row.get("asks", [])) if isinstance(row, dict) else 0,
                                },
                            )
                        result = apply_okx_message(book, payload)
                        if result["status"] == "resync_required":
                            raise RuntimeError(result.get("reason", "OKX book sequence mismatch."))
                        if result["status"] in {"snapshot", "applied"}:
                            last_saved = _maybe_save_book(
                                store, venue=venue, symbol=instrument, book=book,
                                depth=depth, received_at_ms=received_at,
                                last_saved_monotonic=last_saved,
                            )
                            if time.monotonic() - last_status >= 5:
                                store.record_status(
                                    venue=venue, symbol=instrument, status="live",
                                    updated_at_ms=received_at, last_message_ms=received_at,
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
                venue=venue, symbol=instrument, status="reconnecting",
                updated_at_ms=now, reconnects=reconnects,
                last_error=f"{type(exc).__name__}: {exc}",
            )
            LOG.warning("%s %s disconnected: %s", venue, instrument, exc)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30)


async def run_market_stream(
    *,
    symbol: str = "BTCUSDT",
    db_path: str | Path = "data/market_stream.sqlite",
    venues: tuple[str, ...] = ("binance", "bybit", "okx"),
    depth: int = 50,
    retention_hours: int = 24,
    liquidations_enabled: bool = True,
    trades_enabled: bool = True,
) -> None:
    symbol = symbol.upper().strip()
    if not symbol.isalnum() or not symbol.startswith("BTC"):
        raise ValueError("The market stream currently accepts BTC symbols only.")
    if symbol != "BTCUSDT":
        raise ValueError("The first multi-venue collector release is restricted to BTCUSDT.")
    if depth not in {50, 200}:
        raise ValueError("Bybit L2 supports depth 50 or 200 in this collector.")
    supported = {"binance", "bybit", "okx"}
    if not venues or set(venues) - supported:
        raise ValueError(f"venues must be selected from {sorted(supported)}.")
    with MarketDataStore(db_path, retention_hours=retention_hours) as store:
        _maybe_prune(store, now_ms=int(time.time() * 1000))
        tasks = []
        if "binance" in venues:
            tasks.append(_run_binance(store, symbol, depth))
        if "bybit" in venues:
            tasks.append(_run_bybit(store, symbol, depth))
        if "okx" in venues:
            tasks.append(_run_okx(store, symbol, depth))
        if liquidations_enabled:
            tasks.append(run_liquidation_streams(store, symbol=symbol, venues=venues))
        if trades_enabled:
            tasks.append(run_trade_streams(store, symbol=symbol, venues=venues))
        cleanup_task = asyncio.create_task(_periodic_prune(store))
        try:
            await asyncio.gather(*tasks)
        finally:
            cleanup_task.cancel()
            await asyncio.gather(cleanup_task, return_exceptions=True)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Read-only BTC multi-exchange order-book, trade and liquidation collector."
    )
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--db", default="data/market_stream.sqlite")
    parser.add_argument("--venues", default="binance,bybit,okx")
    parser.add_argument("--depth", type=int, default=50)
    parser.add_argument("--retention-hours", type=int, default=24)
    parser.add_argument(
        "--liquidations", action=argparse.BooleanOptionalAction, default=True,
        help="Enable public liquidation feeds from Binance, Bybit and OKX.",
    )
    parser.add_argument(
        "--trades", action=argparse.BooleanOptionalAction, default=True,
        help="Enable public BTC trade feeds for continuous CVD and footprint.",
    )
    parser.add_argument("--log-level", default="INFO", choices=("DEBUG", "INFO", "WARNING", "ERROR"))
    args = parser.parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    venues = tuple(item.strip().lower() for item in args.venues.split(",") if item.strip())
    try:
        asyncio.run(run_market_stream(
            symbol=args.symbol, db_path=args.db, venues=venues,
            depth=args.depth, retention_hours=args.retention_hours,
            liquidations_enabled=args.liquidations,
            trades_enabled=args.trades,
        ))
    except KeyboardInterrupt:
        LOG.info("Market data collector stopped by user.")


if __name__ == "__main__":
    main()
