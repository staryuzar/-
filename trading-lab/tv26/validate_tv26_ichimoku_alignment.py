#!/usr/bin/env python3
"""Validate MT5 Ichimoku raw diagnostics against the published Pine v3 shift contract."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import pandas as pd

TF_LABELS = {"M1": "د1", "M5": "د5", "M15": "د15", "M30": "د30", "H1": "س1"}
ICHIMOKU_LABEL = "إيشيموكو - خط الأساس"
RAW_FIELDS = (
    ("value_a", "tenkan_sen"),
    ("value_b", "kijun_sen"),
    ("value_c", "senkou_span_a_shift26"),
    ("value_d", "senkou_span_b_shift26"),
    ("value_e", "close"),
)


class ValidationError(ValueError):
    pass


def read_rows(path: str | Path) -> list[dict[str, str]]:
    p = Path(path)
    if not p.is_file():
        raise ValidationError(f"Input file not found: {p}")
    with p.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise ValidationError(f"CSV has no header: {p}")
        return [
            {str(k).strip(): (v or "").strip() for k, v in row.items() if k is not None}
            for row in reader
        ]


def number(value: Any) -> float | None:
    try:
        x = float(str(value).strip())
        return x if math.isfinite(x) else None
    except (ValueError, TypeError):
        return None


def sha256(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def expected_ichimoku(bars: list[dict[str, Any]]) -> pd.DataFrame:
    df = (
        pd.DataFrame(bars)
        .sort_values("time")
        .drop_duplicates("time", keep="last")
        .reset_index(drop=True)
    )
    if df.empty:
        raise ValidationError("No OHLC bars available for Ichimoku calculation")
    h, l = df["high"].astype(float), df["low"].astype(float)
    tenkan = (h.rolling(9, min_periods=9).max() + l.rolling(9, min_periods=9).min()) / 2.0
    kijun = (h.rolling(26, min_periods=26).max() + l.rolling(26, min_periods=26).min()) / 2.0
    span_a = (tenkan + kijun) / 2.0
    span_b = (h.rolling(52, min_periods=52).max() + l.rolling(52, min_periods=52).min()) / 2.0
    df["tenkan_sen"] = tenkan
    df["kijun_sen"] = kijun
    # TradingView TechnicalRating v3 reads the span series 26 bars back.
    df["senkou_span_a_shift26"] = span_a.shift(26)
    df["senkou_span_b_shift26"] = span_b.shift(26)
    return df


def validate_files(
    audit_path: str | Path,
    history_path: str | Path,
    tolerance: float = 1e-6,
    min_bars: int = 10,
) -> tuple[dict[str, Any], list[dict[str, str]], str]:
    if tolerance < 0 or min_bars < 1:
        raise ValidationError("Tolerance must be >= 0 and min_bars must be >= 1")
    audit_rows, history_rows = read_rows(audit_path), read_rows(history_path)
    audit_required = {
        "timeframe", "bar_open_time_server", "component", "readiness",
        "value_a", "value_b", "value_c", "value_d", "value_e",
        "candle_open", "candle_high", "candle_low", "candle_close",
    }
    history_required = {
        "timeframe", "bar_open_time_server",
        "candle_open", "candle_high", "candle_low", "candle_close",
    }
    audit_headers = set(audit_rows[0]) if audit_rows else set()
    history_headers = set(history_rows[0]) if history_rows else set()
    if not audit_rows or not audit_required.issubset(audit_headers):
        raise ValidationError(f"MT5 audit missing required columns: {sorted(audit_required - audit_headers)}")
    if not history_rows or not history_required.issubset(history_headers):
        raise ValidationError(f"MT5 OHLC history missing required columns: {sorted(history_required - history_headers)}")

    ichimoku_by_tf: dict[str, list[dict[str, str]]] = defaultdict(list)
    bars_by_tf: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)

    for row in history_rows:
        tf = next((key for key, label in TF_LABELS.items() if label == row.get("timeframe")), None)
        if not tf:
            continue
        stamp = row.get("bar_open_time_server", "")
        if not stamp:
            continue
        values = {key: number(row.get(f"candle_{key}", "")) for key in ("open", "high", "low", "close")}
        if any(value is None for value in values.values()):
            continue
        bars_by_tf[tf][stamp] = {"time": stamp, **values}

    for row in audit_rows:
        tf = next((key for key, label in TF_LABELS.items() if label == row.get("timeframe")), None)
        if not tf:
            continue
        stamp = row.get("bar_open_time_server", "")
        if not stamp:
            continue
        if row.get("component") == "SUMMARY":
            values = {key: number(row.get(f"candle_{key}", "")) for key in ("open", "high", "low", "close")}
            if all(value is not None for value in values.values()):
                # The audit candle replaces its matching history candle if the two overlap.
                bars_by_tf[tf][stamp] = {"time": stamp, **values}
        elif row.get("component") == ICHIMOKU_LABEL:
            ichimoku_by_tf[tf].append(row)

    per_tf: dict[str, dict[str, Any]] = {}
    details: list[dict[str, str]] = []
    for tf in TF_LABELS:
        rows = sorted(ichimoku_by_tf.get(tf, []), key=lambda row: row.get("bar_open_time_server", ""))
        bars = sorted(bars_by_tf.get(tf, {}).values(), key=lambda row: row["time"])
        calculated = expected_ichimoku(bars) if bars else pd.DataFrame()
        expected_by_time = (
            {str(row["time"]): row for row in calculated.to_dict("records")}
            if not calculated.empty else {}
        )
        mismatch_count = 0
        missing_count = 0
        checks = 0
        for row in rows:
            stamp = row.get("bar_open_time_server", "")
            expected = expected_by_time.get(stamp)
            if expected is None:
                missing_count += len(RAW_FIELDS)
                details.append({
                    "timeframe": tf, "time": stamp, "field": "all",
                    "mt5_value": "", "expected_value": "", "abs_delta": "",
                    "result": "MISSING", "note": "No OHLC candle to compute expected values",
                })
                continue
            for mt5_field, expected_field in RAW_FIELDS:
                actual_value = number(row.get(mt5_field, ""))
                expected_value = number(expected.get(expected_field))
                if actual_value is None or expected_value is None:
                    missing_count += 1
                    details.append({
                        "timeframe": tf, "time": stamp, "field": mt5_field,
                        "mt5_value": "" if actual_value is None else str(actual_value),
                        "expected_value": "" if expected_value is None else str(expected_value),
                        "abs_delta": "", "result": "MISSING",
                        "note": "Raw diagnostic or warm-up value not available",
                    })
                    continue
                checks += 1
                delta = abs(actual_value - expected_value)
                passed = delta <= tolerance
                if not passed:
                    mismatch_count += 1
                details.append({
                    "timeframe": tf, "time": stamp, "field": mt5_field,
                    "mt5_value": f"{actual_value:.10g}",
                    "expected_value": f"{expected_value:.10g}",
                    "abs_delta": f"{delta:.10g}",
                    "result": "PASS" if passed else "FAIL",
                    "note": f"Tolerance={tolerance:g}; expected {expected_field}",
                })
        bar_count = len(rows)
        coverage_ok = bar_count >= min_bars
        passed = (
            coverage_ok
            and checks == bar_count * len(RAW_FIELDS)
            and missing_count == 0
            and mismatch_count == 0
        )
        per_tf[tf] = {
            "audit_ichimoku_bars": bar_count,
            "ohlc_bars_for_reconstruction": len(bars),
            "raw_values_checked": checks,
            "expected_raw_values": bar_count * len(RAW_FIELDS),
            "mismatches": mismatch_count,
            "missing_values": missing_count,
            "minimum_bars_required": min_bars,
            "coverage_pass": coverage_ok,
            "status": "PASS" if passed else "FAIL",
        }

    total_bars = sum(item["audit_ichimoku_bars"] for item in per_tf.values())
    total_checks = sum(item["raw_values_checked"] for item in per_tf.values())
    total_mismatches = sum(item["mismatches"] for item in per_tf.values())
    total_missing = sum(item["missing_values"] for item in per_tf.values())
    result = {
        "status": "PASS" if all(item["status"] == "PASS" for item in per_tf.values()) else "FAIL",
        "scope": "MT5 Ichimoku raw buffers vs independently reconstructed OHLC and TechnicalRating v3 26-bar span alignment",
        "tolerance": tolerance,
        "minimum_bars_per_timeframe": min_bars,
        "timeframes": per_tf,
        "total_ichimoku_bars": total_bars,
        "total_raw_values_checked": total_checks,
        "total_mismatches": total_mismatches,
        "total_missing_values": total_missing,
        "audit_sha256": sha256(audit_path),
        "history_sha256": sha256(history_path),
    }
    lines = [
        f"# TV26 Ichimoku raw-value alignment — {result['status']}",
        "",
        "This is a raw-value test, separate from component-vote parity and strategy profitability.",
        f"- Absolute tolerance: {tolerance:g}",
        f"- Minimum bars per timeframe: {min_bars}",
        f"- Ichimoku rows: {total_bars}",
        f"- Raw fields checked: {total_checks}",
        f"- Mismatches: {total_mismatches}",
        f"- Missing values: {total_missing}",
        "",
        "| Timeframe | Ichimoku bars | Raw values checked | Mismatches | Missing | Result |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for tf, item in per_tf.items():
        lines.append(
            f"| {tf} | {item['audit_ichimoku_bars']} | {item['raw_values_checked']} | "
            f"{item['mismatches']} | {item['missing_values']} | {item['status']} |"
        )
    if total_mismatches or total_missing:
        lines += ["", "## First issues", ""]
        for row in [row for row in details if row["result"] != "PASS"][:30]:
            lines.append(
                f"- {row['timeframe']} {row['time']} {row['field']}: "
                f"MT5={row['mt5_value'] or '—'}, expected={row['expected_value'] or '—'}, "
                f"delta={row['abs_delta'] or '—'}"
            )
    else:
        lines += [
            "",
            "All five raw fields—Tenkan, Kijun, Span A shifted 26 bars, Span B shifted 26 bars, "
            "and close—matched the OHLC reconstruction within tolerance.",
        ]
    return result, details, "\n".join(lines) + "\n"


def write_details(path: str | Path, rows: list[dict[str, str]]) -> None:
    fields = ["timeframe", "time", "field", "mt5_value", "expected_value", "abs_delta", "result", "note"]
    with Path(path).open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit", required=True)
    parser.add_argument("--history", required=True)
    parser.add_argument("--tolerance", type=float, default=1e-6)
    parser.add_argument("--min-bars", type=int, default=10)
    parser.add_argument("--report", default="ichimoku-raw-alignment.md")
    parser.add_argument("--details", default="ichimoku-raw-alignment.csv")
    parser.add_argument("--json", default="ichimoku-raw-alignment.json")
    args = parser.parse_args(argv)
    try:
        result, details, report = validate_files(
            args.audit, args.history, args.tolerance, args.min_bars
        )
        Path(args.report).write_text(report, encoding="utf-8")
        write_details(args.details, details)
        Path(args.json).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(report)
        print(f"Details: {args.details}; JSON: {args.json}")
        return 0 if result["status"] == "PASS" else 1
    except (ValidationError, OSError, OverflowError) as exc:
        print(f"Ichimoku raw-value validation could not run: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
