#!/usr/bin/env python3
"""Check provider credentials/model metadata without generating model tokens."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DEFAULT_GEMINI_MODEL = "gemini-3.8-flash"


class PreflightFailure(Exception):
    def __init__(self, category: str, http_status: int | None = None):
        super().__init__(category)
        self.category = category
        self.http_status = http_status


def _get_json(url: str, headers: dict[str, str], timeout: float = 15.0) -> dict:
    request = Request(url, headers=headers, method="GET")
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read(1_000_000).decode("utf-8", "strict")
    except HTTPError as exc:
        status = int(exc.code)
        try:
            exc.close()
        except Exception:
            pass
        if status in (401, 403):
            category = "credential_or_api_permission"
        elif status == 404:
            category = "model_not_found_or_unavailable"
        elif status == 429:
            category = "provider_rate_limit_or_quota_on_preflight"
        elif status >= 500:
            category = "provider_temporarily_unavailable"
        else:
            category = "provider_http_error"
        raise PreflightFailure(category, status) from None
    except (URLError, TimeoutError, OSError):
        raise PreflightFailure("network_tls_or_timeout") from None
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise PreflightFailure("invalid_provider_response") from None
    if not isinstance(payload, dict):
        raise PreflightFailure("invalid_provider_response")
    return payload


def run_preflight(provider: str, *, gemini_key: str = "", openrouter_key: str = "", model: str = DEFAULT_GEMINI_MODEL) -> dict:
    provider = provider.strip().lower()
    if provider == "gemini":
        if not gemini_key.strip():
            raise PreflightFailure("credential_missing")
        normalized_model = model.removeprefix("models/").strip()
        if not normalized_model or any(ch.isspace() for ch in normalized_model):
            raise PreflightFailure("invalid_model_setting")
        metadata = _get_json(
            "https://generativelanguage.googleapis.com/v1beta/models/" + normalized_model,
            {"X-Goog-Api-Key": gemini_key.strip(), "Accept": "application/json"},
        )
        expected = "models/" + normalized_model
        if metadata.get("name") != expected:
            raise PreflightFailure("unexpected_model_metadata")
        methods = metadata.get("supportedGenerationMethods")
        if isinstance(methods, list) and "generateContent" not in methods:
            raise PreflightFailure("model_does_not_advertise_generateContent")
        return {
            "provider": "gemini",
            "model": normalized_model,
            "result": "PASS",
            "credential_accepted": True,
            "model_metadata_confirmed": True,
            "generation_request_sent": False,
            "quota_for_generation_confirmed": False,
        }

    if provider == "openrouter":
        if not openrouter_key.strip():
            raise PreflightFailure("credential_missing")
        payload = _get_json(
            "https://openrouter.ai/api/v1/auth/key",
            {"Authorization": "Bearer " + openrouter_key.strip(), "Accept": "application/json"},
        )
        if not isinstance(payload.get("data"), dict):
            raise PreflightFailure("unexpected_auth_response")
        return {
            "provider": "openrouter",
            "model": "openrouter/free",
            "result": "PASS",
            "credential_accepted": True,
            "model_metadata_confirmed": False,
            "generation_request_sent": False,
            "quota_for_generation_confirmed": False,
        }
    raise PreflightFailure("unsupported_provider")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", default=os.getenv("AI_PROVIDER", "gemini"))
    parser.add_argument("--model", default=os.getenv("GEMINI_MODEL", DEFAULT_GEMINI_MODEL))
    parser.add_argument("--report", type=Path, default=None)
    args = parser.parse_args(argv)

    try:
        report = run_preflight(
            args.provider,
            gemini_key=os.getenv("GEMINI_API_KEY", ""),
            openrouter_key=os.getenv("OPENROUTER_API_KEY", ""),
            model=args.model,
        )
        message = "PASS: selected provider credential accepted; no generation request was sent."
        code = 0
    except PreflightFailure as exc:
        report = {
            "provider": args.provider.strip().lower(),
            "model": args.model if args.provider.strip().lower() == "gemini" else "openrouter/free",
            "result": "FAIL",
            "error_class": exc.category,
            "http_status": exc.http_status,
            "generation_request_sent": False,
            "quota_for_generation_confirmed": False,
        }
        status = f"HTTP {exc.http_status}" if exc.http_status is not None else "no HTTP status"
        message = f"FAIL: provider preflight {exc.category} ({status}); key value suppressed; no generation request was sent."
        code = 1

    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(message)
    if args.report:
        print("Safe preflight report written; no credential values are included.")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
