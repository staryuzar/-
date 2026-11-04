from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mirsad import runtime


class RuntimeErrorLogTests(unittest.TestCase):
    def test_errors_append_as_jsonl_and_rotate_previous_log(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            status_path = Path(directory) / "system_status.json"
            with patch.object(runtime, "STATUS_PATH", status_path):
                path = runtime._append_runtime_error(ValueError("first failure"), max_bytes=1)
                self.assertTrue(path.is_file())
                runtime._append_runtime_error(RuntimeError("second failure"), max_bytes=1)

            rotated = status_path.with_name("runtime_errors.jsonl.1")
            current = status_path.with_name("runtime_errors.jsonl")
            self.assertTrue(rotated.is_file())
            first = json.loads(rotated.read_text(encoding="utf-8").splitlines()[0])
            second = json.loads(current.read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual(first["exception_type"], "ValueError")
            self.assertEqual(first["message"], "first failure")
            self.assertEqual(second["exception_type"], "RuntimeError")
            self.assertEqual(second["message"], "second failure")
            self.assertIn("timestamp_utc_ms", second)

    def test_error_message_is_bounded_and_log_does_not_contain_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            status_path = Path(directory) / "system_status.json"
            with patch.object(runtime, "STATUS_PATH", status_path):
                path = runtime._append_runtime_error(ValueError("x" * 2000))
            record = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual(len(record["message"]), 800)
            self.assertNotIn("traceback", record)


if __name__ == "__main__":
    unittest.main()
