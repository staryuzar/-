"""Strict evidence checks for a real assistant browser E2E.

The UI deliberately redacts page text and hides detailed JSON. The test combines
compact visible action labels with persisted, already-redacted tool records and
the actual visible assistant reply. It never trusts the model answer alone.
"""
from __future__ import annotations

from urllib.parse import urlsplit
from typing import Any


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
        urls = [args.get(key) for key in ("url", "current_url", "final_url")]
        urls.extend(result.get(key) for key in ("url", "current_url", "final_url"))
        if any(_has_target_host(url) for url in urls):
            return True
    return False


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
        ("example domain" in answer, "expected page heading Example Domain in assistant reply"),
    )
    return [description for passed, description in checks if not passed]
