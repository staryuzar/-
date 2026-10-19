"""Offline regression tests for provider API preflight and secret redaction."""
from __future__ import annotations

import io
import json
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

import provider_api_preflight as preflight


class FakeResponse:
    def __init__(self, payload: dict):
        self.payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, n=-1):
        return self.payload[:n]


def http_error(status: int) -> HTTPError:
    return HTTPError("https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash", status, "failure", {}, io.BytesIO(b"private provider detail"))


class ProviderPreflightTests(unittest.TestCase):
    def test_gemini_metadata_success_uses_header_and_sends_no_generation(self):
        secret = "TEST_SECRET_SHOULD_NEVER_APPEAR"
        metadata = {"name": "models/gemini-3.8-flash", "supportedGenerationMethods": ["generateContent"]}
        with patch.object(preflight, "urlopen", return_value=FakeResponse(metadata)) as mocked:
            result = preflight.run_preflight("gemini", gemini_key=secret)
        request = mocked.call_args.args[0]
        self.assertNotIn(secret, request.full_url)
        self.assertIn(secret, request.get_header("X-goog-api-key"))
        self.assertTrue(result["credential_accepted"])
        self.assertTrue(result["model_metadata_confirmed"])
        self.assertFalse(result["generation_request_sent"])

    def test_gemini_429_fails_once_without_retries(self):
        with patch.object(preflight, "urlopen", side_effect=http_error(429)) as mocked:
            with self.assertRaises(preflight.PreflightFailure) as caught:
                preflight.run_preflight("gemini", gemini_key="TEST_SECRET")
        self.assertEqual(caught.exception.category, "provider_rate_limit_or_quota_on_preflight")
        self.assertEqual(caught.exception.http_status, 429)
        mocked.assert_called_once()

    def test_gemini_forbidden_has_safe_diagnosis(self):
        with patch.object(preflight, "urlopen", side_effect=http_error(403)):
            with self.assertRaises(preflight.PreflightFailure) as caught:
                preflight.run_preflight("gemini", gemini_key="TEST_SECRET")
        self.assertEqual(caught.exception.category, "credential_or_api_permission")
        self.assertNotIn("TEST_SECRET", str(caught.exception))

    def test_missing_key_never_makes_request(self):
        with patch.object(preflight, "urlopen") as mocked:
            with self.assertRaisesRegex(preflight.PreflightFailure, "credential_missing"):
                preflight.run_preflight("gemini", gemini_key=" ")
        mocked.assert_not_called()

    def test_openrouter_credential_endpoint_success(self):
        secret = "OPENROUTER_TEST_SECRET"
        with patch.object(preflight, "urlopen", return_value=FakeResponse({"data": {"label": "ci"}})) as mocked:
            result = preflight.run_preflight("openrouter", openrouter_key=secret)
        request = mocked.call_args.args[0]
        self.assertNotIn(secret, request.full_url)
        self.assertEqual(request.get_header("Authorization"), "Bearer " + secret)
        self.assertTrue(result["credential_accepted"])
        self.assertFalse(result["model_metadata_confirmed"])
        self.assertFalse(result["generation_request_sent"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
