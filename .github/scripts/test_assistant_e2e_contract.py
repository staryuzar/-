#!/usr/bin/env python3
"""Standard-library tests for strict live-assistant E2E evidence validation."""
from __future__ import annotations

import unittest

from assistant_e2e_contract import missing_execution_evidence


GOOD_STEPS = """
فتح موقع في متصفح المساعد · تم التحقق
قراءة محتوى الصفحة الحالية · تم التحقق
"""
GOOD_DETAILS = """
browser_open_url: url=https://example.com/
browser_read_page: url=https://example.com/
"""
GOOD_REPLY = "تم فتح Example Domain وقراءة العنوان الرئيسي."


class ExecutionEvidenceContractTests(unittest.TestCase):
    def check(self, steps=GOOD_STEPS, details=GOOD_DETAILS, reply=GOOD_REPLY):
        return missing_execution_evidence(steps, details, reply)

    def test_complete_distributed_evidence_passes(self):
        self.assertEqual(self.check(), [])

    def test_model_answer_alone_is_not_execution_evidence(self):
        missing = set(self.check(steps="", details="", reply="The answer is Example Domain"))
        self.assertEqual(
            missing,
            {
                "browser-open action in compact log",
                "page-read action in compact log",
                "verified-effect marker in compact log",
                "target domain example.com in sanitized tool details",
            },
        )

    def test_correct_reply_without_target_url_is_rejected(self):
        missing = self.check(details="browser_open_url: url=https://other.example/")
        self.assertIn("target domain example.com in sanitized tool details", missing)

    def test_correct_url_without_expected_heading_in_reply_is_rejected(self):
        missing = self.check(reply="The page heading was different.")
        self.assertIn("expected page heading Example Domain in assistant reply", missing)

    def test_actions_without_verified_effect_are_rejected(self):
        missing = self.check(steps="فتح موقع في متصفح المساعد؛ قراءة محتوى الصفحة الحالية")
        self.assertEqual(missing, ["verified-effect marker in compact log"])

    def test_both_browser_actions_are_required(self):
        missing = self.check(steps="فتح موقع في متصفح المساعد؛ تم التحقق")
        self.assertIn("page-read action in compact log", missing)

    def test_matching_is_case_insensitive_for_web_evidence(self):
        self.assertEqual(
            self.check(
                details="browser_open_url https://EXAMPLE.COM/",
                reply="page heading: EXAMPLE DOMAIN",
            ),
            [],
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
