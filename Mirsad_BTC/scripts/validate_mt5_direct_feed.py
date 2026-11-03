from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from mirsad.engines.mt5_chart_candles import MT5ChartCandleHistory
from mirsad.engines.mt5_market import MT5MarketDataEngine
from mirsad.engines.mt5_native_indicators import (
    REQUIRED_INDICATORS,
    TIMEFRAMES,
    MT5NativeIndicatorHistory,
)


def validate(
    common_files: Path,
    *,
    market_symbol: str,
    broker_symbol: str,
    expected_server: str,
) -> dict[str, Any]:
    market = MT5MarketDataEngine(
        common_files=str(common_files),
        symbol=market_symbol,
    ).collect()

    candles = MT5ChartCandleHistory(
        common_files=str(common_files),
        symbol=market_symbol,
    ).collect(market=market)

    indicators = MT5NativeIndicatorHistory(
        common_files=str(common_files),
        symbol=market_symbol,
    ).collect(candle_history=candles)

    failures: list[str] = []
    if market.get("status") != "LIVE":
        failures.append(f"market feed: {market.get('status')} — {market.get('reason')}")
    if candles.get("status") != "READY":
        failures.append(f"candle feed: {candles.get('status')} — {candles.get('reason')}")
    if indicators.get("status") != "READY":
        failures.append(f"native indicator feed: {indicators.get('status')} — {indicators.get('reason')}")

    for feed_name, feed in (
        ("market", market),
        ("candles", candles),
        ("native indicators", indicators),
    ):
        server = str(
            feed.get("feed_health", {}).get("account_server", "")
            if feed_name == "market"
            else feed.get("account_server", "")
        ).strip()
        if feed_name != "market" and not server:
            server = str((feed.get("account") or {}).get("server", "")).strip()
        if expected_server and server and server.casefold() != expected_server.casefold():
            failures.append(f"{feed_name}: broker server identity mismatch")

    candle_frames = candles.get("timeframes") or {}
    for timeframe in TIMEFRAMES:
        if int(candle_frames.get(timeframe, 0) or 0) < 2:
            failures.append(f"candles: {timeframe} timeframe is missing or too short")

    native_frames = indicators.get("timeframes") or {}
    ready_indicator_counts: dict[str, int] = {}
    for timeframe in TIMEFRAMES:
        frame = native_frames.get(timeframe) or {}
        values = frame.get("values") or {}
        ready = [
            name for name, item in values.items()
            if isinstance(item, dict) and item.get("status") == "READY"
        ]
        ready_indicator_counts[timeframe] = len(ready)
        missing_core = [
            name for name in REQUIRED_INDICATORS
            if not isinstance(values.get(name), dict)
            or values[name].get("status") != "READY"
        ]
        if missing_core:
            failures.append(
                f"native indicators: {timeframe} missing core values "
                + ", ".join(missing_core)
            )

    context = market.get("market_context") or {}
    pulse = context.get("microstructure") or {}
    book = context.get("order_book") or {}
    result = {
        "schema": "MIR-MT5-DIRECT-FEED-VALIDATION-1",
        "status": "READY" if not failures else "FAILED",
        "image_capture_enabled": False,
        "decision_eligible": False,
        "read_only": True,
        "market": {
            "status": market.get("status"),
            "symbol": market.get("symbol"),
            "broker_symbol": market.get("feed_health", {}).get("broker_symbol"),
            "age_seconds": market.get("feed_health", {}).get("snapshot_age_seconds"),
            "tick_history_status": pulse.get("status"),
            "tick_count": pulse.get("tick_count"),
            "quote_tick_count": pulse.get("quote_tick_count"),
            "last_price_tick_count": pulse.get("reported_last_price_tick_count"),
            "volume_update_count": pulse.get("reported_volume_update_count"),
            "depth_of_market_status": book.get("status", "NOT_AVAILABLE"),
            "depth_of_market_levels": book.get("level_count", 0),
        },
        "candles": {
            "status": candles.get("status"),
            "broker_symbol": candles.get("broker_symbol"),
            "account_server": candles.get("account_server"),
            "timeframes": candles.get("timeframes", {}),
            "closed_candles": candles.get("closed_candles", {}),
        },
        "native_indicators": {
            "status": indicators.get("status"),
            "source": indicators.get("source"),
            "ready_timeframe_count": indicators.get("ready_timeframe_count"),
            "ready_indicator_count_by_timeframe": ready_indicator_counts,
            "timeframes": list(native_frames.keys()),
        },
        "failures": failures,
        "safety": {
            "trading_api_used": False,
            "execution_ea_loaded": False,
            "mir1_commands_created": False,
            "statement": (
                "Direct MT5 data validation only. No chart image is captured and no "
                "trade command is created or authorized."
            ),
        },
    }
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate Mirsad direct MT5 data feeds without chart screenshots."
    )
    parser.add_argument("--common-files", type=Path, required=True)
    parser.add_argument("--market-symbol", required=True)
    parser.add_argument("--broker-symbol", required=True)
    parser.add_argument("--expected-server", default="")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    report = validate(
        args.common_files,
        market_symbol=args.market_symbol.strip().upper(),
        broker_symbol=args.broker_symbol.strip(),
        expected_server=args.expected_server.strip(),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "status": report["status"],
        "image_capture_enabled": False,
        "market": report["market"]["status"],
        "candles": report["candles"]["status"],
        "native_indicators": report["native_indicators"]["status"],
        "ready_timeframes": report["native_indicators"]["ready_timeframe_count"],
        "failures": report["failures"],
    }, ensure_ascii=False))
    return 0 if report["status"] == "READY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
