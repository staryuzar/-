from __future__ import annotations

from urllib.parse import urlencode

from .http import get_json


BASE = "https://community-api.coinmetrics.io/v4"
DEFAULT_METRICS = ("AdrActCnt", "BlkHgt")
ONCHAIN_METRICS = ("CapMVRVCur", "CapRealUSD", "CapMrktCurUSD")
MVRV_Z_METRICS = ("CapMVRVZ",)
REVIEWED_METRICS = set(DEFAULT_METRICS) | set(ONCHAIN_METRICS) | set(MVRV_Z_METRICS)


def _fetch_metrics(metrics: tuple[str, ...], *, page_size: int) -> dict:
    if not metrics or any(metric not in REVIEWED_METRICS for metric in metrics):
        raise ValueError("Only reviewed Bitcoin Community metric IDs are allowed.")
    query = urlencode({
        "assets": "btc",
        "metrics": ",".join(metrics),
        "frequency": "1d",
        "page_size": page_size,
    })
    payload = get_json(f"{BASE}/timeseries/asset-metrics?{query}")
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise ValueError("Malformed Coin Metrics Community response.")
    rows = payload["data"]
    if any(
        not isinstance(row, dict) or row.get("asset") != "btc"
        for row in rows
    ):
        raise ValueError("Coin Metrics returned an unexpected asset or row.")
    return payload


def fetch_community_metrics(
    metrics: tuple[str, ...] | None = None,
    *,
    page_size: int = 30,
) -> dict:
    """Fetch reviewed daily metrics; optional on-chain groups fail independently."""
    if not 1 <= page_size <= 100:
        raise ValueError("page_size must be between 1 and 100.")

    # Explicit requests preserve the original single-group adapter contract.
    if metrics is not None:
        payload = _fetch_metrics(metrics, page_size=page_size)
        return {
            "source": "Coin Metrics Community API",
            "data": payload["data"],
            "next_page_token": payload.get("next_page_token"),
            "note": (
                "Community data is delayed/limited and licensed for community "
                "non-commercial use; daily metrics are not live order flow."
            ),
        }

    core_payload = _fetch_metrics(DEFAULT_METRICS, page_size=page_size)
    optional: dict[str, list[dict]] = {}
    optional_errors: dict[str, str] = {}
    for label, group in (
        ("market_value_realized_value", ONCHAIN_METRICS),
        ("mvrv_zscore", MVRV_Z_METRICS),
    ):
        try:
            optional[label] = _fetch_metrics(group, page_size=page_size)["data"]
        except Exception as exc:
            # Preserve the base address/block-height metrics when a paid or
            # unlisted community metric is unavailable on this endpoint.
            optional[label] = []
            optional_errors[label] = f"{type(exc).__name__}: {exc}"[:240]

    return {
        "source": "Coin Metrics Community API",
        "data": core_payload["data"],
        "onchain_data": optional.get("market_value_realized_value", []),
        "mvrv_z_data": optional.get("mvrv_zscore", []),
        "onchain_errors": optional_errors,
        "next_page_token": core_payload.get("next_page_token"),
        "note": (
            "Community data is delayed/limited and licensed for community "
            "non-commercial use; daily metrics are not live order flow. "
            "Optional metrics may be absent from the Community tier."
        ),
    }
