#!/usr/bin/env python3
"""Standard-library tests for strict live-assistant E2E evidence validation."""
from __future__ import annotations

import unittest

from assistant_e2e_contract import missing_execution_evidence


GOOD_LOG = """
فتح موقع في متصفح المساعد: https://example.com/
قراءة محتوى الصفحة الحالية: Example Domain
تم التحقق من الأثر: تم فتح الموقع وقراءة العنوان
"""


class ExecutionEvidenceContractTests(unittest.TestCase):
    def test_complete_log_passes(self):
        self.assertEqual(missing_execution_evidence(GOOD_LOG), [])

    def test_model_answer_alone_is_not_execution_evidence(self):
        # Even a correct-sounding chat answer must not substitute for tool logs.
        self.assertEqual(
            set(missing_execution_evidence("The answer is Example Domain")),
            {
                "target domain example.com",
                "browser-open action",
                "page-read action",
                "verified-effect marker",
            },
        )

    def test_correct_page_text_without_target_url_is_rejected(self):
        missing = missing_execution_evidence(
            "فتح موقع في متصفح المساعد؛ قراءة محتوى الصفحة الحالية: Example Domain؛ تم التحقق"
        )
        self.assertIn("target domain example.com", missing)

    def test_correct_url_without_page_heading_is_rejected(self):
        missing = missing_execution_evidence(
            "فتح موقع في متصفح المساعد https://example.com/؛ "
            "قراءة محتوى الصفحة الحالية: a different page; تم التحقق"
        )
        self.assertIn("expected page heading Example Domain", missing)

    def test_actions_without_verified_effect_are_rejected(self):
        missing = missing_execution_evidence(
            "فتح موقع في متصفح المساعد https://example.com/؛ "
            "قراءة محتوى الصفحة الحالية: Example Domain"
        )
        self.assertEqual(missing, ["verified-effect marker"])

    def test_matching_is_case_insensitive_for_web_evidence(self):
        log = GOOD_LOG.replace("example.com", "EXAMPLE.COM").replace("Example Domain", "EXAMPLE DOMAIN")
        self.assertEqual(missing_execution_evidence(log), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
