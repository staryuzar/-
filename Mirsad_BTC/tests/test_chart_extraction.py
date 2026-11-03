from __future__ import annotations

import unittest

import cv2
import numpy as np

from mirsad.engines.chart_extraction import _extract_bars, _select_slot_guided_bars
from mirsad.engines.native_chart_extraction import extract_native_geometry_guided_bars


class SlotGuidedExtractionTests(unittest.TestCase):
    HEIGHT = 260
    WIDTH = 400
    COUNT = 20
    GREEN = (0, 200, 0)

    def _chart(self, active_slots: list[int]) -> np.ndarray:
        image = np.full((self.HEIGHT, self.WIDTH, 3), 255, dtype=np.uint8)
        slot_width = self.WIDTH / self.COUNT
        for index in active_slots:
            x = int(round((index + 0.5) * slot_width))
            top = 58 + (index % 5) * 3
            bottom = 184 - (index % 4) * 2
            open_y = 116 + (index % 3) * 3
            close_y = 139 + (index % 4) * 2
            cv2.line(image, (x, top), (x, bottom), self.GREEN, 2)
            cv2.rectangle(
                image,
                (x - 3, min(open_y, close_y)),
                (x + 3, max(open_y, close_y)),
                self.GREEN,
                -1,
            )
        # A thick same-palette overlay crosses and joins the candle components.
        # Global connected-component filtering rejects this full-width object.
        cv2.line(image, (0, 126), (self.WIDTH - 1, 126), self.GREEN, 20)
        return image

    def _extract(self, image: np.ndarray) -> tuple[list[dict], dict]:
        diagnostics: dict = {}
        bars = _extract_bars(
            image,
            {
                "plot_left_px": 0,
                "plot_right_px": self.WIDTH,
                "plot_top_px": 0,
                "plot_bottom_px": self.HEIGHT,
                "palette_mode": "green_red",
                "expected_candle_count": self.COUNT,
            },
            diagnostics,
        )
        return bars, diagnostics

    def test_slot_guidance_wins_equal_count_when_body_and_wicks_are_better_separated(self) -> None:
        legacy = [
            {
                "high_y_px": 10, "body_top_y_px": 10,
                "body_bottom_y_px": 30, "low_y_px": 30,
                "body_ratio": 1.0, "colour_purity": 0.90,
            }
            for _ in range(20)
        ]
        slot_guided = [
            {
                "high_y_px": 10, "body_top_y_px": 15,
                "body_bottom_y_px": 25, "low_y_px": 30,
                "body_ratio": 0.5, "colour_purity": 0.95,
            }
            for _ in range(20)
        ]
        selected, diagnostics = _select_slot_guided_bars(
            legacy,
            slot_guided,
            expected_candle_count=20,
            slot_mean_purity=0.95,
        )
        self.assertIs(selected, slot_guided)
        self.assertTrue(diagnostics["body_geometry_improves"])
        self.assertTrue(diagnostics["adopted"])

    def test_slot_guidance_does_not_replace_equal_count_without_better_geometry(self) -> None:
        legacy = [
            {
                "high_y_px": 10, "body_top_y_px": 15,
                "body_bottom_y_px": 25, "low_y_px": 30,
                "body_ratio": 0.5, "colour_purity": 0.90,
            }
            for _ in range(20)
        ]
        slot_guided = [
            dict(bar) for bar in legacy
        ]
        selected, diagnostics = _select_slot_guided_bars(
            legacy,
            slot_guided,
            expected_candle_count=20,
            slot_mean_purity=0.95,
        )
        self.assertIs(selected, legacy)
        self.assertFalse(diagnostics["body_geometry_improves"])
        self.assertFalse(diagnostics["adopted"])

    def test_slot_guidance_recovers_candles_joined_by_same_colour_overlay(self) -> None:
        bars, diagnostics = self._extract(self._chart(list(range(self.COUNT))))
        self.assertEqual(len(bars), self.COUNT)
        self.assertEqual(diagnostics["segmentation_mode"], "expected_slot_hint")
        self.assertTrue(all(bar["palette_mode"] == "slot_guided" for bar in bars))
        self.assertEqual(
            [bar["slot_index"] for bar in bars],
            list(range(self.COUNT)),
        )

    def test_empty_slots_are_not_fabricated_from_overlay_line(self) -> None:
        active_slots = list(range(0, self.COUNT, 2))
        bars, diagnostics = self._extract(self._chart(active_slots))
        self.assertEqual(len(bars), len(active_slots))
        self.assertEqual(
            [bar["slot_index"] for bar in bars],
            active_slots,
        )
        slot_info = diagnostics["slot_guided_extraction"]
        self.assertEqual(slot_info["occupied_slots"], len(active_slots))
        self.assertTrue(slot_info["adopted"])

    def test_narrow_candle_body_is_separated_from_one_pixel_wicks(self) -> None:
        image = np.full((self.HEIGHT, self.WIDTH, 3), 255, dtype=np.uint8)
        slot_width = self.WIDTH / self.COUNT
        for index in range(self.COUNT):
            x = int(round((index + 0.5) * slot_width))
            top = 55 + (index % 4) * 2
            bottom = 190 - (index % 3) * 2
            cv2.line(image, (x, top), (x, bottom), self.GREEN, 1)
            cv2.rectangle(image, (x - 1, 105), (x + 1, 140), self.GREEN, -1)

        bars, diagnostics = self._extract(image)
        self.assertEqual(len(bars), self.COUNT)
        self.assertTrue(
            all(bar["body_top_y_px"] > bar["high_y_px"] for bar in bars),
            msg=repr(diagnostics),
        )
        self.assertTrue(
            all(bar["body_bottom_y_px"] < bar["low_y_px"] for bar in bars),
            msg=repr(diagnostics),
        )

    def test_legacy_projection_is_retained_when_slot_hint_does_not_improve_count(self) -> None:
        # No expected count is not required for the fallback contract; this
        # test passes an approximate count but a sparse chart to force abstention.
        image = np.full((self.HEIGHT, self.WIDTH, 3), 255, dtype=np.uint8)
        for index in range(4):
            x = 30 + index * 90
            cv2.line(image, (x, 70), (x, 190), self.GREEN, 2)
            cv2.rectangle(image, (x - 3, 120), (x + 3, 140), self.GREEN, -1)
        bars, diagnostics = self._extract(image)
        self.assertEqual(diagnostics["segmentation_mode"], "projection_groups")
        self.assertFalse(diagnostics["slot_guided_extraction"]["adopted"])
        self.assertEqual(len(bars), 4)


class NativeGeometryGuidedExtractionTests(unittest.TestCase):
    HEIGHT = 280
    WIDTH = 520
    COUNT = 20
    GREEN = (0, 200, 0)
    RED = (0, 0, 220)

    def _centers(self) -> list[dict]:
        return [
            {"slot_index": i, "x_px": 18.0 + i * 24.0 + (i % 3) * 1.5}
            for i in range(self.COUNT)
        ]

    def _chart(self, active: list[int]) -> np.ndarray:
        image = np.full((self.HEIGHT, self.WIDTH, 3), 255, dtype=np.uint8)
        centers = self._centers()
        for i in active:
            x = int(round(centers[i]["x_px"]))
            high, low = 54 + (i % 5) * 4, 204 - (i % 4) * 3
            opened = 112 + (i % 3) * 3
            closed = opened - 24 if i % 2 == 0 else opened + 24
            colour = self.GREEN if i % 2 == 0 else self.RED
            cv2.line(image, (x, high), (x, low), colour, 2)
            cv2.rectangle(image, (x - 3, min(opened, closed)),
                          (x + 3, max(opened, closed)), colour, -1)
        # Long horizontal and off-centre traces are not candle evidence.
        cv2.line(image, (0, 24), (self.WIDTH - 1, 24), self.GREEN, 1)
        for item in centers:
            x = int(round(item["x_px"] + 8.0))
            if x < self.WIDTH:
                cv2.line(image, (x, 72), (x, 196), self.GREEN, 1)
        return image

    def test_native_centres_recover_irregularly_spaced_pixel_candles(self) -> None:
        active = [i for i in range(self.COUNT) if i not in {4, 12}]
        diagnostics: dict = {}
        bars = _extract_bars(
            self._chart(active),
            {
                "plot_left_px": 0, "plot_right_px": self.WIDTH,
                "plot_top_px": 0, "plot_bottom_px": self.HEIGHT,
                "palette_mode": "green_red",
                "expected_candle_count": self.COUNT,
                "native_geometry_slot_centers": self._centers(),
            },
            diagnostics,
        )
        self.assertEqual(
            diagnostics["segmentation_mode"],
            "mt5_native_geometry_guided",
            msg=repr(diagnostics.get("native_geometry_guided_extraction")),
        )
        native = diagnostics["native_geometry_guided_extraction"]
        self.assertTrue(native["adopted"])
        self.assertGreaterEqual(len(bars), len(active) - 2)
        hints = [bar["native_slot_hint"] for bar in bars]
        self.assertEqual(len(hints), len(set(hints)))
        self.assertTrue(set(hints).issubset(set(active)))
        self.assertNotIn("slot_index", bars[0])
        self.assertTrue(all(bar["native_center_residual_px"] <= 4.5 for bar in bars))
        self.assertFalse(native["mapping_verified"])
        self.assertFalse(native["decision_eligible"])

    def test_native_windows_reject_offcentre_lines_and_empty_slots(self) -> None:
        image = np.full((self.HEIGHT, self.WIDTH, 3), 255, dtype=np.uint8)
        centers = self._centers()
        # Each trace sits outside the native centre tolerance; the horizontal
        # line has no candle body and is wider than one slot.
        for item in centers:
            x = int(round(item["x_px"] + 8.0))
            if x < self.WIDTH:
                cv2.line(image, (x, 70), (x, 205), self.GREEN, 1)
        cv2.line(image, (0, 140), (self.WIDTH - 1, 140), self.GREEN, 18)
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
        from mirsad.engines.chart_extraction import _hue_mask, PALETTE_PRESETS
        palette = PALETTE_PRESETS["green_red"]
        bullish = _hue_mask(hsv, palette["bullish"]) > 0
        bearish = _hue_mask(hsv, palette["bearish"]) > 0
        bars, diagnostics = extract_native_geometry_guided_bars(
            bullish, bearish, native_slot_centers=centers,
            plot_left=0, plot_top=0,
        )
        self.assertEqual(bars, [])
        self.assertEqual(diagnostics["occupied_slots"], 0)
        self.assertFalse(diagnostics["decision_eligible"])
        self.assertFalse(diagnostics["mapping_verified"])


class AutomaticPaletteInferenceTests(unittest.TestCase):
    HEIGHT = 260
    WIDTH = 400
    COUNT = 20

    PALETTES = {
        "green_red": ((0, 200, 0), (0, 0, 220)),
        "blue_orange": ((220, 80, 0), (0, 140, 255)),
        "teal_magenta": ((180, 180, 0), (180, 0, 180)),
    }

    def _chart(self, mode: str) -> np.ndarray:
        bullish_bgr, bearish_bgr = self.PALETTES[mode]
        image = np.full((self.HEIGHT, self.WIDTH, 3), 255, dtype=np.uint8)
        slot_width = self.WIDTH / self.COUNT
        for index in range(self.COUNT):
            x = int(round((index + 0.5) * slot_width))
            upper = 52 + (index % 5) * 4
            lower = 194 - (index % 4) * 3
            bullish = index % 2 == 0
            colour = bullish_bgr if bullish else bearish_bgr
            open_y = 116 + (index % 3) * 3
            close_y = open_y - 18 if bullish else open_y + 18
            cv2.line(image, (x, upper), (x, lower), colour, 2)
            cv2.rectangle(
                image,
                (x - 3, min(open_y, close_y)),
                (x + 3, max(open_y, close_y)),
                colour,
                -1,
            )
        return image

    def test_auto_palette_infers_green_red_blue_orange_and_teal_magenta(self) -> None:
        for expected_mode in self.PALETTES:
            with self.subTest(palette=expected_mode):
                diagnostics: dict = {}
                bars = _extract_bars(
                    self._chart(expected_mode),
                    {
                        "plot_left_px": 0,
                        "plot_right_px": self.WIDTH,
                        "plot_top_px": 0,
                        "plot_bottom_px": self.HEIGHT,
                        "palette_mode": "auto",
                        "expected_candle_count": self.COUNT,
                    },
                    diagnostics,
                )
                inference = diagnostics["palette_inference"]
                self.assertEqual(inference["status"], "INFERRED", msg=repr(inference))
                self.assertEqual(inference["selected_mode"], expected_mode, msg=repr(inference))
                self.assertGreaterEqual(len(bars), 18, msg=repr(diagnostics))
                self.assertEqual(diagnostics["selected_palette_mode"], expected_mode)
                self.assertTrue(all(bar["palette_mode"] == expected_mode for bar in bars))

    def test_auto_palette_falls_back_when_no_candle_like_components_exist(self) -> None:
        image = np.full((self.HEIGHT, self.WIDTH, 3), 245, dtype=np.uint8)
        diagnostics: dict = {}
        bars = _extract_bars(
            image,
            {
                "plot_left_px": 0,
                "plot_right_px": self.WIDTH,
                "plot_top_px": 0,
                "plot_bottom_px": self.HEIGHT,
                "palette_mode": "auto",
                "expected_candle_count": self.COUNT,
            },
            diagnostics,
        )
        self.assertEqual(bars, [])
        self.assertEqual(
            diagnostics["palette_inference"]["status"],
            "FALLBACK_NO_RELIABLE_PALETTE",
        )
        self.assertEqual(diagnostics["selected_palette_mode"], "green_red")


if __name__ == "__main__":
    unittest.main()
