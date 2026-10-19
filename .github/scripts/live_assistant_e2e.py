#!/usr/bin/env python3
"""End-to-end test of the real Aurora UI, real provider API, and live public website.

This deliberately does not mock the model, browser, or target website.
"""
from __future__ import annotations
import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import TimeoutException, WebDriverException
from urllib.request import urlopen
from assistant_e2e_contract import missing_execution_evidence


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

        def redact_excerpt(value: str) -> str:
            safe = str(value or "")
            for secret_name in ("GEMINI_API_KEY", "OPENROUTER_API_KEY", "MT5_CREDENTIALS"):
                secret = os.getenv(secret_name, "")
                if secret:
                    safe = safe.replace(secret, "[SECRET REDACTED]")
            safe = re.sub(r"AIza[0-9A-Za-z_-]{20,}", "[GOOGLE KEY REDACTED]", safe)
            safe = re.sub(r"(?i)(api[_-]?key|password|passwd)\s*[:=]\s*\S+", r"\1=[REDACTED]", safe)
            return safe[-3000:]

        failure_markers = (
            "فشل طلب Google Gemini", "فشل طلب Gemini", "تعذر إكمال الطلب:",
            "انتهت مهلة الاتصال بـ Gemini", "تعذر الوصول إلى Google عبر الشبكة",
            "تعذر الاتصال بمزود النموذج", "لم يُرجع مزود النموذج أي اختيار",
            "API_KEY_INVALID", "RESOURCE_EXHAUSTED", "PERMISSION_DENIED",
            "API key not valid", "quota exceeded", "429", "HTTP 401", "HTTP 403",
            "HTTP 404", "HTTP 429", "TimeoutException",
        )

        # First prove that Streamlit actually accepted and rendered this exact prompt.
        try:
            WebDriverWait(driver, 20, poll_frequency=1).until(
                lambda d: prompt in d.find_element(By.TAG_NAME, "body").text
            )
            report["checks"].append("PASS: submitted prompt is visible in the real chat history")
        except TimeoutException:
            body_text = driver.find_element(By.TAG_NAME, "body").text
            report["diagnostic_excerpt"] = redact_excerpt(body_text)
            raise AssertionError("The submitted prompt did not appear in chat history; input submission was not verified.")

        def task_completed(d):
            text = d.find_element(By.TAG_NAME, "body").text
            if "Example Domain" in text and len(text) > len(prompt) + 50:
                return "success"
            lower = text.lower()
            if any(marker.lower() in lower for marker in failure_markers):
                report["diagnostic_excerpt"] = redact_excerpt(text)
                return "provider_or_app_error"
            return False

        try:
            task_state = WebDriverWait(driver, 180, poll_frequency=2).until(task_completed)
        except TimeoutException:
            body_text = driver.find_element(By.TAG_NAME, "body").text
            report["diagnostic_excerpt"] = redact_excerpt(body_text)
            report["result"] = "FAIL"
            report["failure_stage"] = "waiting_for_model_or_tool_result"
            raise AssertionError("Timed out waiting for the real assistant result; the sanitized visible UI snapshot is in the report.")

        body_text = driver.find_element(By.TAG_NAME, "body").text
        if task_state != "success":
            report["result"] = "FAIL"
            lower_body = body_text.lower()
            if "resource_exhausted" in lower_body or "quota exceeded" in lower_body or "http 429" in lower_body or "429" in lower_body:
                report["failure_stage"] = "provider_quota_exhausted"
                report["failure_class"] = "provider_quota_exhausted"
                report["diagnosis"] = "The real UI reports provider quota exhaustion (HTTP 429). Do not retry automatically; this is not a local app/Chrome startup failure."
            elif "http 503" in lower_body or "unavailable" in lower_body:
                report["failure_stage"] = "provider_temporarily_unavailable"
                report["failure_class"] = "provider_transient_unavailable"
                report["diagnosis"] = "The provider returned a temporary unavailable error. The client may perform only its bounded HTTP 503 retry; do not treat this as browser-tool success."
            else:
                report["failure_stage"] = "provider_or_app_error_visible_in_ui"
                report["failure_class"] = "provider_or_application_error"
            raise AssertionError("The real assistant UI displayed a provider/application error instead of the target website result.")
        report["checks"].append("PASS: actual assistant returned the live website heading/title text")

        # Inspect the real execution log. A correct-sounding answer without browser tool evidence is not a pass.
        expanders = driver.find_elements(By.CSS_SELECTOR, '[data-testid="stExpander"]')
        execution_log_expander = None
        for expander in expanders:
            if "خطوات التنفيذ الأخيرة" in expander.text:
                button = expander.find_element(By.CSS_SELECTOR, "summary")
                if button.get_attribute("aria-expanded") != "true":
                    button.click()
                execution_log_expander = expander
                break
        if execution_log_expander is None:
            raise AssertionError("Assistant execution log expander was not found; tool execution cannot be independently verified.")

        # Validate only text inside the expanded execution log. The chat response,
        # prompt, page chrome, or a different log entry must not satisfy this gate.
        def verified_execution_log(_driver):
            log_text = execution_log_expander.text
            return log_text if not missing_execution_evidence(log_text) else False

        try:
            execution_log_text = WebDriverWait(driver, 20, poll_frequency=1).until(verified_execution_log)
        except TimeoutException:
            execution_log_text = execution_log_expander.text
            missing = missing_execution_evidence(execution_log_text)
            report["execution_log_excerpt"] = redact_excerpt(execution_log_text)
            report["missing_execution_evidence"] = missing
            raise AssertionError(
                "The expanded assistant execution log did not independently prove the real browser effect. "
                "Missing evidence: " + ", ".join(missing)
            )

        report["execution_evidence"] = {
            "target_domain_in_execution_log": "example.com" in execution_log_text.casefold(),
            "expected_page_heading_in_execution_log": "example domain" in execution_log_text.casefold(),
            "browser_open_action_in_execution_log": "فتح موقع في متصفح المساعد" in execution_log_text,
            "page_read_action_in_execution_log": "قراءة محتوى الصفحة الحالية" in execution_log_text,
            "verified_effect_in_execution_log": "تم التحقق" in execution_log_text,
        }
        report["checks"].append("PASS: execution log itself proves example.com open, Example Domain read, and verified effect")
        report["result"] = "PASS"
        final_body_text = driver.find_element(By.TAG_NAME, "body").text
        report["assistant_output_excerpt"] = redact_excerpt(final_body_text[-1800:])
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
