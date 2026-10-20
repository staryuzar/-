#!/usr/bin/env python3
"""One explicitly triggered live E2E of Aurora chat -> Gemini tool call -> Chrome -> final answer.

Only example.com is used. No sign-in, form submit, message send, or trading occurs.
This script issues a single user task; it does not re-submit after provider failures.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = REPO_ROOT / "ci_live_e2e_source"
sys.path.insert(0, str(SOURCE_ROOT))
sys.path.insert(0, str(REPO_ROOT / ".github" / "scripts"))

from assistant_e2e_contract import (  # noqa: E402
    assistant_reply_evidence_diagnostics,
    load_persisted_tool_records,
    missing_execution_evidence,
)
from selenium import webdriver  # noqa: E402
from selenium.webdriver.common.by import By  # noqa: E402
from selenium.webdriver.common.keys import Keys  # noqa: E402
from selenium.webdriver.support.ui import WebDriverWait  # noqa: E402

PROMPT = (
    'افتح https://example.com/ واقرأ عنوان الصفحة ونصها الظاهر باستخدام أدوات المتصفح. '
    'أجب بالعربية مع حقلي "عنوان الصفحة:" و"نص الصفحة:"، واحتفظ بجملة الصفحة عن أمثلة التوثيق '
    'دون الحاجة إلى إذن كما تظهر فعلًا. لا تنقر أي عنصر ولا تسجّل دخولًا ولا ترسل شيئًا.'
)
PORT = 8766
BASE_URL = f"http://127.0.0.1:{PORT}"
REPORT_PATH = Path.cwd() / "live-assistant-browser-e2e-report.txt"


def write_report(lines: list[str]) -> None:
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def safe_report_header(status: str, detail: str = "") -> list[str]:
    return [
        "Aurora live assistant browser E2E",
        f"status={status}",
        "target=https://example.com/",
        "provider=Gemini",
        "actions=read-only; no login, message send, form submit, or trading",
        "test_submission_count=1",
        "HTTP 429 retry policy=none",
        *([f"detail={detail}"] if detail else []),
    ]


def app_health(timeout: float = 1.5) -> bool:
    try:
        with urllib.request.urlopen(BASE_URL + "/_stcore/health", timeout=timeout) as response:
            return int(response.status) == 200
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return False


def visible_text(driver) -> str:
    try:
        return str(driver.find_element(By.TAG_NAME, "body").text or "")
    except Exception:
        return ""


def expand_step_log(driver) -> None:
    try:
        summaries = driver.find_elements(By.CSS_SELECTOR, '[data-testid="stExpander"] summary')
    except Exception:
        return
    for summary in summaries:
        try:
            title = str(summary.text or "").strip()
            if not title.startswith("خطوات التنفيذ الأخيرة"):
                continue
            details = summary.find_element(By.XPATH, "..")
            if details.get_attribute("open") is None:
                summary.click()
            return
        except Exception:
            continue


def visible_assistant_reply(driver) -> str:
    contents: list[str] = []
    selectors = (
        '[data-testid="stChatMessage"] [data-testid="stChatMessageContent"]',
        '[data-testid="stChatMessage"]',
    )
    for selector in selectors:
        try:
            for element in driver.find_elements(By.CSS_SELECTOR, selector):
                value = str(element.text or "").strip()
                if value and PROMPT not in value:
                    contents.append(value)
        except Exception:
            continue
        if contents:
            break
    return contents[-1] if contents else ""


def read_records(database: Path) -> list[dict]:
    try:
        return load_persisted_tool_records(
            database,
            PROMPT,
            timeout_seconds=0,
            poll_interval=0.01,
        )
    except AssertionError:
        return []


def provider_failure_category(text: str) -> str:
    body = str(text or "").casefold()
    if any(marker in body for marker in ("http 429", "resource_exhausted", "استُنفدت الحصة", "استنفدت الحصة", "حد استخدام مؤقت")):
        return "provider_quota_or_http_429"
    if any(marker in body for marker in ("فشل طلب google gemini", "تعذر الاتصال بمزود النموذج", "انتهت مهلة الاتصال بالنموذج", "لم يُرجع مزود النموذج أي اختيار")):
        return "provider_request_failed"
    return ""


def main() -> int:
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key or any(marker in api_key.casefold() for marker in ("your_api_key", "placeholder", "changeme", "replace_me")):
        write_report(safe_report_header("BLOCKED", "GEMINI_API_KEY is not configured as a non-placeholder secret; no API request was sent."))
        print("RESULT: BLOCKED — required Gemini secret is missing or is a placeholder; no API request was sent.")
        return 2

    if not (SOURCE_ROOT / "app.py").is_file():
        write_report(safe_report_header("FAIL", "prepared application source was not found."))
        print("RESULT: FAIL — prepared app source missing; no API request was sent.")
        return 2

    runner_temp = Path(os.environ.get("RUNNER_TEMP") or os.environ.get("TEMP") or Path.cwd())
    run_id = re.sub(r"[^A-Za-z0-9_-]", "_", os.environ.get("GITHUB_RUN_ID", "manual"))
    attempt = re.sub(r"[^A-Za-z0-9_-]", "_", os.environ.get("GITHUB_RUN_ATTEMPT", "1"))
    data_dir = runner_temp / f"aurora-live-assistant-e2e-{run_id}-{attempt}"
    data_dir.mkdir(parents=True, exist_ok=False)
    database = data_dir / "aurora.sqlite3"

    child_env = os.environ.copy()
    child_env["AI_PROVIDER"] = "gemini"
    child_env["GEMINI_MODEL"] = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")
    child_env["AURORA_DATA_DIR"] = str(data_dir)
    child_env["AURORA_CHROME_DEBUGGER_ADDRESS"] = ""
    child_env["PYTHONUNBUFFERED"] = "1"

    server_log = runner_temp / f"aurora-live-assistant-server-{run_id}-{attempt}.log"
    server = None
    driver = None
    deadline_seconds = max(120, min(240, int(os.environ.get("AURORA_LIVE_E2E_TIMEOUT_SECONDS", "210"))))
    try:
        with server_log.open("w", encoding="utf-8") as log_handle:
            server = subprocess.Popen(
                [
                    sys.executable, "-m", "streamlit", "run", "app.py",
                    "--server.address", "127.0.0.1",
                    "--server.port", str(PORT),
                    "--server.headless", "true",
                    "--browser.gatherUsageStats", "false",
                ],
                cwd=str(SOURCE_ROOT),
                env=child_env,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
            )

        ready_deadline = time.monotonic() + 45
        while time.monotonic() < ready_deadline:
            if server.poll() is not None:
                raise RuntimeError("streamlit_process_exited_before_health")
            if app_health():
                break
            time.sleep(1)
        else:
            raise RuntimeError("streamlit_health_timeout")

        options = webdriver.ChromeOptions()
        options.add_argument("--headless=new")
        options.add_argument("--disable-gpu")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--no-sandbox")
        options.add_argument("--window-size=1440,1200")
        options.add_argument("--lang=ar")
        driver = webdriver.Chrome(options=options)
        driver.set_page_load_timeout(25)
        driver.get(BASE_URL)

        chat_selector = '[data-testid="stChatInput"] textarea'
        chat_box = WebDriverWait(driver, 40).until(
            lambda d: next(
                (e for e in d.find_elements(By.CSS_SELECTOR, chat_selector) if e.is_displayed() and e.is_enabled()),
                False,
            )
        )
        chat_box.send_keys(PROMPT)
        chat_box.send_keys(Keys.ENTER)

        task_deadline = time.monotonic() + deadline_seconds
        last_missing: list[str] = ["persisted tool log for submitted prompt"]
        last_diagnostics = {
            "reply_nonempty": False,
            "has_title_field": False,
            "has_expected_title_identity": False,
            "has_page_text_field": False,
            "has_known_page_text": False,
        }
        record_count = 0
        tool_names: list[str] = []
        while time.monotonic() < task_deadline:
            body = visible_text(driver)
            expand_step_log(driver)
            body = visible_text(driver)
            answer = visible_assistant_reply(driver)
            records = read_records(database)
            record_count = len(records)
            tool_names = [str(r.get("tool", ""))[:80] for r in records if r.get("tool")]
            last_diagnostics = assistant_reply_evidence_diagnostics(answer)
            last_missing = missing_execution_evidence(body, records, answer) if records else [
                "persisted tool log for submitted prompt"
            ]

            if not last_missing:
                lines = safe_report_header("PASS")
                lines.extend([
                    f"model={child_env['GEMINI_MODEL']}",
                    "streamlit_ui_started=true",
                    "prompt_submitted=true",
                    "target_page_open_verified=true",
                    "target_page_read_verified=true",
                    "final_answer_matches_title_and_known_body=true",
                    f"persisted_tool_record_count={record_count}",
                    "persisted_tool_names=" + ",".join(tool_names),
                    "reply_title_field=true",
                    "reply_expected_title=true",
                    "reply_page_text_field=true",
                    "reply_known_page_text=true",
                ])
                write_report(lines)
                print("PASS: real Streamlit chat accepted one test task.")
                print("PASS: persisted tool log confirms a verified browser_open_url to example.com.")
                print("PASS: persisted tool log confirms browser_read_page on example.com.")
                print("PASS: actual assistant reply contains the page title and known page-body content.")
                print("RESULT: PASS — real Gemini -> tool call -> Chrome -> final answer E2E.")
                return 0

            category = provider_failure_category(body)
            if category:
                lines = safe_report_header("FAIL", category)
                lines.extend([
                    f"model={child_env['GEMINI_MODEL']}",
                    "streamlit_ui_started=true",
                    "prompt_submitted=true",
                    "tool_record_count=" + str(record_count),
                    "tool_names=" + ",".join(tool_names),
                    "No second user submission or automatic repeat was made.",
                ])
                write_report(lines)
                print(f"RESULT: FAIL — {category}; no user prompt was re-submitted.")
                return 2
            time.sleep(2)

        lines = safe_report_header("FAIL", "end_to_end_timeout")
        lines.extend([
            f"model={child_env['GEMINI_MODEL']}",
            "streamlit_ui_started=true",
            "prompt_submitted=true",
            f"persisted_tool_record_count={record_count}",
            "persisted_tool_names=" + ",".join(tool_names),
            "missing_evidence=" + "|".join(last_missing[:9]),
            "reply_diagnostics=" + ",".join(f"{k}:{str(v).lower()}" for k, v in last_diagnostics.items()),
            "No second user submission or automatic repeat was made.",
        ])
        write_report(lines)
        print("RESULT: FAIL — the full E2E evidence contract was not satisfied before timeout.")
        print("Missing signals: " + "; ".join(last_missing[:9]))
        return 2

    except Exception as exc:
        category = str(exc) if str(exc) in {
            "streamlit_process_exited_before_health",
            "streamlit_health_timeout",
        } else type(exc).__name__
        lines = safe_report_header("FAIL", category)
        lines.extend([
            "No provider response text, API key, raw exception text, or server log was written to the report.",
            "No second user submission or automatic repeat was made.",
        ])
        write_report(lines)
        print(f"RESULT: FAIL — {category}; sensitive diagnostics suppressed.")
        return 2
    finally:
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass
        if server is not None and server.poll() is None:
            if os.name == "nt":
                try:
                    subprocess.run(
                        ["taskkill", "/PID", str(server.pid), "/T", "/F"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=12,
                        check=False,
                    )
                except Exception:
                    server.kill()
            else:
                server.terminate()
                try:
                    server.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    server.kill()


if __name__ == "__main__":
    raise SystemExit(main())
