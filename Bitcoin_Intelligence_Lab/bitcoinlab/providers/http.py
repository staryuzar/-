from __future__ import annotations

import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class ProviderError(RuntimeError):
    pass


def get_json(url: str, *, timeout: float = 8.0, headers: dict[str, str] | None = None):
    if not url.startswith("https://"):
        raise ValueError("Only HTTPS provider URLs are allowed.")
    request_headers = {"Accept": "application/json", "User-Agent": "BitcoinIntelligenceLab/0.1 (+read-only market data)"}
    if headers:
        request_headers.update(headers)
    request = Request(url, headers=request_headers, method="GET")
    try:
        with urlopen(request, timeout=timeout) as response:
            if response.status != 200:
                raise ProviderError(f"Provider returned HTTP {response.status}.")
            raw = response.read(8_000_001)
    except HTTPError as exc:
        retry_after = exc.headers.get("Retry-After") if exc.headers else None
        suffix = f" Retry-After={retry_after}." if retry_after else ""
        raise ProviderError(f"Provider HTTP {exc.code}.{suffix}") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise ProviderError(f"Provider connection failed: {exc}") from exc
    if len(raw) > 8_000_000:
        raise ProviderError("Provider response exceeded 8 MB limit.")
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProviderError("Provider returned invalid JSON.") from exc


def get_bytes(url: str, *, timeout: float = 15.0, maximum: int = 20_000_000) -> bytes:
    if not url.startswith("https://"):
        raise ValueError("Only HTTPS provider URLs are allowed.")
    request = Request(url, headers={"User-Agent": "BitcoinIntelligenceLab/0.1 read-only data"}, method="GET")
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read(maximum + 1)
    except HTTPError as exc:
        raise ProviderError(f"Provider HTTP {exc.code}.") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise ProviderError(f"Provider connection failed: {exc}") from exc
    if len(raw) > maximum:
        raise ProviderError("Provider response exceeded configured size limit.")
    return raw
