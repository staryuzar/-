from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
import time
from typing import Any, Callable
from uuid import uuid4

from .live_snapshot import build_live_snapshot


SNAPSHOT_SCHEMA = "BTCIL-SNAPSHOT1"
STATUS_SCHEMA = "BTCIL-SNAPSHOT-SERVICE1"


class SnapshotUnavailableError(RuntimeError):
    pass


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def default_snapshot_path() -> Path:
    configured = os.environ.get("BTCIL_SNAPSHOT_PATH")
    return Path(configured).expanduser() if configured else project_root() / "data" / "live_snapshot.json"


def default_status_path() -> Path:
    configured = os.environ.get("BTCIL_SNAPSHOT_STATUS_PATH")
    return Path(configured).expanduser() if configured else project_root() / "data" / "live_snapshot_service_status.json"


def default_refresh_request_path() -> Path:
    configured = os.environ.get("BTCIL_SNAPSHOT_REFRESH_PATH")
    return Path(configured).expanduser() if configured else project_root() / "data" / "snapshot_refresh.request.json"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _write_json_atomic(path: str | Path, payload: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=target.parent,
            prefix=target.name + ".", suffix=".tmp", delete=False,
        ) as handle:
            temporary = Path(handle.name)
            json.dump(payload, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    except Exception:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
        raise


def read_latest_snapshot(
    path: str | Path | None = None,
    *,
    max_age_seconds: int = 90,
    now: datetime | None = None,
) -> dict[str, Any]:
    if not 5 <= max_age_seconds <= 900:
        raise ValueError("max_age_seconds must be between 5 and 900.")
    target = Path(path) if path is not None else default_snapshot_path()
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SnapshotUnavailableError(
            f"Shared market snapshot has not been published yet: {target}"
        ) from exc
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SnapshotUnavailableError(
            f"Shared market snapshot cannot be read: {type(exc).__name__}: {exc}"
        ) from exc

    if not isinstance(payload, dict) or payload.get("schema") != SNAPSHOT_SCHEMA:
        raise SnapshotUnavailableError("Shared market snapshot schema is invalid.")
    report = payload.get("snapshot")
    if not isinstance(report, dict):
        raise SnapshotUnavailableError("Shared market snapshot payload is missing.")
    try:
        observed = datetime.fromisoformat(
            str(report.get("as_of_utc", "")).replace("Z", "+00:00")
        ).astimezone(timezone.utc)
    except (TypeError, ValueError) as exc:
        raise SnapshotUnavailableError("Shared market snapshot timestamp is invalid.") from exc

    current = now or _utc_now()
    age = (current.astimezone(timezone.utc) - observed).total_seconds()
    if age < -5:
        raise SnapshotUnavailableError("Shared market snapshot timestamp is in the future.")
    if age > max_age_seconds:
        raise SnapshotUnavailableError(
            f"Shared market snapshot is stale ({age:.1f}s > {max_age_seconds}s)."
        )
    return report


def request_snapshot_refresh(
    path: str | Path | None = None,
    *,
    reason: str = "dashboard_manual_refresh",
    symbol: str = "BTCUSDT",
    interval: str = "1m",
) -> dict[str, Any]:
    normalized_symbol = str(symbol).upper().strip()
    normalized_interval = str(interval).lower().strip()
    if not normalized_symbol.isalnum() or not normalized_symbol.startswith("BTC"):
        raise ValueError("Refresh request accepts BTC symbols only.")
    if normalized_interval not in {"1m", "5m", "15m", "1h", "4h"}:
        raise ValueError("Unsupported refresh timeframe.")
    target = Path(path) if path is not None else default_refresh_request_path()
    request = {
        "schema": "BTCIL-SNAPSHOT-REFRESH1",
        "request_id": uuid4().hex,
        "requested_at_utc": _utc_now().isoformat(),
        "reason": str(reason)[:160],
        "symbol": normalized_symbol,
        "interval": normalized_interval,
    }
    _write_json_atomic(target, request)
    return request


def _pid_is_running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True
    except OSError:
        return False


class _ServiceLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.owned = False
        self.pid = os.getpid()

    def __enter__(self) -> "_ServiceLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        for _attempt in range(2):
            try:
                descriptor = os.open(
                    str(self.path),
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                )
                with os.fdopen(descriptor, "w", encoding="ascii") as handle:
                    handle.write(str(self.pid))
                    handle.flush()
                    os.fsync(handle.fileno())
                self.owned = True
                return self
            except FileExistsError:
                try:
                    existing_pid = int(self.path.read_text(encoding="ascii").strip())
                except (OSError, ValueError):
                    existing_pid = -1
                if _pid_is_running(existing_pid):
                    raise RuntimeError(
                        f"Snapshot service already appears active (pid={existing_pid})."
                    )
                try:
                    self.path.unlink()
                except OSError as exc:
                    raise RuntimeError("Cannot clear stale snapshot-service lock.") from exc
        raise RuntimeError("Could not acquire snapshot-service lock.")

    def __exit__(self, *_exc: object) -> None:
        if not self.owned:
            return
        try:
            owner = int(self.path.read_text(encoding="ascii").strip())
            if owner == self.pid:
                self.path.unlink(missing_ok=True)
        except (OSError, ValueError):
            pass


def read_snapshot_service_status(
    path: str | Path | None = None,
    *,
    max_age_seconds: int = 90,
    now: datetime | None = None,
) -> dict[str, Any]:
    target = Path(path) if path is not None else default_status_path()
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"status": "unavailable", "freshness_status": "unavailable", "reason": "Snapshot service status file is missing."}
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return {"status": "invalid", "freshness_status": "invalid", "reason": f"{type(exc).__name__}: {exc}"}
    if not isinstance(payload, dict) or payload.get("schema") != STATUS_SCHEMA:
        return {"status": "invalid", "freshness_status": "invalid", "reason": "Snapshot service status schema is invalid."}
    try:
        observed = datetime.fromisoformat(
            str(payload.get("updated_at_utc", "")).replace("Z", "+00:00")
        ).astimezone(timezone.utc)
    except (TypeError, ValueError):
        return {"status": "invalid", "freshness_status": "invalid", "reason": "Snapshot service heartbeat timestamp is invalid."}
    current = now or _utc_now()
    age = (current.astimezone(timezone.utc) - observed).total_seconds()
    freshness_status = "fresh" if -5 <= age <= max_age_seconds else "stale"
    return {
        **payload,
        "freshness_status": freshness_status,
        "age_seconds": round(max(0.0, age), 2),
    }


def _consume_refresh_request_payload(
    path: Path,
    *,
    max_age_seconds: int = 600,
) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    payload: object = None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return None
        observed = datetime.fromisoformat(
            str(payload.get("requested_at_utc", "")).replace("Z", "+00:00")
        ).astimezone(timezone.utc)
        age = (_utc_now() - observed).total_seconds()
        symbol = str(payload.get("symbol", "BTCUSDT")).upper().strip()
        interval = str(payload.get("interval", "1m")).lower().strip()
        valid = (
            payload.get("schema") == "BTCIL-SNAPSHOT-REFRESH1"
            and -5 <= age <= max_age_seconds
            and symbol.isalnum()
            and symbol.startswith("BTC")
            and interval in {"1m", "5m", "15m", "1h", "4h"}
        )
        if valid:
            return {"symbol": symbol, "interval": interval, "request_id": payload.get("request_id")}
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
        pass
    finally:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
    return None


def _consume_refresh_request(path: Path, *, max_age_seconds: int = 600) -> bool:
    return _consume_refresh_request_payload(
        path, max_age_seconds=max_age_seconds,
    ) is not None

def _publish_status(
    path: Path,
    *,
    status: str,
    interval_seconds: int,
    last_success_utc: str | None,
    cycle_seconds: float | None,
    error: str | None = None,
) -> None:
    _write_json_atomic(path, {
        "schema": STATUS_SCHEMA,
        "status": status,
        "updated_at_utc": _utc_now().isoformat(),
        "interval_seconds": interval_seconds,
        "last_success_utc": last_success_utc,
        "last_cycle_seconds": round(cycle_seconds, 3) if cycle_seconds is not None else None,
        "last_error": error[:500] if error else None,
        "pid": os.getpid(),
    })


def run_snapshot_service(
    *,
    interval_seconds: int = 45,
    symbol: str = "BTCUSDT",
    interval: str = "1m",
    snapshot_path: str | Path | None = None,
    status_path: str | Path | None = None,
    refresh_request_path: str | Path | None = None,
    builder: Callable[..., dict[str, Any]] = build_live_snapshot,
    once: bool = False,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    if not 30 <= interval_seconds <= 300:
        raise ValueError("interval_seconds must be between 30 and 300.")
    if not symbol.isalnum() or not symbol.upper().startswith("BTC"):
        raise ValueError("Snapshot service accepts BTC symbols only.")
    output = Path(snapshot_path) if snapshot_path is not None else default_snapshot_path()
    state_file = Path(status_path) if status_path is not None else default_status_path()
    request_file = (
        Path(refresh_request_path)
        if refresh_request_path is not None
        else default_refresh_request_path()
    )
    lock_file = output.with_suffix(output.suffix + ".service.lock")
    last_success: str | None = None
    last_cycle_seconds: float | None = None
    next_due = 0.0
    last_result: dict[str, Any] = {"status": "not_started"}

    with _ServiceLock(lock_file):
        _publish_status(
            state_file, status="starting", interval_seconds=interval_seconds,
            last_success_utc=last_success, cycle_seconds=None,
        )
        while True:
            request = _consume_refresh_request_payload(request_file)
            requested = request is not None
            if request is not None:
                symbol = request["symbol"]
                interval = request["interval"]
            now_mono = time.monotonic()
            if once or requested or now_mono >= next_due:
                started = time.monotonic()
                try:
                    snapshot = builder(symbol=symbol, interval=interval)
                    if not isinstance(snapshot, dict) or not snapshot.get("as_of_utc"):
                        raise ValueError("Snapshot builder returned an invalid payload.")
                    published_at = _utc_now().isoformat()
                    envelope = {
                        "schema": SNAPSHOT_SCHEMA,
                        "published_at_utc": published_at,
                        "snapshot": snapshot,
                    }
                    _write_json_atomic(output, envelope)
                    last_success = published_at
                    last_cycle_seconds = time.monotonic() - started
                    last_result = {
                        "status": "published",
                        "path": str(output),
                        "as_of_utc": snapshot.get("as_of_utc"),
                        "cycle_seconds": round(last_cycle_seconds, 3),
                    }
                    _publish_status(
                        state_file, status="healthy", interval_seconds=interval_seconds,
                        last_success_utc=last_success, cycle_seconds=last_cycle_seconds,
                    )
                except Exception as exc:
                    last_cycle_seconds = time.monotonic() - started
                    error = f"{type(exc).__name__}: {exc}"
                    last_result = {"status": "cycle_error", "error": error}
                    _publish_status(
                        state_file, status="degraded", interval_seconds=interval_seconds,
                        last_success_utc=last_success, cycle_seconds=last_cycle_seconds,
                        error=error,
                    )
                next_due = time.monotonic() + interval_seconds
                if once:
                    return last_result
            sleep(1.0)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Bitcoin Intelligence Lab shared market snapshot service."
    )
    parser.add_argument("--interval-seconds", type=int, default=45)
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--interval", default="1m")
    parser.add_argument("--snapshot-path", default=str(default_snapshot_path()))
    parser.add_argument("--status-path", default=str(default_status_path()))
    parser.add_argument("--refresh-request-path", default=str(default_refresh_request_path()))
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    try:
        result = run_snapshot_service(
            interval_seconds=args.interval_seconds,
            symbol=args.symbol,
            interval=args.interval,
            snapshot_path=args.snapshot_path,
            status_path=args.status_path,
            refresh_request_path=args.refresh_request_path,
            once=args.once,
        )
        print(json.dumps(result, ensure_ascii=False), flush=True)
        return 0 if result.get("status") == "published" else 1
    except KeyboardInterrupt:
        return 0
    except Exception as exc:
        print(json.dumps({
            "status": "service_error",
            "error": f"{type(exc).__name__}: {exc}"[:500],
        }, ensure_ascii=False), flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
