from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Iterable, Sequence


Level = Sequence[object]


def _parse_levels(rows: Iterable[Level]) -> dict[float, float]:
    parsed: dict[float, float] = {}
    for row in rows:
        if len(row) < 2:
            raise ValueError("Each level requires price and size.")
        try:
            price, size = float(row[0]), float(row[1])
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("Order-book price and size must be numeric.") from exc
        if not math.isfinite(price + size) or price <= 0 or size < 0:
            raise ValueError("Order-book levels must have a positive price and non-negative size.")
        if size > 0:
            parsed[price] = size
    return parsed


@dataclass
class IncrementalOrderBook:
    """Venue-neutral L2 state for Bybit and OKX with venue-specific sequencing."""
    venue: str
    symbol: str
    bids: dict[float, float] = field(default_factory=dict)
    asks: dict[float, float] = field(default_factory=dict)
    update_id: int | None = None
    sequence_id: int | None = None
    synchronized: bool = False
    last_event_ms: int | None = None
    last_error: str | None = None

    def apply_snapshot(
        self,
        bids: Iterable[Level],
        asks: Iterable[Level],
        *,
        update_id: int | None = None,
        sequence_id: int | None = None,
        event_time_ms: int | None = None,
    ) -> dict:
        new_bids, new_asks = _parse_levels(bids), _parse_levels(asks)
        if not new_bids or not new_asks:
            raise ValueError(f"{self.venue} snapshot must include bid and ask levels.")
        if max(new_bids) >= min(new_asks):
            raise ValueError(f"{self.venue} snapshot is crossed or locked.")
        if update_id is not None and update_id < 0:
            raise ValueError("Update ID cannot be negative.")
        if sequence_id is not None and sequence_id < 0:
            raise ValueError("Sequence ID cannot be negative.")
        if event_time_ms is not None and event_time_ms <= 0:
            raise ValueError("Event timestamp must be positive.")
        self.bids, self.asks = new_bids, new_asks
        self.update_id = update_id
        self.sequence_id = sequence_id
        self.last_event_ms = event_time_ms
        self.synchronized = True
        self.last_error = None
        return {"status": "snapshot", "update_id": update_id, "sequence_id": sequence_id}

    def apply_delta(
        self,
        bids: Iterable[Level],
        asks: Iterable[Level],
        *,
        update_id: int | None = None,
        previous_sequence_id: int | None = None,
        sequence_id: int | None = None,
        event_time_ms: int | None = None,
    ) -> dict:
        if not self.synchronized:
            return {"status": "resync_required", "reason": self.last_error or "snapshot_required"}

        if self.venue.lower() == "okx":
            if self.sequence_id is None or previous_sequence_id is None or sequence_id is None:
                return self._invalidate("okx_sequence_fields_missing")
            if sequence_id <= self.sequence_id:
                return {"status": "stale", "reason": "sequence_already_applied"}
            if previous_sequence_id != self.sequence_id:
                return self._invalidate(
                    f"okx_sequence_gap:{self.sequence_id}->{previous_sequence_id}/{sequence_id}"
                )

        if self.venue.lower() == "bybit":
            if update_id is None:
                return self._invalidate("bybit_update_id_missing")
            if update_id == 1:
                return self._invalidate("bybit_service_restart_snapshot_required")
            if self.update_id is not None and update_id <= self.update_id:
                return {"status": "stale", "reason": "update_already_applied"}

        try:
            bid_rows = list(bids)
            ask_rows = list(asks)
            bid_changes = _parse_levels(bid_rows)
            ask_changes = _parse_levels(ask_rows)
            for price_raw, size_raw in bid_rows:
                if float(size_raw) == 0:
                    bid_changes[float(price_raw)] = 0.0
            for price_raw, size_raw in ask_rows:
                if float(size_raw) == 0:
                    ask_changes[float(price_raw)] = 0.0
            self._apply_side(self.bids, bid_changes)
            self._apply_side(self.asks, ask_changes)
        except (TypeError, ValueError, OverflowError, IndexError) as exc:
            return self._invalidate(f"malformed_delta:{type(exc).__name__}")

        if not self.bids or not self.asks or max(self.bids) >= min(self.asks):
            return self._invalidate("book_invalid_after_delta")
        if update_id is not None:
            self.update_id = update_id
        if sequence_id is not None:
            self.sequence_id = sequence_id
        if event_time_ms is not None:
            if event_time_ms <= 0:
                return self._invalidate("invalid_event_timestamp")
            self.last_event_ms = event_time_ms
        return {
            "status": "applied",
            "update_id": self.update_id,
            "sequence_id": self.sequence_id,
            "best_bid": max(self.bids),
            "best_ask": min(self.asks),
        }

    @staticmethod
    def _apply_side(book: dict[float, float], changes: dict[float, float]) -> None:
        for price, size in changes.items():
            if size == 0:
                book.pop(price, None)
            else:
                book[price] = size

    def _invalidate(self, reason: str) -> dict:
        self.synchronized = False
        self.last_error = reason
        return {"status": "resync_required", "reason": reason}

    def mark_stale(self, reason: str = "feed_disconnected") -> None:
        self._invalidate(reason)

    def top(self, depth: int = 50) -> dict:
        if isinstance(depth, bool) or not isinstance(depth, int) or depth < 1:
            raise ValueError("Depth must be a positive integer.")
        if not self.synchronized:
            return {"status": "unavailable", "reason": self.last_error or "snapshot_required"}
        return {
            "status": "ok",
            "venue": self.venue,
            "symbol": self.symbol,
            "update_id": self.update_id,
            "sequence_id": self.sequence_id,
            "last_event_ms": self.last_event_ms,
            "bids": sorted(self.bids.items(), reverse=True)[:depth],
            "asks": sorted(self.asks.items())[:depth],
        }

    def metrics(self, depth: int = 20) -> dict:
        result = self.top(depth)
        if result["status"] != "ok":
            return result
        bids, asks = result["bids"], result["asks"]
        best_bid, best_ask = bids[0][0], asks[0][0]
        mid = (best_bid + best_ask) / 2.0
        bid_value = sum(price * size for price, size in bids)
        ask_value = sum(price * size for price, size in asks)
        total = bid_value + ask_value
        return {
            "status": "ok",
            "venue": self.venue,
            "symbol": self.symbol,
            "best_bid": best_bid,
            "best_ask": best_ask,
            "mid": mid,
            "spread_bps": (best_ask - best_bid) / mid * 10_000.0,
            "bid_notional": bid_value,
            "ask_notional": ask_value,
            "imbalance": (bid_value - ask_value) / total if total else 0.0,
        }


def apply_bybit_message(book: IncrementalOrderBook, message: dict) -> dict:
    """Apply Bybit V5 orderbook.{depth}.{symbol} snapshot/delta messages."""
    if not isinstance(message, dict):
        return book._invalidate("bybit_message_not_object")
    message_type = message.get("type")
    data = message.get("data")
    if not isinstance(data, dict) or not isinstance(data.get("b"), list) or not isinstance(data.get("a"), list):
        return book._invalidate("bybit_orderbook_payload_malformed")
    try:
        update_id = int(data["u"])
        event_time = int(message.get("ts") or 0)
        if message_type == "snapshot" or update_id == 1:
            return book.apply_snapshot(
                data["b"], data["a"], update_id=update_id,
                sequence_id=int(data["seq"]) if data.get("seq") is not None else None,
                event_time_ms=event_time,
            )
        if message_type != "delta":
            return book._invalidate("bybit_unknown_orderbook_message_type")
        return book.apply_delta(
            data["b"], data["a"], update_id=update_id,
            sequence_id=int(data["seq"]) if data.get("seq") is not None else None,
            event_time_ms=event_time,
        )
    except (KeyError, TypeError, ValueError, OverflowError):
        return book._invalidate("bybit_orderbook_sequence_malformed")


def apply_okx_message(book: IncrementalOrderBook, message: dict) -> dict:
    """Apply OKX public books channel snapshots and seqId/prevSeqId updates."""
    if not isinstance(message, dict):
        return book._invalidate("okx_message_not_object")
    action = message.get("action")
    rows = message.get("data")
    if action not in {"snapshot", "update"} or not isinstance(rows, list) or len(rows) != 1:
        return book._invalidate("okx_orderbook_payload_malformed")
    row = rows[0]
    if not isinstance(row, dict) or not isinstance(row.get("bids"), list) or not isinstance(row.get("asks"), list):
        return book._invalidate("okx_orderbook_levels_malformed")
    try:
        sequence_id = int(row["seqId"])
        event_time = int(row["ts"])
        if action == "snapshot":
            return book.apply_snapshot(
                row["bids"], row["asks"],
                sequence_id=sequence_id, event_time_ms=event_time,
            )
        return book.apply_delta(
            row["bids"], row["asks"],
            previous_sequence_id=int(row["prevSeqId"]),
            sequence_id=sequence_id,
            event_time_ms=event_time,
        )
    except (KeyError, TypeError, ValueError, OverflowError):
        return book._invalidate("okx_orderbook_sequence_malformed")
