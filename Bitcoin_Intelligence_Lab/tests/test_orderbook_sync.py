import unittest

from bitcoinlab.orderbook_sync import BinanceOrderBook


class BinanceOrderBookTests(unittest.TestCase):
    def setUp(self):
        self.book = BinanceOrderBook()
        self.book.apply_snapshot(
            last_update_id=100,
            bids=[["100", "2"], ["99", "1"]],
            asks=[["101", "3"], ["102", "1"]],
        )

    def test_snapshot_starts_synchronized(self):
        result = self.book.top(2)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["last_update_id"], 100)
        self.assertEqual(result["bids"][0], (100.0, 2.0))

    def test_stale_event_is_ignored_without_rewinding_book(self):
        result = self.book.apply_diff(
            first_update_id=90, final_update_id=100,
            bids=[["100", "9"]], asks=[],
        )
        self.assertEqual(result["status"], "stale")
        self.assertEqual(self.book.last_update_id, 100)
        self.assertEqual(self.book.bids[100.0], 2.0)

    def test_first_overlapping_event_bridges_snapshot(self):
        result = self.book.apply_diff(
            first_update_id=99, final_update_id=103,
            bids=[["100", "4"], ["98", "0.5"]],
            asks=[["101", "0"]],
            event_time_ms=1_800_000_000_000,
        )
        self.assertEqual(result["status"], "applied")
        self.assertEqual(self.book.last_update_id, 103)
        self.assertEqual(self.book.bids[100.0], 4.0)
        self.assertNotIn(101.0, self.book.asks)
        self.assertEqual(self.book.last_event_ms, 1_800_000_000_000)

    def test_zero_quantity_removes_level(self):
        result = self.book.apply_diff(
            first_update_id=101, final_update_id=102,
            bids=[["99", "0"]], asks=[],
        )
        self.assertEqual(result["status"], "applied")
        self.assertNotIn(99.0, self.book.bids)

    def test_sequence_gap_forces_resync_and_withholds_book(self):
        result = self.book.apply_diff(
            first_update_id=103, final_update_id=105,
            bids=[["100", "5"]], asks=[],
        )
        self.assertEqual(result["status"], "resync_required")
        self.assertFalse(self.book.synchronized)
        self.assertEqual(self.book.top()["status"], "unavailable")
        # Further deltas cannot repair a broken local book without a new snapshot.
        again = self.book.apply_diff(
            first_update_id=106, final_update_id=106,
            bids=[], asks=[],
        )
        self.assertEqual(again["status"], "resync_required")

    def test_snapshot_repairs_a_gap(self):
        self.book.mark_stale("test_disconnect")
        self.book.apply_snapshot(
            last_update_id=900,
            bids=[["110", "2"]],
            asks=[["111", "3"]],
        )
        self.assertEqual(self.book.top()["last_update_id"], 900)
        result = self.book.apply_diff(
            first_update_id=901, final_update_id=901,
            bids=[["110", "2.5"]], asks=[],
        )
        self.assertEqual(result["status"], "applied")

    def test_crossed_book_after_update_requires_resync(self):
        result = self.book.apply_diff(
            first_update_id=101, final_update_id=101,
            bids=[["101", "1"]], asks=[],
        )
        self.assertEqual(result["status"], "resync_required")
        self.assertEqual(self.book.top()["status"], "unavailable")

    def test_book_metrics_are_derived_from_reconstructed_depth(self):
        result = self.book.metrics(depth=2)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["best_bid"], 100.0)
        self.assertEqual(result["best_ask"], 101.0)
        self.assertGreater(result["spread_bps"], 0)
        self.assertLess(result["imbalance"], 0)

    def test_snapshot_with_one_side_missing_is_rejected(self):
        with self.assertRaises(ValueError):
            self.book.apply_snapshot(
                last_update_id=2, bids=[["100", "1"]], asks=[],
            )

    def test_snapshot_cannot_be_crossed_or_locked(self):
        with self.assertRaises(ValueError):
            self.book.apply_snapshot(
                last_update_id=2,
                bids=[["101", "1"]],
                asks=[["101", "1"]],
            )


if __name__ == "__main__":
    unittest.main()
