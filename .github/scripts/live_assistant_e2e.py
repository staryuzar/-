#!/usr/bin/env python3
"""End-to-end test of the real Aurora UI, real provider API, and live public website.

This deliberately does not mock the model, browser, or target website.
"""
from __future__ import annotations
import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import WebDriverException
from urllib.request import urlopen


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    provider = os.getenv("AI_PROVIDER", "gemini").strip().lower()
    key_name = "GEMINI_API_KEY" if provider == "gemini" else "OPENROUTER_API_KEY"
    if not os.getenv(key_name, "").strip():
        raise RuntimeError(f"Missing real provider credential: {key_name}")

    report = {
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "provider": provider,
        "test_type": "REAL_E2E_NO_MOCKS",
        "target": "https://example.com/",
        "checks": [],
    }
    driver = None
    try:
        options = webdriver.ChromeOptions()
        options.add_argument("--headless=new")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1440,1000")
        options.add_argument("--disable-dev-shm-usage")
        # Hosted Windows runners may expose proxy settings that incorrectly route
        # loopback traffic. The app under test is local, so bypass proxies explicitly.
        options.add_argument("--no-proxy-server")
        options.add_argument("--proxy-bypass-list=<-loopback>")
        driver = webdriver.Chrome(options=options)
        driver.set_page_load_timeout(40)
        # Do not mistake a transient local startup race for a broken assistant.
        # Probe the actual HTTP endpoint and retry browser navigation with evidence.
        navigation_errors = []
        for attempt in range(1, 4):
            try:
                with urlopen(args.url + "/_stcore/health", timeout=5) as response:
                    if response.status != 200:
                        raise RuntimeError(f"Streamlit health returned HTTP {response.status}")
                driver.get(args.url)
                break
            except Exception as exc:
                navigation_errors.append(f"attempt {attempt}: {type(exc).__name__}: {str(exc)[:240]}")
                if attempt == 3:
                    raise RuntimeError(
                        "Could not open local app in Chrome after 3 attempts; "
                        + " | ".join(navigation_errors)
                    ) from exc
                time.sleep(2)
        report["checks"].append("PASS: local app health endpoint reachable before Chrome navigation")
        WebDriverWait(driver, 30).until(
            lambda d: d.find_elements(By.CSS_SELECTOR, '[data-testid="stChatInput"] textarea')
        )
        report["checks"].append("PASS: actual Streamlit chat UI rendered in real Chrome")

        prompt = (
            "نفّذ المهمة فعليًا باستخدام أدوات المتصفح، وليس من معرفتك السابقة: "
            "افتح الموقع العام https://example.com/ في متصفح المساعد، واقرأ عنوان الصفحة "
            "والعنوان الرئيسي الظاهر، ثم أخبرني بالنتيجة. لا تكتفِ بوصف ما ستفعله."
        )
        chat_input = driver.find_element(By.CSS_SELECTOR, '[data-testid="stChatInput"] textarea')
        chat_input.send_keys(prompt)
        chat_input.send_keys(Keys.ENTER)

        def task_completed(d):
            text = d.find_element(By.TAG_NAME, "body").text
            return "Example Domain" in text and len(text) > len(prompt) + 50

        WebDriverWait(driver, 180, poll_frequency=2).until(task_completed)
        body_text = driver.find_element(By.TAG_NAME, "body").text
        report["checks"].append("PASS: actual assistant returned the live website heading/title text")

        # Inspect the real execution log. A correct-sounding answer without browser tool evidence is not a pass.
        expanders = driver.find_elements(By.CSS_SELECTOR, '[data-testid="stExpander"]')
        clicked_log = False
        for expander in expanders:
            if "خطوات التنفيذ الأخيرة" in expander.text:
                button = expander.find_element(By.CSS_SELECTOR, "summary")
                if button.get_attribute("aria-expanded") != "true":
                    button.click()
                clicked_log = True
                break
        if not clicked_log:
            raise AssertionError("Assistant execution log expander was not found; tool execution cannot be independently verified.")
        WebDriverWait(driver, 15).until(
            lambda d: "فتح موقع في متصفح المساعد" in d.find_element(By.TAG_NAME, "body").text
            and "قراءة محتوى الصفحة الحالية" in d.find_element(By.TAG_NAME, "body").text
        )
        body_text = driver.find_element(By.TAG_NAME, "body").text
        if "تم التحقق" not in body_text:
            raise AssertionError("No verified effect status was shown for the real browser task.")
        report["checks"].append("PASS: UI execution log confirms browser open + page read + verified effect")
        report["result"] = "PASS"
        report["assistant_output_excerpt"] = body_text[-1800:]
        return 0
    except Exception as exc:
        report["result"] = "FAIL"
        report["error"] = f"{type(exc).__name__}: {str(exc)[:1000]}"
        raise
    finally:
        report["finished_utc"] = datetime.now(timezone.utc).isoformat()
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        if driver is not None:
            driver.quit()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"REAL ASSISTANT E2E FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
