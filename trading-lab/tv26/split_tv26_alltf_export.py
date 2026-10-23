#!/usr/bin/env python3
"""Split one TradingView all-timeframes export into per-timeframe parity CSVs.

The Pine exporter base-4 packs 26 component votes into one exactly representable
integer: digits 0,1,2 => votes -1,0,+1; digit 3 => component not ready.
"""
from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path
from typing import Any

from compare_tv26_csv import COMPONENTS, InputError, as_number, find_col, read_csv

TIMEFRAMES = ("M1", "M5", "M15", "M30", "H1")
BASE = 4
PACKED_LIMIT = BASE ** len(COMPONENTS)

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
            writer.writerow(normalized)
            written += 1
    return {"timeframe": tf, "rows_written": written, "rows_missing_pack": missing_pack,
            "output": str(output)}


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
    print(f"Timeframe={result['timeframe']}; rows={result['rows_written']}; "
          f"missing packed values={result['rows_missing_pack']}; output={result['output']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
