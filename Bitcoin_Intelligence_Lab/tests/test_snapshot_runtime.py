import json
import os
import tempfile
import unittest
from unittest.mock import patch
from datetime import datetime, timedelta, timezone
from pathlib import Path

from bitcoinlab.snapshot_runtime import (
    SNAPSHOT_SCHEMA,
    SnapshotUnavailableError,
    _consume_refresh_request,
    _consume_refresh_request_payload,
    read_latest_snapshot,
    request_snapshot_refresh,
    run_snapshot_service,
)


class SnapshotRuntimeTests(unittest.TestCase):
    def report(self, observed=None):
        timestamp = observed or datetime.now(timezone.utc)
        return {
            "as_of_utc": timestamp.isoformat(),
            "status": "partial",
            "decision": {"action": "HOLD", "score": None, "blockers": ["test"]},
        }

    def test_service_publishes_one_atomic_shared_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "data" / "live_snapshot.json"
            status = root / "data" / "service_status.json"
            result = run_snapshot_service(
                interval_seconds=30,
                snapshot_path=output,
                status_path=status,
                refresh_request_path=root / "refresh.json",
                builder=lambda **_kwargs: self.report(),
                once=True,
            )
            self.assertEqual(result["status"], "published")
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(payload["schema"], SNAPSHOT_SCHEMA)
            self.assertEqual(payload["snapshot"]["decision"]["action"], "HOLD")
            service_state = json.loads(status.read_text(encoding="utf-8"))
            self.assertEqual(service_state["status"], "healthy")
            self.assertFalse(output.with_suffix(".json.service.lock").exists())

    def test_dashboard_refresh_request_selects_market_and_timeframe_for_shared_service(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            request_path = root / "refresh.json"
            output = root / "live_snapshot.json"
            selected = {}
            request_snapshot_refresh(
                request_path, symbol="BTCUSDC", interval="5m",
            )

            def builder(*, symbol, interval):
                selected["symbol"] = symbol
                selected["interval"] = interval
                return self.report()

            result = run_snapshot_service(
                interval_seconds=30,
                snapshot_path=output,
                status_path=root / "status.json",
                refresh_request_path=request_path,
                builder=builder,
                once=True,
            )
            self.assertEqual(result["status"], "published")
            self.assertEqual(selected, {"symbol": "BTCUSDC", "interval": "5m"})

    def test_failed_refresh_preserves_last_successful_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "live_snapshot.json"
            status = root / "status.json"
            request = root / "refresh.json"
            first = run_snapshot_service(
                interval_seconds=30, snapshot_path=output,
                status_path=status, refresh_request_path=request,
                builder=lambda **_kwargs: self.report(), once=True,
            )
            original = output.read_text(encoding="utf-8")
            second = run_snapshot_service(
                interval_seconds=30, snapshot_path=output,
                status_path=status, refresh_request_path=request,
                builder=lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("feed outage")),
                once=True,
            )
            self.assertEqual(first["status"], "published")
            self.assertEqual(second["status"], "cycle_error")
            self.assertEqual(output.read_text(encoding="utf-8"), original)
            service_state = json.loads(status.read_text(encoding="utf-8"))
            self.assertEqual(service_state["status"], "degraded")
            self.assertIsNotNone(service_state["last_success_utc"])

    def test_reader_rejects_missing_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SnapshotUnavailableError):
                read_latest_snapshot(Path(tmp) / "missing.json")

    def test_reader_rejects_stale_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "live_snapshot.json"
            old = self.report(datetime.now(timezone.utc) - timedelta(seconds=120))
            path.write_text(
                json.dumps({"schema": SNAPSHOT_SCHEMA, "snapshot": old}),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(SnapshotUnavailableError, "stale"):
                read_latest_snapshot(path, max_age_seconds=90)

    def test_reader_returns_fresh_shared_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "live_snapshot.json"
            report = self.report()
            path.write_text(
                json.dumps({"schema": SNAPSHOT_SCHEMA, "snapshot": report}),
                encoding="utf-8",
            )
            result = read_latest_snapshot(path)
            self.assertEqual(result["decision"]["action"], "HOLD")

    def test_dashboard_refresh_request_is_consumed_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "refresh.json"
            request = request_snapshot_refresh(path, reason="operator button")
            self.assertEqual(request["schema"], "BTCIL-SNAPSHOT-REFRESH1")
            self.assertTrue(_consume_refresh_request(path))
            self.assertFalse(path.exists())
            self.assertFalse(_consume_refresh_request(path))

    def test_refresh_arriving_during_request_claim_is_preserved_for_next_cycle(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "refresh.json"
            first = request_snapshot_refresh(path, symbol="BTCUSDT", interval="1m")
            real_replace = os.replace

            def replace_then_enqueue(source, destination):
                real_replace(source, destination)
                if str(destination).endswith(".processing"):
                    second = {
                        "schema": "BTCIL-SNAPSHOT-REFRESH1",
                        "request_id": "second-click",
                        "requested_at_utc": datetime.now(timezone.utc).isoformat(),
                        "reason": "simulated concurrent dashboard click",
                        "symbol": "BTCUSDC",
                        "interval": "5m",
                    }
                    temporary = path.with_name("refresh.new")
                    temporary.write_text(json.dumps(second), encoding="utf-8")
                    real_replace(temporary, path)

            with patch("bitcoinlab.snapshot_runtime.os.replace", side_effect=replace_then_enqueue):
                consumed_first = _consume_refresh_request_payload(path)

            self.assertEqual(consumed_first["request_id"], first["request_id"])
            self.assertTrue(path.exists())
            consumed_second = _consume_refresh_request_payload(path)
            self.assertEqual(consumed_second["request_id"], "second-click")
            self.assertEqual(consumed_second["symbol"], "BTCUSDC")
            self.assertFalse(path.exists())

    def test_invalid_refresh_request_is_removed_and_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "refresh.json"
            path.write_text(json.dumps(["invalid"]), encoding="utf-8")
            self.assertFalse(_consume_refresh_request(path))
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
