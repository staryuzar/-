from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mirsad.config import DB_PATH, SYMBOL
from mirsad.engines.chart_structure_evaluation import (
    analyze_and_evaluate_stored_market_structures,
    persist_structure_evaluations,
)
from mirsad.storage import write_json_atomic

TIMEFRAMES = ("1m", "5m", "15m", "1h", "4h", "1d", "1w")


def _parse_horizons(value: str) -> tuple[int, ...]:
    parts = [part.strip() for part in str(value).split(",")]
    if not parts or any(not part for part in parts):
        raise ValueError("horizons must be comma-separated positive candle counts")
    try:
        values = [int(part) for part in parts]
    except ValueError as exc:
        raise ValueError("horizons must contain integers only") from exc
    if any(item <= 0 for item in values):
        raise ValueError("horizons must contain positive candle counts")
    if len(set(values)) != len(values):
        raise ValueError("horizons must not contain duplicates")
    return tuple(sorted(values))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run an auditable Engine 2 historical structure event study on "
            "one venue's stored closed BTC candles."
        )
    )
    parser.add_argument("--symbol", default=SYMBOL)
    parser.add_argument("--venue", required=True, help="Exact stored venue name, e.g. Binance Spot")
    parser.add_argument("--timeframe", required=True, choices=TIMEFRAMES)
    parser.add_argument("--as-of-ms", type=int, required=True,
                        help="Fixed Unix timestamp in milliseconds; reuse it for every split of a dataset")
    parser.add_argument("--data-split", required=True,
                        choices=("train", "validation", "test"))
    parser.add_argument("--dataset-id", required=True,
                        help="Stable identity shared by train/validation/test for the same OHLC dataset")
    parser.add_argument("--split-start-ms", type=int, required=True)
    parser.add_argument("--split-end-ms", type=int, required=True)
    parser.add_argument("--embargo-bars", type=int, default=0)
    parser.add_argument("--limit", type=int, default=2000,
                        help="Maximum stored bars; keep it identical across all splits")
    parser.add_argument("--horizons", default="1,3,5,10,20",
                        help="Comma-separated forward horizons in candles")
    parser.add_argument("--primary-horizon", type=int, default=5,
                        help="Horizon used for the compact database row; must be included in --horizons")
    parser.add_argument("--market-regime", default="UNSPECIFIED")
    parser.add_argument("--fee-bps-per-side", type=float, default=None)
    parser.add_argument("--slippage-bps-per-side", type=float, default=None)
    parser.add_argument("--db-path", type=Path, default=DB_PATH)
    parser.add_argument("--output-json", type=Path, default=None,
                        help="Optional path for the full reproducibility summary")
    return parser


def validate_arguments(args: argparse.Namespace) -> tuple[int, ...]:
    horizons = _parse_horizons(args.horizons)
    if args.primary_horizon <= 0 or args.primary_horizon not in horizons:
        raise ValueError("primary-horizon must be positive and included in --horizons")
    if args.split_start_ms <= 0 or args.split_end_ms <= args.split_start_ms:
        raise ValueError("split bounds must define a positive increasing time window")
    if args.as_of_ms < args.split_end_ms:
        raise ValueError("as-of-ms must be at or after split-end-ms to cover the full split")
    if args.embargo_bars < 0:
        raise ValueError("embargo-bars must be non-negative")
    if not 8 <= args.limit <= 2000:
        raise ValueError("limit must be between 8 and 2000")
    if (args.fee_bps_per_side is None) != (args.slippage_bps_per_side is None):
        raise ValueError("fee and slippage assumptions must both be supplied or both omitted")
    return horizons


def run_study(args: argparse.Namespace) -> dict[str, Any]:
    horizons = validate_arguments(args)
    db_path = str(args.db_path)
    run = analyze_and_evaluate_stored_market_structures(
        symbol=args.symbol,
        venue=args.venue,
        timeframe=args.timeframe,
        as_of_ms=args.as_of_ms,
        data_split=args.data_split,
        dataset_id=args.dataset_id,
        split_start_ms=args.split_start_ms,
        split_end_ms=args.split_end_ms,
        embargo_bars=args.embargo_bars,
        market_regime=args.market_regime,
        limit=args.limit,
        horizons=horizons,
        fee_bps_per_side=args.fee_bps_per_side,
        slippage_bps_per_side=args.slippage_bps_per_side,
        db_path=db_path,
    )
    evaluation = run["evaluation"]
    persisted_records = persist_structure_evaluations(
        evaluation,
        primary_horizon_bars=args.primary_horizon,
        db_path=db_path,
    )
    payload: dict[str, Any] = {
        "status": (
            "PERSISTED" if persisted_records
            else "SPLIT_REGISTERED_NO_PATTERN_ROWS"
        ),
        "symbol": evaluation["symbol"],
        "venue": evaluation["venue"],
        "timeframe": evaluation["timeframe"],
        "dataset_id": evaluation["dataset_id"],
        "dataset_fingerprint": evaluation["dataset_fingerprint"],
        "data_split": evaluation["data_split"],
        "split_start_ms": evaluation["split_start_ms"],
        "split_end_ms": evaluation["split_end_ms"],
        "as_of_ms": evaluation["as_of_ms"],
        "bar_count": evaluation["bar_count"],
        "historical_scan": run["historical_scan"],
        "detected_event_count": len(run["detected_structure_events"]),
        "evaluation_counts": evaluation["counts"],
        "persisted_pattern_records": persisted_records,
        "primary_horizon_bars": args.primary_horizon,
        "horizons": list(horizons),
        "costs_applied": evaluation["costs_applied"],
        "fee_bps_per_side": evaluation["fee_bps_per_side"],
        "slippage_bps_per_side": evaluation["slippage_bps_per_side"],
        "validation_status": evaluation["validation_status"],
        "empirical_status": evaluation["empirical_status"],
        "results_by_pattern": evaluation["results_by_pattern"],
        "limitations": [
            "This is a descriptive event study, not a portfolio backtest or trade signal.",
            "Pattern records remain IN_PROGRESS and UNVALIDATED.",
            "Use the same dataset_id, as_of_ms, limit and stored venue for every split.",
            "Run train, validation and test on non-overlapping chronological windows.",
            "Fee-adjusted results are unavailable unless both fee and slippage are supplied.",
        ],
    }
    if args.output_json is not None:
        write_json_atomic(args.output_json, payload)
        payload["output_json"] = str(args.output_json)
    return payload


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        payload = run_study(args)
    except Exception as exc:
        parser.exit(2, f"Structure study failed: {type(exc).__name__}: {exc}\n")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
