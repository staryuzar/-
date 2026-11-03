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
from mirsad.engines.mt5_price_action import analyze_mt5_native_price_action


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
    failures: list[str] = []
    if market.get("status") != "LIVE":
        failures.append(f"Market feed is not LIVE: {market.get('status')}.")
    if candles.get("status") != "READY":
        failures.append(f"Native candle feed is not READY: {candles.get('status')}.")
    for name, feed in (("market", market), ("candles", candles)):
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

    analysis = analyze_mt5_native_price_action(candles)
    if analysis.get("status") != "READY":
        failures.append(
            "Engine 2 native analysis is not READY: "
            + str(analysis.get("reason") or analysis.get("status"))
        )

    # Keep only aggregate diagnostics in the public CI artifact; never include
    # account credentials, image files, raw OHLC arrays or raw broker manifests.
    timeframe_rows: dict[str, Any] = {}
    for timeframe, row in (analysis.get("timeframes") or {}).items():
        structure = row.get("structure") or {}
        swing = structure.get("swing") or {}
        candle_analysis = row.get("candle_analysis") or {}
        timeframe_rows[timeframe] = {
            "status": row.get("status"),
            "direction": row.get("direction"),
            "structure_strength": row.get("structure_strength"),
            "closed_bars": row.get("closed_bars"),
            "staleness_ms": row.get("staleness_ms"),
            "swing_high_count": len(swing.get("swing_highs", [])),
            "swing_low_count": len(swing.get("swing_lows", [])),
            "higher_highs": swing.get("higher_highs"),
            "higher_lows": swing.get("higher_lows"),
            "lower_highs": swing.get("lower_highs"),
            "lower_lows": swing.get("lower_lows"),
            "bos_choch_count": len(structure.get("bos_choch_events", [])),
            "liquidity_sweep_count": len(structure.get("liquidity_sweeps", [])),
            "order_block_candidate_count": len(structure.get("order_block_candidates", [])),
            "fair_value_gap_count": len(structure.get("fair_value_gaps", [])),
            "candle_pattern_count": candle_analysis.get("detected_count"),
            "latest_candle_pattern_bias": candle_analysis.get("latest_pattern_bias"),
        }

    return {
        "schema": "MIR-ENGINE2-PRICE-ACTION-LIVE-1",
        "status": "READY" if not failures else "FAILED",
        "source": "MT5_COPYRATES_CLOSED_BARS",
        "symbol": market_symbol,
        "broker_symbol": broker_symbol,
        "market_feed_status": market.get("status"),
        "candle_feed_status": candles.get("status"),
        "analysis_status": analysis.get("status"),
        "direction": analysis.get("direction"),
        "direction_ar": analysis.get("direction_ar"),
        "summary": analysis.get("summary"),
        "timeframes": timeframe_rows,
        "warnings": analysis.get("warnings", []),
        "failures": failures,
        "decision_eligible": False,
        "read_only": True,
        "order_execution_enabled": False,
        "chart_image_required": False,
        "technical_indicators_in_engine2": False,
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
        description="Run Mirsad Engine 2 native candle and price-action analysis without chart images."
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
        "structure_score": report.get("summary", {}).get("structure_score"),
        "timeframe_alignment": report.get("summary", {}).get("timeframe_alignment"),
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
