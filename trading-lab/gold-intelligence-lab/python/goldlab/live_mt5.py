"""Read-only adapter for genuine MetaTrader 5 terminal data.

Reads the last tick and completed OHLCV bars only. It does not place, check,
modify, or close orders. MetaTrader5 is imported lazily so tests can run without
a local trading terminal or its Python package.
"""
from __future__ import annotations

import importlib
import math
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from .technical_rating import DataQualityError, analyze_ohlcv
from .pattern_scanner import scan_market_structure
from .advisor import build_advisory

TIMEFRAME_SECONDS = {"M1": 60, "M5": 300, "M15": 900, "M30": 1800, "H1": 3600}
TIMEFRAME_ATTRIBUTES = {
    "M1": "TIMEFRAME_M1", "M5": "TIMEFRAME_M5", "M15": "TIMEFRAME_M15",
    "M30": "TIMEFRAME_M30", "H1": "TIMEFRAME_H1",
}
CLOSED_BAR_START_POSITION = 1
MIN_HISTORY_BARS = 260
MAX_HISTORY_BARS = 5000


class LiveMT5Error(RuntimeError):
    """A clear failure while connecting to the configured MT5 terminal."""


def _validate_request(symbol: str, timeframe: str, bars_count: int,
                      max_quote_age_seconds: float) -> tuple[str, str, int]:
    clean_symbol = str(symbol).strip()
    clean_tf = str(timeframe).strip().upper()
    if not clean_symbol:
        raise ValueError("Enter the exact gold symbol shown in MT5, for example XAUUSD.")
    if clean_tf not in TIMEFRAME_SECONDS:
        raise ValueError("Unsupported timeframe. Choose M1, M5, M15, M30 or H1.")
    if isinstance(bars_count, bool) or not isinstance(bars_count, int):
        raise ValueError("bars_count must be an integer.")
    if not MIN_HISTORY_BARS <= bars_count <= MAX_HISTORY_BARS:
        raise ValueError(f"bars_count must be between {MIN_HISTORY_BARS} and {MAX_HISTORY_BARS}.")
    if isinstance(max_quote_age_seconds, bool) or not math.isfinite(float(max_quote_age_seconds)):
        raise ValueError("max_quote_age_seconds must be a finite positive number.")
    if float(max_quote_age_seconds) <= 0:
        raise ValueError("max_quote_age_seconds must be greater than zero.")
    return clean_symbol, clean_tf, TIMEFRAME_SECONDS[clean_tf]


def _load_mt5() -> Any:
    try:
        return importlib.import_module("MetaTrader5")
    except ImportError as exc:
        raise LiveMT5Error(
            "The MetaTrader5 Python package is not installed. On the Windows PC with MT5, "
            "install python/requirements-ui.txt."
        ) from exc


def _utc_iso(epoch_seconds: float) -> str:
    return datetime.fromtimestamp(float(epoch_seconds), tz=timezone.utc).isoformat()


def read_mt5_snapshot(symbol: str, timeframe: str = "M1", bars_count: int = 500, *,
                      terminal_path: str | None = None,
                      max_quote_age_seconds: float = 120.0) -> dict[str, Any]:
    """Read current quote and completed bars from an already configured MT5 terminal.

    No account credentials are accepted or logged. If a path is supplied it only
    selects the terminal executable; sign-in remains inside that terminal.
    """
    symbol, timeframe, interval_seconds = _validate_request(
        symbol, timeframe, bars_count, max_quote_age_seconds
    )
    clean_path = str(terminal_path or "").strip()
    if clean_path and not Path(clean_path).is_file():
        raise LiveMT5Error(f"MT5 terminal executable was not found: {clean_path}")

    mt5 = _load_mt5()
    init_args: dict[str, Any] = {"timeout": 60_000}
    if clean_path:
        init_args["path"] = clean_path
    initialized = False
    try:
        initialized = bool(mt5.initialize(**init_args))
        if not initialized:
            raise LiveMT5Error(
                "MT5 initialization failed. Open the intended terminal and verify its connection. "
                f"MT5 error: {mt5.last_error()!r}"
            )
        terminal = mt5.terminal_info()
        if terminal is None:
            raise LiveMT5Error(f"MT5 returned no terminal information: {mt5.last_error()!r}")
        if not bool(getattr(terminal, "connected", True)):
            raise LiveMT5Error("The selected MT5 terminal reports that it is disconnected.")

        mt5_tf = getattr(mt5, TIMEFRAME_ATTRIBUTES[timeframe], None)
        if mt5_tf is None:
            raise LiveMT5Error(f"The installed package has no {TIMEFRAME_ATTRIBUTES[timeframe]} constant.")

        info = mt5.symbol_info(symbol)
        if info is None:
            candidates: list[str] = []
            try:
                for item in mt5.symbols_get() or ():
                    name = str(getattr(item, "name", ""))
                    if "XAUUSD" in name.upper() or name.upper() == "GOLD" or name.upper().startswith("GOLD."):
                        candidates.append(name)
            except Exception:
                pass
            options = ", ".join(candidates[:12]) if candidates else "no matching gold symbol returned"
            raise LiveMT5Error(
                f"Symbol {symbol!r} was not found. Check the exact broker symbol in MT5 "
                f"(possible candidates: {options}). The adapter does not change symbol selection."
            )
        if not bool(getattr(info, "visible", True)):
            raise LiveMT5Error(
                f"Symbol {symbol!r} is not visible in Market Watch. Add it manually in MT5; "
                "the adapter will not change terminal symbol selection."
            )

        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            raise LiveMT5Error(f"MT5 returned no current tick for {symbol!r}: {mt5.last_error()!r}")
        bid = float(getattr(tick, "bid", 0.0) or 0.0)
        ask = float(getattr(tick, "ask", 0.0) or 0.0)
        if not math.isfinite(bid) or not math.isfinite(ask) or bid <= 0 or ask <= 0 or ask < bid:
            raise DataQualityError("MT5 returned an invalid bid/ask quote; no replacement price was invented.")

        time_msc = int(getattr(tick, "time_msc", 0) or 0)
        tick_epoch = time_msc / 1000.0 if time_msc > 0 else float(getattr(tick, "time", 0) or 0)
        if tick_epoch <= 0 or not math.isfinite(tick_epoch):
            raise DataQualityError("MT5 quote has no valid timestamp.")
        now = time.time()
        quote_age = now - tick_epoch
        if quote_age < -30:
            raise DataQualityError("MT5 quote timestamp is in the future; current-market review is blocked.")
        quote_fresh = 0 <= quote_age <= float(max_quote_age_seconds)

        # Position 0 is the forming candle. Start at 1 to retrieve completed bars only.
        rates = mt5.copy_rates_from_pos(symbol, mt5_tf, CLOSED_BAR_START_POSITION, bars_count)
        if rates is None:
            raise LiveMT5Error(
                f"MT5 could not read closed {timeframe} bars for {symbol!r}: {mt5.last_error()!r}"
            )
        if len(rates) == 0:
            raise LiveMT5Error(
                f"No closed {timeframe} bars were returned for {symbol!r}. "
                "Open the chart and allow MT5 to load its market history."
            )

        bars = pd.DataFrame(rates)
        required = {"time", "open", "high", "low", "close", "tick_volume"}
        missing = required - set(bars.columns)
        if missing:
            raise DataQualityError("MT5 bar data is missing columns: " + ", ".join(sorted(missing)))
        if bars["time"].duplicated().any():
            raise DataQualityError("MT5 returned duplicate bar timestamps.")
        if not bars["time"].is_monotonic_increasing:
            raise DataQualityError("MT5 bars are not ordered oldest-to-newest; refusing to sort silently.")

        last_open = float(bars.iloc[-1]["time"])
        last_close = last_open + interval_seconds
        bar_age = now - last_close
        if bar_age < -30:
            raise DataQualityError("The latest closed-bar timestamp is unexpectedly in the future.")
        max_bar_age = max(float(max_quote_age_seconds), float(interval_seconds * 3))

        point = float(getattr(info, "point", 0.0) or 0.0)
        tick_size = float(getattr(info, "trade_tick_size", 0.0) or 0.0) or point
        if tick_size <= 0:
            raise DataQualityError("MT5 did not provide a valid price tick size.")

        return {
            "read_only": True,
            "symbol": symbol,
            "timeframe": timeframe,
            "terminal_connected": True,
            "bars": bars,
            "bars_requested": bars_count,
            "bars_received": int(len(bars)),
            "closed_bar_start_position": CLOSED_BAR_START_POSITION,
            "market": {
                "bid": bid, "ask": ask, "spread_price": ask - bid,
                "spread_points": (ask - bid) / point if point > 0 else None,
                "quote_time_utc": _utc_iso(tick_epoch),
                "quote_age_seconds": round(quote_age, 2), "quote_fresh": quote_fresh,
                "last_closed_bar_open_utc": _utc_iso(last_open),
                "last_closed_bar_close_utc": _utc_iso(last_close),
                "last_closed_bar_age_seconds": round(bar_age, 2),
                "closed_bar_fresh": 0 <= bar_age <= max_bar_age,
                "maximum_quote_age_seconds": float(max_quote_age_seconds),
                "maximum_closed_bar_age_seconds": max_bar_age,
                "price_digits": int(getattr(info, "digits", 0) or 0),
                "point": point, "trade_tick_size": tick_size,
            },
        }
    finally:
        if initialized:
            mt5.shutdown()


def analyze_live_mt5(symbol: str, timeframe: str = "M1", bars_count: int = 500, *,
                      terminal_path: str | None = None,
                      max_quote_age_seconds: float = 120.0,
                      adx_profile: str = "official_help") -> dict[str, Any]:
    """Produce a read-only analysis report from genuine terminal quotes and closed bars."""
    snapshot = read_mt5_snapshot(
        symbol, timeframe, bars_count,
        terminal_path=terminal_path, max_quote_age_seconds=max_quote_age_seconds,
    )
    bars = snapshot.pop("bars")
    market = snapshot.pop("market")
    scanner = scan_market_structure(bars, timeframe, tick_size=market["trade_tick_size"])
    analysis = analyze_ohlcv(
        bars, timeframe, adx_profile=adx_profile,  # type: ignore[arg-type]
        tick_size=market["trade_tick_size"],
        source_label=f"MT5 terminal feed: {symbol}",
    )
    ready = bool(analysis["readiness"]["complete"])
    eligible = bool(market["quote_fresh"] and market["closed_bar_fresh"] and ready)
    analysis["current_market_review"] = {
        "eligible": eligible,
        "status": "READY_FOR_MANUAL_REVIEW" if eligible else "BLOCKED_DATA_QUALITY",
        "reason_ar": (
            "السعر والشمعة المكتملة حديثان وجميع المؤشرات جاهزة؛ النتيجة للمراجعة اليدوية فقط ولا ترسل أمر تداول."
            if eligible else
            "التحليل غير مؤهل لمراجعة سوق حالية: افحص حداثة السعر والشمعة واكتمال المؤشرات؛ لا يوجد أمر تداول."
        ),
    }
    advisor = build_advisory(analysis, scanner)
    return {"market_source": snapshot, "market": market, "analysis": analysis, "scanner": scanner, "advisor": advisor}


__all__ = ["LiveMT5Error", "analyze_live_mt5", "read_mt5_snapshot"]
