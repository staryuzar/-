"""Strict evidence checks for a real assistant browser E2E.

The UI deliberately redacts page text and hides detailed JSON. The test combines
compact visible action labels with persisted, already-redacted tool records and
the actual visible assistant reply. It never trusts the model answer alone.
"""
from __future__ import annotations

import json
import re
import sqlite3
from contextlib import closing
import time
import unicodedata
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


def load_persisted_tool_records(
    database_path: str | Path,
    prompt: str,
    *,
    timeout_seconds: float = 15.0,
    poll_interval: float = 1.0,
) -> list[dict]:
    """Read the persisted sanitized tool log for the row containing this exact prompt.

    The connection is read-only; the helper does not mutate the assistant database.
    """
    database = Path(database_path)
    deadline = time.monotonic() + max(0.0, float(timeout_seconds))
    last_reason = "database file not found"
    while True:
        if database.is_file():
            try:
                uri = database.resolve().as_uri() + "?mode=ro"
                with closing(sqlite3.connect(uri, uri=True, timeout=5)) as connection:
                    rows = connection.execute(
                        "SELECT messages_json, log_json FROM conversations ORDER BY updated_at DESC LIMIT 30"
                    ).fetchall()
                for messages_json, log_json in rows:
                    try:
                        messages = json.loads(messages_json or "[]")
                        logs = json.loads(log_json or "[]")
                    except (TypeError, json.JSONDecodeError):
                        continue
                    if not isinstance(messages, list):
                        continue
                    matched = any(
                        isinstance(message, dict)
                        and message.get("role") == "user"
                        and str(prompt or "") in str(message.get("content") or "")
                        for message in messages
                    )
                    if matched:
                        if not isinstance(logs, list):
                            raise AssertionError("Persisted tool log is not a JSON list.")
                        return [entry for entry in logs if isinstance(entry, dict)]
                last_reason = "exact submitted prompt was not present in recent conversation rows"
            except sqlite3.Error as exc:
                last_reason = f"SQLite read unavailable ({type(exc).__name__})"
        if time.monotonic() >= deadline:
            break
        time.sleep(max(0.01, min(float(poll_interval), deadline - time.monotonic())))
    raise AssertionError("Could not retrieve the persisted tool log for this E2E prompt: " + last_reason)


def _has_target_host(value: Any) -> bool:
    try:
        parsed = urlsplit(str(value or "").strip())
        return parsed.scheme in {"http", "https"} and (parsed.hostname or "").casefold().rstrip(".") == "example.com"
    except (TypeError, ValueError):
        return False


def _successful_tool_on_target(records: list[dict], name: str) -> bool:
    for record in records:
        if not isinstance(record, dict) or record.get("tool") != name:
            continue
        args = record.get("args") if isinstance(record.get("args"), dict) else {}
        result = record.get("result") if isinstance(record.get("result"), dict) else {}
        if result.get("ok") is not True or result.get("effect_verified") is not True:
            continue
        arg_urls = [args.get(key) for key in ("url", "current_url", "final_url") if args.get(key)]
        result_urls = [result.get(key) for key in ("url", "current_url", "final_url") if result.get(key)]
        if name == "browser_open_url":
            # Verify the requested URL and the observed final URL independently.
            if arg_urls and any(_has_target_host(url) for url in arg_urls) and any(
                _has_target_host(url) for url in result_urls
            ):
                return True
        elif name == "browser_read_page":
            # Page-read normally takes no URL argument; its reported current URL is authoritative.
            if (not arg_urls or all(_has_target_host(url) for url in arg_urls)) and any(
                _has_target_host(url) for url in result_urls
            ):
                return True
    return False


def _normalized_reply(value: Any) -> str:
    """Normalize common Arabic diacritics/alef variants without erasing words."""
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    text = re.sub(r"[\u064B-\u065F\u0670\u0640]", "", text)
    text = text.translate(str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ى": "ي"}))
    return " ".join(text.split())


def assistant_reply_has_page_title(value: Any) -> bool:
    text = _normalized_reply(value)
    return any(label in text for label in (
        "document title:", "عنوان المستند:", "عنوان الصفحة:", "العنوان:",
        "العنوان/الافتتاحية:"
    ))


def assistant_reply_has_page_text_field(value: Any) -> bool:
    text = _normalized_reply(value)
    return any(label in text for label in (
        "page text:", "نص الصفحة:", "محتوى الصفحة:", "النص الظاهر في الصفحة",
        "النص والعنوان الرئيسي الظاهر"
    ))


def assistant_reply_has_page_identity(value: Any) -> bool:
    """Require the title field and a known original/translated title value."""
    text = _normalized_reply(value)
    has_title_field = assistant_reply_has_page_title(text)
    has_known_title = any(label in text for label in (
        "example domain", "مثال النطاق", "نطاق المثال", "domain example",
        "مجال مثال", "مثال المجال"
    ))
    return has_title_field and has_known_title


def assistant_reply_has_known_page_text(value: Any) -> bool:
    text = _normalized_reply(value)
    known_english = "this domain is for use in documentation examples without needing permission"
    known_arabic = "هذا النطاق مخصص للاستخدام في امثلة التوثيق دون الحاجة الي اذن"
    return known_english in text or known_arabic in text


def classify_submission_evidence(body_text: Any, baseline_body_text: Any, prompt: str) -> str | None:
    """Classify transient prompt-acceptance evidence; never treat it as final task success."""
    body = str(body_text or "")
    baseline = str(baseline_body_text or "")
    requested = str(prompt or "")
    if requested and requested in body:
        return "prompt_visible"
    # Aurora may temporarily hide the submitted user bubble while the assistant is
    # planning. Accept only a newly appeared, explicit processing marker; the strict
    # end-of-task SQLite/tool contract still proves the exact prompt and real effects.
    indicators = (
        "يخطط المساعد للخطوة التالية ويسترجع سياق المهمة المحفوظ",
        "يخطط المساعد للخطوة التالية",
    )
    for indicator in indicators:
        if indicator in body and indicator not in baseline:
            return "processing_indicator_only"
    return None


def assistant_reply_evidence_diagnostics(value: Any) -> dict[str, bool]:
    """Return non-secret evidence booleans to diagnose E2E timeouts without weakening checks."""
    return {
        "reply_nonempty": bool(str(value or "").strip()),
        "has_title_field": assistant_reply_has_page_title(value),
        "has_expected_title_identity": assistant_reply_has_page_identity(value),
        "has_page_text_field": assistant_reply_has_page_text_field(value),
        "has_known_page_text": assistant_reply_has_known_page_text(value),
    }


def missing_execution_evidence(
    execution_log_text: str,
    tool_records: list[dict],
    assistant_output_text: str,
) -> list[str]:
    """Return missing mandatory signals from their distinct evidence sources."""
    steps = " ".join(str(execution_log_text or "").split()).casefold()
    answer = " ".join(str(assistant_output_text or "").split()).casefold()
    records = tool_records if isinstance(tool_records, list) else []
    checks = (
        ("فتح موقع في متصفح المساعد" in steps, "browser-open action in compact log"),
        ("قراءة محتوى الصفحة الحالية" in steps, "page-read action in compact log"),
        ("تم التحقق" in steps, "verified-effect marker in compact log"),
        (_successful_tool_on_target(records, "browser_open_url"), "successful browser_open_url record on example.com"),
        (_successful_tool_on_target(records, "browser_read_page"), "successful browser_read_page record on example.com"),
        (assistant_reply_has_page_title(answer), "Document title field in assistant reply"),
        (assistant_reply_has_page_identity(answer), "Example Domain title/identity in assistant reply"),
        (assistant_reply_has_page_text_field(answer), "Page text field in assistant reply"),
        (
            assistant_reply_has_known_page_text(answer),
            "known example.com body phrase in English or verified Arabic translation",
        ),
    )
    return [description for passed, description in checks if not passed]
