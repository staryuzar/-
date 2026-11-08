from __future__ import annotations

import inspect
import unittest
from pathlib import Path

import mirsad.runtime as runtime
from mirsad.engines.mt5_chart_candles import MT5ChartCandleHistory


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class MT5NativeObserverContractTests(unittest.TestCase):
    def test_live_runtime_has_no_legacy_image_observer_dependency(self) -> None:
        source = Path(runtime.__file__).read_text(encoding="utf-8")
        self.assertNotIn("mirsad.engines.mt5_observer", source)
        self.assertNotIn("_inspect_mt5_chart_observer", source)
        self.assertNotIn("_analyze_mt5_observer_chart", source)
        self.assertNotIn("analyze_chart_image", source)

    def test_engine2_native_candle_reader_accepts_only_bridge_identity(self) -> None:
        parameters = inspect.signature(MT5ChartCandleHistory.collect).parameters
        self.assertEqual(set(parameters), {"self", "bridge"})
        self.assertNotIn("image", parameters)
        self.assertNotIn("chart", parameters)

    def test_mt5_observer_publishes_native_feeds_without_image_capture_code(self) -> None:
        source = (PROJECT_ROOT / "mt5" / "Mirsad_ChartObserver.mq5").read_text(encoding="utf-8")
        for forbidden in (
            "InpEnableImageCapture", "ChartScreenShot", "g_image_root",
            "BeginCapture", "BuildCapturePayload", "observer_status.json",
            "capture_", ".png", "screenshot",
        ):
            self.assertNotIn(forbidden.lower(), source.lower())
        self.assertIn("market.json", source)
        self.assertIn("candles.json", source)
        self.assertIn("indicators.json", source)
        self.assertIn("CopyRates(", source)
        self.assertIn("CopyBuffer(", source)
        self.assertNotRegex(source, r"(?i)\b(OrderSend|OrderSendAsync|CTrade|PositionOpen|PositionClose)\s*\(")



if __name__ == "__main__":
    unittest.main()

