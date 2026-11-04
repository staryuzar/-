from __future__ import annotations

import ast
import unittest
from pathlib import Path

import mirsad.runtime as runtime


class NativeEngine2RuntimeContractTests(unittest.TestCase):
    def test_live_runtime_has_no_image_pipeline_imports_or_calls(self) -> None:
        source_path = Path(runtime.__file__)
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        forbidden_imports = {
            "PIL", "cv2", "rapidocr",
            "mirsad.engines.chart",
            "mirsad.engines.mt5_chart_pipeline",
        }
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
        self.assertFalse(forbidden_imports.intersection(imported))
        names = {
            node.id for node in ast.walk(tree)
            if isinstance(node, ast.Name)
        }
        self.assertNotIn("analyze_chart_image", names)
        self.assertNotIn("Engine2MT5ChartImagePipeline", names)
        self.assertFalse(hasattr(runtime, "_analyze_mt5_observer_chart"))

    def test_engine2_and_engine3_runtime_path_is_native_mt5_data_only(self) -> None:
        source = Path(runtime.__file__).read_text(encoding="utf-8")
        self.assertIn("MT5ChartCandleHistory().collect(bridge=bridge)", source)
        self.assertIn("analyze_mt5_native_price_action(candle_history)", source)
        self.assertIn("IndicatorsEngine().analyze(candle_history)", source)
        compact = source.replace(" ", "")
        self.assertIn('"engine_2_chart_images_to_engine_4":False', compact)
        self.assertIn('"engine_2_candles_to_engine_3":True', compact)

    def test_image_capture_is_not_a_runtime_readiness_gate(self) -> None:
        source = Path(runtime.__file__).read_text(encoding="utf-8")
        compact = source.replace(" ", "")
        self.assertIn('"engine_2_visual_analysis"', source)
        self.assertIn('"required_for_native_direction_analysis":False', compact)
        self.assertIn('"engine_2_visual_chart":"OPTIONAL_DISABLED"', compact)


if __name__ == "__main__":
    unittest.main()
