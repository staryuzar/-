#!/usr/bin/env python3
"""Split one TradingView all-timeframes export into per-timeframe parity CSVs.

Repeated higher-timeframe candles are expected when exporting from an M1 chart.
The splitter verifies those duplicate rows are identical, then emits each candle
once. A repeated timestamp with conflicting OHLC/ratings/votes is rejected.
The Pine exporter base-4 packs 26 votes: digits 0,1,2 => -1,0,+1; digit 3 => NA.
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Any

from compare_tv26_csv import (
    COMPONENTS, InputError, as_number, find_col, parse_time, read_csv, time_key,
)

TIMEFRAMES = ("M1", "M5", "M15", "M30", "H1")
BASE = 4
PACKED_LIMIT = BASE ** len(COMPONENTS)
BLANK_VALUES = {"", "na", "n/a", "nan", "none", "null", "—", "-"}

FIELDS = (
    "packed", "total", "ma", "osc",
    "formula_total", "formula_ma", "formula_osc",
    "bar_open_time", "open", "high", "low", "close",
)


def decode_votes(raw: Any) -> list[str]:
    value = as_number(raw)
    if value is None:
        return [""] * len(COMPONENTS)
    packed = int(round(value))
    if abs(value - packed) > 0.1:
        raise InputError(f"Packed votes value is not an integer: {raw!r}")
    if packed < 0 or packed >= PACKED_LIMIT:
        raise InputError(f"Packed votes out of range [0, {PACKED_LIMIT - 1}]: {raw!r}")
    out: list[str] = []
    for i in range(len(COMPONENTS)):
        digit = (packed // (BASE ** i)) % BASE
        out.append("" if digit == 3 else str(digit - 1))
    return out


def _canonical_value(raw: Any) -> float | str | None:
    """Normalize CSV number formatting so equivalent repeated values compare cleanly."""
    text = "" if raw is None else str(raw).strip()
    if text.casefold() in BLANK_VALUES:
        return None
    number = as_number(text)
    if number is not None:
        return number
    return text.casefold()


def _bar_key(raw: Any, timeframe: str) -> int | None:
    text = "" if raw is None else str(raw).strip()
    if text.casefold() in BLANK_VALUES:
        return None
    try:
        return time_key(parse_time(text))
    except (InputError, OSError, OverflowError, ValueError) as exc:
        raise InputError(f"Invalid {timeframe} bar timestamp {text!r}: {exc}") from exc


def split_file(input_path: str | Path, timeframe: str, output_path: str | Path) -> dict[str, int | str]:
    tf = timeframe.upper()
    if tf not in TIMEFRAMES:
        raise InputError(f"Unsupported timeframe: {timeframe}")
    headers, rows = read_csv(input_path)
    if not rows:
        raise InputError(f"TradingView export has no data rows: {input_path}")
    columns = {name: find_col(headers, f"TV26.{tf}.{name}") for name in FIELDS}
    output_headers = [
        "time", "TV26.total", "TV26.ma", "TV26.osc",
        "TV26.formula_total", "TV26.formula_ma", "TV26.formula_osc",
        "TV26.bar_open_time", "TV26.open", "TV26.high", "TV26.low", "TV26.close",
    ] + ["TV26." + name for name in COMPONENTS]
    written = 0
    missing_pack = 0
    duplicates_collapsed = 0
    bars_without_timestamp = 0
    seen: dict[int, tuple[str, dict[str, float | str | None]]] = {}
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=output_headers)
        writer.writeheader()
        for row in rows:
            raw_pack = row.get(columns["packed"], "")
            decoded = decode_votes(raw_pack)
            if as_number(raw_pack) is None:
                missing_pack += 1
            normalized = {
                "time": row.get("time", ""),
                "TV26.total": row.get(columns["total"], ""),
                "TV26.ma": row.get(columns["ma"], ""),
                "TV26.osc": row.get(columns["osc"], ""),
                "TV26.formula_total": row.get(columns["formula_total"], ""),
                "TV26.formula_ma": row.get(columns["formula_ma"], ""),
                "TV26.formula_osc": row.get(columns["formula_osc"], ""),
                "TV26.bar_open_time": row.get(columns["bar_open_time"], ""),
                "TV26.open": row.get(columns["open"], ""),
                "TV26.high": row.get(columns["high"], ""),
                "TV26.low": row.get(columns["low"], ""),
                "TV26.close": row.get(columns["close"], ""),
            }
            normalized.update({"TV26." + name: decoded[i] for i, name in enumerate(COMPONENTS)})

            key = _bar_key(normalized["TV26.bar_open_time"], tf)
            if key is None:
                bars_without_timestamp += 1
                writer.writerow(normalized)
                written += 1
                continue

            # Compare every data series except the chart's own time and the timestamp key.
            signature = {
                field: _canonical_value(normalized[field])
                for field in output_headers
                if field not in {"time", "TV26.bar_open_time"}
            }
            previous = seen.get(key)
            if previous is not None:
                previous_time, previous_signature = previous
                if signature != previous_signature:
                    changed = next(
                        (field for field in signature if signature[field] != previous_signature.get(field)),
                        "unknown",
                    )
                    raise InputError(
                        f"Conflicting repeated {tf} candle at {normalized['TV26.bar_open_time']!r} "
                        f"(first export timestamp {previous_time!r}); series {changed!r} changed. "
                        "Do not compare until the export is corrected."
                    )
                duplicates_collapsed += 1
                continue

            seen[key] = (str(normalized["TV26.bar_open_time"]), signature)
            writer.writerow(normalized)
            written += 1
    return {
        "timeframe": tf,
        "rows_written": written,
        "rows_missing_pack": missing_pack,
        "duplicate_rows_collapsed": duplicates_collapsed,
        "rows_without_timestamp": bars_without_timestamp,
        "output": str(output),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="Single CSV exported from TradingView_Parity_AllTF_Export.pine")
    parser.add_argument("--timeframe", required=True, choices=TIMEFRAMES)
    parser.add_argument("--output", required=True, help="Normalized per-timeframe CSV path")
    args = parser.parse_args()
    try:
        result = split_file(args.input, args.timeframe, args.output)
    except (InputError, OSError, OverflowError, ValueError) as exc:
        parser.error(str(exc))
    print(
        f"Timeframe={result['timeframe']}; unique bars={result['rows_written']}; "
        f"duplicate rows collapsed={result['duplicate_rows_collapsed']}; "
        f"missing packed values in source rows={result['rows_missing_pack']}; "
        f"rows without timestamp={result['rows_without_timestamp']}; output={result['output']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
