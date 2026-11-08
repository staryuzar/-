from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mirsad.storage import write_json_atomic


class AtomicJsonSnapshotWriterTests(unittest.TestCase):
    def test_transient_windows_sharing_locks_are_retried_and_publish_complete_utf8_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "system_status.json"
            target.write_text('{"old":true}', encoding="utf-8")
            real_replace = Path.replace
            calls = {"count": 0}

            def flaky_replace(source: Path, destination: Path) -> Path:
                calls["count"] += 1
                if calls["count"] < 4:
                    raise PermissionError("simulated Windows sharing violation")
                return real_replace(source, destination)

            with patch.object(Path, "replace", new=flaky_replace), patch(
                "mirsad.storage.time.sleep"
            ):
                write_json_atomic(target, {"status": "READY", "label": "مرصاد"})

            self.assertEqual(calls["count"], 4)
            self.assertEqual(
                json.loads(target.read_text(encoding="utf-8")),
                {"status": "READY", "label": "مرصاد"},
            )
            self.assertEqual(list(Path(directory).glob("*.tmp")), [])

    def test_persistent_lock_preserves_previous_snapshot_and_cleans_temp_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "system_status.json"
            previous = {"status": "PREVIOUS_VALID"}
            target.write_text(json.dumps(previous), encoding="utf-8")
            with patch.object(
                Path, "replace", side_effect=PermissionError("persistent sharing violation")
            ) as replace_mock, patch("mirsad.storage.time.sleep"):
                with self.assertRaises(PermissionError):
                    write_json_atomic(target, {"status": "NEW"})
            self.assertEqual(replace_mock.call_count, 8)
            self.assertEqual(json.loads(target.read_text(encoding="utf-8")), previous)
            self.assertEqual(list(Path(directory).glob("*.tmp")), [])


if __name__ == "__main__":
    unittest.main()

