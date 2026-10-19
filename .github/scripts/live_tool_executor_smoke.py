#!/usr/bin/env python3
"""Exercise Aurora's actual browser tools in real Chrome without an LLM call."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = REPO_ROOT / "ci_browser_source"
sys.path.insert(0, str(SOURCE_ROOT if (SOURCE_ROOT / "tool_executor.py").is_file() else REPO_ROOT))

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from tool_executor import LocalToolExecutor


def is_example_domain(url: object) -> bool:
    try:
        parsed = urlsplit(str(url or ""))
        return parsed.scheme == "https" and (parsed.hostname or "").casefold().rstrip(".") == "example.com"
    except (TypeError, ValueError):
        return False


def main() -> int:
    driver = None
    checks = []
    try:
        options = Options()
        options.add_argument("--headless=new")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1280,900")
        options.add_argument("--disable-dev-shm-usage")
        driver = webdriver.Chrome(options=options)
        driver.set_page_load_timeout(35)

        with tempfile.TemporaryDirectory(prefix="aurora-tool-executor-") as temp:
            root = Path(temp)
            executor = LocalToolExecutor(
                root / "Workspace",
                root / "Drafts",
                lambda: driver,
                resolve_dns=True,
                browser_peeker=lambda: driver,
                memory_path=root / "aurora.sqlite3",
            )

            opened = executor.execute("browser_open_url", {"url": "https://example.com/"})
            if not opened.get("ok") or not opened.get("effect_verified") or not is_example_domain(opened.get("url")):
                raise AssertionError("The actual browser_open_url tool did not verify HTTPS navigation to example.com.")
            checks.append("PASS: real LocalToolExecutor browser_open_url opened example.com and verified final URL")

            read = executor.execute("browser_read_page", {})
            if not read.get("ok") or not read.get("effect_verified"):
                raise AssertionError("The actual browser_read_page tool did not verify its read result.")
            if not is_example_domain(read.get("url")):
                raise AssertionError("browser_read_page did not report example.com as its current URL.")
            if "Example Domain" not in str(read.get("page_title", "")):
                raise AssertionError("browser_read_page did not return the live document title.")
            if "Example Domain" not in str(read.get("page_h1", "")):
                safe_text = str(read.get("text", "") or "")
                try:
                    direct_h1 = str(driver.find_element("tag name", "h1").text or "").strip()
                except Exception:
                    direct_h1 = ""
                raise AssertionError(
                    "browser_read_page did not return the visible H1. "
                    f"body_text_length={len(safe_text)}; direct_dom_h1_match={direct_h1 == 'Example Domain'}"
                )
            if not str(read.get("text", "") or "").strip():
                raise AssertionError("browser_read_page returned empty visible body text.")
            checks.append("PASS: real browser_read_page returned document title, visible H1, and body text from the live site")

            before = str(driver.current_url or "")
            blocked = executor.execute("browser_open_url", {"url": "http://127.0.0.1:8765/"})
            if blocked.get("ok") or str(driver.current_url or "") != before:
                raise AssertionError("The tool executor failed to reject loopback navigation without changing the page.")
            checks.append("PASS: actual tool executor blocked loopback navigation without changing the public page")

        print("\n".join(checks))
        print(f"RESULT: {len(checks)}/{len(checks)} actual tool-executor checks passed")
        return 0
    except Exception as exc:
        print(f"REAL TOOL-EXECUTOR SMOKE FAILED: {type(exc).__name__}: {str(exc)[:300]}", file=sys.stderr)
        return 1
    finally:
        if driver is not None:
            driver.quit()


if __name__ == "__main__":
    raise SystemExit(main())
