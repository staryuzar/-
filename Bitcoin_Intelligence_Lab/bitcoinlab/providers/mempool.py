from __future__ import annotations

from ..quality import utc_now_ms
from .http import get_json


BASE = "https://mempool.space/api"


def fetch_network_snapshot() -> dict:
    # Three low-volume public GETs. HTTP 429 is surfaced by the shared client.
    hashrate = get_json(f"{BASE}/v1/mining/hashrate/1m")
    fees = get_json(f"{BASE}/v1/fees/recommended")
    mempool = get_json(f"{BASE}/mempool")
    if not isinstance(hashrate, dict) or not isinstance(fees, dict) or not isinstance(mempool, dict):
        raise ValueError("Malformed mempool.space response.")
    return {
        "fetched_at_ms": utc_now_ms(),
        "hashrate": hashrate, "recommended_fees": fees, "mempool": mempool,
        "source": "mempool.space",
        "note": "Mining/network context is slower-moving context, not an intraday directional signal by itself.",
    }
