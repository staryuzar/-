#!/usr/bin/env python3
"""Real Chrome smoke test against a disposable local page; no external accounts used."""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
import time
import sys
from pathlib import Path

# Running a script from .github/scripts does not reliably put the repository root on sys.path.
REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = REPO_ROOT / "ci_browser_source"
sys.path.insert(0, str(SOURCE_ROOT if (SOURCE_ROOT / "browser_control.py").is_file() else REPO_ROOT))

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import InvalidArgumentException

from browser_control import (
    find_text_target,
    get_visible_page_text,
    validate_current_page,
    validate_debugger_address,
    validate_text_entry,
)

HTML = b"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Aurora Browser Test Fixture</title></head>
<body>
<h1>Aurora browser integration fixture</h1>
<p id="fixture-copy">The page is loaded and readable.</p>
<button id="open-detail" onclick="document.getElementById('status').textContent='clicked-ok'">Open test detail</button>
<div id="status">not-clicked</div>
<label>Search <input id="search" type="text" value=""></label>
<label>Password <input id="password" type="password"></label>
<button>Delete</button><button>Delete</button>
</body></html>"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(HTML)))
        self.end_headers()
        self.wfile.write(HTML)

    def log_message(self, *_args):
        pass


def main() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    driver = None
    checks = []
    try:
        options = Options()
        options.add_argument("--headless=new")
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--window-size=1280,900")
        driver = webdriver.Chrome(options=options)
        driver.set_page_load_timeout(30)
        driver.get(f"http://127.0.0.1:{server.server_port}/")
        assert driver.title == "Aurora Browser Test Fixture"
        checks.append("PASS: real Chrome launched and loaded local fixture")

        page_text = get_visible_page_text(driver, limit=2000)
        assert "The page is loaded and readable." in page_text
        checks.append("PASS: visible page text extraction")

        button, label = find_text_target(driver, "Open test detail")
        assert label == "Open test detail"
        button.click()
        WebDriverWait(driver, 5).until(
            lambda d: d.find_element("id", "status").text == "clicked-ok"
        )
        checks.append("PASS: unique visible button targeting and click verification")

        search = driver.find_element("id", "search")
        assert validate_text_entry(search) == "حقل نصي"
        try:
            validate_text_entry(driver.find_element("id", "password"))
        except ValueError:
            checks.append("PASS: password field rejected by text-entry guard")
        else:
            raise AssertionError("Password field was incorrectly accepted")

        try:
            find_text_target(driver, "Delete")
        except ValueError as exc:
            assert "أكثر من عنصر" in str(exc) or "عدة عناصر" in str(exc)
            checks.append("PASS: ambiguous duplicate buttons rejected")
        else:
            raise AssertionError("Ambiguous duplicate button was incorrectly selected")

        assert validate_debugger_address("127.0.0.1:9222") == "127.0.0.1:9222"
        try:
            validate_debugger_address("192.0.2.5:9222")
        except ValueError:
            checks.append("PASS: remote Chrome debugging endpoint rejected")
        else:
            raise AssertionError("Remote debugging endpoint was incorrectly accepted")

        # An invalid URL must fail before Chrome leaves the known-good fixture.
        known_good_url = driver.current_url
        try:
            driver.get("not a valid URL with spaces")
        except InvalidArgumentException:
            assert driver.current_url == known_good_url
            assert "The page is loaded and readable." in get_visible_page_text(driver, limit=2000)
            checks.append("PASS: malformed navigation URL rejected without leaving the current page")
        else:
            raise AssertionError("Malformed navigation URL was unexpectedly accepted")

        # Localhost is intentionally not a public navigation target for the assistant.
        try:
            validate_current_page(driver)
        except ValueError:
            assert driver.current_url == "about:blank"
            checks.append("PASS: loopback page rejected by public-URL guard")
        else:
            raise AssertionError("Loopback page unexpectedly passed public-URL validation")

        print("\n".join(checks))
        print(f"RESULT: {len(checks)}/{len(checks)} browser checks passed")
    finally:
        if driver is not None:
            driver.quit()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


if __name__ == "__main__":
    main()
