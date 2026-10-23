#!/usr/bin/env python3
"""Strictly compare the TV26 MT5 audit CSV with TradingView's component-export CSV."""
from __future__ import annotations

import argparse
import csv
import math
import re
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

# Pine export series name -> MT5 Arabic audit component label.
COMPONENTS = {
    "SMA10": "متوسط بسيط 10", "SMA20": "متوسط بسيط 20",
    "SMA30": "متوسط بسيط 30", "SMA50": "متوسط بسيط 50",
    "SMA100": "متوسط بسيط 100", "SMA200": "متوسط بسيط 200",
    "EMA10": "متوسط أسي 10", "EMA20": "متوسط أسي 20",
    "EMA30": "متوسط أسي 30", "EMA50": "متوسط أسي 50",
    "EMA100": "متوسط أسي 100", "EMA200": "متوسط أسي 200",
    "HMA9": "متوسط هال 9", "VWMA20": "متوسط مرجّح بالحجم",
    "Ichimoku": "إيشيموكو - خط الأساس",
    "RSI14": "القوة النسبية RSI", "Stochastic": "ستوكاستك",
    "CCI20": "قناة السلع CCI", "ADX": "مؤشر الاتجاه ADX",
    "AO": "المذبذب الرائع AO", "Momentum10": "الزخم Momentum",
    "MACD": "تقارب/تباعد المتوسطات MACD", "StochRSI": "ستوكاستك RSI",
    "WilliamsR": "ويليامز %R", "BullBearPower": "قوة الثيران والدببة",
    "UltimateOscillator": "المذبذب النهائي",
}
SUMMARY = {"overall": ("TV26.total", "value_a"),
           "ma": ("TV26.ma", "value_b"),
           "osc": ("TV26.osc", "value_c")}
PRICE = (("open", "candle_open", "TV26.open"),
         ("high", "candle_high", "TV26.high"),
         ("low", "candle_low", "TV26.low"),
         ("close", "candle_close", "TV26.close"))
TF_ALIASES = {
    "m1": "M1", "1m": "M1", "د1": "M1", "period_m1": "M1",
    "m5": "M5", "5m": "M5", "د5": "M5", "period_m5": "M5",
    "m15": "M15", "15m": "M15", "د15": "M15", "period_m15": "M15",
    "m30": "M30", "30m": "M30", "د30": "M30", "period_m30": "M30",
    "h1": "H1", "1h": "H1", "س1": "H1", "period_h1": "H1",
}


class InputError(ValueError):
    pass


def norm_header(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (text or "").strip().strip('"').lstrip("\ufeff").lower())


def find_col(headers: list[str], wanted: str, required: bool = True) -> str | None:
    target = norm_header(wanted)
    for field in headers:
        val = norm_header(field)
        if val == target or val.endswith(target):
            return field
    if required:
        raise InputError(f"Missing required CSV column {wanted!r}; available: {', '.join(headers)}")
    return None


def read_csv(path: str | Path) -> tuple[list[str], list[dict[str, str]]]:
    path = Path(path)
    if not path.is_file():
        raise InputError(f"File not found: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        sample = f.read(4096)
        f.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
        reader = csv.DictReader(f, dialect=dialect)
        if not reader.fieldnames:
            raise InputError(f"CSV has no header: {path}")
        headers = [str(h).strip().strip('"').lstrip("\ufeff") for h in reader.fieldnames]
        rows = [{str(k).strip().strip('"').lstrip("\ufeff"): (v or "").strip().strip('"')
                 for k, v in row.items() if k is not None} for row in reader]
    return headers, rows


def as_number(value: Any) -> float | None:
    if value is None:
        return None
    raw = str(value).strip().replace(",", "")
    if not raw or raw.lower() in {"na", "n/a", "nan", "none", "null", "—", "-"}:
        return None
    try:
        result = float(raw)
    except (ValueError, TypeError):
        return None
    return result if math.isfinite(result) else None


def parse_time(value: str, naive_utc_offset_hours: float | None = None) -> datetime:
    raw = (value or "").strip().strip('"')
    if not raw:
        raise InputError("Blank candle timestamp")
    numeric = as_number(raw)
    if numeric is not None and abs(numeric) >= 1e8:
        epoch = numeric / 1000.0 if abs(numeric) >= 1e11 else numeric
        return datetime.fromtimestamp(epoch, tz=timezone.utc).replace(second=0, microsecond=0)
    parsed = None
    normal = raw.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normal)
    except ValueError:
        for fmt in ("%Y.%m.%d %H:%M:%S", "%Y.%m.%d %H:%M",
                    "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M",
                    "%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M",
                    "%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M"):
            try:
                parsed = datetime.strptime(raw, fmt)
                break
            except ValueError:
                pass
    if parsed is None:
        raise InputError(f"Unsupported timestamp format: {raw!r}")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
        if naive_utc_offset_hours is not None:
            # Broker server time UTC+3 becomes UTC by subtracting three hours.
            parsed -= timedelta(hours=naive_utc_offset_hours)
    else:
        parsed = parsed.astimezone(timezone.utc)
    return parsed.astimezone(timezone.utc).replace(second=0, microsecond=0)


def time_key(value: datetime) -> int:
    return int(value.timestamp() // 60)


def canonical_tf(value: str) -> str:
    raw = re.sub(r"\s+", "", (value or "").strip().casefold())
    return TF_ALIASES.get(raw, TF_ALIASES.get(raw.replace("_", ""), raw.upper()))


def lookup(row: dict[str, str], headers: list[str], colname: str) -> str:
    actual = find_col(headers, colname, required=False)
    return row.get(actual, "") if actual else ""


def compare_files(mt5_path: str | Path, tv_path: str | Path, timeframe: str,
                  mt5_utc_offset_hours: float, min_bars: int = 10,
                  price_tolerance: float = 0.01, rating_tolerance: float = 0.0011
                  ) -> tuple[dict[str, Any], list[dict[str, str]], str]:
    tf = canonical_tf(timeframe)
    if tf not in {"M1", "M5", "M15", "M30", "H1"}:
        raise InputError(f"Unsupported timeframe {timeframe!r}")
    mh, mr = read_csv(mt5_path)
    th, tr = read_csv(tv_path)
    mc = {name: find_col(mh, name) for name in (
        "bar_open_time_server", "timeframe", "component", "readiness", "vote",
        "value_a", "value_b", "value_c", "candle_open", "candle_high",
        "candle_low", "candle_close", "tick_volume")}
    tv_time = find_col(th, "TV26.bar_open_time")
    for col in ("TV26.total", "TV26.ma", "TV26.osc", "TV26.open", "TV26.high",
                "TV26.low", "TV26.close"):
        find_col(th, col)
    tv_vol_col = find_col(th, "TV26.volume", required=False)
    symbol_col = find_col(mh, "symbol", required=False)

    mt: dict[int, dict[str, dict[str, str]]] = defaultdict(dict)
    mt_times: dict[int, str] = {}
    symbols: set[str] = set()
    for row in mr:
        if canonical_tf(row.get(mc["timeframe"], "")) != tf:
            continue
        key = time_key(parse_time(row.get(mc["bar_open_time_server"], ""), mt5_utc_offset_hours))
        component = row.get(mc["component"], "").strip()
        if component:
            mt[key][component] = row
            mt_times[key] = row.get(mc["bar_open_time_server"], "")
        if symbol_col and row.get(symbol_col):
            symbols.add(row[symbol_col])

    tv: dict[int, dict[str, str]] = {}
    for row in tr:
        raw = row.get(tv_time, "")
        if not raw:
            continue
        try:
            key = time_key(parse_time(raw))
        except (InputError, OSError, OverflowError, ValueError):
            continue
        # A trailing blank line can be ignored; keep the last data row for duplicate keys.
        if any((v or "").strip() for v in row.values()):
            tv[key] = row

    common = sorted(set(mt) & set(tv))
    counts = {
        "matched_bars": len(common), "mt5_bars": len(mt), "tv_bars": len(tv),
        "unmatched_mt5_bars": len(set(mt) - set(tv)),
        "unmatched_tv_bars": len(set(tv) - set(mt)),
        "price_values_checked": 0, "price_mismatches": 0,
        "volume_mismatches_info_only": 0, "complete_mt5_summary_bars": 0,
        "incomplete_mt5_summary_bars": 0, "summary_values_checked": 0,
        "summary_mismatches": 0, "component_votes_checked": 0,
        "component_vote_mismatches": 0, "component_values_missing": 0,
    }
    details: list[dict[str, str]] = []
    max_price_delta = 0.0
    max_rating_delta = 0.0

    def add_detail(bar: str, component: str, check: str, left: Any, right: Any,
                   delta: float | None, ok: bool | None, note: str = "") -> None:
        details.append({
            "timeframe": tf, "mt5_bar_time_server": bar, "component": component,
            "check": check, "mt5_value": "" if left is None else str(left),
            "tradingview_value": "" if right is None else str(right),
            "absolute_delta": "" if delta is None else f"{delta:.10g}",
            "result": "PASS" if ok is True else ("FAIL" if ok is False else "INFO"),
            "note": note,
        })

    for key in common:
        bar, tr_row, block = mt_times[key], tv[key], mt[key]
        summ = block.get("SUMMARY")
        if summ is None:
            counts["incomplete_mt5_summary_bars"] += 1
            add_detail(bar, "SUMMARY", "summary_row", None, None, None, False,
                       "MT5 SUMMARY row missing")
        elif summ.get(mc["readiness"], "").upper() != "OK":
            counts["incomplete_mt5_summary_bars"] += 1
            add_detail(bar, "SUMMARY", "readiness", summ.get(mc["readiness"]), "OK",
                       None, False, "MT5 summary incomplete")
        else:
            counts["complete_mt5_summary_bars"] += 1
            for name, (tv_col, mt_col) in SUMMARY.items():
                left = as_number(summ.get(mc[mt_col], ""))
                right = as_number(lookup(tr_row, th, tv_col))
                delta = abs(left - right) if left is not None and right is not None else None
                if delta is None:
                    counts["summary_mismatches"] += 1
                    add_detail(bar, name, "summary_rating", left, right, None, False,
                               "Blank or non-numeric rating")
                    continue
                counts["summary_values_checked"] += 1
                max_rating_delta = max(max_rating_delta, delta)
                ok = delta <= rating_tolerance
                if not ok:
                    counts["summary_mismatches"] += 1
                add_detail(bar, name, "summary_rating", left, right, delta, ok,
                           f"tolerance={rating_tolerance:g}")

        for label, mt_col, tv_col in PRICE:
            left = as_number(block.get("SUMMARY", {}).get(mc[mt_col], ""))
            right = as_number(lookup(tr_row, th, tv_col))
            delta = abs(left - right) if left is not None and right is not None else None
            if delta is None:
                counts["price_mismatches"] += 1
                add_detail(bar, "OHLC", label, left, right, None, False, "OHLC value missing")
                continue
            counts["price_values_checked"] += 1
            max_price_delta = max(max_price_delta, delta)
            ok = delta <= price_tolerance
            if not ok:
                counts["price_mismatches"] += 1
            add_detail(bar, "OHLC", label, left, right, delta, ok,
                       f"tolerance={price_tolerance:g}")

        mt_vol = as_number(block.get("SUMMARY", {}).get(mc["tick_volume"], ""))
        tv_vol = as_number(lookup(tr_row, th, "TV26.volume")) if tv_vol_col else None
        if mt_vol is not None and tv_vol is not None and mt_vol != tv_vol:
            counts["volume_mismatches_info_only"] += 1
            add_detail(bar, "VOLUME", "tick_vs_tv_volume", mt_vol, tv_vol,
                       abs(mt_vol-tv_vol), None,
                       "Informational: provider volume conventions may differ")

        for tv_name, mt_name in COMPONENTS.items():
            item = block.get(mt_name)
            left = as_number(item.get(mc["vote"], "")) if item else None
            right = as_number(lookup(tr_row, th, "TV26." + tv_name))
            if not item or item.get(mc["readiness"], "").upper() != "OK" or left is None:
                counts["component_values_missing"] += 1
                add_detail(bar, mt_name, "component_vote", left, right, None, None,
                           "MT5 component not ready; comparison unavailable")
                continue
            if right is None:
                counts["component_values_missing"] += 1
                add_detail(bar, mt_name, "component_vote", left, None, None, False,
                           "TradingView vote missing or not numeric")
                continue
            delta = abs(left-right)
            counts["component_votes_checked"] += 1
            ok = delta <= 1e-9
            if not ok:
                counts["component_vote_mismatches"] += 1
            add_detail(bar, mt_name, "component_vote", left, right, delta, ok,
                       f"TradingView series=TV26.{tv_name}")

    enough = counts["matched_bars"] >= min_bars
    complete = counts["component_values_missing"] == 0 and counts["incomplete_mt5_summary_bars"] == 0
    requirements = {
        "enough_matched_bars": enough,
        "all_required_values_present": complete,
        "ohlc_matches": counts["price_mismatches"] == 0,
        "summary_ratings_match": counts["summary_mismatches"] == 0,
        "all_26_component_votes_match": counts["component_vote_mismatches"] == 0,
    }
    result = {
        "status": "PASS" if all(requirements.values()) else "FAIL",
        "timeframe": tf, "min_bars_required": min_bars,
        "mt5_utc_offset_hours": mt5_utc_offset_hours, "mt5_symbols": sorted(symbols),
        "price_tolerance": price_tolerance, "rating_tolerance": rating_tolerance,
        "max_absolute_price_delta": max_price_delta,
        "max_absolute_summary_rating_delta": max_rating_delta,
        **counts, "pass_requirements": requirements,
    }
    report = make_report(result, mt5_path, tv_path)
    return result, details, report


def make_report(r: dict[str, Any], mt5_path: str | Path, tv_path: str | Path) -> str:
    checks = "\n".join(f"- [{'x' if ok else ' '}] {key.replace('_', ' ')}"
                       for key, ok in r["pass_requirements"].items())
    return f"""# تقرير مقارنة TV26 — {r['status']}

- الإطار الزمني: **{r['timeframe']}**
- ملف MT5: {mt5_path}
- ملف TradingView: {tv_path}
- رموز MT5 في الملف: {', '.join(r['mt5_symbols']) or 'غير محدد'}
- فرق توقيت خادم MT5 عن UTC المستخدم: **{r['mt5_utc_offset_hours']:+g} ساعة**
- الشموع المشتركة: **{r['matched_bars']}** (الحد الأدنى المطلوب: {r['min_bars_required']})
- شموع MT5: {r['mt5_bars']}؛ شموع TradingView: {r['tv_bars']}
- شموع MT5 غير الموجودة في TradingView: {r['unmatched_mt5_bars']}
- شموع TradingView غير الموجودة في MT5: {r['unmatched_tv_bars']}

## ملخص القياس

| الفحص | العدد |
|---|---:|
| قيم OHLC المقارنة | {r['price_values_checked']} |
| اختلافات OHLC | {r['price_mismatches']} |
| شموع الملخص المكتملة | {r['complete_mt5_summary_bars']} |
| شموع الملخص غير المكتملة | {r['incomplete_mt5_summary_bars']} |
| درجات الملخص المقارنة | {r['summary_values_checked']} |
| اختلافات درجات الملخص | {r['summary_mismatches']} |
| أصوات المكونات المقارنة | {r['component_votes_checked']} |
| اختلافات أصوات المكونات | {r['component_vote_mismatches']} |
| قيم مكونات غير متاحة | {r['component_values_missing']} |
| اختلاف الحجم — معلومة فقط | {r['volume_mismatches_info_only']} |
| أكبر فرق سعري | {r['max_absolute_price_delta']:.10g} |
| أكبر فرق في درجة الملخص | {r['max_absolute_summary_rating_delta']:.10g} |

## شروط النجاح

{checks}

## قراءة النتيجة

- PASS يعني أن هذه الملفات اجتازت فحوص الشموع والمكونات لهذا الإطار فقط؛ لا يثبت الربحية ولا جميع ظروف السوق.
- FAIL يعني أن شرطًا واحدًا على الأقل لم يتحقق. افتح ملف التفاصيل لتحديد الشمعة والمؤشر المختلف.
- اختلاف الحجم مسجل كمعلومة فقط، لأن تعريف الحجم قد يختلف بين مزودين أو بين tick volume والحجم المعروض.
- إذا كان عدد الشموع المشتركة صفرًا، راجع --mt5-utc-offset-hours أولًا ثم مزود السعر وتوقيت الشموع.
- شغّل الاختبار منفصلًا لكل إطار M1/M5/M15/M30/H1، مع تصدير TradingView الذي يستخدم الإطار نفسه.
- الأداة تقارن ملفات مرجعية فعلية؛ لا تخترع قيم TradingView ولا تستبدل اختبار الاستراتيجية في MT5.
"""


def write_details(path: str | Path, rows: list[dict[str, str]]) -> None:
    fields = ["timeframe", "mt5_bar_time_server", "component", "check", "mt5_value",
              "tradingview_value", "absolute_delta", "result", "note"]
    with Path(path).open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mt5", required=True, help="MT5 Common Files TV26_Audit_*.csv")
    parser.add_argument("--tv", required=True, help="TradingView component CSV export")
    parser.add_argument("--timeframe", required=True, choices=("M1", "M5", "M15", "M30", "H1"))
    parser.add_argument("--mt5-utc-offset-hours", required=True, type=float,
                        help="MT5 server UTC offset: UTC+3 -> 3; UTC-2 -> -2")
    parser.add_argument("--min-bars", type=int, default=10)
    parser.add_argument("--price-tolerance", type=float, default=0.01)
    parser.add_argument("--rating-tolerance", type=float, default=0.0011)
    parser.add_argument("--report", default="tv26-parity-report.md")
    parser.add_argument("--details", default="tv26-parity-details.csv")
    args = parser.parse_args(argv)
    if args.min_bars < 1 or args.price_tolerance < 0 or args.rating_tolerance < 0:
        parser.error("min-bars must be >= 1 and tolerances must be >= 0")
    try:
        result, details, report = compare_files(
            args.mt5, args.tv, args.timeframe, args.mt5_utc_offset_hours,
            args.min_bars, args.price_tolerance, args.rating_tolerance)
        Path(args.report).write_text(report, encoding="utf-8")
        write_details(args.details, details)
        print(report)
        print(f"\nDetailed rows: {args.details}\nReport: {args.report}")
        return 0 if result["status"] == "PASS" else 1
    except (InputError, OSError, OverflowError) as exc:
        print(f"TV26 parity comparison could not run: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
