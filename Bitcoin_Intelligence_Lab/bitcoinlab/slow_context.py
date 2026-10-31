from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from .providers import cftc, coinmetrics, deribit, mempool
from .quality import utc_now_ms


def build_slow_context(*, now_ms: int | None = None) -> dict[str, Any]:
    """
    Read slower Bitcoin context feeds independently.

    These feeds are displayed beside the live decision, never mixed into
    intraday entry votes because their cadence/licensing/source semantics differ.
    """
    now = utc_now_ms() if now_ms is None else int(now_ms)
    now_dt = datetime.fromtimestamp(now / 1000, tz=timezone.utc)
    start_ms = int((now_dt - timedelta(days=7)).timestamp() * 1000)
    data: dict[str, Any] = {}
    states: dict[str, dict[str, str]] = {}
    errors: dict[str, str] = {}

    readers = {
        "network": mempool.fetch_network_snapshot,
        "cftc": cftc.fetch_bitcoin_cot,
        "coinmetrics": coinmetrics.fetch_community_metrics,
        "dvol": lambda: deribit.fetch_dvol_history(
            start_timestamp_ms=start_ms,
            end_timestamp_ms=now,
            resolution="3600",
        ),
    }
    for name, reader in readers.items():
        try:
            result = reader()
            data[name] = result
            states[name] = {
                "status": "loaded" if result else "empty",
                "fetched_at_utc": now_dt.isoformat(),
            }
        except Exception as exc:
            states[name] = {"status": "error", "fetched_at_utc": now_dt.isoformat()}
            errors[name] = f"{type(exc).__name__}: {exc}"[:300]

    return {
        "as_of_utc": now_dt.isoformat(),
        "data": data,
        "source_states": states,
        "errors": errors,
        "limitations": [
            "Network and mining statistics describe chain activity, not exchange order flow.",
            "CFTC TFF positioning is weekly CME futures-only context, not spot positioning.",
            "Coin Metrics Community data is subject to its community non-commercial license and limited data coverage.",
            "Deribit DVOL is options-implied volatility, not a directional forecast.",
            "These slower feeds are not used as intraday entry triggers.",
        ],
    }
