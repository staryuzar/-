"""Strict, provider-independent evidence checks for real assistant browser E2E.

The compact UI action log omits URL arguments and page contents for privacy.
Validate action state, sanitized detailed tool records, and the assistant reply
as three separate evidence sources rather than mixing all visible page text.
"""
from __future__ import annotations


def missing_execution_evidence(
    execution_log_text: str,
    detailed_tool_log_text: str,
    assistant_output_text: str,
) -> list[str]:
    """Return missing mandatory evidence from the correct UI source."""
    steps = " ".join(str(execution_log_text or "").split()).casefold()
    details = " ".join(str(detailed_tool_log_text or "").split()).casefold()
    answer = " ".join(str(assistant_output_text or "").split()).casefold()
    checks = (
        ("فتح موقع في متصفح المساعد" in steps, "browser-open action in compact log"),
        ("قراءة محتوى الصفحة الحالية" in steps, "page-read action in compact log"),
        ("تم التحقق" in steps, "verified-effect marker in compact log"),
        ("example.com" in details, "target domain example.com in sanitized tool details"),
        ("example domain" in answer, "expected page heading Example Domain in assistant reply"),
    )
    return [description for passed, description in checks if not passed]
