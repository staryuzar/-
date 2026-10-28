"""Broker timestamp conversion contracts; these are unit tests, not market simulation."""
import unittest
from datetime import datetime, timezone

from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
from goldlab.market_time import server_timestamp_sequence_to_utc, server_timestamp_to_utc

UTC = timezone.utc

def wall_epoch(value):
    # Encode a server wall-clock reading as if it were UTC, matching observed feed semantics.
    return datetime.fromisoformat(value).replace(tzinfo=UTC).timestamp()

class MarketTimeContracts(unittest.TestCase):
    def test_headway_winter_server_wall_time_maps_to_utc_plus_two(self):
        raw = wall_epoch("2026-10-29T00:43:00")
        converted = server_timestamp_to_utc(raw, "Europe/Athens")
        self.assertEqual(datetime.fromtimestamp(converted, UTC).isoformat(),
                         "2026-10-28T22:43:00+00:00")

    def test_headway_summer_server_wall_time_maps_to_utc_plus_three(self):
        raw = wall_epoch("2026-06-15T00:43:00")
        converted = server_timestamp_to_utc(raw, "Europe/Athens")
        self.assertEqual(datetime.fromtimestamp(converted, UTC).isoformat(),
                         "2026-06-14T21:43:00+00:00")

    def test_utc_profile_is_unchanged(self):
        raw = wall_epoch("2026-10-29T00:43:00")
        self.assertEqual(server_timestamp_to_utc(raw, "UTC"), raw)

    def test_dst_fall_back_is_disambiguated_by_bar_sequence(self):
        raw = [
            wall_epoch("2026-10-25T03:58:00"),
            wall_epoch("2026-10-25T03:59:00"),
            wall_epoch("2026-10-25T03:00:00"),
            wall_epoch("2026-10-25T03:01:00"),
        ]
        converted = server_timestamp_sequence_to_utc(raw, "Europe/Athens", expected_interval_seconds=60)
        self.assertEqual(
            [datetime.fromtimestamp(item, UTC).strftime("%H:%M") for item in converted],
            ["00:58", "00:59", "01:00", "01:01"],
        )
        self.assertTrue(all(b > a for a, b in zip(converted, converted[1:])))

    def test_unknown_timezone_fails_closed(self):
        with self.assertRaises(ValueError):
            server_timestamp_to_utc(wall_epoch("2026-10-29T00:43:00"), "Unknown/Timezone")

    def test_unmappable_or_nonchronological_sequence_is_rejected(self):
        raw = [wall_epoch("2026-10-29T00:02:00"), wall_epoch("2026-10-29T00:01:00")]
        with self.assertRaises(ValueError):
            server_timestamp_sequence_to_utc(raw, "UTC", expected_interval_seconds=60)

if __name__ == "__main__":
    unittest.main()
