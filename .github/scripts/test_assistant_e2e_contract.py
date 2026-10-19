#!/usr/bin/env python3
"""Standard-library tests for strict live-assistant E2E evidence validation."""
from __future__ import annotations

import json
import sqlite3
import tempfile
from contextlib import closing
import unittest
from pathlib import Path

from assistant_e2e_contract import load_persisted_tool_records, missing_execution_evidence


PROMPT = "افتح https://example.com/ واقرأ عنوان الصفحة"
GOOD_STEPS = """
فتح موقع في متصفح المساعد · تم التحقق
قراءة محتوى الصفحة الحالية · تم التحقق
"""
GOOD_REPLY = "Document title: Example Domain\nH1: Example Domain"
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
                "Document title field in assistant reply",
                "H1 field in assistant reply",
                "matching Example Domain document title and H1 values in assistant reply",
            },
        )

    def test_url_on_wrong_host_is_rejected(self):
        records = [
            dict(GOOD_RECORDS[0], args={"url": "https://notexample.com/"}, result={"ok": True, "effect_verified": True, "url": "https://notexample.com/"}),
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

    def test_open_redirected_away_from_target_is_rejected(self):
        records = [
            dict(GOOD_RECORDS[0], result={"ok": True, "effect_verified": True, "url": "https://other.example/"}),
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
            dict(GOOD_RECORDS[0], args={"url": "https://example.com.evil.invalid/"}, result={"ok": True, "effect_verified": True, "url": "https://example.com.evil.invalid/"}),
            dict(GOOD_RECORDS[1], result={"ok": True, "effect_verified": True, "url": "https://fakeexample.com/"}),
        ]
        missing = self.check(records=records)
        self.assertIn("successful browser_open_url record on example.com", missing)
        self.assertIn("successful browser_read_page record on example.com", missing)


class PersistedToolLogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = Path(self.temp.name) / "aurora.sqlite3"
        with closing(sqlite3.connect(self.database)) as connection:
            connection.execute(
                "CREATE TABLE conversations (id TEXT, updated_at TEXT, messages_json TEXT, log_json TEXT)"
            )
            connection.commit()

    def tearDown(self):
        self.temp.cleanup()

    def add_conversation(self, conversation_id, prompt, records, updated="2026-10-19T00:00:00Z"):
        messages = [{"role": "user", "content": prompt}]
        with closing(sqlite3.connect(self.database)) as connection:
            connection.execute(
                "INSERT INTO conversations VALUES (?, ?, ?, ?)",
                (conversation_id, updated, json.dumps(messages), json.dumps(records)),
            )
            connection.commit()

    def test_reads_records_for_exact_prompt(self):
        self.add_conversation("target", PROMPT, GOOD_RECORDS)
        self.assertEqual(load_persisted_tool_records(self.database, PROMPT, timeout_seconds=0.01), GOOD_RECORDS)

    def test_does_not_confuse_a_different_conversation(self):
        self.add_conversation("other", "a completely different request", GOOD_RECORDS)
        with self.assertRaisesRegex(AssertionError, "exact submitted prompt"):
            load_persisted_tool_records(self.database, PROMPT, timeout_seconds=0.02, poll_interval=0.005)

    def test_ignores_unrelated_rows_and_finds_matching_row(self):
        self.add_conversation("older-target", PROMPT, GOOD_RECORDS, updated="2026-10-18T00:00:00Z")
        self.add_conversation("latest-unrelated", "latest unrelated request", [], updated="2026-10-19T00:00:00Z")
        self.assertEqual(load_persisted_tool_records(self.database, PROMPT, timeout_seconds=0.01), GOOD_RECORDS)

    def test_uses_read_only_database_connection(self):
        self.add_conversation("target", PROMPT, GOOD_RECORDS)
        load_persisted_tool_records(self.database, PROMPT, timeout_seconds=0.01)
        with closing(sqlite3.connect(self.database)) as connection:
            count = connection.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]
        self.assertEqual(count, 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
