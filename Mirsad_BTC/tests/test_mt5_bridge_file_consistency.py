from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest.mock import patch

from mirsad.engines.mt5_bridge import _read_json_array, _read_object


class MT5BridgeSnapshotReaderTests(unittest.TestCase):
    def test_object_reader_retries_transient_partial_and_locked_snapshots(self) -> None:
        valid = '{"schema":"MIR1","terminal_connected":true}'
        with patch.object(
            Path,
            "read_text",
            side_effect=[
                json.JSONDecodeError("partial", "{", 1),
                OSError("sharing violation during atomic replacement"),
                valid,
            ],
        ), patch("mirsad.engines.mt5_bridge.time.sleep"):
            payload = _read_object(Path("status.json"))
        self.assertEqual(payload["schema"], "MIR1")
        self.assertTrue(payload["terminal_connected"])

    def test_array_reader_retries_without_treating_partial_positions_as_empty(self) -> None:
        with patch.object(
            Path,
            "read_text",
            side_effect=[
                json.JSONDecodeError("partial", "[", 1),
                '[{"ticket":123,"position_id":123}]',
            ],
        ), patch("mirsad.engines.mt5_bridge.time.sleep"):
            payload = _read_json_array(Path("positions.json"))
        self.assertEqual(payload, [{"ticket": 123, "position_id": 123}])

    def test_persistently_malformed_status_never_becomes_a_connected_object(self) -> None:
        with patch.object(
            Path,
            "read_text",
            side_effect=[json.JSONDecodeError("partial", "{", 1)] * 6,
        ), patch("mirsad.engines.mt5_bridge.time.sleep"):
            payload = _read_object(Path("status.json"))
        self.assertEqual(payload, {})


if __name__ == "__main__":
    unittest.main()
