from __future__ import annotations

import inspect
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from mirsad.engines.mt5_chart_pipeline import (
    Engine2MT5ChartImagePipeline,
    analyze_mt5_observer_chart,
)


class Engine2MT5ChartImagePipelineTests(unittest.TestCase):
    def test_reads_the_existing_common_files_observer_image_folder(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            common_files = Path(directory) / "Terminal" / "Common" / "Files"
            inbox = Mock()
            inbox.inspect_latest.return_value = {
                "status": "READY_FOR_ENGINE_2_VALIDATION",
                "capture_id": "capture-folder-test",
            }
            with patch(
                "mirsad.engines.mt5_chart_pipeline.MT5ChartObserverInbox.from_common_files",
                return_value=inbox,
            ) as factory:
                result = Engine2MT5ChartImagePipeline(
                    common_files=common_files,
                ).inspect_latest(now_ms=1_800_000_000_000)

            factory.assert_called_once_with(str(common_files))
            inbox.inspect_latest.assert_called_once_with(now_ms=1_800_000_000_000)
            self.assertEqual(result["capture_id"], "capture-folder-test")
            self.assertEqual(result["pipeline_component"], "engine2_mt5_chart_image_pipeline")
            self.assertEqual(
                Path(result["image_directory"]),
                common_files / "MirsadBTC" / "observer" / "images",
            )

    def test_missing_capture_allows_manual_chart_fallback(self) -> None:
        pipeline = Engine2MT5ChartImagePipeline(common_files="C:/MT5/Common/Files")
        self.assertIsNone(pipeline.analyze_capture(
            {"status": "WAITING_FOR_CAPTURE"}, {}
        ))

    def test_engine2_observer_pipeline_has_no_engine1_market_input(self) -> None:
        self.assertNotIn("market", inspect.signature(analyze_mt5_observer_chart).parameters)
        self.assertNotIn("market", inspect.signature(
            Engine2MT5ChartImagePipeline.analyze_capture
        ).parameters)

    def test_stale_or_invalid_newest_capture_blocks_fallback(self) -> None:
        analyzer = Mock()
        pipeline = Engine2MT5ChartImagePipeline(
            common_files="C:/MT5/Common/Files",
            image_analyzer=analyzer,
        )
        result = pipeline.analyze_capture(
            {"status": "STALE", "reason": "newest capture is old"},
            {},
        )
        analyzer.assert_not_called()
        self.assertEqual(result["status"], "OBSERVER_INBOX_VALIDATION_BLOCKED")
        self.assertFalse(result["decision_eligible"])
        self.assertEqual(result["observer_block_reason"], "newest capture is old")


if __name__ == "__main__":
    unittest.main()
