from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from typing import Any

from playwright.sync_api import Browser, sync_playwright


ROOT = Path(__file__).resolve().parents[1]
REFRESH_BUTTON = "طلب تحديث التحليل من محرك اللقطات"


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def http_status(url: str, timeout: float = 2.0) -> int | None:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return int(response.status)
    except (OSError, urllib.error.URLError):
        return None


def start_streamlit(port: int, root: Path, scratch: Path) -> tuple[subprocess.Popen[str], Any]:
    env = os.environ.copy()
    env["BTCIL_SNAPSHOT_PATH"] = str(scratch / "missing-live-snapshot.json")
    env["BTCIL_SNAPSHOT_STATUS_PATH"] = str(scratch / "missing-service-status.json")
    env["BTCIL_SNAPSHOT_REFRESH_PATH"] = str(scratch / "refresh-request.json")
    env["BTCIL_MARKET_DB"] = str(scratch / "missing-market.sqlite")
    log_handle = (scratch / "streamlit.log").open("w", encoding="utf-8")
    command = [
        sys.executable, "-m", "streamlit", "run", "app.py",
        "--server.address", "127.0.0.1",
        "--server.port", str(port),
        "--server.headless", "true",
        "--browser.gatherUsageStats", "false",
        "--server.fileWatcherType", "none",
    ]
    process = subprocess.Popen(
        command,
        cwd=root,
        env=env,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        text=True,
    )
    return process, log_handle


def wait_for_health(process: subprocess.Popen[str], url: str, log_path: Path) -> None:
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(
                f"Streamlit exited with {process.returncode}:\n"
                + log_path.read_text(encoding="utf-8", errors="replace")[-6000:]
            )
        if http_status(url) == 200:
            return
        time.sleep(0.5)
    raise TimeoutError(
        "Streamlit did not become healthy:\n"
        + log_path.read_text(encoding="utf-8", errors="replace")[-6000:]
    )


def run_browser(browser: Browser, name: str, base_url: str, scratch: Path) -> dict[str, Any]:
    page_errors: list[str] = []
    context = browser.new_context(
        viewport={"width": 1440, "height": 1000},
        device_scale_factor=1,
        reduced_motion="reduce",
    )
    page = context.new_page()
    page.on("pageerror", lambda error: page_errors.append(str(error)[:500]))

    root_response = page.goto(base_url, wait_until="domcontentloaded", timeout=45_000)
    if root_response is None or root_response.status != 200:
        raise AssertionError(
            f"{name}: dashboard root returned "
            f"{None if root_response is None else root_response.status}"
        )

    page.locator("div[data-testid='stAppViewContainer']").wait_for(
        state="visible", timeout=30_000,
    )
    page.get_by_text("Bitcoin Intelligence Lab", exact=False).first.wait_for(
        state="visible", timeout=30_000,
    )
    page.get_by_text("إعدادات السوق", exact=True).wait_for(
        state="visible", timeout=20_000,
    )
    page.screenshot(
        path=str(scratch / f"bitcoin-dashboard-{name}-desktop.png"),
        full_page=True,
        animations="disabled",
    )

    refresh = page.locator("button").filter(has_text=REFRESH_BUTTON).first
    refresh.wait_for(state="visible", timeout=20_000)
    refresh.scroll_into_view_if_needed()
    refresh.click(timeout=15_000)
    # Streamlit callback reruns the script asynchronously; wait for its atomic file.
    page.wait_for_timeout(1_000)

    refresh_file = scratch / "refresh-request.json"
    deadline = time.monotonic() + 20
    payload: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        if refresh_file.exists():
            try:
                candidate = json.loads(refresh_file.read_text(encoding="utf-8"))
                if isinstance(candidate, dict) and candidate.get("schema") == "BTCIL-SNAPSHOT-REFRESH1":
                    payload = candidate
                    break
            except (OSError, json.JSONDecodeError):
                pass
        time.sleep(0.25)
    if payload is None:
        log_tail = ""
        try:
            log_tail = (scratch / "streamlit.log").read_text(encoding="utf-8", errors="replace")[-5000:]
        except OSError:
            pass
        raise AssertionError(
            f"{name}: manual refresh button did not publish {refresh_file}. "
            f"Button text={refresh.inner_text(timeout=3000)!r}. Streamlit log tail: {log_tail}"
        )
    if payload.get("symbol") != "BTCUSDT" or payload.get("interval") != "1m":
        raise AssertionError(f"{name}: refresh request did not preserve selected market/timeframe: {payload}")

    page.set_viewport_size({"width": 390, "height": 844})
    page.wait_for_timeout(600)
    page.screenshot(
        path=str(scratch / f"bitcoin-dashboard-{name}-mobile.png"),
        full_page=True,
        animations="disabled",
    )
    dimensions = page.evaluate(
        """() => ({
          viewport: window.innerWidth,
          document: document.documentElement.scrollWidth,
          body: document.body.scrollWidth
        })"""
    )
    if dimensions["document"] > dimensions["viewport"] + 24:
        raise AssertionError(f"{name}: horizontal overflow at mobile viewport: {dimensions}")
    if page_errors:
        raise AssertionError(f"{name}: uncaught browser page errors: {page_errors}")

    context.close()
    return {
        "browser": name,
        "root_http_status": root_response.status,
        "refresh_request": payload,
        "mobile_dimensions": dimensions,
        "uncaught_page_errors": page_errors,
        "status": "passed",
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Real Chromium/Firefox browser checks for the Bitcoin dashboard."
    )
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts" / "dashboard_browser")
    args = parser.parse_args()
    port = args.port or free_port()
    args.output.mkdir(parents=True, exist_ok=True)

    report: dict[str, Any] = {
        "schema": "BTCIL-DASHBOARD-BROWSER1",
        "port": port,
        "browsers": [],
        "status": "running",
    }
    scratch = Path(tempfile.mkdtemp(prefix="btc-dashboard-browser-test-"))
    process: subprocess.Popen[str] | None = None
    log_handle: Any = None
    try:
        process, log_handle = start_streamlit(port, ROOT, scratch)
        base_url = f"http://127.0.0.1:{port}"
        wait_for_health(
            process,
            base_url + "/_stcore/health",
            scratch / "streamlit.log",
        )
        with sync_playwright() as playwright:
            for name in ("chromium", "firefox"):
                browser = getattr(playwright, name).launch(headless=True)
                try:
                    result = run_browser(browser, name, base_url, args.output)
                    report["browsers"].append(result)
                finally:
                    browser.close()
        report["status"] = "passed"
        return_code = 0
    except Exception as exc:
        report["status"] = "failed"
        report["error"] = f"{type(exc).__name__}: {exc}"
        return_code = 1
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        if log_handle is not None:
            log_handle.close()
        if (scratch / "streamlit.log").exists():
            (args.output / "streamlit-browser-test.log").write_text(
                (scratch / "streamlit.log").read_text(encoding="utf-8", errors="replace"),
                encoding="utf-8",
            )
        (args.output / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    # GitHub Windows runners may use cp1252; keep the console report ASCII-safe.
    print(json.dumps(report, ensure_ascii=True, indent=2))
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
