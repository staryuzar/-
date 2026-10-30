from __future__ import annotations

from urllib.parse import urlencode

from .http import get_json


BASE = "https://community-api.coinmetrics.io/v4"
DEFAULT_METRICS = ("AdrActCnt", "BlkHgt")


def fetch_community_metrics(metrics: tuple[str, ...] = DEFAULT_METRICS, *, page_size: int = 30) -> dict:
    allowed = set(DEFAULT_METRICS)
    if not metrics or any(metric not in allowed for metric in metrics):
        raise ValueError("Only the reviewed Bitcoin Community metrics are allowed in this adapter.")
    if not 1 <= page_size <= 100:
        raise ValueError("page_size must be between 1 and 100.")
    query = urlencode({"assets": "btc", "metrics": ",".join(metrics), "frequency": "1d", "page_size": page_size})
    payload = get_json(f"{BASE}/timeseries/asset-metrics?{query}")
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise ValueError("Malformed Coin Metrics Community response.")
    rows = payload["data"]
    if any(row.get("asset") != "btc" for row in rows if isinstance(row, dict)):
        raise ValueError("Coin Metrics returned an unexpected asset.")
    return {
        "source": "Coin Metrics Community API", "data": rows,
        "next_page_token": payload.get("next_page_token"),
        "note": "Community data is delayed/limited and licensed for community non-commercial use; do not treat daily metrics as live order flow.",
    }
