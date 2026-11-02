from __future__ import annotations

import json
import math
from statistics import mean, median
import time
from typing import Any

from .visual_knowledge import CANDLE_PATTERN_CATALOG

_PATTERN_DEFINITIONS = {
    item["pattern_id"]: item for item in CANDLE_PATTERN_CATALOG
}
_HUMAN_LABEL_SOURCES = {"HUMAN", "HUMAN_REVIEWED", "EXPERT_REVIEWED"}


def _normalise_bars(bars: list[dict[str, Any]]) -> list[dict[str, float]]:
    if not isinstance(bars, list):
        raise TypeError("bars must be a list")
    result: list[dict[str, float]] = []
    for index, bar in enumerate(bars):
        try:
            item = {
                key: float(bar[key])
                for key in ("open", "high", "low", "close")
            }
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"Invalid OHLC at index {index}: {exc}") from exc
        if not all(math.isfinite(value) for value in item.values()):
            raise ValueError(f"Non-finite OHLC at index {index}")
        if (
            item["low"] <= 0
            or item["high"] < max(item["open"], item["close"], item["low"])
            or item["low"] > min(item["open"], item["close"])
        ):
            raise ValueError(f"Inconsistent OHLC bounds at index {index}")
        result.append(item)
    return result


def _event(event: dict[str, Any], bar_count: int, kind: str) -> dict[str, Any]:
    pattern_id = str(event.get("pattern_id", ""))
    if pattern_id not in _PATTERN_DEFINITIONS:
        raise ValueError(f"Unknown candle pattern id in {kind}: {pattern_id}")
    raw_end = event.get("end_index", event.get("index"))
    if raw_end is None:
        raise ValueError(f"{kind} event requires end_index or index")
    end_index = int(raw_end)
    start_index = int(event.get("start_index", end_index))
    if start_index < 0 or end_index < start_index or end_index >= bar_count:
        raise ValueError(f"{kind} event has invalid candle indexes")
    return {
        **event,
        "pattern_id": pattern_id,
        "start_index": start_index,
        "end_index": end_index,
    }


def _classification_metrics(tp: int, fp: int, fn: int) -> dict[str, Any]:
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision + recall else 0.0
    )
    return {
        "true_positives": tp,
        "false_positives": fp,
        "false_negatives": fn,
        "precision": round(precision, 6),
        "recall": round(recall, 6),
        "f1": round(f1, 6),
    }


def _outcome_metrics(
    bars: list[dict[str, float]],
    events: list[dict[str, Any]],
    direction: str,
    horizons: tuple[int, ...],
    fee_bps: float,
    slippage_bps: float,
) -> dict[str, Any]:
    sign = 1.0 if direction == "BULLISH" else -1.0
    round_trip_cost_pct = (2.0 * (fee_bps + slippage_bps)) / 100.0
    results: dict[str, Any] = {}

    for horizon in horizons:
        gross_returns: list[float] = []
        net_returns: list[float] = []
        mae_values: list[float] = []
        mfe_values: list[float] = []
        for event in events:
            end_index = int(event["end_index"])
            exit_index = end_index + horizon
            if exit_index >= len(bars):
                continue
            entry = bars[end_index]["close"]
            exit_close = bars[exit_index]["close"]
            future = bars[end_index + 1:exit_index + 1]
            gross = sign * ((exit_close / entry) - 1.0) * 100.0
            directional_extremes = [
                sign * ((price / entry) - 1.0) * 100.0
                for bar in future
                for price in (bar["high"], bar["low"])
            ]
            if not directional_extremes:
                continue
            gross_returns.append(gross)
            net_returns.append(gross - round_trip_cost_pct)
            mfe_values.append(max(directional_extremes))
            mae_values.append(min(directional_extremes))

        results[str(horizon)] = {
            "sample_count": len(net_returns),
            "mean_gross_return_pct": round(mean(gross_returns), 6) if gross_returns else None,
            "median_gross_return_pct": round(median(gross_returns), 6) if gross_returns else None,
            "mean_net_return_pct": round(mean(net_returns), 6) if net_returns else None,
            "median_net_return_pct": round(median(net_returns), 6) if net_returns else None,
            "fee_adjusted_expectancy_pct": round(mean(net_returns), 6) if net_returns else None,
            "win_rate_after_costs": round(
                sum(value > 0 for value in net_returns) / len(net_returns), 6
            ) if net_returns else None,
            "mean_mae_pct": round(mean(mae_values), 6) if mae_values else None,
            "mean_mfe_pct": round(mean(mfe_values), 6) if mfe_values else None,
            "round_trip_cost_pct": round(round_trip_cost_pct, 6),
        }
    return results


def evaluate_candle_pattern_detections(
    bars: list[dict[str, Any]],
    detections: list[dict[str, Any]],
    ground_truth: list[dict[str, Any]],
    *,
    symbol: str,
    timeframe: str,
    dataset_fingerprint: str,
    data_split: str,
    label_source: str,
    manual_reviewed: bool = False,
    market_regime: str = "UNKNOWN",
    horizons: tuple[int, ...] = (1, 3, 5, 10, 20),
    tolerance_bars: int = 0,
    fee_bps: float = 5.0,
    slippage_bps: float = 2.0,
    minimum_validation_samples: int = 30,
) -> dict[str, Any]:
    """Compare detector events with independent labels and measure forward outcomes.

    VALIDATED means only that the pattern classifier was evaluated against a
    sufficiently sized human-reviewed test/holdout annotation set. It does not
    certify strategy profitability or guarantee future performance.
    """
    normalised = _normalise_bars(bars)
    if not symbol.strip() or not timeframe.strip():
        raise ValueError("symbol and timeframe are required")
    if not dataset_fingerprint.strip():
        raise ValueError("dataset_fingerprint is required")
    split = data_split.strip().lower()
    if split not in {"train", "validation", "test", "holdout"}:
        raise ValueError("data_split must be train, validation, test or holdout")
    label_source_normalised = label_source.strip().upper()
    if not label_source_normalised:
        raise ValueError("label_source is required")
    if not isinstance(tolerance_bars, int) or tolerance_bars < 0 or tolerance_bars > 20:
        raise ValueError("tolerance_bars must be between 0 and 20")
    if not isinstance(minimum_validation_samples, int) or minimum_validation_samples < 1:
        raise ValueError("minimum_validation_samples must be positive")
    if (
        not math.isfinite(float(fee_bps))
        or not math.isfinite(float(slippage_bps))
        or fee_bps < 0
        or slippage_bps < 0
    ):
        raise ValueError("fee_bps and slippage_bps must be finite and non-negative")
    horizons = tuple(sorted(set(int(value) for value in horizons)))
    if not horizons or any(value <= 0 or value > 1000 for value in horizons):
        raise ValueError("horizons must contain positive candle counts up to 1000")

    predicted = [
        _event(item, len(normalised), "detection")
        for item in detections
    ]
    labelled = [
        _event(item, len(normalised), "ground_truth")
        for item in ground_truth
    ]

    pattern_ids = sorted({
        item["pattern_id"] for item in predicted + labelled
    })
    per_pattern: dict[str, Any] = {}
    all_tp = all_fp = all_fn = 0
    for pattern_id in pattern_ids:
        predictions = sorted(
            [x for x in predicted if x["pattern_id"] == pattern_id],
            key=lambda x: (x["end_index"], x["start_index"]),
        )
        labels = sorted(
            [x for x in labelled if x["pattern_id"] == pattern_id],
            key=lambda x: (x["end_index"], x["start_index"]),
        )
        unmatched = set(range(len(labels)))
        matched_events: list[dict[str, Any]] = []
        false_positives = 0
        for prediction in predictions:
            candidates = [
                index for index in unmatched
                if abs(labels[index]["end_index"] - prediction["end_index"]) <= tolerance_bars
            ]
            if not candidates:
                false_positives += 1
                continue
            chosen = min(
                candidates,
                key=lambda index: (
                    abs(labels[index]["end_index"] - prediction["end_index"]),
                    labels[index]["end_index"],
                    index,
                ),
            )
            unmatched.remove(chosen)
            matched_events.append(prediction)

        true_positives = len(matched_events)
        false_negatives = len(unmatched)
        metrics = _classification_metrics(
            true_positives, false_positives, false_negatives
        )
        definition = _PATTERN_DEFINITIONS[pattern_id]
        direction = str(definition["direction"]).upper()
        if direction not in {"BULLISH", "BEARISH"} and matched_events:
            event_directions = {
                str(event.get("direction", "")).upper()
                for event in matched_events
            }
            if len(event_directions) == 1:
                direction = next(iter(event_directions))
        outcome = (
            _outcome_metrics(
                normalised, matched_events, direction, horizons,
                float(fee_bps), float(slippage_bps),
            )
            if direction in {"BULLISH", "BEARISH"}
            else {
                str(horizon): {
                    "sample_count": 0,
                    "mean_gross_return_pct": None,
                    "median_gross_return_pct": None,
                    "mean_net_return_pct": None,
                    "median_net_return_pct": None,
                    "fee_adjusted_expectancy_pct": None,
                    "win_rate_after_costs": None,
                    "mean_mae_pct": None,
                    "mean_mfe_pct": None,
                    "round_trip_cost_pct": round(
                        (2.0 * (fee_bps + slippage_bps)) / 100.0, 6
                    ),
                }
                for horizon in horizons
            }
        )
        sample_count = len(labels)
        human_source = (
            bool(manual_reviewed)
            and label_source_normalised in _HUMAN_LABEL_SOURCES
        )
        if not human_source or not dataset_fingerprint:
            validation_status = "UNVALIDATED"
        elif split in {"test", "holdout"} and sample_count >= minimum_validation_samples:
            validation_status = "VALIDATED"
        else:
            validation_status = "IN_PROGRESS"

        per_pattern[pattern_id] = {
            **metrics,
            "sample_count": sample_count,
            "prediction_count": len(predictions),
            "matched_event_count": true_positives,
            "direction": direction,
            "horizon_metrics": outcome,
            "validation_status": validation_status,
        }
        all_tp += true_positives
        all_fp += false_positives
        all_fn += false_negatives

    return {
        "status": "EVALUATED",
        "symbol": symbol.upper(),
        "timeframe": timeframe,
        "market_regime": market_regime,
        "dataset_fingerprint": dataset_fingerprint,
        "data_split": split,
        "label_source": label_source_normalised,
        "manual_reviewed": bool(manual_reviewed),
        "minimum_validation_samples": minimum_validation_samples,
        "fee_bps_per_side": float(fee_bps),
        "slippage_bps_per_side": float(slippage_bps),
        "tolerance_bars": tolerance_bars,
        "overall": _classification_metrics(all_tp, all_fp, all_fn),
        "patterns": per_pattern,
        "interpretation": (
            "PATTERN_CLASSIFICATION_EVALUATION_ONLY; outcomes are historical "
            "descriptive measurements, not a trading strategy or a promise "
            "of future profitability."
        ),
    }


def save_pattern_evaluation(
    evaluation: dict[str, Any],
    pattern_id: str,
    *,
    primary_horizon_bars: int = 5,
    db_path: str | None = None,
) -> dict[str, Any]:
    """Persist one pattern's human-label evaluation and all measured horizons."""
    from ..storage import connect

    summary = (evaluation.get("patterns") or {}).get(pattern_id)
    if summary is None:
        raise ValueError(f"No evaluation summary for pattern: {pattern_id}")
    if pattern_id not in _PATTERN_DEFINITIONS:
        raise ValueError(f"Unknown candle pattern id: {pattern_id}")
    if primary_horizon_bars <= 0:
        raise ValueError("primary_horizon_bars must be positive")

    status = str(summary.get("validation_status", "UNVALIDATED"))
    if status not in {"UNVALIDATED", "IN_PROGRESS", "VALIDATED", "REJECTED"}:
        raise ValueError("Invalid evaluation validation_status")
    data_split = str(evaluation.get("data_split", "train"))
    label_source = str(evaluation.get("label_source", "UNSPECIFIED"))
    manual_reviewed = bool(evaluation.get("manual_reviewed", False))
    sample_count = int(summary.get("sample_count", 0))
    min_samples = int(evaluation.get("minimum_validation_samples", 30))
    if status == "VALIDATED" and not (
        manual_reviewed
        and label_source in _HUMAN_LABEL_SOURCES
        and data_split in {"test", "holdout"}
        and sample_count >= min_samples
        and bool(evaluation.get("dataset_fingerprint"))
    ):
        raise ValueError("Cannot persist VALIDATED without independent human-reviewed labels")

    all_horizons = summary.get("horizon_metrics") or {}
    selected = all_horizons.get(str(primary_horizon_bars), {})
    conn = connect(db_path) if db_path is not None else connect()
    now = int(time.time() * 1000)
    args = (
        pattern_id,
        str(evaluation.get("symbol", "")).upper(),
        str(evaluation.get("timeframe", "")),
        str(evaluation.get("market_regime", "UNKNOWN") or "UNKNOWN"),
        sample_count,
        summary.get("precision"),
        summary.get("recall"),
        summary.get("f1"),
        selected.get("mean_gross_return_pct"),
        selected.get("median_gross_return_pct"),
        selected.get("mean_mae_pct"),
        selected.get("mean_mfe_pct"),
        selected.get("fee_adjusted_expectancy_pct"),
        str(evaluation.get("dataset_fingerprint", "")),
        status,
        now,
        json.dumps(all_horizons, ensure_ascii=False, sort_keys=True),
        int(primary_horizon_bars),
        str(evaluation.get("data_split", "train")),
        str(evaluation.get("label_source", "UNSPECIFIED")),
        1 if manual_reviewed else 0,
        float(evaluation.get("fee_bps_per_side", 0)),
        float(evaluation.get("slippage_bps_per_side", 0)),
    )
    try:
        with conn:
            conn.execute(
                """INSERT INTO visual_pattern_evaluations
                (pattern_id,symbol,timeframe,market_regime,sample_count,precision,recall,f1,
                 mean_return_pct,median_return_pct,mae_pct,mfe_pct,fee_adjusted_expectancy_pct,
                 dataset_fingerprint,validation_status,calculated_at_ms,horizon_metrics_json,
                 primary_horizon_bars,data_split,label_source,human_reviewed,fee_bps,slippage_bps)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(pattern_id,symbol,timeframe,market_regime,dataset_fingerprint)
                DO UPDATE SET
                 sample_count=excluded.sample_count,precision=excluded.precision,
                 recall=excluded.recall,f1=excluded.f1,
                 mean_return_pct=excluded.mean_return_pct,
                 median_return_pct=excluded.median_return_pct,mae_pct=excluded.mae_pct,
                 mfe_pct=excluded.mfe_pct,
                 fee_adjusted_expectancy_pct=excluded.fee_adjusted_expectancy_pct,
                 validation_status=excluded.validation_status,
                 calculated_at_ms=excluded.calculated_at_ms,
                 horizon_metrics_json=excluded.horizon_metrics_json,
                 primary_horizon_bars=excluded.primary_horizon_bars,
                 data_split=excluded.data_split,label_source=excluded.label_source,
                 human_reviewed=excluded.human_reviewed,fee_bps=excluded.fee_bps,
                 slippage_bps=excluded.slippage_bps""",
                args,
            )
    finally:
        conn.close()

    return {
        "status": "STORED",
        "pattern_id": pattern_id,
        "validation_status": status,
        "primary_horizon_bars": primary_horizon_bars,
        "sample_count": sample_count,
    }


__all__ = [
    "evaluate_candle_pattern_detections",
    "save_pattern_evaluation",
]
