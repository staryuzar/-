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
from mirsad.engines.mt5_native_indicators import MT5NativeIndicatorHistory
from mirsad.engines.mt5_trend_analysis import analyze_mt5_native_trend


def build_report(
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
    native = MT5NativeIndicatorHistory(
        common_files=str(common_files),
        symbol=market_symbol,
    ).collect(candle_history=candles)

    failures: list[str] = []
    if market.get("status") != "LIVE":
        failures.append(f"Market feed is not LIVE: {market.get('status')}.")
    if candles.get("status") != "READY":
        failures.append(f"Native candle feed is not READY: {candles.get('status')}.")
    if native.get("status") != "READY":
        failures.append(f"Native indicator feed is not READY: {native.get('status')}.")

    for name, feed in (("market", market), ("candles", candles), ("indicators", native)):
        actual_symbol = (
            str((feed.get("feed_health") or {}).get("broker_symbol", "")).strip()
            if name == "market"
            else str(feed.get("broker_symbol", "")).strip()
        )
        if actual_symbol != broker_symbol:
            failures.append(f"{name} broker symbol identity mismatch.")
        server = (
            str((feed.get("feed_health") or {}).get("account_server", "")).strip()
            if name == "market"
            else str(feed.get("account_server", "")).strip()
        )
        if expected_server and server.casefold() != expected_server.casefold():
            failures.append(f"{name} broker server identity mismatch.")

    analysis = analyze_mt5_native_trend(
        candles,
        native_indicators=native,
    )
    if analysis.get("status") != "READY":
        failures.append(
            "Engine 2 native analysis is not READY: "
            + str(analysis.get("reason") or analysis.get("status"))
        )

    # Keep only aggregate diagnostics in the public CI artifact; never include
    # account credentials, image files, raw OHLC arrays or raw broker manifests.
    timeframe_rows: dict[str, Any] = {}
    for timeframe, row in (analysis.get("timeframes") or {}).items():
        metrics = row.get("indicators") or {}
        timeframe_rows[timeframe] = {
            "status": row.get("status"),
            "direction": row.get("direction"),
            "trend_score": row.get("trend_score"),
            "trend_strength": row.get("trend_strength"),
            "market_regime": row.get("market_regime"),
            "closed_bars": row.get("closed_bars"),
            "staleness_ms": row.get("staleness_ms"),
            "indicators": {
                name: metrics.get(name) for name in (
                    "rsi14", "atr14_pct", "adx14",
                    "plus_di14", "minus_di14",
                    "ema20_slope_atr_5bars", "macd_histogram_atr",
                    "relative_tick_volume",
                )
            },
            "structure_direction": (row.get("structure") or {}).get("direction"),
            "pattern_count": (row.get("patterns") or {}).get("count"),
        }

    parity_rows = {}
    for timeframe, row in (
        (analysis.get("native_indicator_parity") or {}).get("timeframes") or {}
    ).items():
        parity_rows[timeframe] = {
            "status": row.get("status"),
            "indicator_statuses": {
                name: item.get("status")
                for name, item in (row.get("indicators") or {}).items()
            },
        }

    return {
        "schema": "MIR-ENGINE2-NATIVE-TREND-LIVE-1",
        "status": "READY" if not failures else "FAILED",
        "source": "MT5_COPYRATES_CLOSED_BARS",
        "symbol": market_symbol,
        "broker_symbol": broker_symbol,
        "market_feed_status": market.get("status"),
        "candle_feed_status": candles.get("status"),
        "native_indicator_feed_status": native.get("status"),
        "analysis_status": analysis.get("status"),
        "direction": analysis.get("direction"),
        "direction_ar": analysis.get("direction_ar"),
        "summary": analysis.get("summary"),
        "timeframes": timeframe_rows,
        "native_indicator_parity": {
            "status": (analysis.get("native_indicator_parity") or {}).get("status"),
            "timeframes": parity_rows,
        },
        "warnings": analysis.get("warnings", []),
        "failures": failures,
        "decision_eligible": False,
        "read_only": True,
        "order_execution_enabled": False,
        "chart_image_required": False,
        "safety": {
            "raw_ohlc_uploaded": False,
            "chart_image_uploaded": False,
            "account_credentials_uploaded": False,
            "execution_ea_used": False,
            "mir1_commands_created": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run Mirsad Engine 2 native trend analysis on MT5 Common Files without chart images."
    )
    parser.add_argument("--common-files", type=Path, required=True)
    parser.add_argument("--market-symbol", required=True)
    parser.add_argument("--broker-symbol", required=True)
    parser.add_argument("--expected-server", default="")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    report = build_report(
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
        "direction": report["direction"],
        "analysis_status": report["analysis_status"],
        "eligible_timeframes": (
            report.get("summary", {}).get("eligible_timeframes", [])
        ),
        "failures": report["failures"],
        "decision_eligible": False,
    }, ensure_ascii=False))
    return 0 if report["status"] == "READY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
