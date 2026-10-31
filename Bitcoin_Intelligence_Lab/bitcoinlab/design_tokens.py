from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Mapping


TOKEN_NAMES = {
    "Canvas/Background": "canvas",
    "Surface/Default": "surface",
    "Surface/Raised": "raised",
    "Surface/Subtle": "subtle",
    "Border/Default": "border",
    "Text/Primary": "text",
    "Text/Secondary": "secondary",
    "Text/Muted": "muted",
    "Signal/Bull": "bull",
    "Signal/Bear": "bear",
    "Signal/Warning": "warning",
    "Signal/Info": "info",
}

FALLBACK_COLORS = {
    "canvas": "#0B1220",
    "surface": "#111C2D",
    "raised": "#17253A",
    "subtle": "#1E2E45",
    "border": "#2B3C54",
    "text": "#F4F7FB",
    "secondary": "#A9B8CC",
    "muted": "#7E91AA",
    "bull": "#2CCB9A",
    "bear": "#F16D75",
    "warning": "#EAB85C",
    "info": "#65A8E8",
}

_HEX_COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")


def load_dashboard_colors(
    token_path: str | Path | None = None,
) -> tuple[dict[str, str], str | None]:
    """Load the single Figma-authored color source, falling back safely."""
    path = (
        Path(token_path)
        if token_path is not None
        else Path(__file__).resolve().parents[1] / "design" / "bitcoin_dashboard.tokens.json"
    )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or not isinstance(payload.get("colors"), dict):
            raise ValueError("Design token document has no colors object.")
        raw = payload["colors"]
        colors: dict[str, str] = {}
        for source, target in TOKEN_NAMES.items():
            value = raw.get(source)
            if not isinstance(value, str) or not _HEX_COLOR.fullmatch(value):
                raise ValueError(f"Design color token is missing or invalid: {source}")
            colors[target] = value.upper()
        return colors, None
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        return dict(FALLBACK_COLORS), f"{type(exc).__name__}: {exc}"


def build_css_variables(colors: Mapping[str, str]) -> str:
    """Return deterministic CSS custom properties from validated color tokens."""
    missing = set(FALLBACK_COLORS).difference(colors)
    if missing:
        raise ValueError(f"Missing dashboard colors: {', '.join(sorted(missing))}")
    invalid = [name for name in FALLBACK_COLORS if not _HEX_COLOR.fullmatch(str(colors[name]))]
    if invalid:
        raise ValueError(f"Invalid dashboard colors: {', '.join(sorted(invalid))}")
    return "\n".join(
        f"--btc-{name}: {colors[name]};"
        for name in FALLBACK_COLORS
    )
