from __future__ import annotations

from urllib.parse import urlencode

from .http import get_json


BASE = "https://www.deribit.com/api/v2"


def fetch_dvol_history(*, start_timestamp_ms: int, end_timestamp_ms: int, resolution: str = "3600") -> dict:
    if start_timestamp_ms <= 0 or end_timestamp_ms <= start_timestamp_ms:
        raise ValueError("Invalid DVOL time range.")
    if resolution not in {"60", "300", "900", "3600", "1D"}:
        raise ValueError("Unsupported DVOL candle resolution.")
    query = urlencode({
        "currency": "BTC", "start_timestamp": start_timestamp_ms,
        "end_timestamp": end_timestamp_ms, "resolution": resolution,
    })
    payload = get_json(f"{BASE}/public/get_volatility_index_data?{query}")
    if not isinstance(payload, dict) or payload.get("error") or not isinstance(payload.get("result"), dict):
        raise ValueError("Deribit DVOL response was invalid.")
    result = payload["result"]
    return {
        "status": "ok", "currency": "BTC",
        "data": result.get("data", []), "continuation": result.get("continuation"),
        "source": "Deribit DVOL public market data",
        "note": "DVOL is an options-implied volatility index; it is not a directional forecast.",
    }
