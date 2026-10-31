from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .decision import central_decision
from .derivatives import derivatives_profile
from .indicators import technical_profile
from .orderflow import order_book_metrics, orderflow_profile, trade_flow_metrics
from .providers import binance, bybit
from .quality import freshness, utc_now_ms, validate_bars
from .multi_timeframe import build_multi_timeframe_profile
from .market_structure import market_structure_profile
from .market_intelligence import build_market_intelligence
from .market_store import read_market_stream_dashboard
from .feed_health import build_data_health
from .trade_analytics import read_trade_analytics
from .trade_profile import (
    blend_orderflow_evidence,
    build_streamed_footprint_profiles,
    build_streamed_trade_flow_profile,
)


def build_live_snapshot(*, symbol: str = "BTCUSDT", interval: str = "1m", now_ms: int | None = None) -> dict[str, Any]:
    """Fetch real public exchange data, validate each feed, and compute one explainable snapshot."""
    if not symbol.isalnum():
        raise ValueError("Invalid symbol.")
    now = utc_now_ms() if now_ms is None else int(now_ms)

    # Read-only source acquisition. Each domain can fail independently and is surfaced in its status.
    errors: dict[str, str] = {}
    bars = []
    depth = {}
    trades = []
    funding = []
    open_interest = {}
    taker = []
    oi_history = []
    try:
        bars = binance.fetch_spot_klines(symbol, interval, 200, now_ms=now)
    except Exception as exc:
        errors["spot"] = f"{type(exc).__name__}: {exc}"[:300]
    try:
        depth = binance.fetch_spot_depth(symbol, 100)
    except Exception as exc:
        errors["orderflow"] = f"{type(exc).__name__}: {exc}"[:300]
    try:
        trades = binance.fetch_spot_agg_trades(symbol, 500)
    except Exception as exc:
        errors["trades"] = f"{type(exc).__name__}: {exc}"[:300]
    try:
        funding = binance.fetch_funding_history(symbol, 3)
        open_interest = binance.fetch_open_interest(symbol)
        taker = binance.fetch_taker_ratio(symbol, "5m", 3)
        try:
            oi_history = binance.fetch_open_interest_history(symbol, "5m", 6)
        except Exception as history_exc:
            errors["open_interest_history"] = f"{type(history_exc).__name__}: {history_exc}"[:240]
    except Exception as exc:
        errors["derivatives"] = f"{type(exc).__name__}: {exc}"[:300]

    interval_max_age = {
        "1m": 180, "3m": 540, "5m": 900, "15m": 2700,
        "30m": 5400, "1h": 10800, "2h": 21600, "4h": 43200,
        "6h": 64800, "8h": 86400, "12h": 129600, "1d": 172800,
    }.get(interval, 180)
    spot_quality = validate_bars(
        bars, min_bars=60, max_age_seconds=interval_max_age, now_ms=now,
    ) if bars else {
        "status": "unavailable", "reason": errors.get("spot", "No spot candles.")
    }
    source_states: dict[str, dict[str, Any]] = {"spot": {"status": spot_quality["status"], **spot_quality}}
    technical = technical_profile(bars) if bars and spot_quality["status"] == "fresh" else {
        "status": "incomplete", "score": None, "reason": spot_quality.get("reason")
    }

    book_metrics = None
    flow_metrics = None
    flow_engine = {"status": "incomplete", "score": None, "reason": "Order-flow source unavailable."}
    if depth and trades:
        try:
            book_metrics = order_book_metrics(depth["bids"], depth["asks"], levels=20)
            flow_metrics = trade_flow_metrics(trades)
            flow_engine = orderflow_profile(book_metrics, flow_metrics)
            # A depth REST snapshot is current at fetch time. Trade timestamps provide a separate sanity check.
            observed = [int(x.get("T") or x.get("time") or 0) for x in trades if x.get("T") or x.get("time")]
            last_trade = max(observed) if observed else None
            flow_fresh = freshness(last_trade, 60, now_ms=now) if last_trade else {
                "status": "unavailable", "age_seconds": None, "observed_at_utc": None
            }
            source_states["orderflow"] = {"status": flow_fresh["status"], **flow_fresh}
            if flow_fresh["status"] != "fresh":
                flow_engine = {"status": "incomplete", "score": None, "reason": "Recent public trade feed is stale or has no event timestamp."}
        except Exception as exc:
            errors["orderflow"] = f"{type(exc).__name__}: {exc}"[:300]
            source_states["orderflow"] = {"status": "error"}

    deriv_data = None
    deriv_engine = {"status": "incomplete", "score": None, "reason": "Derivatives source unavailable."}
    if open_interest and taker:
        try:
            deriv_data = binance.normalize_derivatives(
                funding, open_interest, taker, open_interest_history=oi_history,
            )
            deriv_age = freshness(deriv_data["observed_at_ms"], 600, now_ms=now)
            source_states["derivatives"] = {"status": deriv_age["status"], **deriv_age}
            deriv_engine = derivatives_profile(
                funding_rate=deriv_data["funding_rate"],
                open_interest_change_pct=deriv_data["open_interest_change_pct"],
                taker_buy_sell_ratio=deriv_data["taker_buy_sell_ratio"],
            )
            if deriv_age["status"] != "fresh":
                deriv_engine = {"status": "incomplete", "score": None, "reason": "Futures source is stale."}
        except Exception as exc:
            errors["derivatives_binance"] = f"{type(exc).__name__}: {exc}"[:300]
            source_states["derivatives"] = {"status": "error", "venue": "Binance"}

    # A second, independent venue is used only when Binance derivatives are unavailable/stale.
    if deriv_engine.get("status") != "ok":
        try:
            fallback = bybit.fetch_derivatives_snapshot(symbol, interval_time="5min")
            deriv_age = freshness(fallback["observed_at_ms"], 600, now_ms=now)
            source_states["derivatives"] = {
                "status": deriv_age["status"], **deriv_age, "venue": "Bybit",
            }
            deriv_data = fallback
            deriv_engine = derivatives_profile(
                funding_rate=deriv_data["funding_rate"],
                open_interest_change_pct=deriv_data["open_interest_change_pct"],
                taker_buy_sell_ratio=deriv_data["taker_buy_sell_ratio"],
            )
            if deriv_age["status"] != "fresh":
                deriv_engine = {
                    "status": "incomplete", "score": None,
                    "reason": "Bybit futures source is stale.",
                }
        except Exception as exc:
            errors["derivatives_bybit"] = f"{type(exc).__name__}: {exc}"[:300]
            source_states["derivatives"] = {"status": "error", "venue": "Binance/Bybit"}

    timeframe_inputs = {interval: bars} if interval in {"1d", "4h", "1h", "15m", "5m", "1m"} and bars else {}
    multi_timeframe = build_multi_timeframe_profile(
        symbol=symbol, now_ms=now, preloaded_bars=timeframe_inputs,
    )
    # The spot gate and command de-duplication timestamp always use the latest 1m candle,
    # irrespective of the chart interval currently selected by the user.
    one_minute = multi_timeframe["frames"].get("1m", {})
    if one_minute.get("status") == "fresh":
        source_states["spot"] = {
            "status": "fresh",
            "age_seconds": one_minute.get("age_seconds"),
            "observed_at_utc": one_minute.get("observed_at_utc"),
            "timeframe": "1m",
        }
    else:
        source_states["spot"] = {
            "status": one_minute.get("status", "unavailable"),
            "age_seconds": one_minute.get("age_seconds"),
            "reason": one_minute.get("reason", "Latest 1m completed candle is unavailable."),
            "timeframe": "1m",
        }
    # The central technical vote is the weighted six-frame trend, not a single chart interval.
    decision_technical = {
        "status": "ok" if multi_timeframe["status"] == "ok" else "incomplete",
        "score": multi_timeframe["score"],
        "reason": "; ".join(multi_timeframe["blockers"]) if multi_timeframe["blockers"] else None,
    }

    market_structure = market_structure_profile(bars, trades) if bars and trades else {
        "status": "incomplete",
        "bars": {"status": "incomplete", "reason": "Spot bars unavailable."},
        "volume_profile": {"status": "unavailable", "reason": "Recent trade sample unavailable."},
    }

    # Read the local read-only market collector. Its data is never connected to MT5.
    stream_state = read_market_stream_dashboard(
        "data/market_stream.sqlite", symbol=symbol, limit=20,
    )
    trade_analytics = read_trade_analytics(
        "data/market_stream.sqlite", symbol=symbol, now_ms=now,
    )
    stream_state["trade_feed_status"] = trade_analytics.get("trade_feed_status", [])
    streamed_trade_flow = build_streamed_trade_flow_profile(
        trade_analytics.get("trade_flow_summary", []),
        now_ms=now,
        timeframe="5m",
        max_age_seconds=35,
        minimum_trade_count=5,
        minimum_venues=2,
    )
    streamed_footprint_profiles = build_streamed_footprint_profiles(
        trade_analytics.get("trade_footprint", []),
    )
    if streamed_trade_flow.get("status") == "ok":
        flow_engine = blend_orderflow_evidence(flow_engine, streamed_trade_flow)
        streamed_flow_age = freshness(
            streamed_trade_flow.get("last_trade_time_ms"),
            35,
            now_ms=now,
        )
        if streamed_flow_age.get("status") == "fresh":
            source_states["orderflow"] = {
                **streamed_flow_age,
                "status": "fresh",
                "source": "multi_venue_streamed_cvd",
                "venue_count": streamed_trade_flow.get("venue_count", 0),
                "active_venues": streamed_trade_flow.get("active_venues", []),
            }
    market_intelligence = build_market_intelligence(
        stream_state, market_structure, now_ms=now,
    )
    market_structure_signal = market_intelligence["market_structure_signal"]
    cross_venue_engine = market_intelligence["cross_venue_orderbook"]
    liquidation_risk = market_intelligence["liquidation_risk"]

    if market_structure_signal.get("status") == "ok" and bars:
        structure_age = freshness(
            bars[-1].close_time_ms, interval_max_age, now_ms=now,
        )
        uses_trade_delta = "sampled_trade_delta" in market_structure_signal.get("components", {})
        trade_input_fresh = source_states.get("orderflow", {}).get("status") == "fresh"
        structure_is_fresh = (
            structure_age["status"] == "fresh"
            and (not uses_trade_delta or trade_input_fresh)
        )
        source_states["market_structure"] = {
            "status": "fresh" if structure_is_fresh else "stale",
            **structure_age,
            "timeframe": interval,
            "trade_sample_fresh": trade_input_fresh if uses_trade_delta else None,
        }
        if not structure_is_fresh:
            market_structure_signal = {
                "status": "incomplete", "score": None,
                "reason": (
                    "Market-structure candles or sampled trade delta are stale."
                ),
                "warnings": market_structure_signal.get("warnings", []),
            }
    else:
        source_states["market_structure"] = {
            "status": "unavailable",
            "reason": market_structure_signal.get("reason", "Market-structure profile incomplete."),
        }

    source_states["cross_venue"] = {
        "status": "fresh" if cross_venue_engine.get("status") == "ok" else "unavailable",
        "venue_count": cross_venue_engine.get("venue_count", 0),
        "active_venues": cross_venue_engine.get("active_venues", []),
    }

    spread_bps = float(book_metrics["spread_bps"]) if book_metrics else float("inf")
    data_health = build_data_health(
        source_states=source_states,
        stream_state=stream_state,
        now_ms=now,
    )
    decision = central_decision(
        technical=decision_technical, orderflow=flow_engine, derivatives=deriv_engine,
        market_structure=market_structure_signal, cross_venue=cross_venue_engine,
        liquidation_risk=liquidation_risk,
        source_states=source_states, spread_bps=spread_bps,
    )
    return {
        "status": "ok" if all(source_states.get(key, {}).get("status") == "fresh" for key in ("spot", "orderflow", "derivatives")) else "partial",
        "symbol": symbol, "interval": interval, "as_of_utc": datetime.fromtimestamp(now / 1000, tz=timezone.utc).isoformat(),
        "source_states": source_states, "errors": errors,
        "spot": {
            "bar_count": len(bars),
            "chart_last_bar": bars[-1].__dict__ if bars else None,
            "last_bar": one_minute.get("last_bar"),
            "last_price": one_minute.get("close"),
            "price_history": {
                "time_utc": [
                    datetime.fromtimestamp(bar.close_time_ms / 1000, tz=timezone.utc).isoformat()
                    for bar in bars[-120:]
                ],
                "close": [bar.close for bar in bars[-120:]],
                "volume": [bar.volume for bar in bars[-120:]],
            },
        },
        "technical": technical,
        "multi_timeframe": multi_timeframe,
        "decision_technical": decision_technical,
        "market_structure": market_structure,
        "market_intelligence": market_intelligence,
        "market_stream": stream_state,
        "trade_analytics": trade_analytics,
        "streamed_trade_flow": streamed_trade_flow,
        "streamed_footprint_profiles": streamed_footprint_profiles,
        "data_health": data_health,
        "order_book": book_metrics, "trade_flow": flow_metrics, "orderflow": flow_engine,
        "derivatives_data": deriv_data, "derivatives": deriv_engine,
        "decision": decision,
        "limitations": [
            "Binance is one venue, not the entire Bitcoin market.",
            "Order-book imbalance is a snapshot and can change or be spoofed; it is not executed volume.",
            "The REST trade sample is bounded; streamed CVD is limited to selected public venues and its displayed window.",
            "Spot and linear perpetual trade volumes remain separate and are never summed into a single market-wide size.",
            "Funding, open interest and taker ratios describe one derivatives venue.",
            "CFTC and on-chain metrics are slow context and are deliberately not used as live entry triggers.",
            "This module is read-only and never sends or modifies orders.",
        ],
    }
