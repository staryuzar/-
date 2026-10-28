"""Public CFTC Commitment of Traders feed for COMEX gold (read-only, no API token)."""
from __future__ import annotations
from datetime import date, datetime, timezone
import hashlib, json, math
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen
from typing import Any

DATASET_ID = "72hh-3qpy"
API_URL = f"https://publicreporting.cftc.gov/resource/{DATASET_ID}.json"
SOURCE_URL = f"https://publicreporting.cftc.gov/Commitments-of-Traders/Disaggregated-Futures-Only/{DATASET_ID}"
HOST = "publicreporting.cftc.gov"
GOLD_CODE = "088691"
MAX_ROWS = 260
MAX_BYTES = 4_000_000

class COTDataError(RuntimeError):
    """CFTC schema, network, or response error; does not affect MT5 analysis."""

def _count(value: Any, field: str) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise COTDataError(f"Invalid Boolean in CFTC field {field}.")
    try:
        number = float(str(value).replace(",", "").strip())
    except (TypeError, ValueError) as exc:
        raise COTDataError(f"Invalid numeric value in CFTC field {field}.") from exc
    if not math.isfinite(number) or not number.is_integer():
        raise COTDataError(f"CFTC field {field} is not a finite whole-number count.")
    return int(number)

def parse_cftc_cot_rows(payload: Any, *, fetched_at_utc: datetime | None = None) -> dict[str, Any]:
    """Validate and normalize CFTC rows. Null positions stay null, never zero."""
    if not isinstance(payload, list):
        raise COTDataError("CFTC returned a non-list response; the schema may have changed.")
    if not payload:
        raise COTDataError("CFTC returned no rows for gold contract code 088691.")
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in payload:
        if not isinstance(raw, dict):
            raise COTDataError("Unexpected CFTC row shape.")
        required = {"report_date_as_yyyy_mm_dd", "cftc_contract_market_code", "open_interest_all",
                    "m_money_positions_long_all", "m_money_positions_short_all", "m_money_positions_spread_all"}
        missing = required - set(raw)
        if missing:
            raise COTDataError("CFTC response schema is missing fields: " + ", ".join(sorted(missing)))
        code = str(raw.get("cftc_contract_market_code", "")).strip()
        if code != GOLD_CODE:
            raise COTDataError(f"Unexpected CFTC contract code {code!r}; expected {GOLD_CODE}.")
        raw_date = str(raw.get("report_date_as_yyyy_mm_dd", "")).strip()
        try:
            report_date = date.fromisoformat(raw_date[:10]).isoformat()
        except ValueError as exc:
            raise COTDataError(f"Invalid CFTC report date {raw_date!r}.") from exc
        if report_date in seen:
            raise COTDataError(f"Duplicate CFTC report date {report_date}.")
        seen.add(report_date)
        long = _count(raw.get("m_money_positions_long_all"), "m_money_positions_long_all")
        short = _count(raw.get("m_money_positions_short_all"), "m_money_positions_short_all")
        spread = _count(raw.get("m_money_positions_spread_all"), "m_money_positions_spread_all")
        oi = _count(raw.get("open_interest_all"), "open_interest_all")
        net = long - short if long is not None and short is not None else None
        net_pct = (net / oi * 100.0) if net is not None and oi is not None and oi > 0 else None
        rows.append({
            "report_date": report_date,
            "market_name": str(raw.get("market_and_exchange_names") or "GOLD - COMMODITY EXCHANGE INC."),
            "contract_market_code": code, "scope": "futures_only",
            "open_interest": oi, "managed_money_long": long, "managed_money_short": short,
            "managed_money_spread": spread, "managed_money_net": net,
            "managed_money_net_pct_open_interest": net_pct, "net_change_vs_previous_report": None,
        })
    rows.sort(key=lambda item: item["report_date"], reverse=True)
    for i, row in enumerate(rows[:-1]):
        newer, older = row["managed_money_net"], rows[i + 1]["managed_money_net"]
        row["net_change_vs_previous_report"] = newer - older if newer is not None and older is not None else None
    fetched = fetched_at_utc or datetime.now(timezone.utc)
    if fetched.tzinfo is None:
        raise ValueError("fetched_at_utc must be timezone-aware.")
    fetched = fetched.astimezone(timezone.utc)
    age_days = (fetched.date() - date.fromisoformat(rows[0]["report_date"])).days
    return {
        "status": "ok", "source_name": "CFTC Disaggregated Commitments of Traders — Futures Only",
        "source_url": SOURCE_URL, "dataset_id": DATASET_ID, "contract_market_code": GOLD_CODE,
        "market_name": rows[0]["market_name"], "scope": "futures_only",
        "fetched_at_utc": fetched.isoformat(), "latest_report_date": rows[0]["report_date"],
        "latest_report_age_days": age_days, "rows_count": len(rows), "rows": rows,
        "note_ar": (
            "بيانات أسبوعية لمراكز عقود COMEX الآجلة للذهب، تمثل عادةً المراكز كما في الثلاثاء وتُنشر يوم الجمعة. "
            "ليست مراكز السوق الفوري أو جميع المشاركين عالميًا وليست إشارة دخول. الحقول الفارغة تبقى غير متاحة."
        ),
    }

def fetch_cftc_gold_cot(*, rows_count: int = 156, timeout_seconds: float = 15.0) -> dict[str, Any]:
    """Fetch public CFTC gold positioning history without an API key or token."""
    if isinstance(rows_count, bool) or not isinstance(rows_count, int) or not 1 <= rows_count <= MAX_ROWS:
        raise ValueError(f"rows_count must be 1..{MAX_ROWS}.")
    if not 1 <= float(timeout_seconds) <= 30:
        raise ValueError("timeout_seconds must be between 1 and 30.")
    select = ",".join([
        "report_date_as_yyyy_mm_dd", "market_and_exchange_names", "cftc_contract_market_code",
        "open_interest_all", "m_money_positions_long_all", "m_money_positions_short_all",
        "m_money_positions_spread_all",
    ])
    query = urlencode({
        "$select": select, "$where": f"cftc_contract_market_code='{GOLD_CODE}'",
        "$order": "report_date_as_yyyy_mm_dd DESC", "$limit": str(rows_count),
    })
    req = Request(API_URL + "?" + query, headers={
        "User-Agent": "GoldIntelligenceLab/0.1 (read-only public CFTC positioning reader)",
        "Accept": "application/json",
    }, method="GET")
    try:
        with urlopen(req, timeout=float(timeout_seconds)) as response:
            parts = urlsplit(response.geturl())
            if parts.scheme != "https" or parts.hostname != HOST:
                raise COTDataError("CFTC API redirected outside the official HTTPS host.")
            raw = response.read(MAX_BYTES + 1)
    except HTTPError as exc:
        # Preserve a bounded server diagnostic so schema/query changes can be fixed precisely.
        try:
            detail = " ".join(exc.read(2049).decode("utf-8", "replace").split())[:1200]
        except Exception:
            detail = ""
        suffix = f" Details: {detail}" if detail else ""
        raise COTDataError(f"CFTC API HTTP error: {exc.code}.{suffix}") from exc
    except URLError as exc:
        raise COTDataError(f"Could not reach CFTC public data: {exc.reason}.") from exc
    except TimeoutError as exc:
        raise COTDataError("CFTC API request timed out.") from exc
    if len(raw) > MAX_BYTES:
        raise COTDataError("CFTC API response exceeded the size limit.")
    try:
        payload = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise COTDataError("CFTC response is not valid JSON.") from exc
    result = parse_cftc_cot_rows(payload)
    result["response_bytes"] = len(raw)
    result["response_sha256"] = hashlib.sha256(raw).hexdigest()
    result["requested_rows"] = rows_count
    return result

__all__ = ["API_URL", "SOURCE_URL", "COTDataError", "fetch_cftc_gold_cot", "parse_cftc_cot_rows"]
