"""Strict, provider-independent evidence checks for real assistant browser E2E.

This module does not simulate or claim a live model/tool call. It prevents the
live E2E harness from passing unless the visible execution log itself contains
the target domain, page heading, browser-open/read actions, and verified effect.
"""
from __future__ import annotations


_REQUIRED_EVIDENCE = (
    ("example.com", "target domain example.com"),
    ("example domain", "expected page heading Example Domain"),
    ("فتح موقع في متصفح المساعد", "browser-open action"),
    ("قراءة محتوى الصفحة الحالية", "page-read action"),
    ("تم التحقق", "verified-effect marker"),
)


def missing_execution_evidence(execution_log_text: str) -> list[str]:
    """Return missing mandatory signals from the execution log only."""
    normalized = " ".join(str(execution_log_text or "").split()).casefold()
    return [label for token, label in _REQUIRED_EVIDENCE if token.casefold() not in normalized]
