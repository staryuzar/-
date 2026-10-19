#!/usr/bin/env python3
"""Apply small, reviewable release fixes to an extracted Aurora source tree.

The script is intentionally idempotent. It preserves the original ZIP in the
repository and builds a separately testable patched package artifact.
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import zipfile


SWITCH_WRAPPER = '''def switch_existing_chrome_tab(tab_query: str = "Gmail") -> dict[str, Any]:
    """Switch tabs without leaving the user's text clipboard overwritten."""
    import pyperclip
    try:
        clipboard_before = str(pyperclip.paste() or "")
        clipboard_captured = True
    except Exception:
        clipboard_before = ""
        clipboard_captured = False
    try:
        return _switch_existing_chrome_tab_impl(tab_query)
    finally:
        if clipboard_captured:
            try:
                pyperclip.copy(clipboard_before)
            except Exception:
                pass


'''

READ_WRAPPER = '''def read_existing_chrome_page(window_title: str = "Google Chrome", limit: int = 16000) -> dict[str, Any]:
    """Read the visible page and restore the user's text clipboard afterward."""
    import pyperclip
    try:
        clipboard_before = str(pyperclip.paste() or "")
        clipboard_captured = True
    except Exception:
        clipboard_before = ""
        clipboard_captured = False
    try:
        return _read_existing_chrome_page_impl(window_title, limit)
    finally:
        if clipboard_captured:
            try:
                pyperclip.copy(clipboard_before)
            except Exception:
                pass


'''

REGRESSION_TEST = '''"""Regression tests for preserving the user's clipboard around Chrome helpers."""
import sys
import types
import unittest
from unittest.mock import patch

import windows_tools


class ClipboardPreservationTests(unittest.TestCase):
    def _fake_clipboard(self, initial):
        state = {"value": initial}
        module = types.ModuleType("pyperclip")
        module.paste = lambda: state["value"]
        module.copy = lambda value: state.__setitem__("value", str(value))
        return state, module

    def test_switch_existing_tab_restores_clipboard_on_success(self):
        state, clipboard = self._fake_clipboard("my copied text")
        def operation(query):
            state["value"] = "https://mail.google.com/"
            return {"found": True, "query": query}
        with patch.dict(sys.modules, {"pyperclip": clipboard}), patch.object(
            windows_tools, "_switch_existing_chrome_tab_impl", side_effect=operation
        ):
            result = windows_tools.switch_existing_chrome_tab("Gmail")
        self.assertTrue(result["found"])
        self.assertEqual(state["value"], "my copied text")

    def test_read_existing_page_restores_clipboard_on_exception(self):
        state, clipboard = self._fake_clipboard("important clipboard content")
        def operation(*args):
            state["value"] = "page contents"
            raise RuntimeError("simulated read failure")
        with patch.dict(sys.modules, {"pyperclip": clipboard}), patch.object(
            windows_tools, "_read_existing_chrome_page_impl", side_effect=operation
        ):
            with self.assertRaisesRegex(RuntimeError, "simulated read failure"):
                windows_tools.read_existing_chrome_page("Google Chrome")
        self.assertEqual(state["value"], "important clipboard content")


if __name__ == "__main__":
    unittest.main()
'''


GEMINI_RETRY_TEST = '''"""Bounded retry behavior for temporary Gemini service overload."""
import io
import json
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from gemini_native_client import GeminiNativeError, native_gemini_chat_completion


class FakeResponse:
    status = 200

    def __init__(self, payload):
        self.payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, n=-1):
        return self.payload[:n]


def http_error(status, provider_status, message):
    payload = {"error": {"status": provider_status, "message": message}}
    return HTTPError(
        "https://generativelanguage.googleapis.com/", status, "failure", {},
        io.BytesIO(json.dumps(payload).encode("utf-8")),
    )


def success_response():
    return FakeResponse({"candidates": [{"content": {"parts": [{"text": "ready"}]}}]})


class Gemini503RetryTests(unittest.TestCase):
    def _call(self):
        return native_gemini_chat_completion(
            "TEST_API_KEY", "gemini-3.8-flash", "system",
            [{"role": "user", "content": "hello"}],
        )

    def test_one_503_retries_once_and_then_succeeds(self):
        with patch(
            "gemini_native_client.urlopen",
            side_effect=[http_error(503, "UNAVAILABLE", "temporary high demand"), success_response()],
        ) as mocked, patch("gemini_native_client.time.sleep") as sleep:
            result = self._call()
        self.assertEqual(result.choices[0].message.content, "ready")
        self.assertEqual(mocked.call_count, 2)
        sleep.assert_called_once_with(2)

    def test_persistent_503_stops_after_one_retry(self):
        with patch(
            "gemini_native_client.urlopen",
            side_effect=[
                http_error(503, "UNAVAILABLE", "temporary high demand"),
                http_error(503, "UNAVAILABLE", "still unavailable"),
            ],
        ) as mocked, patch("gemini_native_client.time.sleep") as sleep:
            with self.assertRaises(GeminiNativeError) as caught:
                self._call()
        self.assertEqual(caught.exception.status_code, 503)
        self.assertEqual(mocked.call_count, 2)
        sleep.assert_called_once_with(2)

    def test_429_is_not_retried(self):
        with patch(
            "gemini_native_client.urlopen",
            side_effect=http_error(429, "RESOURCE_EXHAUSTED", "quota"),
        ) as mocked, patch("gemini_native_client.time.sleep") as sleep:
            with self.assertRaises(GeminiNativeError) as caught:
                self._call()
        self.assertEqual(caught.exception.status_code, 429)
        mocked.assert_called_once()
        sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()
'''


def apply_gemini_503_retry(root: Path) -> None:
    """Retry a single Gemini HTTP 503 after two seconds; never auto-retry HTTP 429."""
    source = root / "gemini_native_client.py"
    if not source.is_file():
        raise SystemExit(f"Expected Gemini native client not found: {source}")
    text = source.read_text(encoding="utf-8")
    marker = "# AURORA_GEMINI_503_RETRY: exactly one bounded retry for transient overload."
    if marker not in text:
        import_anchor = "import json\nimport uuid\n"
        if import_anchor not in text:
            raise SystemExit("Could not safely locate Gemini native-client imports for retry patch.")
        text = text.replace(import_anchor, "import json\nimport time\nimport uuid\n", 1)

        old_block = '''    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read(2_000_000).decode("utf-8", "replace")
            status = int(getattr(response, "status", 200))
    except HTTPError as exc:
        try:
            raw = exc.read(64_000).decode("utf-8", "replace")
        except Exception:
            raw = ""
        raise GeminiNativeError(int(exc.code), _safe_google_error(int(exc.code), raw, api_key)) from None
    except URLError as exc:
        reason = str(getattr(exc, "reason", exc)).replace(api_key, "[مفتاح مخفي]")[:260]
        raise GeminiNativeError(None, "تعذر الوصول إلى Google عبر الشبكة أو DNS أو TLS: " + reason) from None
    except TimeoutError:
        raise GeminiNativeError(None, "انتهت مهلة الاتصال بـ Gemini؛ لم تُعد المحاولة تلقائيًا.") from None
    except Exception as exc:
        message = str(exc).replace(api_key, "[مفتاح مخفي]")[:260]
        raise GeminiNativeError(None, type(exc).__name__ + ": " + message) from None
'''
        new_block = '''    # AURORA_GEMINI_503_RETRY: exactly one bounded retry for transient overload.
    retry_503_count = 0
    while True:
        try:
            with urlopen(request, timeout=timeout) as response:
                raw = response.read(2_000_000).decode("utf-8", "replace")
                status = int(getattr(response, "status", 200))
            break
        except HTTPError as exc:
            try:
                raw = exc.read(64_000).decode("utf-8", "replace")
            except Exception:
                raw = ""
            # No function call has been returned, so no tool/effect was run yet.
            # Retry only a temporary 503 once; never retry quota or auth errors.
            if int(exc.code) == 503 and retry_503_count == 0:
                retry_503_count += 1
                time.sleep(2)
                continue
            raise GeminiNativeError(int(exc.code), _safe_google_error(int(exc.code), raw, api_key)) from None
        except URLError as exc:
            reason = str(getattr(exc, "reason", exc)).replace(api_key, "[مفتاح مخفي]")[:260]
            raise GeminiNativeError(None, "تعذر الوصول إلى Google عبر الشبكة أو DNS أو TLS: " + reason) from None
        except TimeoutError:
            raise GeminiNativeError(None, "انتهت مهلة الاتصال بـ Gemini؛ لم تُعد المحاولة تلقائيًا.") from None
        except Exception as exc:
            message = str(exc).replace(api_key, "[مفتاح مخفي]")[:260]
            raise GeminiNativeError(None, type(exc).__name__ + ": " + message) from None
'''
        if old_block not in text:
            raise SystemExit("Could not safely locate the Gemini HTTP transport block; refusing a fuzzy replacement.")
        text = text.replace(old_block, new_block, 1)
        source.write_text(text, encoding="utf-8", newline="\n")

    test_path = root / "tests" / "test_gemini_503_retry.py"
    test_path.parent.mkdir(parents=True, exist_ok=True)
    if not test_path.exists():
        test_path.write_text(GEMINI_RETRY_TEST, encoding="utf-8", newline="\n")

    report = root / "PATCH_REPORT_AR.md"
    if report.exists():
        report_text = report.read_text(encoding="utf-8")
        # Replace an old test count that predates the current 350-test CI matrix.
        # The runtime count belongs in the CI JUnit reports, not in a timeless package note.
        legacy_evidence = "- الدليل: 223 اختبارًا ناجحًا، ومن ضمنها اختبار المسار الأولي الجديد واختبار عدم تكرار الزرع عند إعادة التشغيل."
        if legacy_evidence in report_text:
            report_text = report_text.replace(
                legacy_evidence,
                "- الدليل والعدد الفعلي محفوظان في أحدث windows-test-results.xml على GitHub Actions لكل إصدار Python."
            )
        report_marker = "### معالجة ضغط Gemini المؤقت (HTTP 503)"
        if report_marker not in report_text:
            report_text += (
                "\n\n" + report_marker + "\n"
                "- إذا أعاد Gemini HTTP 503، ينتظر العميل ثانيتين ثم يعيد الطلب مرة واحدة فقط.\n"
                "- لا تتم إعادة المحاولة عند HTTP 429 (الحصة)، أو خطأ المفتاح/الصلاحيات، أو صيغة طلب غير صالحة.\n"
                "- أضيفت اختبارات انحدار لنجاح المحاولة الثانية، وفشل محاولتين، وعدم إعادة 429.\n"
            )
        report.write_text(report_text, encoding="utf-8", newline="\n")



def apply_fixes(root: Path) -> None:
    apply_gemini_503_retry(root)
    source = root / "windows_tools.py"
    text = source.read_text(encoding="utf-8")
    switch_signature = 'def switch_existing_chrome_tab(tab_query: str = "Gmail") -> dict[str, Any]:'
    read_signature = 'def read_existing_chrome_page(window_title: str = "Google Chrome", limit: int = 16000) -> dict[str, Any]:'

    if "_switch_existing_chrome_tab_impl" not in text:
        if switch_signature not in text:
            raise SystemExit("Expected switch_existing_chrome_tab signature was not found; refusing a fuzzy patch.")
        text = text.replace(switch_signature, SWITCH_WRAPPER + switch_signature.replace(
            "def switch_existing_chrome_tab", "def _switch_existing_chrome_tab_impl"
        ), 1)
    if "_read_existing_chrome_page_impl" not in text:
        if read_signature not in text:
            raise SystemExit("Expected read_existing_chrome_page signature was not found; refusing a fuzzy patch.")
        text = text.replace(read_signature, READ_WRAPPER + read_signature.replace(
            "def read_existing_chrome_page", "def _read_existing_chrome_page_impl"
        ), 1)
    source.write_text(text, encoding="utf-8", newline="\n")

    # Windows cmd.exe can misread a UTF-8 BOM before @echo off on older setups.
    batch = root / "DIAGNOSE_WINDOWS.bat"
    if batch.exists():
        data = batch.read_bytes()
        if data.startswith(b"\xef\xbb\xbf"):
            batch.write_bytes(data[3:])

    test_path = root / "tests" / "test_clipboard_preservation.py"
    test_path.parent.mkdir(parents=True, exist_ok=True)
    if not test_path.exists():
        test_path.write_text(REGRESSION_TEST, encoding="utf-8", newline="\n")

    report = root / "PATCH_REPORT_AR.md"
    if report.exists():
        report_text = report.read_text(encoding="utf-8")
        marker = "### إصلاح استعادة الحافظة عند التحكم في Chrome"
        if marker not in report_text:
            report_text += (
                "\n\n" + marker + "\n"
                "- حفظ النص الموجود في الحافظة قبل البحث عن علامة Chrome أو قراءة الصفحة.\n"
                "- استعادة النص الأصلي في مسار النجاح والفشل؛ فشل الاستعادة لا يخفي نتيجة العملية الأساسية.\n"
                "- إضافة اختبارات انحدار لمحاكاة النجاح والاستثناء.\n"
                "- إزالة BOM من DIAGNOSE_WINDOWS.bat قبل بناء الحزمة.\n"
            )
            report.write_text(report_text, encoding="utf-8", newline="\n")


def rebuild_manifest(root: Path) -> None:
    manifest = root / "PACKAGE_SHA256SUMS_AR.txt"
    header = [
        "SHA-256 checksums for Aurora Control Room — patched CI release package",
        "Generated from the patched release tree; this list excludes itself.",
    ]
    lines = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path == manifest:
            continue
        if "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        relative = path.relative_to(root).as_posix()
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        lines.append(f"{digest}  {relative}")
    manifest.write_text("\n".join(header + lines) + "\n", encoding="utf-8", newline="\n")


def build_zip(root: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path == output:
                continue
            if "__pycache__" in path.parts or path.suffix == ".pyc":
                continue
            archive.write(path, arcname=path.relative_to(root).as_posix())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source_dir", type=Path)
    parser.add_argument("--build-zip", type=Path)
    args = parser.parse_args()
    root = args.source_dir.resolve()
    if not root.is_dir():
        raise SystemExit(f"Source directory does not exist: {root}")
    apply_fixes(root)
    if args.build_zip:
        rebuild_manifest(root)
        build_zip(root, args.build_zip.resolve())
        print(f"Built patched package: {args.build_zip.resolve()}")


if __name__ == "__main__":
    main()
