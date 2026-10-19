#!/usr/bin/env python3
"""Standard-library tests for strict live-assistant E2E evidence validation."""
from __future__ import annotations

import unittest

from assistant_e2e_contract import missing_execution_evidence


GOOD_STEPS = """
فتح موقع في متصفح المساعد · تم التحقق
قراءة محتوى الصفحة الحالية · تم التحقق
"""
GOOD_REPLY = "تم فتح Example Domain وقراءة العنوان الرئيسي."
GOOD_RECORDS = [
    {
        "tool": "browser_open_url",
        "args": {"url": "https://example.com/"},
        "result": {"ok": True, "effect_verified": True, "url": "https://example.com/"},
    },
    {
        "tool": "browser_read_page",
        "args": {},
        "result": {"ok": True, "effect_verified": True, "url": "https://example.com/", "text": "[محتوى الصفحة الخاصة غير محفوظ]"},
    },
]


class ExecutionEvidenceContractTests(unittest.TestCase):
    def check(self, steps=GOOD_STEPS, records=None, reply=GOOD_REPLY):
        return missing_execution_evidence(steps, GOOD_RECORDS if records is None else records, reply)

    def test_complete_persisted_evidence_passes(self):
        self.assertEqual(self.check(), [])

    def test_model_answer_alone_is_not_execution_evidence(self):
        missing = set(self.check(steps="", records=[], reply="The answer is Example Domain"))
        self.assertEqual(
            missing,
            {
                "browser-open action in compact log",
                "page-read action in compact log",
                "verified-effect marker in compact log",
                "successful browser_open_url record on example.com",
                "successful browser_read_page record on example.com",
            },
        )

    def test_url_on_wrong_host_is_rejected(self):
        records = [
            dict(GOOD_RECORDS[0], args={"url": "https://notexample.com/"}),
            dict(GOOD_RECORDS[1], result={"ok": True, "effect_verified": True, "url": "https://notexample.com/"}),
        ]
        missing = self.check(records=records)
        self.assertIn("successful browser_open_url record on example.com", missing)
        self.assertIn("successful browser_read_page record on example.com", missing)

    def test_failed_tool_result_is_rejected_even_with_target_url(self):
        records = [
            dict(GOOD_RECORDS[0], result={"ok": False, "effect_verified": False, "url": "https://example.com/"}),
            GOOD_RECORDS[1],
        ]
        self.assertIn("successful browser_open_url record on example.com", self.check(records=records))

    def test_unverified_effect_is_rejected(self):
        records = [GOOD_RECORDS[0], dict(GOOD_RECORDS[1], result={"ok": True, "effect_verified": False, "url": "https://example.com/"})]
        self.assertIn("successful browser_read_page record on example.com", self.check(records=records))

    def test_correct_url_without_expected_heading_is_rejected(self):
        missing = self.check(reply="The page heading was different.")
        self.assertIn("expected page heading Example Domain in assistant reply", missing)

    def test_actions_without_verified_effect_are_rejected(self):
        missing = self.check(steps="فتح موقع في متصفح المساعد؛ قراءة محتوى الصفحة الحالية")
        self.assertIn("verified-effect marker in compact log", missing)

    def test_subdomains_and_similar_domain_names_are_rejected(self):
        records = [
            dict(GOOD_RECORDS[0], args={"url": "https://example.com.evil.invalid/"}),
            dict(GOOD_RECORDS[1], result={"ok": True, "effect_verified": True, "url": "https://fakeexample.com/"}),
        ]
        missing = self.check(records=records)
        self.assertIn("successful browser_open_url record on example.com", missing)
        self.assertIn("successful browser_read_page record on example.com", missing)


if __name__ == "__main__":
    unittest.main(verbosity=2)
