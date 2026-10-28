"""BLS ICS parser contracts. These are calendar-format fixtures, not market data or trading simulations."""
import unittest
from datetime import datetime, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))

from goldlab.economic_calendar import (
    BLS_CALENDAR_URL,
    EconomicCalendarError,
    fetch_bls_calendar,
    parse_bls_ics,
)


ICS_FIXTURE = """BEGIN:VCALENDAR
VERSION:2.0
X-WR-TIMEZONE:America/New_York
BEGIN:VEVENT
UID:cpi-example@bls.gov
DTSTART;TZID=America/New_York:20261030T083000
SUMMARY:Consumer Price Index\\, October 2026
DESCRIPTION:Official release\\nSchedule only
URL:https://www.bls.gov/schedule/news_release/cpi.htm
END:VEVENT
BEGIN:VEVENT
UID:all-day-example@bls.gov
DTSTART;VALUE=DATE:20261031
SUMMARY:Calendar Maintenance Day
END:VEVENT
BEGIN:VEVENT
UID:bad-event@bls.gov
SUMMARY:Missing start is ignored
END:VEVENT
END:VCALENDAR
"""


class BLSEconomicCalendarContractTests(unittest.TestCase):
    def test_parses_local_timezone_and_escaped_ical_text(self):
        parsed = parse_bls_ics(
            ICS_FIXTURE,
            now_utc=datetime(2026, 10, 28, tzinfo=timezone.utc),
            window_days=30,
        )
        self.assertEqual(parsed["status"], "ok")
        self.assertEqual(parsed["count"], 2)
        event = parsed["events"][0]
        self.assertEqual(event["title"], "Consumer Price Index, October 2026")
        self.assertEqual(event["starts_at_utc"], "2026-10-30T12:30:00+00:00")
        self.assertEqual(event["url"], "https://www.bls.gov/schedule/news_release/cpi.htm")
        self.assertIn("التضخم والأسعار", event["topic_tags_ar"])

    def test_legacy_us_eastern_timezone_alias_is_normalized(self):
        legacy_ics = ICS_FIXTURE.replace("America/New_York", "US-Eastern")
        parsed = parse_bls_ics(
            legacy_ics,
            now_utc=datetime(2026, 10, 28, tzinfo=timezone.utc),
            window_days=30,
        )
        event = parsed["events"][0]
        self.assertEqual(event["starts_at_utc"], "2026-10-30T12:30:00+00:00")

    def test_all_day_events_remain_marked_as_all_day(self):
        parsed = parse_bls_ics(
            ICS_FIXTURE,
            now_utc=datetime(2026, 10, 28, tzinfo=timezone.utc),
            window_days=30,
        )
        all_day = next(event for event in parsed["events"] if event["all_day"])
        self.assertEqual(all_day["date"], "2026-10-31")
        self.assertIsNone(all_day["starts_at_utc"])

    def test_expired_events_are_filtered_and_missing_start_is_counted(self):
        parsed = parse_bls_ics(
            ICS_FIXTURE,
            now_utc=datetime(2026, 11, 1, tzinfo=timezone.utc),
            window_days=30,
        )
        self.assertEqual(parsed["count"], 0)
        self.assertEqual(parsed["events_skipped_missing_or_invalid"], 1)

    def test_invalid_calendar_is_rejected(self):
        with self.assertRaises(EconomicCalendarError):
            parse_bls_ics("not a calendar")

    def test_only_official_fixed_source_is_configured(self):
        self.assertEqual(BLS_CALENDAR_URL, "https://www.bls.gov/schedule/news_release/bls.ics")
        source = (ROOT / "python" / "goldlab" / "economic_calendar.py").read_text(encoding="utf-8")
        self.assertNotIn('input("API', source)
        self.assertIn("MAX_CALENDAR_BYTES", source)
        self.assertIn("timeout=", source)
        self.assertIn("final_parts.hostname != BLS_CALENDAR_HOST", source)


if __name__ == "__main__":
    unittest.main()
