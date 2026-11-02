from __future__ import annotations

import json
import time
from pathlib import Path

from PIL import Image

from mirsad.engines.mt5_observer import MT5ChartObserverInbox


def _make_capture(tmp_path: Path, *, now_ms: int | None = None) -> tuple[Path, dict]:
    captured = int(time.time() * 1000) if now_ms is None else now_ms
    root = tmp_path / "MirsadBTC" / "observer"
    images = root / "images"
    images.mkdir(parents=True)

    capture_id = f"1700000000000_987654321_1"
    image_name = f"o_{capture_id}.png"
    image_path = images / image_name
    Image.new("RGB", (640, 360), (22, 28, 38)).save(image_path, format="PNG")

    bars = []
    start = 1_800_000_000_000
    for index in range(30):
        base = 90_000.0 + index * 10.0
        bars.append({
            "time_server_ms": start + index * 60_000,
            "open": base,
            "high": base + 25,
            "low": base - 15,
            "close": base + 5,
            "tick_volume": 100 + index,
            "real_volume": 0,
            "spread_points": 20,
            "is_closed": index < 29,
        })

    payload = {
        "schema": "MIR-CHART-OBSERVATION-1",
        "capture_id": capture_id,
        "capture_at_utc_ms": captured,
        "published_at_utc_ms": captured + 100,
        "image_file": image_name,
        "image_width_px": 640,
        "image_height_px": 360,
        "image_size_bytes": image_path.stat().st_size,
        "forming_bar_included": True,
        "bars_time_basis": "MT5_SERVER_TIME",
        "bars_copied": len(bars),
        "bars": bars,
        "chart": {
            "symbol": "BTC",
            "timeframe": "M1",
            "digits": 2,
            "price_min": 89_000.0,
            "price_max": 92_000.0,
            "plot_bounds_status": "NOT_CALIBRATED_FROM_PIXELS",
        },
    }
    manifest = root / f"capture_{capture_id}.json"
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    return root, payload


def test_reads_valid_image_and_native_rates_without_authorizing_decision(tmp_path: Path) -> None:
    now = int(time.time() * 1000)
    root, _ = _make_capture(tmp_path, now_ms=now)

    result = MT5ChartObserverInbox(root, max_age_seconds=120).inspect_latest(now_ms=now + 500)

    assert result["status"] == "READY_FOR_ENGINE_2_VALIDATION"
    assert result["decision_eligible"] is False
    assert result["chart"]["symbol"] == "BTC"
    assert result["chart"]["timeframe"] == "1m"
    assert result["bar_count"] == 30
    assert result["bars"][-1]["is_closed"] is False
    assert len(result["image_sha256"]) == 64


def test_rejects_stale_capture_instead_of_falling_back(tmp_path: Path) -> None:
    now = int(time.time() * 1000)
    root, _ = _make_capture(tmp_path, now_ms=now - 300_000)

    result = MT5ChartObserverInbox(root, max_age_seconds=60).inspect_latest(now_ms=now)

    assert result["status"] == "STALE"
    assert result["decision_eligible"] is False


def test_rejects_path_traversal_image_name(tmp_path: Path) -> None:
    now = int(time.time() * 1000)
    root, payload = _make_capture(tmp_path, now_ms=now)
    payload["image_file"] = "../outside.png"
    (root / f"capture_{payload['capture_id']}.json").write_text(json.dumps(payload), encoding="utf-8")

    result = MT5ChartObserverInbox(root).inspect_latest(now_ms=now + 500)

    assert result["status"] == "INVALID_IMAGE_PATH"


def test_rejects_image_size_mismatch(tmp_path: Path) -> None:
    now = int(time.time() * 1000)
    root, payload = _make_capture(tmp_path, now_ms=now)
    payload["image_size_bytes"] += 4
    (root / f"capture_{payload['capture_id']}.json").write_text(json.dumps(payload), encoding="utf-8")

    result = MT5ChartObserverInbox(root).inspect_latest(now_ms=now + 500)

    assert result["status"] == "IMAGE_SIZE_MISMATCH"


def test_rejects_non_monotonic_bar_times(tmp_path: Path) -> None:
    now = int(time.time() * 1000)
    root, payload = _make_capture(tmp_path, now_ms=now)
    payload["bars"][4]["time_server_ms"] = payload["bars"][3]["time_server_ms"]
    (root / f"capture_{payload['capture_id']}.json").write_text(json.dumps(payload), encoding="utf-8")

    result = MT5ChartObserverInbox(root).inspect_latest(now_ms=now + 500)

    assert result["status"] == "INVALID_OHLC_SNAPSHOT"


def test_rejects_inconsistent_ohlc(tmp_path: Path) -> None:
    now = int(time.time() * 1000)
    root, payload = _make_capture(tmp_path, now_ms=now)
    payload["bars"][8]["high"] = payload["bars"][8]["low"] - 1
    (root / f"capture_{payload['capture_id']}.json").write_text(json.dumps(payload), encoding="utf-8")

    result = MT5ChartObserverInbox(root).inspect_latest(now_ms=now + 500)

    assert result["status"] == "INVALID_OHLC_SNAPSHOT"


def test_rejects_wrong_manifest_schema(tmp_path: Path) -> None:
    now = int(time.time() * 1000)
    root, payload = _make_capture(tmp_path, now_ms=now)
    payload["schema"] = "MIR1"
    (root / f"capture_{payload['capture_id']}.json").write_text(json.dumps(payload), encoding="utf-8")

    result = MT5ChartObserverInbox(root).inspect_latest(now_ms=now + 500)

    assert result["status"] == "SCHEMA_MISMATCH"


def test_waits_when_no_capture_exists(tmp_path: Path) -> None:
    result = MT5ChartObserverInbox(tmp_path / "empty").inspect_latest()

    assert result["status"] == "WAITING_FOR_CAPTURE"
    assert result["decision_eligible"] is False
