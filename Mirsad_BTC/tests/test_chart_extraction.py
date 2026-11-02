from __future__ import annotations

import unittest

import cv2
import numpy as np

from mirsad.engines.chart_extraction import _extract_bars, _select_slot_guided_bars


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


if __name__ == "__main__":
    unittest.main()
