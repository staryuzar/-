from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .decision import central_decision
from .derivatives import attach_cross_venue_context, derivatives_profile
from .indicators import technical_profile
from .orderflow import order_book_metrics, orderflow_profile, trade_flow_metrics
from .providers import binance, bybit
from .providers.okx import fetch_derivatives_snapshot as fetch_okx_derivatives_snapshot
from .quality import freshness, utc_now_ms, validate_bars
from .multi_timeframe import (
    MINIMUM_FRESH_TIMEFRAMES,
    REQUIRED_MACRO_FRAMES,
    build_multi_timeframe_profile,
)
from .market_structure import market_structure_profile
from .market_intelligence import build_market_intelligence
from .market_store import read_market_stream_dashboard
from .feed_health import build_data_health
from .trade_analytics import read_trade_analytics
from .depth_analytics import read_depth_liquidity_context
from .cross_venue_derivatives import build_cross_venue_derivatives_context
from .providers.cross_venue import fetch_cross_venue_derivatives_rows
from .screener import build_market_screener
from .liquidation_heatmap import read_liquidation_heatmap
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
        errors["order_book"] = f"{type(exc).__name__}: {exc}"[:300]
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
    flow_engine = {"status": "incomplete", "score": None, "reason": "Recent public trade-flow source unavailable."}

    # Depth and executed trades are independent observations. A failed REST book
    # must not suppress a valid trade-delta vote; cross-venue depth has its own domain.
    if depth:
        try:
            book_metrics = order_book_metrics(depth["bids"], depth["asks"], levels=20)
        except Exception as exc:
            errors["order_book"] = f"{type(exc).__name__}: {exc}"[:300]

    if trades:
        try:
            flow_metrics = trade_flow_metrics(trades)
            flow_engine = orderflow_profile(book_metrics, flow_metrics)
            observed = [
                int(x.get("T") or x.get("time") or 0)
                for x in trades if x.get("T") or x.get("time")
            ]
            last_trade = max(observed) if observed else None
            flow_fresh = freshness(last_trade, 60, now_ms=now) if last_trade else {
                "status": "unavailable", "age_seconds": None, "observed_at_utc": None
            }
            source_states["orderflow"] = {"status": flow_fresh["status"], **flow_fresh}
            if flow_fresh["status"] != "fresh":
                flow_engine = {
                    "status": "incomplete", "score": None,
                    "reason": "Recent public trade feed is stale or has no event timestamp.",
                }
        except Exception as exc:
            errors["orderflow"] = f"{type(exc).__name__}: {exc}"[:300]
            source_states["orderflow"] = {"status": "error"}
    else:
        source_states["orderflow"] = {
            "status": "unavailable",
            "reason": errors.get("trades", "No recent aggregate trades returned."),
        }

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

    try:
        cross_derivatives_rows, cross_derivatives_errors = fetch_cross_venue_derivatives_rows(symbol)
        cross_derivatives_context = build_cross_venue_derivatives_context(
            cross_derivatives_rows, now_ms=now, max_age_seconds=120,
        )
        cross_derivatives_context["fetch_errors"] = cross_derivatives_errors
        source_states["cross_venue_derivatives_context"] = {
            "status": "fresh" if cross_derivatives_context.get("status") == "ok" else "partial",
            "venue_count": cross_derivatives_context.get("venue_count", 0),
            "venues": [row.get("venue") for row in cross_derivatives_context.get("venues", [])],
        }
    except Exception as exc:
        cross_derivatives_context = {
            "status": "unavailable",
            "venue_count": 0,
            "venues": [],
            "warnings": ["cross_venue_derivatives_context_unavailable"],
            "fetch_errors": {"collector": f"{type(exc).__name__}: {exc}"[:240]},
            "vote_policy": "context_only_not_a_decision_vote",
        }
        source_states["cross_venue_derivatives_context"] = {
            "status": "unavailable",
        }

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

    # Third source: OKX BTC-USDT-SWAP public trade tape. It provides a
    # separate derivatives venue when Binance USDⓈ-M and Bybit are blocked.
    if deriv_engine.get("status") != "ok":
        try:
            okx_fallback = fetch_okx_derivatives_snapshot(
                symbol,
                cross_venue_context=cross_derivatives_context,
                trade_limit=500,
            )
            deriv_age = freshness(okx_fallback["observed_at_ms"], 180, now_ms=now)
            source_states["derivatives"] = {
                "status": deriv_age["status"], **deriv_age, "venue": "OKX",
                "instrument": okx_fallback.get("symbol"),
                "trade_count": okx_fallback.get("trade_count", 0),
            }
            deriv_data = okx_fallback
            deriv_engine = derivatives_profile(
                funding_rate=deriv_data.get("funding_rate"),
                open_interest_change_pct=deriv_data.get("open_interest_change_pct"),
                taker_buy_sell_ratio=deriv_data.get("taker_buy_sell_ratio"),
            )
            deriv_engine["venue"] = "OKX"
            deriv_engine["funding_rate_kind"] = deriv_data.get("funding_rate_kind")
            deriv_engine["taker_trade_count"] = deriv_data.get("trade_count", 0)
            deriv_engine["warnings"] = list(deriv_data.get("warnings", []))
            deriv_engine["limitations"] = list(deriv_data.get("limitations", []))
            if deriv_age["status"] != "fresh":
                deriv_engine = {
                    **deriv_engine,
                    "status": "incomplete", "score": None,
                    "reason": "OKX perpetual trade sample is stale.",
                }
        except Exception as exc:
            errors["derivatives_okx"] = f"{type(exc).__name__}: {exc}"[:300]
            source_states["derivatives"] = {
                "status": "error", "venue": "Binance/Bybit/OKX",
            }

    # Preserve context-only cross-venue diagnostics after any fallback replacement.
    deriv_engine = attach_cross_venue_context(deriv_engine, cross_derivatives_context)

    timeframe_inputs = {interval: bars} if interval in {"1d", "4h", "1h", "15m", "5m", "1m"} and bars else {}
    multi_timeframe = build_multi_timeframe_profile(
        symbol=symbol, now_ms=now, preloaded_bars=timeframe_inputs,
    )
    # Publish technical freshness as a first-class source state so the central
    # decision engine can reject stale/incomplete MTF evidence independently.
    technical_frames = multi_timeframe.get("frames", {})
    fresh_technical_frames = int(multi_timeframe.get("coverage", {}).get("fresh_frames", 0))
    macro_context_fresh = any(
        technical_frames.get(frame, {}).get("status") == "fresh"
        for frame in ("1d", "4h")
    )
    source_states["technical"] = {
        "status": "fresh" if multi_timeframe.get("status") == "ok" else "incomplete",
        "fresh_frames": fresh_technical_frames,
        "total_frames": len(technical_frames),
        "minimum_fresh_frames": MINIMUM_FRESH_TIMEFRAMES,
        "macro_context_required": list(REQUIRED_MACRO_FRAMES),
        "macro_context_met": macro_context_fresh,
        "blockers": list(multi_timeframe.get("blockers", [])),
    }
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
        "warnings": list(multi_timeframe.get("warnings", [])),
        "macro_conflict": bool(multi_timeframe.get("macro_conflict")),
        "countertrend_setup": bool(multi_timeframe.get("countertrend_setup")),
        "macro_score": multi_timeframe.get("macro_score"),
        "intraday_score": multi_timeframe.get("intraday_score"),
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
    liquidation_heatmap = read_liquidation_heatmap(
        "data/market_stream.sqlite", symbol=symbol, now_ms=now,
        lookback_minutes=60, price_bucket_usd=100.0,
        minimum_cluster_events=1,
    )
    trade_analytics = read_trade_analytics(
        "data/market_stream.sqlite", symbol=symbol, now_ms=now,
    )
    stream_state["trade_feed_status"] = trade_analytics.get("trade_feed_status", [])
    liquidity_context = read_depth_liquidity_context(
        "data/market_stream.sqlite", symbol=symbol, now_ms=now,
        lookback_minutes=30, bucket_step_usd=50.0,
    )
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
    market_intelligence["historical_depth_context"] = liquidity_context
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

    spread_bps = float(book_metrics["spread_bps"]) if book_metrics else None
    screener = build_market_screener(
        multi_timeframe=multi_timeframe,
        market_structure=market_structure,
        market_interval=interval,
        order_book={
            **(book_metrics or {}),
            "observed_at_ms": depth.get("fetched_at_ms") if isinstance(depth, dict) else None,
        },
        streamed_trade_flow=streamed_trade_flow,
        derivatives=deriv_engine,
        cross_venue_derivatives=cross_derivatives_context,
        liquidation_risk=liquidation_risk,
        now_ms=now,
    )
    data_health = build_data_health(
        source_states=source_states,
        stream_state=stream_state,
        now_ms=now,
    )
    decision = central_decision(
        technical=decision_technical, orderflow=flow_engine, derivatives=deriv_engine,
        market_structure=market_structure_signal, cross_venue=cross_venue_engine,
        liquidation_risk=liquidation_risk,
        source_states=source_states, event_context=screener, spread_bps=spread_bps,
    )
    return {
        "status": "ok" if all(source_states.get(key, {}).get("status") == "fresh" for key in ("spot", "technical", "orderflow", "derivatives")) else "partial",
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
        "liquidity_context": liquidity_context,
        "liquidation_heatmap": liquidation_heatmap,
        "data_health": data_health,
        "order_book": book_metrics, "trade_flow": flow_metrics, "orderflow": flow_engine,
        "derivatives_data": deriv_data, "derivatives": deriv_engine,
        "cross_venue_derivatives_context": cross_derivatives_context,
        "screener": screener,
        "decision": decision,
        "limitations": [
            "Binance is one venue, not the entire Bitcoin market.",
            "Order-book imbalance is a snapshot and can change or be spoofed; it is not executed volume.",
            "The REST trade sample is bounded; streamed CVD is limited to selected public venues and its displayed window.",
            "Spot and linear perpetual trade volumes remain separate and are never summed into a single market-wide size.",
            "Historical depth heatmap and Pull/Stack are sampled context proxies, not proof of executable liquidity or confirmed cancellations.",
            "The separate cross-venue derivatives context compares per-venue basis and funding; open-interest units are retained per source and never summed.",
            "CFTC and on-chain metrics are slow context and are deliberately not used as live entry triggers.",
            "This module is read-only and never sends or modifies orders.",
        ],
    }
