from __future__ import annotations

import hashlib
import json
import math
import time
from pathlib import Path
from typing import Any

from PIL import Image

OBSERVER_SCHEMA = "MIR-CHART-OBSERVATION-1"
SUPPORTED_TIMEFRAMES = {
    "M1": "1m",
    "M5": "5m",
    "M15": "15m",
    "H1": "1h",
    "H4": "4h",
    "D1": "1d",
    "W1": "1w",
}
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def observer_root_from_common_files(common_files: str | Path) -> Path:
    """Return the MT5 Common\Files inbox used by the independent observer EA."""
    return Path(common_files).expanduser() / "MirsadBTC" / "observer"


def _invalid(status: str, reason: str, **extra: Any) -> dict[str, Any]:
    return {
        "engine": "mt5_chart_observer_inbox",
        "status": status,
        "decision_eligible": False,
        "reason": reason,
        **extra,
    }


def _validate_bars(raw_bars: Any) -> tuple[list[dict[str, Any]] | None, str | None]:
    if not isinstance(raw_bars, list) or len(raw_bars) < 20:
        return None, "At least 20 OHLC bars are required in an observer capture."
    if len(raw_bars) > 500:
        return None, "Observer capture exceeds the 500-bar protocol limit."

    bars: list[dict[str, Any]] = []
    previous_time = 0
    for index, raw in enumerate(raw_bars):
        if not isinstance(raw, dict):
            return None, f"Bar {index} is not an object."
        try:
            stamp = int(raw["time_server_ms"])
            values = {
                key: float(raw[key])
                for key in ("open", "high", "low", "close")
            }
            tick_volume = int(raw.get("tick_volume", 0))
            real_volume = int(raw.get("real_volume", 0))
            spread_points = int(raw.get("spread_points", 0))
        except (KeyError, TypeError, ValueError, OverflowError):
            return None, f"Bar {index} is missing valid time or OHLCV fields."

        if stamp <= previous_time:
            return None, "Bar timestamps must be strictly increasing in server-time order."
        previous_time = stamp
        if not all(math.isfinite(value) and value > 0 for value in values.values()):
            return None, f"Bar {index} contains a non-finite or non-positive price."
        if values["high"] < max(values["open"], values["close"], values["low"]):
            return None, f"Bar {index} has a high below one of its OHLC values."
        if values["low"] > min(values["open"], values["close"], values["high"]):
            return None, f"Bar {index} has a low above one of its OHLC values."
        if min(tick_volume, real_volume, spread_points) < 0:
            return None, f"Bar {index} contains a negative volume or spread."

        is_closed = raw.get("is_closed")
        if not isinstance(is_closed, bool):
            return None, f"Bar {index} is missing the boolean is_closed field."
        bars.append({
            "time_server_ms": stamp,
            **values,
            "tick_volume": tick_volume,
            "real_volume": real_volume,
            "spread_points": spread_points,
            "is_closed": is_closed,
        })

    if bars[-1]["is_closed"]:
        return None, "The newest CopyRates bar must be marked as forming, not closed."
    if any(not bar["is_closed"] for bar in bars[:-1]):
        return None, "Only the newest bar may be marked as forming."
    return bars, None


class MT5ChartObserverInbox:
    """Validate manifests written by Mirsad_ChartObserver.mq5.

    Reading an observer capture is intentionally not the same as authorizing
    Engine 2 or Engine 4. The returned decision_eligible flag always remains
    false until image layout, price/time calibration and Engine 2 analysis pass.
    """

    def __init__(
        self,
        observer_root: str | Path,
        *,
        max_age_seconds: int = 120,
        max_future_skew_seconds: int = 30,
    ) -> None:
        self.root = Path(observer_root).expanduser()
        self.images = self.root / "images"
        self.max_age_seconds = max(1, int(max_age_seconds))
        self.max_future_skew_seconds = max(0, int(max_future_skew_seconds))

    @classmethod
    def from_common_files(
        cls,
        common_files: str | Path,
        *,
        max_age_seconds: int = 120,
    ) -> "MT5ChartObserverInbox":
        return cls(
            observer_root_from_common_files(common_files),
            max_age_seconds=max_age_seconds,
        )

    def inspect_latest(self, *, now_ms: int | None = None) -> dict[str, Any]:
        manifests = sorted(
            self.root.glob("capture_*.json"),
            key=lambda item: (item.stat().st_mtime_ns, item.name),
            reverse=True,
        ) if self.root.exists() else []
        if not manifests:
            return _invalid("WAITING_FOR_CAPTURE", "No published MT5 observer manifest exists yet.")

        # Do not fall back to an older good image if the newest capture is bad.
        # Doing so could make the dashboard silently display a stale chart.
        manifest_path = manifests[0]
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            return _invalid("INVALID_MANIFEST", f"Could not read the newest observer manifest: {exc}")

        if not isinstance(payload, dict) or payload.get("schema") != OBSERVER_SCHEMA:
            return _invalid("SCHEMA_MISMATCH", "Observer manifest schema is missing or unsupported.")

        capture_id = str(payload.get("capture_id", "")).strip()
        if not capture_id or manifest_path.stem != f"capture_{capture_id}":
            return _invalid("IDENTITY_MISMATCH", "Manifest filename and capture_id do not match.")

        try:
            captured_at = int(payload["capture_at_utc_ms"])
            published_at = int(payload["published_at_utc_ms"])
            image_width = int(payload["image_width_px"])
            image_height = int(payload["image_height_px"])
            expected_size = int(payload["image_size_bytes"])
        except (KeyError, TypeError, ValueError, OverflowError):
            return _invalid("INVALID_METADATA", "Capture timestamps, image dimensions or file size are missing.")

        clock_now = int(time.time() * 1000) if now_ms is None else int(now_ms)
        if captured_at > clock_now + self.max_future_skew_seconds * 1000:
            return _invalid("FUTURE_DATED", "Capture timestamp is too far in the future.")
        age_seconds = (clock_now - captured_at) / 1000.0
        if age_seconds > self.max_age_seconds:
            return _invalid(
                "STALE",
                f"Newest observer capture is {age_seconds:.1f}s old (limit {self.max_age_seconds}s).",
                capture_id=capture_id,
                age_seconds=round(age_seconds, 2),
            )
        if published_at < captured_at or published_at > clock_now + self.max_future_skew_seconds * 1000:
            return _invalid("INVALID_PUBLISH_TIME", "Manifest publish time is inconsistent with the capture time.")
        if not (320 <= image_width <= 3840 and 180 <= image_height <= 2160):
            return _invalid("INVALID_IMAGE_DIMENSIONS", "Observer image dimensions are outside the accepted bounds.")
        if expected_size < 128:
            return _invalid("INVALID_IMAGE_SIZE", "Observer PNG is unexpectedly small.")

        image_name = payload.get("image_file")
        if (
            not isinstance(image_name, str)
            or Path(image_name).name != image_name
            or Path(image_name).suffix.lower() != ".png"
        ):
            return _invalid("INVALID_IMAGE_PATH", "Image file must be a basename ending in .png.")

        image_path = (self.images / image_name).resolve()
        try:
            image_path.relative_to(self.images.resolve())
        except ValueError:
            return _invalid("INVALID_IMAGE_PATH", "Image path escapes the observer images directory.")
        if not image_path.is_file():
            return _invalid("IMAGE_MISSING", "Published manifest exists but its PNG image is missing.")

        try:
            image_bytes = image_path.read_bytes()
        except OSError as exc:
            return _invalid("IMAGE_READ_ERROR", f"Could not read observer image: {exc}")
        if len(image_bytes) != expected_size:
            return _invalid("IMAGE_SIZE_MISMATCH", "PNG size does not match the published manifest.")
        if not image_bytes.startswith(PNG_SIGNATURE):
            return _invalid("INVALID_IMAGE_FORMAT", "Observer image does not have a PNG signature.")

        try:
            with Image.open(image_path) as image:
                image.verify()
            with Image.open(image_path) as image:
                actual_size = image.size
        except Exception as exc:  # Pillow raises several decoder-specific exceptions.
            return _invalid("IMAGE_DECODE_ERROR", f"Observer PNG could not be decoded: {exc}")
        if actual_size != (image_width, image_height):
            return _invalid("IMAGE_DIMENSION_MISMATCH", "Decoded PNG dimensions do not match the manifest.")

        chart = payload.get("chart")
        if not isinstance(chart, dict):
            return _invalid("INVALID_CHART_METADATA", "Chart metadata is missing.")
        symbol = str(chart.get("symbol", "")).strip()
        source_timeframe = str(chart.get("timeframe", "")).strip().upper()
        timeframe = SUPPORTED_TIMEFRAMES.get(source_timeframe)
        if not symbol or not timeframe:
            return _invalid(
                "UNSUPPORTED_CHART",
                "Chart symbol is missing or timeframe is not supported by the current Engine 2 contract.",
                symbol=symbol or None,
                source_timeframe=source_timeframe or None,
            )

        bars, bar_error = _validate_bars(payload.get("bars"))
        if bar_error:
            return _invalid("INVALID_OHLC_SNAPSHOT", bar_error, capture_id=capture_id)
        if int(payload.get("bars_copied", -1)) != len(bars or []):
            return _invalid("BAR_COUNT_MISMATCH", "bars_copied does not match the actual bars array.")
        if not bool(payload.get("forming_bar_included")):
            return _invalid("FORMING_BAR_FLAG_MISMATCH", "Protocol says a forming bar is included but flag is false.")

        digest = hashlib.sha256(image_bytes).hexdigest()
        return {
            "engine": "mt5_chart_observer_inbox",
            "status": "READY_FOR_ENGINE_2_VALIDATION",
            "decision_eligible": False,
            "capture_id": capture_id,
            "captured_at_utc_ms": captured_at,
            "published_at_utc_ms": published_at,
            "age_seconds": round(age_seconds, 2),
            "image_path": str(image_path),
            "image_sha256": digest,
            "image_size_bytes": len(image_bytes),
            "chart": {
                **chart,
                "source_timeframe": source_timeframe,
                "timeframe": timeframe,
            },
            "bars_time_basis": payload.get("bars_time_basis"),
            "bars": bars,
            "bar_count": len(bars or []),
            "plot_bounds_status": chart.get("plot_bounds_status", "UNKNOWN"),
            "message": (
                "Image and native OHLC snapshot passed inbox validation. "
                "Engine 2 must still validate layout, calibration and visual/data alignment."
            ),
        }
