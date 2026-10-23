#!/usr/bin/env python3
"""Validate structure and internal arithmetic of a TV26 MT5 audit CSV."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

TIMEFRAMES = ("د1", "د5", "د15", "د30", "س1")
TF_NAMES = {"د1": "M1", "د5": "M5", "د15": "M15", "د30": "M30", "س1": "H1"}
MIN_BARS_DEFAULT = {"د1": 1000, "د5": 200, "د15": 60, "د30": 30, "س1": 15}
MA_COMPONENTS = (
    "متوسط بسيط 10", "متوسط أسي 10",
    "متوسط بسيط 20", "متوسط أسي 20",
    "متوسط بسيط 30", "متوسط أسي 30",
    "متوسط بسيط 50", "متوسط أسي 50",
    "متوسط بسيط 100", "متوسط أسي 100",
    "متوسط بسيط 200", "متوسط أسي 200",
    "إيشيموكو - خط الأساس", "متوسط مرجّح بالحجم", "متوسط هال 9",
)
OSC_COMPONENTS = (
    "القوة النسبية RSI", "ستوكاستك", "قناة السلع CCI", "مؤشر الاتجاه ADX",
    "المذبذب الرائع AO", "الزخم Momentum", "تقارب/تباعد المتوسطات MACD",
    "ستوكاستك RSI", "ويليامز %R", "قوة الثيران والدببة", "المذبذب النهائي",
)
ALL_COMPONENTS = MA_COMPONENTS + OSC_COMPONENTS
REQUIRED_COLUMNS = (
    "bar_open_time_server", "symbol", "broker_company", "broker_server",
    "timeframe", "component", "readiness", "vote", "value_a", "value_b",
    "value_c", "candle_open", "candle_high", "candle_low", "candle_close",
    "tick_volume",
)


class AuditError(ValueError):
    pass


def as_float(value: Any) -> float | None:
    try:
        result = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def read_audit(path: str | Path) -> tuple[list[str], list[dict[str, str]]]:
    p = Path(path)
    if not p.is_file():
        raise AuditError("Audit CSV does not exist: " + str(p))
    with p.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise AuditError("Audit CSV has no header")
        headers = [str(h).strip().lstrip("\ufeff") for h in reader.fieldnames]
        missing = [c for c in REQUIRED_COLUMNS if c not in headers]
        if missing:
            raise AuditError("Missing columns: " + ", ".join(missing))
        rows = [{str(k).strip(): (v or "").strip() for k, v in row.items() if k is not None}
                for row in reader]
    return headers, rows


def validate_rows(rows: list[dict[str, str]], min_bars: dict[str, int] | None = None,
                  source_path: str = "", sha256: str = "") -> dict[str, Any]:
    mins = dict(MIN_BARS_DEFAULT)
    if min_bars:
        mins.update(min_bars)
    problems: list[dict[str, str]] = []
    def issue(code: str, timeframe: str = "", timestamp: str = "",
              component: str = "", detail: str = "") -> None:
        problems.append({"code": code, "timeframe": timeframe, "timestamp": timestamp,
                         "component": component, "detail": detail})

    groups: dict[tuple[str, str], dict[str, dict[str, str]]] = defaultdict(dict)
    duplicate_rows = 0
    unknown_tf_rows = 0
    unknown_component_rows = 0
    metadata = set()
    votes = Counter()
    readiness = Counter()
    row_counts = Counter()
    timestamp_errors = 0

    for row in rows:
        tf = row.get("timeframe", "")
        component = row.get("component", "")
        stamp = row.get("bar_open_time_server", "")
        if tf not in TIMEFRAMES:
            unknown_tf_rows += 1
            issue("UNKNOWN_TIMEFRAME", tf, stamp, component, "Unexpected timeframe label")
            continue
        row_counts[tf] += 1
        metadata.add((row.get("symbol", ""), row.get("broker_company", ""), row.get("broker_server", "")))
        readiness[(tf, row.get("readiness", ""))] += 1
        if component != "SUMMARY" and component not in ALL_COMPONENTS:
            unknown_component_rows += 1
            issue("UNKNOWN_COMPONENT", tf, stamp, component, "Component is not in the expected 26")
            continue
        try:
            datetime.strptime(stamp, "%Y.%m.%d %H:%M")
        except ValueError:
            timestamp_errors += 1
            issue("BAD_TIMESTAMP", tf, stamp, component, "Expected YYYY.MM.DD HH:MM")
        key = (tf, stamp)
        if component in groups[key]:
            duplicate_rows += 1
            issue("DUPLICATE_ROW", tf, stamp, component, "Duplicate component row for same candle")
        groups[key][component] = row
        if component != "SUMMARY":
            vote = row.get("vote", "")
            votes[vote] += 1
            if vote not in {"-1", "0", "1"}:
                issue("INVALID_VOTE", tf, stamp, component, "Expected -1, 0 or 1; got " + repr(vote))
            if row.get("readiness") != "OK":
                issue("COMPONENT_NOT_READY", tf, stamp, component,
                      "Readiness is " + repr(row.get("readiness")))

    summary_counts = Counter()
    complete_counts = Counter()
    incomplete_counts = Counter()
    ohlc_checks = 0
    ohlc_invalid = 0
    aggregate_checked = 0
    aggregate_mismatches = 0
    component_vote_rows_checked = 0
    candle_bundle_errors = 0
    unique_bar_times = Counter()

    for (tf, stamp), components in groups.items():
        unique_bar_times[tf] += 1
        summary = components.get("SUMMARY")
        if summary is None:
            candle_bundle_errors += 1
            issue("MISSING_SUMMARY", tf, stamp, "SUMMARY", "No summary row")
            continue
        summary_counts[tf] += 1
        expected_set = set(ALL_COMPONENTS) | {"SUMMARY"}
        actual_set = set(components)
        missing = expected_set - actual_set
        extra = actual_set - expected_set
        if missing or extra:
            candle_bundle_errors += 1
            issue("BAD_COMPONENT_SET", tf, stamp, "SUMMARY",
                  "missing=" + repr(sorted(missing)) + "; extra=" + repr(sorted(extra)))
        if summary.get("readiness") != "OK":
            incomplete_counts[tf] += 1
            issue("SUMMARY_NOT_READY", tf, stamp, "SUMMARY",
                  "Summary readiness is " + repr(summary.get("readiness")))
        else:
            complete_counts[tf] += 1

        numeric_votes: dict[str, int] = {}
        for name in ALL_COMPONENTS:
            item = components.get(name)
            if item is None:
                continue
            vote_text = item.get("vote", "")
            if vote_text not in {"-1", "0", "1"}:
                continue
            numeric_votes[name] = int(vote_text)
            component_vote_rows_checked += 1
        if len(numeric_votes) == 26:
            ma_mean = sum(numeric_votes[n] for n in MA_COMPONENTS) / 15.0
            osc_mean = sum(numeric_votes[n] for n in OSC_COMPONENTS) / 11.0
            overall = (ma_mean + osc_mean) / 2.0
            expected_values = (
                ("value_a", overall, "overall"),
                ("value_b", ma_mean, "moving averages"),
                ("value_c", osc_mean, "oscillators"),
            )
            for field, expected, label in expected_values:
                actual = as_float(summary.get(field, ""))
                if actual is None:
                    aggregate_mismatches += 1
                    issue("AGGREGATE_MISSING", tf, stamp, "SUMMARY",
                          label + " rating is blank or non-numeric")
                else:
                    aggregate_checked += 1
                    if abs(actual - expected) > 1e-7:
                        aggregate_mismatches += 1
                        issue("AGGREGATE_MISMATCH", tf, stamp, "SUMMARY",
                              label + ": saved=" + str(actual) + ", recalculated=" + str(expected))

        vals = {field: as_float(summary.get(field, "")) for field in
                ("candle_open", "candle_high", "candle_low", "candle_close")}
        if all(v is not None for v in vals.values()):
            o, h, low, c = vals["candle_open"], vals["candle_high"], vals["candle_low"], vals["candle_close"]
            ohlc_checks += 1
            if h < max(o, c, low) - 1e-8 or low > min(o, c, h) + 1e-8:
                ohlc_invalid += 1
                issue("INVALID_OHLC", tf, stamp, "SUMMARY", "OHLC high/low relationship invalid")
        else:
            ohlc_invalid += 1
            issue("MISSING_OHLC", tf, stamp, "SUMMARY", "OHLC contains blank or nonnumeric value")

    metadata_list = sorted(metadata)
    if len(metadata_list) != 1:
        issue("MIXED_FEED_METADATA", detail="Expected one symbol/company/server identity; got " + repr(metadata_list))
    if unknown_tf_rows:
        issue("UNKNOWN_TIMEFRAME_ROWS", detail=str(unknown_tf_rows))
    if duplicate_rows:
        issue("DUPLICATE_ROWS_TOTAL", detail=str(duplicate_rows))
    if timestamp_errors:
        issue("TIMESTAMP_ERRORS_TOTAL", detail=str(timestamp_errors))

    per_tf: dict[str, dict[str, Any]] = {}
    coverage_ok = True
    readiness_ok = True
    for tf in TIMEFRAMES:
        seen = summary_counts[tf]
        complete = complete_counts[tf]
        bad = incomplete_counts[tf]
        minimum = mins.get(tf, 1)
        tf_issues = sum(1 for problem in problems if problem["timeframe"] == tf)
        tf_coverage = seen >= minimum
        if not tf_coverage:
            coverage_ok = False
            issue("LOW_COVERAGE", tf, detail="Expected at least " + str(minimum) + " summary candles; got " + str(seen))
        tf_ready = bad == 0 and complete == seen and seen > 0
        if not tf_ready:
            readiness_ok = False
        per_tf[TF_NAMES[tf]] = {
            "timeframe_label": tf,
            "summary_candles": seen,
            "complete_summaries": complete,
            "incomplete_summaries": bad,
            "component_votes_present": sum(1 for (group_tf, _), group in groups.items()
                                           if group_tf == tf for name in ALL_COMPONENTS
                                           if name in group and group[name].get("vote", "") in {"-1", "0", "1"}),
            "minimum_required_candles": minimum,
            "coverage_pass": tf_coverage,
            "readiness_pass": tf_ready,
            "issues": tf_issues,
        }

    # Coverage is defined by summary counts. The row bundle, arithmetic, OHLC,
    # timestamp, duplicate, and feed-identity checks must also all pass.
    fatal_codes = {
        "UNKNOWN_TIMEFRAME", "UNKNOWN_COMPONENT", "BAD_TIMESTAMP", "DUPLICATE_ROW",
        "INVALID_VOTE", "COMPONENT_NOT_READY", "MISSING_SUMMARY", "BAD_COMPONENT_SET",
        "SUMMARY_NOT_READY", "AGGREGATE_MISSING", "AGGREGATE_MISMATCH",
        "INVALID_OHLC", "MISSING_OHLC", "MIXED_FEED_METADATA", "LOW_COVERAGE",
        "UNKNOWN_TIMEFRAME_ROWS", "DUPLICATE_ROWS_TOTAL", "TIMESTAMP_ERRORS_TOTAL",
    }
    fatal_count = sum(1 for item in problems if item["code"] in fatal_codes)
    passed = (coverage_ok and readiness_ok and fatal_count == 0 and
              aggregate_mismatches == 0 and ohlc_invalid == 0 and
              duplicate_rows == 0 and timestamp_errors == 0 and
              unknown_component_rows == 0 and unknown_tf_rows == 0 and
              candle_bundle_errors == 0 and len(metadata_list) == 1)
    return {
        "status": "PASS" if passed else "FAIL",
        "source_file": source_path,
        "sha256": sha256,
        "data_rows": len(rows),
        "unique_candle_groups": len(groups),
        "feed_metadata": [{"symbol": x[0], "broker_company": x[1], "broker_server": x[2]} for x in metadata_list],
        "per_timeframe": per_tf,
        "rows_by_timeframe_including_components": {TF_NAMES[k]: row_counts[k] for k in TIMEFRAMES},
        "readiness_row_counts": {TF_NAMES[k[0]] + ":" + k[1]: v for k, v in sorted(readiness.items())},
        "vote_distribution": dict(votes),
        "component_vote_rows_checked": component_vote_rows_checked,
        "summary_aggregate_values_checked": aggregate_checked,
        "summary_aggregate_mismatches": aggregate_mismatches,
        "ohlc_candles_checked": ohlc_checks,
        "ohlc_invalid_rows": ohlc_invalid,
        "duplicate_rows": duplicate_rows,
        "unknown_timeframe_rows": unknown_tf_rows,
        "unknown_component_rows": unknown_component_rows,
        "timestamp_errors": timestamp_errors,
        "candle_bundle_errors": candle_bundle_errors,
        "coverage_pass": coverage_ok,
        "readiness_pass": readiness_ok,
        "fatal_issue_count": fatal_count,
        "problems": problems[:100],
    }


def markdown(result: dict[str, Any]) -> str:
    per_tf = result["per_timeframe"]
    lines = [
        "# TV26 MT5 audit data integrity check — " + result["status"], "",
        "- File: " + result["source_file"],
        "- SHA-256: " + result["sha256"],
        "- Data rows excluding header: " + str(result["data_rows"]),
        "- Candle groups: " + str(result["unique_candle_groups"]),
        "- Component votes checked: " + str(result["component_vote_rows_checked"]),
        "- Summary aggregate values re-calculated: " + str(result["summary_aggregate_values_checked"]),
        "- Summary aggregate mismatches: " + str(result["summary_aggregate_mismatches"]),
        "- OHLC candles checked: " + str(result["ohlc_candles_checked"]),
        "- Invalid OHLC rows: " + str(result["ohlc_invalid_rows"]),
        "- Duplicate rows: " + str(result["duplicate_rows"]),
        "- Timestamp errors: " + str(result["timestamp_errors"]),
        "- Unknown components/timeframes: " + str(result["unknown_component_rows"]) + "/" + str(result["unknown_timeframe_rows"]),
        "- Fatal issue count: " + str(result["fatal_issue_count"]), "",
        "| Frame | Summary candles | Complete | Incomplete | Component votes | Minimum | Coverage |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for frame, item in per_tf.items():
        lines.append("| " + frame + " | " + str(item["summary_candles"]) + " | " +
                     str(item["complete_summaries"]) + " | " + str(item["incomplete_summaries"]) + " | " +
                     str(item["component_votes_present"]) + " | " + str(item["minimum_required_candles"]) + " | " +
                     ("PASS" if item["coverage_pass"] else "FAIL") + " |")
    lines += ["", "## Vote distribution", ""]
    for vote in ("-1", "0", "1", ""):
        if vote in result["vote_distribution"]:
            lines.append("- " + (vote or "(blank)") + ": " + str(result["vote_distribution"][vote]))
    lines += ["", "## Issues", ""]
    if result["problems"]:
        for item in result["problems"][:50]:
            lines.append("- " + item["code"] + " | " + item["timeframe"] + " | " +
                         item["timestamp"] + " | " + item["component"] + " | " + item["detail"])
    else:
        lines.append("No integrity issues found.")
    lines += ["", "Interpretation: PASS validates the exported MT5 CSV structure and internal aggregate arithmetic only. It is not proof of TradingView parity, strategy profitability, or real-tick performance.", ""]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", required=True, help="Path to TV26_Audit_*.csv")
    parser.add_argument("--report", default="tv26-audit-integrity.md")
    parser.add_argument("--json", default="tv26-audit-integrity.json")
    parser.add_argument("--min-m1", type=int, default=1000)
    parser.add_argument("--min-m5", type=int, default=200)
    parser.add_argument("--min-m15", type=int, default=60)
    parser.add_argument("--min-m30", type=int, default=30)
    parser.add_argument("--min-h1", type=int, default=15)
    args = parser.parse_args()
    minimums = dict(zip(TIMEFRAMES, (args.min_m1, args.min_m5, args.min_m15, args.min_m30, args.min_h1)))
    if any(x < 1 for x in minimums.values()):
        parser.error("All minimum bar thresholds must be >= 1")
    try:
        headers, rows = read_audit(args.csv)
        sha = hashlib.sha256(Path(args.csv).read_bytes()).hexdigest()
        result = validate_rows(rows, minimums, str(args.csv), sha)
        Path(args.report).write_text(markdown(result), encoding="utf-8")
        Path(args.json).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(markdown(result))
        print("JSON report: " + args.json)
        return 0 if result["status"] == "PASS" else 1
    except (AuditError, OSError) as exc:
        print("Audit validation failed to run: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
