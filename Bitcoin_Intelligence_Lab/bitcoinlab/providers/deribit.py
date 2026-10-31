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

def fetch_btc_options_snapshot() -> dict:
    """Fetch BTC option instrument metadata and public book summaries from Deribit."""
    instruments_query = urlencode({
        "currency": "BTC",
        "kind": "option",
        "expired": "false",
    })
    summaries_query = urlencode({
        "currency": "BTC",
        "kind": "option",
    })
    instruments_payload = get_json(
        f"{BASE}/public/get_instruments?{instruments_query}",
        timeout=15.0,
    )
    summaries_payload = get_json(
        f"{BASE}/public/get_book_summary_by_currency?{summaries_query}",
        timeout=15.0,
    )

    def result_rows(payload: object, label: str) -> list[dict]:
        if not isinstance(payload, dict) or payload.get("error"):
            raise ValueError(f"Deribit {label} response was invalid.")
        rows = payload.get("result")
        if not isinstance(rows, list):
            raise ValueError(f"Deribit {label} response did not contain a result list.")
        if len(rows) > 25_000:
            raise ValueError(f"Deribit {label} response exceeded the accepted row limit.")
        return [row for row in rows if isinstance(row, dict)]

    instruments = result_rows(instruments_payload, "BTC option instruments")
    summaries = result_rows(summaries_payload, "BTC option summaries")
    return {
        "status": "ok" if instruments and summaries else "empty",
        "currency": "BTC",
        "instruments": instruments,
        "summaries": summaries,
        "instrument_count": len(instruments),
        "summary_count": len(summaries),
        "source": "Deribit public/get_instruments + public/get_book_summary_by_currency",
        "note": (
            "For BTC options, Deribit reports open_interest in underlying BTC units; "
            "mark_iv is in percentage points. This feed is context only."
        ),
    }
