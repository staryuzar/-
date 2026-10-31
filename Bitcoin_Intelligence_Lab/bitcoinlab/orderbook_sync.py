from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Iterable, Sequence


Level = Sequence[object]


def _levels(rows: Iterable[Level], side: str) -> dict[float, float]:
    book: dict[float, float] = {}
    for row in rows:
        if len(row) < 2:
            raise ValueError("Order-book levels require price and quantity.")
        try:
            price, quantity = float(row[0]), float(row[1])
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("Order-book price and quantity must be numeric.") from exc
        if (
            not math.isfinite(price) or not math.isfinite(quantity)
            or price <= 0 or quantity < 0
        ):
            raise ValueError("Order-book levels must be finite with positive price and non-negative quantity.")
        if quantity > 0:
            book[price] = quantity
    return book


@dataclass
class BinanceOrderBook:
    """
    In-memory Binance Spot L2 order book reconstructed from a REST snapshot
    plus depth-diff events.

    Sequence policy follows the documented update-id protocol:
    - Ignore events already fully covered by the local update id.
    - Resync if the first update id jumps beyond local id + 1.
    - Apply overlapping events when they still cover the next required id.
    - Never claim the book is synchronized after a detected gap.
    """
    last_update_id: int = 0
    bids: dict[float, float] = field(default_factory=dict)
    asks: dict[float, float] = field(default_factory=dict)
    synchronized: bool = False
    needs_resync: bool = True
    last_event_ms: int | None = None
    last_error: str | None = None

    def apply_snapshot(
        self,
        *,
        last_update_id: int,
        bids: Iterable[Level],
        asks: Iterable[Level],
    ) -> dict:
        if isinstance(last_update_id, bool) or int(last_update_id) <= 0:
            raise ValueError("Snapshot lastUpdateId must be a positive integer.")
        new_bids = _levels(bids, "bid")
        new_asks = _levels(asks, "ask")
        if not new_bids or not new_asks:
            raise ValueError("Snapshot must include both bid and ask levels.")
        if max(new_bids) >= min(new_asks):
            raise ValueError("Snapshot is crossed or locked.")
        self.last_update_id = int(last_update_id)
        self.bids = new_bids
        self.asks = new_asks
        self.synchronized = True
        self.needs_resync = False
        self.last_error = None
        self.last_event_ms = None
        return {"status": "synced", "last_update_id": self.last_update_id}

    def apply_diff(
        self,
        *,
        first_update_id: int,
        final_update_id: int,
        bids: Iterable[Level],
        asks: Iterable[Level],
        event_time_ms: int | None = None,
    ) -> dict:
        if not self.synchronized or self.needs_resync:
            return {
                "status": "resync_required",
                "reason": self.last_error or "snapshot_required",
                "last_update_id": self.last_update_id,
            }
        if (
            isinstance(first_update_id, bool) or isinstance(final_update_id, bool)
            or int(first_update_id) <= 0 or int(final_update_id) < int(first_update_id)
        ):
            self._require_resync("invalid_update_id_range")
            return {"status": "resync_required", "reason": self.last_error}

        first_id, final_id = int(first_update_id), int(final_update_id)
        if final_id <= self.last_update_id:
            return {
                "status": "stale",
                "reason": "event_already_applied",
                "last_update_id": self.last_update_id,
            }
        if first_id > self.last_update_id + 1:
            self._require_resync(
                f"sequence_gap:{self.last_update_id}->{first_id}-{final_id}"
            )
            return {
                "status": "resync_required",
                "reason": self.last_error,
                "last_update_id": self.last_update_id,
            }

        try:
            bid_updates = _levels(bids, "bid")
            ask_updates = _levels(asks, "ask")
            # Zero quantity rows must be retained as deletions rather than
            # filtered by the snapshot normalizer.
            for row in bids:
                price, quantity = float(row[0]), float(row[1])
                if quantity == 0:
                    bid_updates[price] = 0.0
            for row in asks:
                price, quantity = float(row[0]), float(row[1])
                if quantity == 0:
                    ask_updates[price] = 0.0
            for price, quantity in bid_updates.items():
                if quantity == 0:
                    self.bids.pop(price, None)
                else:
                    self.bids[price] = quantity
            for price, quantity in ask_updates.items():
                if quantity == 0:
                    self.asks.pop(price, None)
                else:
                    self.asks[price] = quantity
            if not self.bids or not self.asks or max(self.bids) >= min(self.asks):
                self._require_resync("book_invalid_after_diff")
                return {"status": "resync_required", "reason": self.last_error}
            if event_time_ms is not None:
                event_time = int(event_time_ms)
                if event_time <= 0:
                    self._require_resync("invalid_event_timestamp")
                    return {"status": "resync_required", "reason": self.last_error}
                self.last_event_ms = event_time
            self.last_update_id = final_id
            return {
                "status": "applied",
                "last_update_id": self.last_update_id,
                "best_bid": max(self.bids),
                "best_ask": min(self.asks),
            }
        except (TypeError, ValueError, OverflowError) as exc:
            self._require_resync(f"invalid_depth_delta:{type(exc).__name__}")
            return {"status": "resync_required", "reason": self.last_error}

    def mark_stale(self, reason: str = "feed_disconnected") -> None:
        self._require_resync(reason)

    def _require_resync(self, reason: str) -> None:
        self.synchronized = False
        self.needs_resync = True
        self.last_error = reason

    def top(self, depth: int = 20) -> dict:
        if isinstance(depth, bool) or not isinstance(depth, int) or depth < 1:
            raise ValueError("depth must be a positive integer.")
        if not self.synchronized or self.needs_resync:
            return {"status": "unavailable", "reason": self.last_error or "snapshot_required"}
        return {
            "status": "ok",
            "last_update_id": self.last_update_id,
            "bids": sorted(self.bids.items(), reverse=True)[:depth],
            "asks": sorted(self.asks.items())[:depth],
            "last_event_ms": self.last_event_ms,
        }

    def metrics(self, depth: int = 20) -> dict:
        book = self.top(depth)
        if book["status"] != "ok":
            return book
        bid_levels, ask_levels = book["bids"], book["asks"]
        bid_notional = sum(price * quantity for price, quantity in bid_levels)
        ask_notional = sum(price * quantity for price, quantity in ask_levels)
        total = bid_notional + ask_notional
        best_bid, best_ask = bid_levels[0][0], ask_levels[0][0]
        mid = (best_bid + best_ask) / 2.0
        return {
            "status": "ok",
            "last_update_id": self.last_update_id,
            "best_bid": best_bid,
            "best_ask": best_ask,
            "spread_bps": (best_ask - best_bid) / mid * 10_000.0,
            "bid_notional": bid_notional,
            "ask_notional": ask_notional,
            "imbalance": (bid_notional - ask_notional) / total if total else 0.0,
        }
