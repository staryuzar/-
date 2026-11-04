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
from mirsad.engines.mt5_bridge import MT5BridgeEngine
from mirsad.engines.mt5_native_indicators import (
    REQUIRED_INDICATORS,
    REQUIRED_TIMEFRAMES,
    TIMEFRAMES,
    MT5NativeIndicatorHistory,
)
from mirsad.engines.indicators import IndicatorsEngine


def validate(
    common_files: Path,
    *,
    market_symbol: str,
    broker_symbol: str,
    expected_server: str,
) -> dict[str, Any]:
    # Engine 5 supplies both quote telemetry and bridge identity. Engine 2
    # candle ingestion validates its own Observer payload against that bridge;
    # it must never receive Engine 5's quote snapshot or Engine 1 intelligence.
    bridge = MT5BridgeEngine(common_files=str(common_files)).inspect()
    # This workflow intentionally installs only the read-only Observer, not
    # the execution EA. Cross-check with Engine 5 when its bridge is present;
    # otherwise validate the independent Observer symbol/server fields and
    # keep decision_eligible=False. Runtime itself still requires a connected
    # Engine 5 bridge before any decision can become eligible.
    bridge_for_validation = bridge if bridge.get("status") == "CONNECTED" else None
    market = MT5MarketDataEngine(
        common_files=str(common_files),
        symbol=market_symbol,
    ).collect(bridge=bridge_for_validation)

    candles = MT5ChartCandleHistory(
        common_files=str(common_files),
        symbol=market_symbol,
    ).collect(bridge=bridge_for_validation)

    indicators = MT5NativeIndicatorHistory(
        common_files=str(common_files),
        symbol=market_symbol,
    ).collect(candle_history=candles)
    calculated_indicators = IndicatorsEngine().analyze(candles)

    engine2_failures: list[str] = []
    engine3_warnings: list[str] = []
    if market.get("status") != "LIVE":
        engine2_failures.append(f"market feed: {market.get('status')} — {market.get('reason')}")
    if candles.get("status") != "READY":
        engine2_failures.append(f"candle feed: {candles.get('status')} — {candles.get('reason')}")

    market_symbol_actual = str((market.get("feed_health") or {}).get("broker_symbol", "")).strip()
    candle_symbol_actual = str(candles.get("broker_symbol", "")).strip()
    for feed_name, actual_symbol in (("market", market_symbol_actual), ("candles", candle_symbol_actual)):
        if actual_symbol != broker_symbol:
            engine2_failures.append(
                f"{feed_name}: broker symbol mismatch (expected {broker_symbol}, got {actual_symbol or 'missing'})"
            )
    indicator_symbol_actual = str(indicators.get("broker_symbol", "")).strip()
    if indicator_symbol_actual != broker_symbol:
        engine3_warnings.append(
            "native indicators: broker symbol mismatch "
            f"(expected {broker_symbol}, got {indicator_symbol_actual or 'missing'})"
        )

    for feed_name, feed in (("market", market), ("candles", candles)):
        server = str(
            feed.get("feed_health", {}).get("account_server", "")
            if feed_name == "market"
            else feed.get("account_server", "")
        ).strip()
        if feed_name != "market" and not server:
            server = str((feed.get("account") or {}).get("server", "")).strip()
        if expected_server and server and server.casefold() != expected_server.casefold():
            engine2_failures.append(f"{feed_name}: broker server identity mismatch")

    indicator_server = str(indicators.get("account_server", "")).strip()
    if not indicator_server:
        indicator_server = str((indicators.get("account") or {}).get("server", "")).strip()
    if expected_server and indicator_server and indicator_server.casefold() != expected_server.casefold():
        engine3_warnings.append("native indicators: broker server identity mismatch")
    if indicators.get("status") != "READY":
        engine3_warnings.append(
            f"native indicator feed: {indicators.get('status')} — {indicators.get('reason')}"
        )
    if calculated_indicators.get("status") != "READY":
        engine3_warnings.append(
            "calculated Engine 3 signal: "
            f"{calculated_indicators.get('status')} — {calculated_indicators.get('reason')}"
        )

    candle_frames = candles.get("timeframes") or {}
    closed_frames = candles.get("closed_candles") or {}
    for timeframe in TIMEFRAMES:
        closed_count = int(closed_frames.get(timeframe, 0) or 0)
        if closed_count < 24:
            engine2_failures.append(
                f"candles: {timeframe} has {closed_count} closed bars; Engine 2 requires at least 24"
            )

    native_frames = indicators.get("timeframes") or {}
    ready_indicator_counts: dict[str, int] = {}
    optional_indicator_gaps: dict[str, list[str]] = {}
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
        if missing_core and timeframe in REQUIRED_TIMEFRAMES:
            engine3_warnings.append(
                f"native indicators: {timeframe} missing core values "
                + ", ".join(missing_core)
            )
        elif missing_core:
            optional_indicator_gaps[timeframe] = missing_core

    engine2_status = "READY" if not engine2_failures else "FAILED"
    engine3_status = "READY" if not engine3_warnings else "PARTIAL"
    overall_status = (
        "READY" if engine2_status == "READY" and engine3_status == "READY"
        else "PARTIAL" if engine2_status == "READY"
        else "FAILED"
    )

    context = market.get("market_context") or {}
    pulse = context.get("microstructure") or {}
    book = context.get("order_book") or {}
    result = {
        "schema": "MIR-MT5-DIRECT-FEED-VALIDATION-2",
        "status": overall_status,
        "engine2": {
            "status": engine2_status,
            "source": "NATIVE_MT5_OHLC",
            "failures": engine2_failures,
        },
        "engine3": {
            "status": engine3_status,
            "source": "ENGINE2_CLOSED_OHLC_WITH_MT5_COPYBUFFER_PARITY",
            "native_status": indicators.get("status"),
            "calculated_status": calculated_indicators.get("status"),
            "signal_score": calculated_indicators.get("signal_score"),
            "signal_quality": calculated_indicators.get("signal_quality"),
            "signal_timeframe_weight_coverage": calculated_indicators.get("signal_timeframe_weight_coverage"),
            "trend_score": calculated_indicators.get("trend_score"),
            "signal_group_weights": calculated_indicators.get("signal_group_weights", {}),
            "signal_volume_basis": calculated_indicators.get("signal_volume_basis"),
            "signal_components_by_timeframe": calculated_indicators.get("signal_components_by_timeframe", {}),
            "missing_signal_timeframes": calculated_indicators.get("missing_signal_timeframes", []),
            "warnings": engine3_warnings,
        },
        "image_capture_enabled": False,
        "decision_eligible": False,
        "read_only": True,
        "engine5_bridge": {
            "status": bridge.get("status"),
            "symbol": bridge.get("symbol"),
            "market_symbol": bridge.get("market_symbol"),
            "account_server": (bridge.get("account") or {}).get("server"),
            "cross_check": "MATCHED" if bridge_for_validation is not None else "NOT_PART_OF_READ_ONLY_FEED_TEST",
            "required_for_live_decision": True,
        },
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
            "required_timeframes": list(REQUIRED_TIMEFRAMES),
            "optional_timeframe_missing_core_values": optional_indicator_gaps,
            "timeframes": list(native_frames.keys()),
        },
        "failures": engine2_failures + engine3_warnings,
        "warnings": engine3_warnings,
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
        "engine2_status": report["engine2"]["status"],
        "engine3_status": report["engine3"]["status"],
        "image_capture_enabled": False,
        "engine5_bridge": report["engine5_bridge"]["status"],
        "market": report["market"]["status"],
        "candles": report["candles"]["status"],
        "native_indicators": report["native_indicators"]["status"],
        "ready_timeframes": report["native_indicators"]["ready_timeframe_count"],
        "failures": report["engine2"]["failures"],
        "engine3_warnings": report["engine3"]["warnings"],
        "engine3_signal_score": report["engine3"]["signal_score"],
        "engine3_signal_quality": report["engine3"]["signal_quality"],
        "engine3_signal_volume_basis": report["engine3"]["signal_volume_basis"],
        "engine3_calculated_status": report["engine3"]["calculated_status"],
    }, ensure_ascii=False))
    # Integrated validation requires both Engine 2's native OHLC history and
    # Engine 3's calculated signal plus native MT5 buffer readiness.
    return 0 if report["engine2"]["status"] == "READY" and report["engine3"]["status"] == "READY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
