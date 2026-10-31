from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from .providers import cftc, coinmetrics, deribit, mempool
from .quality import utc_now_ms
from .options_surface import build_btc_options_surface
from .onchain import build_onchain_context


def _fetch_btc_options_context(now_ms: int) -> dict[str, Any]:
    raw = deribit.fetch_btc_options_snapshot()
    surface = build_btc_options_surface(
        raw.get("instruments", []),
        raw.get("summaries", []),
        now_ms=now_ms,
    )
    return {
        **surface,
        "source": raw.get("source"),
        "instrument_count": raw.get("instrument_count", 0),
        "summary_count": raw.get("summary_count", 0),
        "source_note": raw.get("note"),
        "use": "slow_context_only_not_intraday_directional_vote",
    }


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
        "options": lambda: _fetch_btc_options_context(now),
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

    onchain_context = build_onchain_context(
        data.get("coinmetrics"), now_ms=now,
    )
    data["onchain"] = onchain_context
    states["onchain"] = {
        "status": onchain_context.get("status", "unavailable"),
        "fetched_at_utc": now_dt.isoformat(),
    }

    return {
        "as_of_utc": now_dt.isoformat(),
        "data": data,
        "source_states": states,
        "errors": errors,
        "limitations": [
            "Network and mining statistics describe chain activity, not exchange order flow.",
            "CFTC TFF positioning is weekly CME futures-only context, not spot positioning.",
            "Coin Metrics Community data is subject to its community non-commercial license and limited data coverage; MVRV, realized cap and MVRV Z-score are optional groups and may be unavailable.",
            "Daily MVRV and the derived NUPL proxy remain slow context only; no SOPR value is inferred when the source does not provide it.",
            "Deribit DVOL is options-implied volatility, not a directional forecast.",
            "Deribit options OI is reported in BTC for BTC options; gross OI does not reveal dealer inventory.",
            "The options surface is descriptive (nearest-strike ATM IV and approximate Black-Scholes 25-delta skew), not a fitted arbitrage-free SVI surface.",
            "These slower feeds are not used as intraday entry triggers.",
        ],
    }
