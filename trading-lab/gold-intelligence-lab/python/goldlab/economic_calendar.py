"""Read-only adapter for the official U.S. Bureau of Labor Statistics release calendar.

This source reports publication schedules, not actual economic values, forecasts,
or trading signals. Fetching is explicit/on-demand and never blocks MT5 analysis.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
import hashlib
import re
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

BLS_CALENDAR_URL = "https://www.bls.gov/schedule/news_release/bls.ics"
BLS_CALENDAR_HOST = "www.bls.gov"
DEFAULT_CALENDAR_TZ = "America/New_York"
MAX_CALENDAR_BYTES = 2_000_000
DEFAULT_WINDOW_DAYS = 120
DEFAULT_MAX_EVENTS = 100


class EconomicCalendarError(RuntimeError):
    """Calendar source/network/format error, separate from market-data errors."""


def _unfold_ical_lines(content: str) -> list[str]:
    normalised = content.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    result: list[str] = []
    for line in normalised.split("\n"):
        if line.startswith((" ", "\t")) and result:
            result[-1] += line[1:]
        else:
            result.append(line)
    return result


def _unescape_ical_text(value: str) -> str:
    # RFC 5545 text escaping. Order matters: decode escaped backslashes last.
    value = value.replace("\\n", "\n").replace("\\N", "\n")
    value = value.replace("\\,", ",").replace("\\;", ";")
    value = value.replace("\\\\", "\\")
    return value.strip()


def _parse_property(line: str) -> tuple[str, dict[str, str], str] | None:
    if ":" not in line:
        return None
    left, value = line.split(":", 1)
    fragments = left.split(";")
    name = fragments[0].upper().strip()
    params: dict[str, str] = {}
    for fragment in fragments[1:]:
        if "=" not in fragment:
            continue
        key, parameter = fragment.split("=", 1)
        params[key.upper().strip()] = parameter.strip().strip('"')
    return name, params, value.strip()


def _parse_ical_datetime(
    raw: str, params: dict[str, str], default_timezone: str
) -> tuple[datetime, bool, str | None]:
    value = raw.strip()
    is_date = params.get("VALUE", "").upper() == "DATE" or bool(re.fullmatch(r"\d{8}", value))
    if is_date:
        parsed_date = datetime.strptime(value[:8], "%Y%m%d").date()
        # Sorting/filtering for an all-day event uses UTC midnight; the published date is kept separately.
        sort_time = datetime.combine(parsed_date, time.min, tzinfo=timezone.utc)
        return sort_time, True, parsed_date.isoformat()

    if value.endswith("Z"):
        body = value[:-1]
        parsed = _parse_datetime_body(body).replace(tzinfo=timezone.utc)
        return parsed, False, None

    if re.search(r"[+-]\d{4}$", value):
        parsed = datetime.strptime(value, "%Y%m%dT%H%M%S%z")
        return parsed.astimezone(timezone.utc), False, None

    zone_name = params.get("TZID") or default_timezone
    try:
        zone = ZoneInfo(zone_name)
    except ZoneInfoNotFoundError as exc:
        raise EconomicCalendarError(
            f"Timezone {zone_name!r} is unavailable; install tzdata or check the calendar."
        ) from exc
    parsed = _parse_datetime_body(value).replace(tzinfo=zone)
    return parsed.astimezone(timezone.utc), False, None


def _parse_datetime_body(value: str) -> datetime:
    for fmt in ("%Y%m%dT%H%M%S", "%Y%m%dT%H%M"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    raise EconomicCalendarError(f"Unsupported calendar datetime value: {value!r}")


def _event_relevance(title: str) -> tuple[str, list[str]]:
    value = title.casefold()
    tags: list[str] = []
    if any(term in value for term in ("consumer price", "cpi", "producer price", "ppi", "import and export price")):
        tags.append("التضخم والأسعار")
    if any(term in value for term in ("employment situation", "payroll", "unemployment", "job openings", "jolts")):
        tags.append("سوق العمل")
    if any(term in value for term in ("employment cost", "real earnings", "productivity and costs", "wage")):
        tags.append("الأجور وتكاليف العمل")
    if tags:
        return "قد يكون ذا صلة بسياق الذهب الكلي؛ لا يدل وحده على اتجاه السعر", tags
    return "إصدار رسمي مجدول من BLS؛ صلته بالذهب تحتاج إلى تقييم سياقي", ["بيانات اقتصادية"]


def parse_bls_ics(
    content: str,
    *,
    now_utc: datetime | None = None,
    window_days: int = DEFAULT_WINDOW_DAYS,
    max_events: int = DEFAULT_MAX_EVENTS,
) -> dict[str, Any]:
    """Parse an ICS calendar fixture/text and return upcoming BLS scheduled releases.

    This function has no network dependency; use it for deterministic format tests
    and parse the official calendar only in fetch_bls_calendar().
    """
    if not isinstance(content, str) or not content.strip():
        raise EconomicCalendarError("The BLS calendar response is empty.")
    if len(content.encode("utf-8")) > MAX_CALENDAR_BYTES:
        raise EconomicCalendarError("The calendar exceeds the configured size limit.")
    lines = _unfold_ical_lines(content)
    if not any(line.strip().upper() == "BEGIN:VCALENDAR" for line in lines):
        raise EconomicCalendarError("The response is not an iCalendar document (BEGIN:VCALENDAR missing).")

    now = now_utc or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("now_utc must include a timezone.")
    now = now.astimezone(timezone.utc)
    if isinstance(window_days, bool) or not isinstance(window_days, int) or not 1 <= window_days <= 366:
        raise ValueError("window_days must be an integer from 1 to 366.")
    if isinstance(max_events, bool) or not isinstance(max_events, int) or not 1 <= max_events <= 500:
        raise ValueError("max_events must be an integer from 1 to 500.")

    default_zone = DEFAULT_CALENDAR_TZ
    for line in lines:
        prop = _parse_property(line)
        if prop and prop[0] == "X-WR-TIMEZONE" and prop[2]:
            default_zone = prop[2]
            break

    events: list[dict[str, Any]] = []
    skipped = 0
    in_event = False
    fields: dict[str, tuple[dict[str, str], str]] = {}
    for line in lines:
        upper = line.strip().upper()
        if upper == "BEGIN:VEVENT":
            in_event = True
            fields = {}
            continue
        if upper == "END:VEVENT" and in_event:
            in_event = False
            start_item = fields.get("DTSTART")
            summary_item = fields.get("SUMMARY")
            if not start_item or not summary_item:
                skipped += 1
                continue
            try:
                starts_utc, is_all_day, all_day_date = _parse_ical_datetime(
                    start_item[1], start_item[0], default_zone
                )
            except (ValueError, OverflowError) as exc:
                skipped += 1
                continue
            if starts_utc < now - timedelta(hours=1) or starts_utc > now + timedelta(days=window_days):
                continue
            title = _unescape_ical_text(summary_item[1])
            if not title:
                skipped += 1
                continue
            description = _unescape_ical_text(fields.get("DESCRIPTION", ({}, ""))[1])
            url_value = fields.get("URL", ({}, ""))[1].strip()
            parts = urlsplit(url_value) if url_value else None
            safe_url = (
                url_value if parts and parts.scheme == "https" and
                (parts.hostname == BLS_CALENDAR_HOST or (parts.hostname or "").endswith(".bls.gov"))
                else None
            )
            relevance, tags = _event_relevance(title)
            events.append({
                "title": title,
                "starts_at_utc": None if is_all_day else starts_utc.isoformat(),
                "sort_at_utc": starts_utc.isoformat(),
                "all_day": is_all_day,
                "date": all_day_date,
                "description": description[:1200],
                "url": safe_url,
                "source": "U.S. Bureau of Labor Statistics (BLS)",
                "relevance_note_ar": relevance,
                "topic_tags_ar": tags,
            })
            continue
        if not in_event:
            continue
        prop = _parse_property(line)
        if prop:
            # Preserve the first occurrence of each relevant property.
            fields.setdefault(prop[0], (prop[1], prop[2]))

    events.sort(key=lambda item: item["sort_at_utc"])
    return {
        "status": "ok",
        "source_name": "تقويم الإصدارات الرسمي لمكتب إحصاءات العمل الأمريكي (BLS)",
        "source_url": BLS_CALENDAR_URL,
        "calendar_timezone": default_zone,
        "window_days": window_days,
        "count": min(len(events), max_events),
        "events": events[:max_events],
        "events_parsed_in_window": len(events),
        "events_skipped_missing_or_invalid": skipped,
        "note_ar": (
            "هذا جدول لمواعيد نشر البيانات فقط، وليس القيم الفعلية أو توقعات المحللين أو توصية تداول. "
            "قد لا يشمل كل الأحداث الاقتصادية المؤثرة في الذهب."
        ),
    }


def fetch_bls_calendar(
    *,
    now_utc: datetime | None = None,
    window_days: int = DEFAULT_WINDOW_DAYS,
    max_events: int = DEFAULT_MAX_EVENTS,
    timeout_seconds: float = 12.0,
) -> dict[str, Any]:
    """Fetch the fixed official BLS ICS endpoint on demand with strict resource limits."""
    if not (1 <= float(timeout_seconds) <= 30):
        raise ValueError("timeout_seconds must be between 1 and 30 seconds.")
    request = Request(
        BLS_CALENDAR_URL,
        headers={
            "User-Agent": "GoldIntelligenceLab/0.1 (read-only public schedule reader)",
            "Accept": "text/calendar, text/plain;q=0.9, */*;q=0.1",
        },
        method="GET",
    )
    try:
        with urlopen(request, timeout=float(timeout_seconds)) as response:
            final_url = response.geturl()
            final_parts = urlsplit(final_url)
            if final_parts.scheme != "https" or final_parts.hostname != BLS_CALENDAR_HOST:
                raise EconomicCalendarError("The calendar redirected outside the official BLS HTTPS host.")
            raw = response.read(MAX_CALENDAR_BYTES + 1)
    except HTTPError as exc:
        raise EconomicCalendarError(f"BLS calendar HTTP error: {exc.code}.") from exc
    except URLError as exc:
        raise EconomicCalendarError(f"Could not reach the official BLS calendar: {exc.reason}.") from exc
    except TimeoutError as exc:
        raise EconomicCalendarError("The official BLS calendar request timed out.") from exc
    if len(raw) > MAX_CALENDAR_BYTES:
        raise EconomicCalendarError("The official BLS calendar response exceeded the size limit.")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise EconomicCalendarError("The calendar response was not valid UTF-8.") from exc
    parsed = parse_bls_ics(text, now_utc=now_utc, window_days=window_days, max_events=max_events)
    parsed["fetched_at_utc"] = datetime.now(timezone.utc).isoformat()
    parsed["response_bytes"] = len(raw)
    parsed["response_sha256"] = hashlib.sha256(raw).hexdigest()
    return parsed


__all__ = ["BLS_CALENDAR_URL", "EconomicCalendarError", "fetch_bls_calendar", "parse_bls_ics"]
