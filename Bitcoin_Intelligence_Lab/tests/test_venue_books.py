import unittest

from bitcoinlab.venue_books import (
    IncrementalOrderBook,
    apply_bybit_message,
    apply_okx_message,
)


class BybitOrderBookTests(unittest.TestCase):
    def setUp(self):
        self.book = IncrementalOrderBook("Bybit", "BTCUSDT")

    def test_snapshot_then_delta_updates_and_removes_levels(self):
        snapshot = {
            "type": "snapshot", "ts": 1_800_000_000_000,
            "data": {
                "u": 100, "seq": 500,
                "b": [["100", "2"], ["99", "1"]],
                "a": [["101", "3"], ["102", "1"]],
            },
        }
        self.assertEqual(apply_bybit_message(self.book, snapshot)["status"], "snapshot")
        delta = {
            "type": "delta", "ts": 1_800_000_001_000,
            "data": {
                "u": 101, "seq": 501,
                "b": [["100", "4"], ["98", "0.5"]],
                "a": [["101", "0"]],
            },
        }
        result = apply_bybit_message(self.book, delta)
        self.assertEqual(result["status"], "applied")
        self.assertEqual(self.book.bids[100.0], 4.0)
        self.assertNotIn(101.0, self.book.asks)

    def test_duplicate_update_is_ignored(self):
        apply_bybit_message(self.book, {
            "type": "snapshot", "ts": 1_800_000_000_000,
            "data": {"u": 100, "seq": 1, "b": [["100", "1"]], "a": [["101", "1"]]},
        })
        result = apply_bybit_message(self.book, {
            "type": "delta", "ts": 1_800_000_001_000,
            "data": {"u": 100, "seq": 1, "b": [["100", "9"]], "a": []},
        })
        self.assertEqual(result["status"], "stale")
        self.assertEqual(self.book.bids[100.0], 1.0)

    def test_service_restart_update_id_resets_book_only_as_snapshot(self):
        apply_bybit_message(self.book, {
            "type": "snapshot", "ts": 1_800_000_000_000,
            "data": {"u": 200, "seq": 10, "b": [["100", "1"]], "a": [["101", "1"]]},
        })
        result = apply_bybit_message(self.book, {
            "type": "delta", "ts": 1_800_000_001_000,
            "data": {"u": 1, "seq": 1, "b": [["99", "2"]], "a": [["102", "2"]]},
        })
        self.assertEqual(result["status"], "snapshot")
        self.assertEqual(self.book.update_id, 1)
        self.assertNotIn(100.0, self.book.bids)

    def test_delta_before_snapshot_is_not_exposed(self):
        result = apply_bybit_message(self.book, {
            "type": "delta", "ts": 1_800_000_001_000,
            "data": {"u": 101, "seq": 1, "b": [], "a": []},
        })
        self.assertEqual(result["status"], "resync_required")
        self.assertEqual(self.book.top()["status"], "unavailable")


class OKXOrderBookTests(unittest.TestCase):
    def setUp(self):
        self.book = IncrementalOrderBook("OKX", "BTC-USDT")

    def snapshot(self):
        return {
            "action": "snapshot",
            "data": [{
                "ts": "1800000000000",
                "seqId": 1000,
                "bids": [["100", "2", "0", "1"], ["99", "1", "1", "1"]],
                "asks": [["101", "3", "0", "1"], ["102", "1", "1", "1"]],
            }],
        }

    def test_snapshot_then_contiguous_sequence_update(self):
        self.assertEqual(apply_okx_message(self.book, self.snapshot())["status"], "snapshot")
        result = apply_okx_message(self.book, {
            "action": "update",
            "data": [{
                "ts": "1800000000100", "prevSeqId": 1000, "seqId": 1005,
                "bids": [["100", "4", "4", "2"]],
                "asks": [["101", "0", "0", "0"]],
            }],
        })
        self.assertEqual(result["status"], "applied")
        self.assertEqual(self.book.sequence_id, 1005)
        self.assertEqual(self.book.bids[100.0], 4.0)
        self.assertNotIn(101.0, self.book.asks)

    def test_prev_sequence_mismatch_invalidates_book(self):
        apply_okx_message(self.book, self.snapshot())
        result = apply_okx_message(self.book, {
            "action": "update",
            "data": [{
                "ts": "1800000000100", "prevSeqId": 999, "seqId": 1005,
                "bids": [], "asks": [],
            }],
        })
        self.assertEqual(result["status"], "resync_required")
        self.assertEqual(self.book.top()["status"], "unavailable")

    def test_stale_sequence_is_ignored(self):
        apply_okx_message(self.book, self.snapshot())
        result = apply_okx_message(self.book, {
            "action": "update",
            "data": [{
                "ts": "1800000000100", "prevSeqId": 1000, "seqId": 999,
                "bids": [["100", "8", "8", "1"]], "asks": [],
            }],
        })
        self.assertEqual(result["status"], "stale")
        self.assertEqual(self.book.bids[100.0], 2.0)

    def test_checksum_is_not_required_and_sequence_is_authoritative(self):
        message = self.snapshot()
        message["data"][0]["checksum"] = 0
        result = apply_okx_message(self.book, message)
        self.assertEqual(result["status"], "snapshot")
        self.assertEqual(self.book.sequence_id, 1000)

    def test_snapshot_with_crossed_levels_is_rejected(self):
        message = self.snapshot()
        message["data"][0]["bids"] = [["101", "2", "0", "1"]]
        self.assertEqual(apply_okx_message(self.book, message)["status"], "resync_required")


if __name__ == "__main__":
    unittest.main()
