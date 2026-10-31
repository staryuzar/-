import json
import tempfile
import unittest
from pathlib import Path

from bitcoinlab.design_tokens import (
    FALLBACK_COLORS,
    build_css_variables,
    load_dashboard_colors,
)


class DashboardDesignTokenTests(unittest.TestCase):
    def test_loads_all_figma_authored_colors(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "tokens.json"
            raw = {
                "Canvas/Background": "#0B1220",
                "Surface/Default": "#111C2D",
                "Surface/Raised": "#17253A",
                "Surface/Subtle": "#1E2E45",
                "Border/Default": "#2B3C54",
                "Text/Primary": "#F4F7FB",
                "Text/Secondary": "#A9B8CC",
                "Text/Muted": "#7E91AA",
                "Signal/Bull": "#2CCB9A",
                "Signal/Bear": "#F16D75",
                "Signal/Warning": "#EAB85C",
                "Signal/Info": "#65A8E8",
            }
            path.write_text(json.dumps({"colors": raw}), encoding="utf-8")
            colors, warning = load_dashboard_colors(path)
            self.assertIsNone(warning)
            self.assertEqual(len(colors), len(FALLBACK_COLORS))
            self.assertEqual(colors["canvas"], "#0B1220")

    def test_missing_token_uses_safe_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "tokens.json"
            path.write_text(json.dumps({"colors": {"Canvas/Background": "#000000"}}), encoding="utf-8")
            colors, warning = load_dashboard_colors(path)
            self.assertEqual(colors, FALLBACK_COLORS)
            self.assertIn("missing or invalid", warning)

    def test_malformed_json_uses_safe_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "tokens.json"
            path.write_text("{broken", encoding="utf-8")
            colors, warning = load_dashboard_colors(path)
            self.assertEqual(colors, FALLBACK_COLORS)
            self.assertTrue(warning.startswith("JSONDecodeError"))

    def test_css_variables_are_complete_and_deterministic(self):
        css = build_css_variables(FALLBACK_COLORS)
        self.assertIn("--btc-canvas: #0B1220;", css)
        self.assertIn("--btc-bull: #2CCB9A;", css)
        self.assertEqual(css, build_css_variables(FALLBACK_COLORS))
        self.assertEqual(len([line for line in css.splitlines() if line.startswith("--btc-")]), 12)

    def test_css_generation_rejects_invalid_color_values(self):
        colors = dict(FALLBACK_COLORS)
        colors["bull"] = "url(javascript:alert(1))"
        with self.assertRaises(ValueError):
            build_css_variables(colors)


if __name__ == "__main__":
    unittest.main()
