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
from assistant_e2e_contract import (
    assistant_reply_evidence_diagnostics,
    classify_submission_evidence,
    assistant_reply_has_known_page_text,
    assistant_reply_has_page_identity,
    assistant_reply_has_page_text_field,
    assistant_reply_has_page_title,
    load_persisted_tool_records,
    missing_execution_evidence,
)



def visible_assistant_reply(driver, prompt: str) -> str:
    """Return visible chat-message text excluding the exact user prompt bubble."""
    replies = []
    for message in driver.find_elements(By.CSS_SELECTOR, '[data-testid="stChatMessage"]'):
        text = str(message.text or "").strip()
        if text and prompt not in text:
            replies.append(text)
    return "\n".join(replies)


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
        "test_type": "REAL_E2E_NO_MOCKS_SKILL_PACK_SEARCH",
        "target": "DuckDuckGo live search followed by https://example.com/",
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

        # One bounded rerun is allowed after the previous real-provider HTTP 503; this is not a mocked retry.\n        prompt = (\n            "نفّذ المهمة فعليًا باستخدام أدوات المتصفح، وليس من معرفتك السابقة. الخطوة الأولى إلزامية: "
            "استخدم أداة البحث browser_search_web للبحث عن site:example.com Example Domain، ولا تتجاوز البحث. "
            "بعد ذلك افتح الموقع العام https://example.com/ في متصفح المساعد، ثم اقرأ عنوان المستند "
            "وأول جملة من النص الظاهر في الصفحة. أجب بحقلين مستقلين: Document title: أو عنوان المستند:؛ "
            "وPage text: أو نص الصفحة:. انقل النص كما أعادته أداة القراءة دون تخمين؛ "
            "إذا كان المتصفح قد ترجم الصفحة، انقل الترجمة الظاهرة بأمانة. النص الإنجليزي المتوقع إذا ظهر "
            "بلغة المصدر هو: This domain is for use in documentation examples without needing permission."
        )
        body_before_send = driver.find_element(By.TAG_NAME, "body").text
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

        # Some Aurora reruns intentionally hide the submitted user bubble while the
        # execution planner is active. Accept a newly appearing processing marker as
        # provisional submit evidence only; final proof still requires the exact prompt
        # in persisted SQLite tool records and verified browser effects.
        try:
            def submission_evidence(d):
                current_body = d.find_element(By.TAG_NAME, "body").text
                return classify_submission_evidence(current_body, body_before_send, prompt) or False

            submission_state = WebDriverWait(driver, 25, poll_frequency=1).until(submission_evidence)
            report["submission_evidence"] = submission_state
            if submission_state == "prompt_visible":
                report["checks"].append("PASS: submitted prompt is visible in the real chat history")
            elif submission_state == "processing_indicator_only":
                report["checks"].append(
                    "PASS: new assistant planning indicator appeared after submit; exact prompt and effects still require final SQLite contract"
                )
        except TimeoutException:
            body_text = driver.find_element(By.TAG_NAME, "body").text
            report["diagnostic_excerpt"] = redact_excerpt(body_text)
            report["submission_evidence"] = "not_observed"
            raise AssertionError(
                "Neither the exact submitted prompt nor a new assistant processing indicator appeared; submission was not verified."
            )

        def task_completed(d):
            text = d.find_element(By.TAG_NAME, "body").text
            reply = visible_assistant_reply(d, prompt)
            # Preserve criterion-level booleans in the report while waiting.
            report["assistant_reply_evidence_diagnostics"] = assistant_reply_evidence_diagnostics(reply)
            report["assistant_reply_chars"] = len(reply)
            report["assistant_chat_message_count"] = len(
                d.find_elements(By.CSS_SELECTOR, '[data-testid="stChatMessage"]')
            )
            if assistant_reply_has_page_identity(reply) or assistant_reply_has_known_page_text(reply):
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
            reply_snapshot = visible_assistant_reply(driver, prompt)
            report["assistant_reply_evidence_diagnostics"] = assistant_reply_evidence_diagnostics(reply_snapshot)
            report["assistant_reply_chars"] = len(reply_snapshot)
            report["assistant_reply_excerpt"] = redact_excerpt(reply_snapshot[-1800:])
            report["assistant_chat_message_count"] = len(
                driver.find_elements(By.CSS_SELECTOR, '[data-testid="stChatMessage"]')
            )
            report["result"] = "FAIL"
            report["failure_stage"] = "waiting_for_model_or_tool_result"
            raise AssertionError("Timed out waiting for the real assistant result; per-condition evidence booleans and a sanitized reply excerpt are in the report.")

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

        # The compact execution list intentionally hides URLs and page text.
        # First require both browser action labels and a verified-effect marker there.
        def verified_execution_log(_driver):
            log_text = execution_log_expander.text
            required = (
                "فتح موقع في متصفح المساعد",
                "قراءة محتوى الصفحة الحالية",
                "تم التحقق",
            )
            return log_text if all(marker in log_text for marker in required) else False

        try:
            execution_log_text = WebDriverWait(driver, 20, poll_frequency=1).until(verified_execution_log)
        except TimeoutException:
            execution_log_text = execution_log_expander.text
            report["execution_log_excerpt"] = redact_excerpt(execution_log_text)
            missing = [m for m in (
                "فتح موقع في متصفح المساعد",
                "قراءة محتوى الصفحة الحالية",
                "تم التحقق",
            ) if m not in execution_log_text]
            report["missing_execution_evidence"] = missing
            raise AssertionError(
                "The compact execution log did not show both browser actions and a verified effect. Missing: "
                + ", ".join(missing)
            )

        # The UI intentionally redacts page content and hides nested JSON values.
        # Read the app's own persisted, already-redacted tool records for this exact prompt.
        assistant_reply = visible_assistant_reply(driver, prompt)
        data_dir = os.getenv("AURORA_DATA_DIR", "").strip()
        tool_records = load_persisted_tool_records(Path(data_dir) / "aurora.sqlite3", prompt)
        missing = missing_execution_evidence(
            execution_log_text,
            tool_records,
            assistant_reply,
        )
        search_records = [r for r in tool_records if r.get("tool") == "browser_search_web"]
        verified_search_record = any(
            isinstance(r.get("result"), dict)
            and r["result"].get("ok") is True
            and r["result"].get("effect_verified") is True
            for r in search_records
        )
        report["search_evidence"] = {
            "persisted_successful_search_record": verified_search_record,
            "search_record_count": len(search_records),
        }
        if not verified_search_record:
            missing.append("verified browser_search_web search record")
        if missing:
            report["missing_execution_evidence"] = missing
            report["execution_log_excerpt"] = redact_excerpt(execution_log_text)
            # Never put full tool args/results or page content into the CI report.
            report["persisted_tool_record_count"] = len(tool_records)
            raise AssertionError(
                "The evidence contract failed across the compact execution log, persisted redacted tool records, "
                "and assistant reply. Missing evidence: " + ", ".join(missing)
            )

        open_records = [r for r in tool_records if r.get("tool") == "browser_open_url"]
        read_records = [r for r in tool_records if r.get("tool") == "browser_read_page"]
        report["execution_evidence"] = {
            "persisted_successful_search_record": verified_search_record,
            "persisted_successful_open_url_record": any(
                isinstance(r.get("result"), dict) and r["result"].get("ok") is True
                and r["result"].get("effect_verified") is True for r in open_records
            ),
            "persisted_successful_read_page_record": any(
                isinstance(r.get("result"), dict) and r["result"].get("ok") is True
                and r["result"].get("effect_verified") is True for r in read_records
            ),
            "target_host_found_in_persisted_redacted_records": True,
            "document_title_and_page_text_phrase_returned": (
                assistant_reply_has_page_title(assistant_reply)
                and assistant_reply_has_page_identity(assistant_reply)
                and assistant_reply_has_page_text_field(assistant_reply)
                and assistant_reply_has_known_page_text(assistant_reply)
            ),
            "browser_open_action_in_execution_log": "فتح موقع في متصفح المساعد" in execution_log_text,
            "page_read_action_in_execution_log": "قراءة محتوى الصفحة الحالية" in execution_log_text,
            "verified_effect_in_execution_log": "تم التحقق" in execution_log_text,
        }
        report["persisted_tool_record_count"] = len(tool_records)
        report["checks"].append("PASS: compact UI action log, persisted redacted tool records, and assistant reply prove the real browser effect")
        report["result"] = "PASS"
        report["assistant_output_excerpt"] = redact_excerpt(assistant_reply[-1800:])
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
