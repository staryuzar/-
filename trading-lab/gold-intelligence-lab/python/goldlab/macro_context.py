"""Read-only U.S. macro context for gold from official Treasury and FRED sources.

Treasury nominal/real yields are primary. FRED USD/VIX series are supplementary.
This module supplies context only and does not produce a gold forecast or trade signal.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
import hashlib
from io import BytesIO, StringIO
import math
import xml.etree.ElementTree as ET
import zipfile
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

import pandas as pd

FRED_HOST = "fred.stlouisfed.org"
FRED_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"
MAX_RESPONSE_BYTES = 2_000_000
MAX_LOOKBACK_ROWS = 5000
DEFAULT_MAX_STALENESS_DAYS = 10
FRED_SOURCE_URL = "https://fred.stlouisfed.org/"
TREASURY_SOURCE_URL = "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/TextView?type=daily_treasury_yield_curve"
TREASURY_REAL_SOURCE_URL = "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/TextView?type=daily_treasury_real_yield_curve"
TREASURY_XML_BASE = "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml"
SERIES = {
    "DGS10": {
        "label_ar": "عائد الخزانة الأمريكية الاسمي لأجل 10 سنوات",
        "unit_ar": "%",
        "change_unit_ar": "نقطة أساس",
        "scale": 100.0,
        "change_kind": "basis_points",
        "source_url": TREASURY_SOURCE_URL,
        "context_ar": "مقياس لسياق أسعار الفائدة الاسمية طويلة الأجل.",
    },
    "DFII10": {
        "label_ar": "العائد الحقيقي الأمريكي لأجل 10 سنوات",
        "unit_ar": "%",
        "change_unit_ar": "نقطة أساس",
        "scale": 100.0,
        "change_kind": "basis_points",
        "source_url": TREASURY_REAL_SOURCE_URL,
        "context_ar": "مقياس للعائد الحقيقي؛ لا يكفي وحده لاستنتاج اتجاه الذهب.",
    },
    "DTWEXAFEGS": {
        "label_ar": "مؤشر الدولار مقابل اقتصادات أجنبية متقدمة",
        "unit_ar": "مؤشر",
        "change_unit_ar": "%",
        "scale": None,
        "change_kind": "percent",
        "source_url": "https://fred.stlouisfed.org/series/DTWEXAFEGS",
        "context_ar": "مؤشر دولار محدود النطاق؛ ليس مؤشرًا شاملًا لكل عملات العالم.",
    },
    "VIXCLS": {
        "label_ar": "مؤشر تقلب سوق الأسهم VIX",
        "unit_ar": "نقطة",
        "change_unit_ar": "نقطة",
        "scale": None,
        "change_kind": "points",
        "source_url": "https://fred.stlouisfed.org/series/VIXCLS",
        "context_ar": "مقياس تقلب متوقع في سوق الأسهم وليس مقياسًا مباشرًا لتقلب الذهب.",
    },
}
FRED_SOURCE_URL = "https://fred.stlouisfed.org/"
TREASURY_SOURCE_URL = "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/TextView?type=daily_treasury_yield_curve"
TREASURY_REAL_SOURCE_URL = "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/TextView?type=daily_treasury_real_yield_curve"
TREASURY_XML_BASE = "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml"
SOURCE_URL = TREASURY_SOURCE_URL


class MacroDataError(RuntimeError):
    """FRED schema, network, or validation error."""


def _aware_utc(value: datetime | None) -> datetime:
    result = value or datetime.now(timezone.utc)
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("fetched_at_utc must be timezone-aware.")
    return result.astimezone(timezone.utc)


def parse_fred_macro_csv(
    csv_text: str,
    *,
    fetched_at_utc: datetime | None = None,
    max_staleness_days: int = DEFAULT_MAX_STALENESS_DAYS,
) -> dict[str, Any]:
    """Validate a FRED multi-series CSV and summarize each series independently."""
    fetched = _aware_utc(fetched_at_utc)
    if isinstance(max_staleness_days, bool) or not isinstance(max_staleness_days, int) or not 0 <= max_staleness_days <= 90:
        raise ValueError("max_staleness_days must be an integer in 0..90.")
    if not isinstance(csv_text, str) or not csv_text.strip():
        raise MacroDataError("FRED returned an empty response.")
    raw_bytes = csv_text.encode("utf-8")
    if len(raw_bytes) > MAX_RESPONSE_BYTES:
        raise MacroDataError("FRED CSV response exceeded the configured size limit.")
    try:
        frame = pd.read_csv(StringIO(csv_text), dtype=str)
    except Exception as exc:
        raise MacroDataError(f"FRED response is not readable CSV: {exc}") from exc
    date_col = next((c for c in ("observation_date", "DATE", "date") if c in frame.columns), None)
    if date_col is None:
        raise MacroDataError("FRED CSV has no recognized date column.")
    available = [sid for sid in SERIES if sid in frame.columns]
    if not available:
        raise MacroDataError("FRED CSV contains none of the requested series.")
    parsed_dates = pd.to_datetime(frame[date_col], errors="coerce", utc=True)
    if parsed_dates.isna().any() or parsed_dates.duplicated().any():
        raise MacroDataError("FRED CSV contains invalid or duplicate observation dates.")
    if not parsed_dates.is_monotonic_increasing:
        raise MacroDataError("FRED observations are not ordered oldest-to-newest.")
    frame = frame.copy()
    frame["_date"] = parsed_dates
    # Prevent accidentally using a future-dated observation as if already published.
    frame = frame[frame["_date"].dt.date <= fetched.date()]
    if frame.empty:
        raise MacroDataError("FRED returned no observations dated on or before retrieval time.")

    summaries: dict[str, Any] = {}
    used_dates: set[str] = set()
    for sid in available:
        values = pd.to_numeric(frame[sid].replace({".": None, "": None, "nan": None}), errors="coerce")
        valid = pd.DataFrame({"date": frame["_date"], "value": values}).dropna(subset=["value"])
        if valid.empty:
            summaries[sid] = {
                **SERIES[sid], "series_id": sid, "status": "unavailable",
                "latest_observation_date": None, "latest_value": None,
                "previous_observation_date": None, "change_1_observation": None,
                "change_5_observations": None, "change_5_display": None,
                "age_days": None, "history": [],
            }
            continue
        if not all(math.isfinite(float(x)) for x in valid["value"]):
            raise MacroDataError(f"FRED series {sid} contains a non-finite numeric value.")
        valid = valid.tail(60).reset_index(drop=True)
        last = valid.iloc[-1]
        obs_date = last["date"].date()
        age_days = (fetched.date() - obs_date).days
        latest = float(last["value"])
        prior_1 = float(valid.iloc[-2]["value"]) if len(valid) >= 2 else None
        prior_5 = float(valid.iloc[-6]["value"]) if len(valid) >= 6 else None
        d1 = latest - prior_1 if prior_1 is not None else None
        d5 = latest - prior_5 if prior_5 is not None else None
        change_kind = SERIES[sid]["change_kind"]
        if change_kind == "basis_points":
            display_change = d5 * 100.0 if d5 is not None else None
            display_change_1 = d1 * 100.0 if d1 is not None else None
        elif change_kind == "percent":
            display_change = (d5 / prior_5 * 100.0) if d5 is not None and prior_5 else None
            display_change_1 = (d1 / prior_1 * 100.0) if d1 is not None and prior_1 else None
        else:
            display_change = d5
            display_change_1 = d1
        status = "stale" if age_days > max_staleness_days else "ok"
        used_dates.add(obs_date.isoformat())
        history = [
            {"date": row["date"].date().isoformat(), "value": float(row["value"])}
            for _, row in valid.iterrows()
        ]
        summaries[sid] = {
            **SERIES[sid], "series_id": sid, "status": status,
            "latest_observation_date": obs_date.isoformat(), "latest_value": latest,
            "previous_observation_date": valid.iloc[-2]["date"].date().isoformat() if len(valid) >= 2 else None,
            "change_1_observation": d1, "change_1_display": display_change_1,
            "change_5_observations": d5, "change_5_display": display_change,
            "age_days": age_days, "history": history,
        }
    if not summaries:
        raise MacroDataError("FRED data did not contain any recognizable series.")
    stale_ids = [sid for sid, value in summaries.items() if value["status"] == "stale"]
    unavailable_ids = [sid for sid, value in summaries.items() if value["status"] == "unavailable"]
    if stale_ids and all(summaries[sid]["status"] == "stale" for sid in summaries if summaries[sid]["latest_value"] is not None):
        overall_status = "stale"
    elif stale_ids or unavailable_ids:
        overall_status = "partial"
    else:
        overall_status = "ok"
    return {
        "status": overall_status,
        "source_name": "Federal Reserve Economic Data (FRED)",
        "source_url": SOURCE_URL,
        "series": summaries,
        "fetched_at_utc": fetched.isoformat(),
        "response_bytes": len(raw_bytes),
        "response_sha256": hashlib.sha256(raw_bytes).hexdigest(),
        "observation_dates": sorted(used_dates),
        "note_ar": (
            "بيانات كلية يومية أو حسب تواتر السلسلة؛ قد تتأخر عن سعر الذهب اللحظي. "
            "التغير لخمسة أرصاد يعني آخر قيمة مقابل القيمة السادسة من النهاية، وليس خمسة أيام تقويمية. "
            "لا تتحول هذه القياسات تلقائيًا إلى توصية شراء أو بيع."
        ),
    }


def _fetch_fred_macro_context(
    *,
    timeout_seconds: float = 12.0,
    max_staleness_days: int = DEFAULT_MAX_STALENESS_DAYS,
) -> dict[str, Any]:
    """Fetch selected public FRED series; failure is isolated from MT5 analysis."""
    if isinstance(timeout_seconds, bool) or not 1.0 <= float(timeout_seconds) <= 30.0:
        raise ValueError("timeout_seconds must be between 1 and 30.")
    query = urlencode({"id": ",".join(SERIES)})
    request = Request(
        FRED_CSV_URL + "?" + query,
        headers={
            "User-Agent": "GoldIntelligenceLab/0.1 (read-only macro context)",
            "Accept": "text/csv,text/plain;q=0.9,*/*;q=0.1",
        },
        method="GET",
    )
    try:
        with urlopen(request, timeout=float(timeout_seconds)) as response:
            parts = urlsplit(response.geturl())
            if parts.scheme != "https" or parts.hostname != FRED_HOST:
                raise MacroDataError("FRED redirected away from the official HTTPS host.")
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except HTTPError as exc:
        raise MacroDataError(f"FRED public CSV endpoint returned HTTP {exc.code}.") from exc
    except (URLError, TimeoutError) as exc:
        raise MacroDataError(f"Unable to reach FRED public CSV endpoint: {exc}.") from exc
    if len(raw) > MAX_RESPONSE_BYTES:
        raise MacroDataError("FRED CSV response exceeded the configured size limit.")
    # FRED returns a ZIP archive containing one CSV per requested series when
    # multiple IDs are requested. Parse each named data file independently.
    csv_texts: list[str] = []
    if raw.startswith(b"PK\x03\x04"):
        try:
            with zipfile.ZipFile(BytesIO(raw)) as archive:
                candidates = [
                    item for item in archive.infolist()
                    if item.filename.lower().endswith(".csv") and not item.is_dir()
                ]
                if not candidates:
                    raise MacroDataError("FRED ZIP contains no CSV data files.")
                for info in candidates:
                    if info.file_size > MAX_RESPONSE_BYTES:
                        raise MacroDataError("A FRED extracted CSV exceeded the size limit.")
                    csv_bytes = archive.read(info)
                    try:
                        csv_texts.append(csv_bytes.decode("utf-8-sig"))
                    except UnicodeDecodeError as exc:
                        raise MacroDataError(f"FRED data file {info.filename!r} is not UTF-8 CSV.") from exc
        except zipfile.BadZipFile as exc:
            raise MacroDataError("FRED returned a malformed ZIP archive.") from exc
    else:
        try:
            csv_texts.append(raw.decode("utf-8-sig"))
        except UnicodeDecodeError as exc:
            raise MacroDataError("FRED response is neither UTF-8 CSV nor a supported ZIP of CSVs.") from exc
    parsed_results = [
        parse_fred_macro_csv(csv_text, max_staleness_days=max_staleness_days)
        for csv_text in csv_texts
    ]
    if not parsed_results:
        raise MacroDataError("FRED did not return any usable CSV data.")
    result = dict(parsed_results[0])
    merged_series: dict[str, Any] = {}
    observation_dates: set[str] = set()
    for parsed in parsed_results:
        merged_series.update(parsed.get("series", {}))
        observation_dates.update(parsed.get("observation_dates", []))
    result["series"] = merged_series
    result["observation_dates"] = sorted(observation_dates)
    result["status"] = "ok" if all(item.get("status") == "ok" for item in merged_series.values()) else "partial"
    result["response_bytes"] = len(raw)
    result["response_sha256"] = hashlib.sha256(raw).hexdigest()
    return result



TREASURY_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "metadata": "http://schemas.microsoft.com/ado/2007/08/dataservices/metadata",
    "data": "http://schemas.microsoft.com/ado/2007/08/dataservices",
}


def parse_treasury_yield_xml(
    xml_text: str,
    *,
    curve_type: str,
    fetched_at_utc: datetime | None = None,
    max_staleness_days: int = DEFAULT_MAX_STALENESS_DAYS,
) -> dict[str, Any]:
    """Parse official U.S. Treasury nominal or real 10-year yield XML."""
    fetched = _aware_utc(fetched_at_utc)
    if curve_type not in {"nominal", "real"}:
        raise ValueError("curve_type must be 'nominal' or 'real'.")
    if not isinstance(xml_text, str) or not xml_text.strip():
        raise MacroDataError("U.S. Treasury returned an empty XML response.")
    sid = "DGS10" if curve_type == "nominal" else "DFII10"
    field = "BC_10YEAR" if curve_type == "nominal" else "TC_10YEAR"
    if len(xml_text.encode("utf-8")) > MAX_RESPONSE_BYTES:
        raise MacroDataError("U.S. Treasury XML response exceeded the size limit.")
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise MacroDataError(f"U.S. Treasury response is not valid XML: {exc}") from exc
    entries = root.findall(".//atom:entry", TREASURY_NS)
    if not entries:
        raise MacroDataError("U.S. Treasury XML contains no Atom entries.")
    observed: dict[str, float] = {}
    for entry in entries:
        props = entry.find(".//metadata:properties", TREASURY_NS)
        if props is None:
            continue
        fields = {node.tag.rsplit("}", 1)[-1]: (node.text or "").strip() for node in list(props)}
        raw_date = fields.get("NEW_DATE", "")
        try:
            obs_date = date.fromisoformat(raw_date[:10])
        except ValueError:
            continue
        if obs_date > fetched.date():
            continue
        raw_value = fields.get(field, "")
        if raw_value in {"", ".", "null", "None"}:
            continue
        try:
            value = float(raw_value.replace(",", ""))
        except ValueError as exc:
            raise MacroDataError(f"Invalid U.S. Treasury value for {field}: {raw_value!r}.") from exc
        if not math.isfinite(value):
            raise MacroDataError(f"Non-finite U.S. Treasury value for {field}.")
        key = obs_date.isoformat()
        if key in observed:
            raise MacroDataError(f"Duplicate U.S. Treasury observation date {key}.")
        observed[key] = value
    if not observed:
        raise MacroDataError(f"No usable {field} observations were found in U.S. Treasury XML.")
    points = sorted(observed.items())
    latest_date, latest = points[-1]
    age_days = (fetched.date() - date.fromisoformat(latest_date)).days
    prior_1 = points[-2][1] if len(points) >= 2 else None
    prior_5 = points[-6][1] if len(points) >= 6 else None
    change_1 = latest - prior_1 if prior_1 is not None else None
    change_5 = latest - prior_5 if prior_5 is not None else None
    meta = SERIES[sid]
    return {
        **meta,
        "series_id": sid,
        "status": "stale" if age_days > max_staleness_days else "ok",
        "latest_observation_date": latest_date,
        "latest_value": latest,
        "previous_observation_date": points[-2][0] if len(points) >= 2 else None,
        "change_1_observation": change_1,
        "change_1_display": change_1 * 100.0 if change_1 is not None else None,
        "change_5_observations": change_5,
        "change_5_display": change_5 * 100.0 if change_5 is not None else None,
        "age_days": age_days,
        "history": [{"date": d, "value": v} for d, v in points[-60:]],
        "provider": "U.S. Department of the Treasury",
    }


def _fetch_treasury_curve(
    *,
    curve_type: str,
    year: int,
    timeout_seconds: float,
    fetched_at_utc: datetime,
    max_staleness_days: int,
) -> tuple[dict[str, Any], str, int]:
    dataset = "daily_treasury_yield_curve" if curve_type == "nominal" else "daily_treasury_real_yield_curve"
    query = urlencode({"data": dataset, "field_tdr_date_value": str(year)})
    request = Request(
        TREASURY_XML_BASE + "?" + query,
        headers={"User-Agent": "GoldIntelligenceLab/0.1 (read-only official macro data)", "Accept": "application/atom+xml,application/xml,text/xml"},
        method="GET",
    )
    try:
        with urlopen(request, timeout=float(timeout_seconds)) as response:
            final_url = urlsplit(response.geturl())
            if final_url.scheme != "https" or final_url.hostname != "home.treasury.gov":
                raise MacroDataError("U.S. Treasury redirected away from its official HTTPS host.")
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except HTTPError as exc:
        raise MacroDataError(f"U.S. Treasury XML endpoint returned HTTP {exc.code}.") from exc
    except (URLError, TimeoutError) as exc:
        raise MacroDataError(f"Unable to reach official U.S. Treasury data: {exc}.") from exc
    if len(raw) > MAX_RESPONSE_BYTES:
        raise MacroDataError("U.S. Treasury XML response exceeded the size limit.")
    try:
        xml_text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise MacroDataError("U.S. Treasury XML response is not valid UTF-8.") from exc
    parsed = parse_treasury_yield_xml(
        xml_text, curve_type=curve_type, fetched_at_utc=fetched_at_utc,
        max_staleness_days=max_staleness_days,
    )
    return parsed, hashlib.sha256(raw).hexdigest(), len(raw)


def fetch_gold_macro_context(
    *,
    timeout_seconds: float = 12.0,
    max_staleness_days: int = DEFAULT_MAX_STALENESS_DAYS,
) -> dict[str, Any]:
    """Read Treasury yields as the primary source; add FRED dollar/VIX when reachable.

    A blocked or timed-out FRED request does not discard Treasury yields.
    """
    if isinstance(timeout_seconds, bool) or not 1.0 <= float(timeout_seconds) <= 30.0:
        raise ValueError("timeout_seconds must be between 1 and 30.")
    fetched = datetime.now(timezone.utc)
    treasury_series: dict[str, Any] = {}
    treasury_hashes: dict[str, str] = {}
    treasury_sizes: dict[str, int] = {}
    treasury_errors: dict[str, str] = {}
    for curve in ("nominal", "real"):
        sid = "DGS10" if curve == "nominal" else "DFII10"
        try:
            item, digest, size = _fetch_treasury_curve(
                curve_type=curve, year=fetched.year,
                timeout_seconds=float(timeout_seconds), fetched_at_utc=fetched,
                max_staleness_days=max_staleness_days,
            )
            treasury_series[sid] = item
            treasury_hashes[sid] = digest
            treasury_sizes[sid] = size
        except MacroDataError as exc:
            treasury_errors[sid] = str(exc)

    fred: dict[str, Any] | None = None
    fred_error: str | None = None
    try:
        fred = _fetch_fred_macro_context(
            timeout_seconds=min(5.0, float(timeout_seconds)),
            max_staleness_days=max_staleness_days,
        )
    except MacroDataError as exc:
        fred_error = str(exc)

    series: dict[str, Any] = {}
    for sid in ("DGS10", "DFII10"):
        if sid in treasury_series:
            series[sid] = treasury_series[sid]
        elif fred and fred.get("series", {}).get(sid, {}).get("latest_value") is not None:
            series[sid] = {
                **fred["series"][sid],
                "provider": "FRED fallback",
                "source_url": f"https://fred.stlouisfed.org/series/{sid}",
            }
        else:
            series[sid] = {
                **SERIES[sid], "series_id": sid, "status": "unavailable",
                "latest_observation_date": None, "latest_value": None,
                "previous_observation_date": None, "change_1_observation": None,
                "change_1_display": None, "change_5_observations": None,
                "change_5_display": None, "age_days": None, "history": [],
                "provider": "unavailable",
            }

    for sid in ("DTWEXAFEGS", "VIXCLS"):
        if fred and sid in fred.get("series", {}):
            series[sid] = fred["series"][sid]
        else:
            series[sid] = {
                **SERIES[sid], "series_id": sid, "status": "unavailable",
                "latest_observation_date": None, "latest_value": None,
                "previous_observation_date": None, "change_1_observation": None,
                "change_1_display": None, "change_5_observations": None,
                "change_5_display": None, "age_days": None, "history": [],
                "provider": "FRED unreachable or unavailable",
            }

    warnings: list[str] = []
    if treasury_errors:
        warnings.append("تعذّر جلب بعض سلاسل وزارة الخزانة: " + "؛ ".join(f"{k}: {v}" for k, v in treasury_errors.items()))
    if fred_error:
        warnings.append("تعذّر جلب المؤشرات المساندة من FRED؛ بقيت سلاسل العائد الرسمي متاحة إن نجحت قراءة الخزانة. " + fred_error)
    if any(item["status"] != "ok" for item in series.values()):
        warnings.append("بعض السلاسل مفقودة أو قديمة؛ لا تُعامل البيانات على أنها تغطية كاملة أو لحظية.")
    status = "ok" if all(item["status"] == "ok" for item in series.values()) and not warnings else "partial"
    digest_parts = [*treasury_hashes.values()]
    if fred and fred.get("response_sha256"):
        digest_parts.append(fred["response_sha256"])
    digest = hashlib.sha256("|".join(digest_parts).encode("ascii")).hexdigest() if digest_parts else None
    sizes = [*treasury_sizes.values()]
    if fred:
        sizes.append(int(fred.get("response_bytes", 0)))
    return {
        "status": status,
        "source_name": "U.S. Treasury + FRED macro context",
        "source_url": TREASURY_SOURCE_URL,
        "fetched_at_utc": fetched.isoformat(),
        "series": series,
        "response_bytes": sum(sizes),
        "response_sha256": digest,
        "sources": {
            "treasury": {"source_url": TREASURY_XML_BASE, "series_hashes": treasury_hashes, "errors": treasury_errors},
            "fred": {"source_url": FRED_SOURCE_URL, "available": fred is not None, "response_sha256": fred.get("response_sha256") if fred else None, "error": fred_error},
        },
        "warnings_ar": warnings,
        "note_ar": (
            "العوائد الاسمية والحقيقية تُقرأ من منحنيات وزارة الخزانة الأمريكية اليومية. "
            "مؤشر الدولار وVIX إضافيان من FRED وقد لا يتاحان على كل شبكة. "
            "تواريخ الرصد تختلف بين السلاسل وأيام العطل، والتغير لخمسة أرصاد يقارن آخر قيمة بالقيمة السادسة من النهاية، وليس خمسة أيام تقويمية. "
            "هذه خلفية وصفية وليست توقعًا سعريًا أو توصية شراء/بيع."
        ),
    }


__all__ = [
    "FRED_CSV_URL", "SOURCE_URL", "FRED_SOURCE_URL", "TREASURY_SOURCE_URL", "TREASURY_REAL_SOURCE_URL", "SERIES", "MacroDataError",
    "parse_fred_macro_csv", "parse_treasury_yield_xml", "fetch_gold_macro_context",
]

[executed on device: DESKTOP-BCGR98A (28de460a-0fbe-4532-90a8-ff34da68192c)]