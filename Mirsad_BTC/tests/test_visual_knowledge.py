from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from mirsad.engines.visual_knowledge import (
    CANDLE_PATTERN_CATALOG,
    KNOWLEDGE_VERSION,
    MARKET_STRUCTURE_CATALOG,
    record_pattern_observations,
    record_structure_observations,
    seed_visual_knowledge,
    visual_knowledge_summary,
)
from mirsad.storage import connect


class VisualKnowledgeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp.name) / "visual-knowledge.sqlite3"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_catalogs_are_versioned_and_do_not_claim_empirical_validation(self) -> None:
        self.assertGreaterEqual(len(CANDLE_PATTERN_CATALOG), 20)
        self.assertGreaterEqual(len(MARKET_STRUCTURE_CATALOG), 20)
        self.assertEqual(KNOWLEDGE_VERSION, "1.1.0")
        self.assertTrue(all(x["empirical_status"] == "UNVALIDATED" for x in CANDLE_PATTERN_CATALOG))
        self.assertTrue(all(x["empirical_status"] == "UNVALIDATED" for x in MARKET_STRUCTURE_CATALOG))

    def test_seed_is_idempotent_and_populates_both_catalog_tables(self) -> None:
        first = seed_visual_knowledge(str(self.db_path))
        second = seed_visual_knowledge(str(self.db_path))
        self.assertEqual(first["status"], "READY")
        self.assertEqual(first["version"], KNOWLEDGE_VERSION)
        self.assertEqual(first["candle_pattern_definitions"], len(CANDLE_PATTERN_CATALOG))
        self.assertEqual(first["market_structure_definitions"], len(MARKET_STRUCTURE_CATALOG))
        self.assertEqual(second["candle_pattern_definitions"], first["candle_pattern_definitions"])

        conn = connect(self.db_path)
        try:
            patterns = conn.execute("SELECT COUNT(*) FROM visual_candle_pattern_knowledge").fetchone()[0]
            structures = conn.execute("SELECT COUNT(*) FROM visual_structure_knowledge").fetchone()[0]
            self.assertEqual(patterns, len(CANDLE_PATTERN_CATALOG))
            self.assertEqual(structures, len(MARKET_STRUCTURE_CATALOG))
        finally:
            conn.close()

    def test_pattern_observations_are_idempotent_and_unknown_ids_are_rejected(self) -> None:
        seed_visual_knowledge(str(self.db_path))
        event = {
            "pattern_id": "bullish_engulfing", "index": 12,
            "start_index": 11, "end_index": 12,
            "confirmation_state": "CANDIDATE_ONLY",
        }
        first = record_pattern_observations(
            "chart-fingerprint", "BTCUSDT", "15m", [event], db_path=str(self.db_path)
        )
        second = record_pattern_observations(
            "chart-fingerprint", "BTCUSDT", "15m", [event], db_path=str(self.db_path)
        )
        self.assertEqual(first, 1)
        self.assertEqual(second, 1)
        with self.assertRaisesRegex(ValueError, "Unknown candle pattern"):
            record_pattern_observations(
                "chart-fingerprint", "BTCUSDT", "15m",
                [{"pattern_id": "invented_pattern", "index": 1}],
                db_path=str(self.db_path),
            )

        conn = connect(self.db_path)
        try:
            rows = conn.execute("SELECT COUNT(*) FROM visual_pattern_observations").fetchone()[0]
            self.assertEqual(rows, 1)
        finally:
            conn.close()

    def test_structure_observations_are_persisted_and_validated(self) -> None:
        seed_visual_knowledge(str(self.db_path))
        saved = record_structure_observations(
            "chart-fingerprint", "BTCUSDT", "1h",
            [{
                "structure_id": "pivot_high", "index": 20,
                "confirmed": True, "level_price": 71000.0,
            }],
            db_path=str(self.db_path),
        )
        self.assertEqual(saved, 1)
        with self.assertRaisesRegex(ValueError, "Unknown market structure"):
            record_structure_observations(
                "chart-fingerprint", "BTCUSDT", "1h",
                [{"structure_id": "unknown", "index": 20}],
                db_path=str(self.db_path),
            )
        summary = visual_knowledge_summary(str(self.db_path))
        self.assertEqual(summary["candle_pattern_definitions"], len(CANDLE_PATTERN_CATALOG))
        self.assertEqual(summary["market_structure_definitions"], len(MARKET_STRUCTURE_CATALOG))
        self.assertEqual(summary["structure_observations"], 1)
        self.assertEqual(summary["validated_evaluation_records"], 0)
        self.assertEqual(summary["empirical_status"], "UNVALIDATED")


if __name__ == "__main__":
    unittest.main()
