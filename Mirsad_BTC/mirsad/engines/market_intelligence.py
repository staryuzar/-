from __future__ import annotations

import json
import math
import re
import threading
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

from ..config import (
    MARKET_INTELLIGENCE_TIMEOUT_SECONDS,
    MARKET_INTELLIGENCE_DERIVATIVES_MAX_AGE_SECONDS,
    MARKET_INTELLIGENCE_FEAR_GREED_MAX_AGE_SECONDS,
    MARKET_INTELLIGENCE_GLOBAL_METRICS_MAX_AGE_SECONDS,
    TRADING_ECONOMICS_CALENDAR_COUNTRIES,
    SYMBOL,
    TRADING_ECONOMICS_API_KEY,
)

ENGINE_SCHEMA = "MIR-ENGINE1-INTELLIGENCE-1"
USER_AGENT = "MirsadBTC/1.0 (+market-intelligence; read-only)"
NEWS_FEEDS = (
    ("CoinDesk", "https://www.coindesk.com/arc/outboundfeeds/rss/"),
    ("Cointelegraph", "https://cointelegraph.com/rss"),
    ("The Block", "https://www.theblock.co/rss.xml"),
    ("Decrypt", "https://decrypt.co/feed"),
)
CACHE: dict[str, tuple[float, bytes]] = {}
CACHE_PROVIDER_TIMESTAMPS: dict[str, int | None] = {}
CACHE_LOCK = threading.Lock()
MAX_RESPONSE_BYTES = 2_000_000
MAX_HEADLINES = 40
COMPONENT_WEIGHTS = {"derivatives": 0.55, "news": 0.40, "fear_greed": 0.05}
DERIVATIVE_SIGNAL_WEIGHTS = {"funding_rate": 0.55, "long_short_ratio": 0.45}

_POSITIVE_TERMS = (
    "etf inflow", "inflows", "adoption", "approved", "approval", "launches",
    "record high", "institutional buying", "reserve", "accumulation",
    "mainstream adoption", "upgrade", "partnership", "recovery",
)
_NEGATIVE_TERMS = (
    "hack", "hacked", "exploit", "exploited", "breach", "insolvency",
    "bankruptcy", "bankrupt", "lawsuit", "sued", "ban", "banned",
    "outflow", "outflows", "liquidation", "liquidations", "depeg",
    "delisting", "halt", "halted", "fraud", "default", "crackdown",
)
_RISK_TERMS = (
    "hack", "exploit", "breach", "insolvency", "bankruptcy", "depeg",
    "exchange halt", "withdrawals paused", "regulatory action",
)


def _finite(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def _clamp(value: float, low: float = -1.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _parse_time(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        if not math.isfinite(number) or number <= 0:
            return None
        return int(number if number > 10_000_000_000 else number * 1000)
    raw = str(value).strip()
    if not raw:
        return None
    if raw.isdigit():
        return _parse_time(int(raw))
    try:
        parsed = parsedate_to_datetime(raw)
    except (TypeError, ValueError, OverflowError):
        parsed = None
        for date_format in (
            "%m/%d/%Y %I:%M:%S %p", "%m/%d/%Y %I:%M %p",
            "%m/%d/%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d",
        ):
            try:
                parsed = datetime.strptime(raw, date_format)
                break
            except ValueError:
                continue
        if parsed is None:
            try:
                parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            except ValueError:
                return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int(parsed.astimezone(timezone.utc).timestamp() * 1000)


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _child_text(element: ET.Element, names: tuple[str, ...]) -> str:
    wanted = set(names)
    for child in element.iter():
        if _local_name(child.tag) in wanted and child.text:
            value = child.text.strip()
            if value:
                return value
        if _local_name(child.tag) == "link":
            href = child.attrib.get("href")
            if href and "link" in wanted:
                return href.strip()
    return ""


def parse_rss(payload: bytes, *, source: str, limit: int = MAX_HEADLINES) -> list[dict[str, Any]]:
    """Parse RSS/Atom metadata only; article bodies are never copied into Mirsad."""
    root = ET.fromstring(payload)
    entries = [node for node in root.iter() if _local_name(node.tag) in {"item", "entry"}]
    output: list[dict[str, Any]] = []
    for item in entries[:max(1, min(200, int(limit)))]:
        title = _child_text(item, ("title",))
        link = _child_text(item, ("link", "guid", "id"))
        published = _child_text(item, ("pubdate", "published", "updated", "date"))
        summary = _child_text(item, ("description", "summary", "encoded", "content"))
        title = re.sub(r"\s+", " ", title).strip()
        link = link.strip()
        published_at = _parse_time(published)
        if not title or not link:
            continue
        text = re.sub(r"<[^>]+>", " ", summary)
        text = re.sub(r"\s+", " ", text).strip()[:1200]
        sentiment_score, positive_hits, negative_hits = score_headline_text(title + " " + text)
        lowered = (title + " " + text).lower()
        risk_flags = [term for term in _RISK_TERMS if term in lowered]
        output.append({
            "source": source,
            "title": title[:400],
            "url": link[:1200],
            "published_at_ms": published_at,
            "summary": text,
            "sentiment_score": sentiment_score,
            "positive_terms": positive_hits,
            "negative_terms": negative_hits,
            "risk_flags": risk_flags,
        })
    return output


def score_headline_text(text: str) -> tuple[float, list[str], list[str]]:
    lowered = re.sub(r"\s+", " ", str(text or "").lower())
    positive = [term for term in _POSITIVE_TERMS if term in lowered]
    negative = [term for term in _NEGATIVE_TERMS if term in lowered]
    total = len(positive) + len(negative)
    score = _clamp((len(positive) - len(negative)) / max(2, total)) if total else 0.0
    return round(score, 4), positive, negative


def deduplicate_news_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse identical headlines across publishers without losing source breadth."""
    selected: dict[str, dict[str, Any]] = {}
    ordered = sorted(
        (item for item in items if isinstance(item, dict)),
        key=lambda value: value.get("published_at_ms") or 0,
        reverse=True,
    )
    for raw in ordered:
        item = dict(raw)
        # Unicode-aware normalization keeps Arabic/CJK and other non-Latin
        # headlines eligible for cross-publisher story de-duplication.
        title_key = re.sub(r"[\W_]+", " ", str(item.get("title", "")).casefold()).strip()
        url_key = str(item.get("url") or "").strip().casefold()
        key = title_key if len(title_key) >= 12 else url_key
        if not key:
            continue
        source = str(item.get("source") or "").strip()
        if key not in selected:
            item["sources"] = [source] if source else []
            item["duplicate_count"] = 1
            selected[key] = item
            continue
        current = selected[key]
        sources = list(current.get("sources") or [])
        if source and source not in sources:
            sources.append(source)
        current["sources"] = sources
        current["duplicate_count"] = int(current.get("duplicate_count", 1)) + 1
    return list(selected.values())


def score_news_items(items: list[dict[str, Any]]) -> dict[str, Any]:
    directional = [
        item for item in items
        if _finite(item.get("sentiment_score")) not in (None, 0.0)
    ]
    if not directional:
        return {"status": "INSUFFICIENT", "score": None, "classified_count": 0,
                "confidence": 0.0, "scope": "Explainable headline keyword signal; not an AI fact-check or calibrated forecast."}
    values = [_clamp(float(item["sentiment_score"])) for item in directional]
    sources = {
        str(source)
        for item in directional
        for source in (item.get("sources") or [item.get("source", "")])
        if source
    }
    score = sum(values) / len(values)
    source_factor = min(1.0, len(sources) / 3.0)
    sample_factor = min(1.0, len(values) / 10.0)
    confidence = round(source_factor * sample_factor, 4)
    return {
        "status": "READY" if len(values) >= 3 and len(sources) >= 2 else "PARTIAL",
        "score": round(_clamp(score), 4),
        "classified_count": len(values),
        "source_count": len(sources),
        "confidence": confidence,
        "scope": "Explainable headline keyword signal; not an AI fact-check or calibrated forecast.",
    }


def score_derivatives(
    venues: dict[str, Any], *, now_ms: int | None = None,
    max_age_seconds: int = MARKET_INTELLIGENCE_DERIVATIVES_MAX_AGE_SECONDS,
) -> dict[str, Any]:
    """Score each derivative input only when that input has its own fresh timestamp."""
    captured = int(time.time() * 1000) if now_ms is None else int(now_ms)
    observations: list[tuple[float, float, str]] = []
    diagnostics: dict[str, Any] = {}
    stale_count = 0

    def freshness(stamp: int | None) -> tuple[str, float | None]:
        if stamp is None:
            return "FRESHNESS_UNKNOWN", None
        age = (captured - stamp) / 1000.0
        if age < -120.0 or age > max_age_seconds:
            return "STALE", age
        return "FRESH", age

    for name, raw in venues.items():
        if not isinstance(raw, dict) or raw.get("status") not in {"READY", "PARTIAL"}:
            continue

        funding = _finite(raw.get("funding_rate"))
        ratio = _finite(raw.get("long_short_ratio"))
        funding_status, funding_age = freshness(_parse_time(raw.get("funding_timestamp_ms"))) if funding is not None else ("NOT_AVAILABLE", None)
        ratio_status, ratio_age = freshness(_parse_time(raw.get("long_short_timestamp_ms"))) if ratio is not None else ("NOT_AVAILABLE", None)

        venue_stale = funding_status == "STALE" or ratio_status == "STALE"
        if venue_stale:
            stale_count += 1
        valid_funding = funding is not None and funding_status == "FRESH"
        valid_ratio = ratio is not None and ratio > 0 and ratio_status == "FRESH"
        venue_parts: list[float] = []
        total_weight = 0.0
        if valid_funding:
            # Positive funding means longs pay shorts; crowded long positioning
            # is treated as contrarian risk, not as bullish momentum.
            venue_parts.append(_clamp(-float(funding) / 0.0005) * DERIVATIVE_SIGNAL_WEIGHTS["funding_rate"])
            total_weight += DERIVATIVE_SIGNAL_WEIGHTS["funding_rate"]
        if valid_ratio:
            venue_parts.append(_clamp(-math.log(float(ratio)) / math.log(3.0)) * DERIVATIVE_SIGNAL_WEIGHTS["long_short_ratio"])
            total_weight += DERIVATIVE_SIGNAL_WEIGHTS["long_short_ratio"]

        if not venue_parts:
            diagnostics[name] = {
                **raw,
                "directional_status": "STALE" if venue_stale else "FRESHNESS_UNKNOWN",
                "funding_directional_status": funding_status,
                "long_short_directional_status": ratio_status,
                "directional_score": None,
                "age_seconds": max(
                    [age for age in (funding_age, ratio_age) if age is not None],
                    default=None,
                ),
            }
            continue

        score = sum(venue_parts) / max(0.0001, total_weight)
        confidence = 1.0 if valid_funding and valid_ratio else 0.55
        ages = [age for valid, age in ((valid_funding, funding_age), (valid_ratio, ratio_age)) if valid and age is not None]
        observations.append((score, confidence, name))
        diagnostics[name] = {
            **raw,
            "directional_status": "FRESH",
            "funding_directional_status": funding_status,
            "long_short_directional_status": ratio_status,
            "directional_score": round(_clamp(score), 4),
            "age_seconds": round(max(ages), 2) if ages else None,
            "directional_inputs_used": {
                "funding_rate": valid_funding,
                "long_short_ratio": valid_ratio,
            },
        }

    if not observations:
        return {
            "status": "UNAVAILABLE", "score": None, "confidence": 0.0,
            "venue_count": 0, "stale_venue_count": stale_count,
            "venues": diagnostics,
            "directional_input_weights": dict(DERIVATIVE_SIGNAL_WEIGHTS),
            "freshness_max_age_seconds": max_age_seconds,
            "scope": "Perpetual futures positioning; each funding and long/short input needs its own fresh provider timestamp.",
        }
    weights = [item[1] for item in observations]
    score = sum(item[0] * item[1] for item in observations) / sum(weights)
    confidence = min(1.0, len(observations) / 2.0) * (sum(weights) / len(weights))
    return {
        "status": "READY" if len(observations) >= 2 else "PARTIAL",
        "score": round(_clamp(score), 4),
        "confidence": round(confidence, 4),
        "venue_count": len(observations),
        "stale_venue_count": stale_count,
        "freshness_max_age_seconds": max_age_seconds,
        "venues": diagnostics,
        "directional_input_weights": dict(DERIVATIVE_SIGNAL_WEIGHTS),
        "scope": "Funding and long/short positioning are interpreted contrarily. Each factor is freshness-gated independently; open-interest change is context/intensity, not direction by itself.",
    }


def assess_market_risk(
    *, news: dict[str, Any], fear_greed: dict[str, Any],
    derivatives: dict[str, Any], calendar: dict[str, Any],
    now_ms: int | None = None,
) -> dict[str, Any]:
    """Descriptive non-directional risk overlay; it never creates an order or hidden gate."""
    captured = int(time.time() * 1000) if now_ms is None else int(now_ms)
    drivers: list[str] = []
    fresh_risk_items = []
    for item in news.get("items", []) if isinstance(news.get("items"), list) else []:
        if not isinstance(item, dict) or not item.get("risk_flags"):
            continue
        stamp = _parse_time(item.get("published_at_ms"))
        if stamp is not None and -2 * 60 * 60_000 <= captured - stamp <= 72 * 60 * 60_000:
            fresh_risk_items.append(item)
    if calendar.get("high_impact_window_active") is True:
        drivers.append("HIGH_IMPACT_MACRO_EVENT_WINDOW")
    if fresh_risk_items:
        drivers.append("RECENT_HEADLINE_RISK")
    crowded = []
    venues = derivatives.get("venue_scores") if isinstance(derivatives.get("venue_scores"), dict) else {}
    if not venues:
        venues = derivatives.get("venues") if isinstance(derivatives.get("venues"), dict) else {}
    for venue, raw in venues.items():
        if not isinstance(raw, dict) or raw.get("directional_status") != "FRESH":
            continue
        funding = _finite(raw.get("funding_rate")) if raw.get("funding_directional_status") == "FRESH" else None
        ratio = _finite(raw.get("long_short_ratio")) if raw.get("long_short_directional_status") == "FRESH" else None
        if (funding is not None and abs(funding) >= 0.0005) or (ratio is not None and (ratio >= 2.0 or ratio <= 0.5)):
            crowded.append(str(venue))
    if crowded:
        drivers.append("EXTREME_DERIVATIVES_POSITIONING")
    sentiment_value = _finite(fear_greed.get("value"))
    if fear_greed.get("status") == "READY" and sentiment_value is not None and (sentiment_value >= 80 or sentiment_value <= 20):
        drivers.append("EXTREME_CROWD_SENTIMENT")
    news_sentiment = news.get("sentiment") if isinstance(news.get("sentiment"), dict) else {}
    if calendar.get("high_impact_window_active") is True or len(fresh_risk_items) >= 2:
        level = "HIGH"
    elif drivers:
        level = "ELEVATED"
    elif derivatives.get("status") == "READY" and news_sentiment.get("status") in {"READY", "PARTIAL"}:
        level = "NORMAL"
    else:
        level = "UNKNOWN"
    return {
        "status": "READY" if level != "UNKNOWN" else "PARTIAL",
        "level": level,
        "drivers": drivers,
        "recent_risk_headline_count": len(fresh_risk_items),
        "crowded_derivatives_venues": crowded,
        "automatic_entry_block": False,
        "policy": "Context-only overlay. Only the explicit high-impact economic-calendar gate in Engine 4 pauses new entries; this descriptive heuristic does not independently block or authorize trades.",
        "scope": "Rule-based context classification, not a forecast, calibrated probability or replacement for Engine 4 risk controls.",
    }


def compose_directional_context(
    *,
    news: dict[str, Any],
    fear_greed: dict[str, Any],
    derivatives: dict[str, Any],
) -> dict[str, Any]:
    components = {
        "derivatives": derivatives,
        "news": news,
        "fear_greed": fear_greed,
    }
    weighted: list[tuple[float, float, float]] = []
    covered_weight = 0.0
    detail: dict[str, Any] = {}
    for name, weight in COMPONENT_WEIGHTS.items():
        part = components[name]
        score = _finite(part.get("score"))
        status = str(part.get("status", "UNAVAILABLE")).upper()
        usable = score is not None and status in {"READY", "PARTIAL"}
        confidence = _finite(part.get("confidence"))
        confidence = _clamp(confidence or 0.0, 0.0, 1.0)
        detail[name] = {
            "status": status,
            "score": round(_clamp(score), 4) if usable else None,
            "weight": weight,
            "confidence": round(confidence, 4),
            "contributes": usable,
        }
        if usable:
            weighted.append((float(score), weight, confidence))
            covered_weight += weight
    if not weighted:
        return {
            "status": "OFFLINE", "direction": "UNKNOWN", "directional_score": None,
            "confidence": 0.0, "evidence_coverage": 0.0, "components": detail,
            "confidence_basis": "Evidence coverage and source freshness; not a probability of profit or forecast accuracy.",
        }
    active_weight = sum(weight for _, weight, _ in weighted)
    score = sum(value * weight for value, weight, _ in weighted) / active_weight
    confidence = covered_weight * (
        sum(weight * conf for _, weight, conf in weighted) / active_weight
    )
    status = "READY" if len(weighted) >= 2 and covered_weight >= 0.55 else "PARTIAL"
    direction = "BULLISH" if score >= 0.18 else "BEARISH" if score <= -0.18 else "NEUTRAL"
    return {
        "status": status,
        "direction": direction,
        "directional_score": round(_clamp(score), 4),
        "confidence": round(_clamp(confidence, 0.0, 1.0), 4),
        "evidence_coverage": round(covered_weight, 4),
        "components": detail,
        "confidence_basis": "Weighted evidence coverage and provider availability; this is not a probability of profit or a calibrated forecast.",
        "scenario": {
            "primary": direction,
            "label": {
                "BULLISH": "ميل سياقي صاعد",
                "BEARISH": "ميل سياقي هابط",
                "NEUTRAL": "سياق متوازن",
                "UNKNOWN": "الأدلة غير كافية",
            }.get(direction, "الأدلة غير كافية"),
            "horizon": "context_only_no_calibrated_horizon",
        },
    }


class MarketIntelligenceEngine:
    """Engine 1's non-chart intelligence: news, macro calendar, sentiment and derivatives."""

    def __init__(
        self,
        *,
        symbol: str = SYMBOL,
        timeout_seconds: float = MARKET_INTELLIGENCE_TIMEOUT_SECONDS,
        trading_economics_api_key: str = TRADING_ECONOMICS_API_KEY,
        calendar_countries: tuple[str, ...] | list[str] | str = TRADING_ECONOMICS_CALENDAR_COUNTRIES,
    ) -> None:
        self.symbol = str(symbol or "BTCUSDT").strip().upper()
        self.timeout_seconds = max(2.0, min(15.0, float(timeout_seconds)))
        self.trading_economics_api_key = str(trading_economics_api_key or "").strip()
        raw_countries = calendar_countries.split(",") if isinstance(calendar_countries, str) else calendar_countries
        self.calendar_countries = tuple(dict.fromkeys(
            str(country).strip().lower() for country in (raw_countries or ()) if str(country).strip()
        )) or ("united states",)

    def _fetch(self, url: str, *, ttl_seconds: int, accept: str) -> bytes:
        now = time.time()
        with CACHE_LOCK:
            cached = CACHE.get(url)
            if cached and now - cached[0] <= ttl_seconds:
                return cached[1]
        request = urllib.request.Request(
            url,
            headers={"User-Agent": USER_AGENT, "Accept": accept},
        )
        with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
            if int(getattr(response, "status", 200)) != 200:
                raise RuntimeError(f"HTTP {getattr(response, 'status', 'unknown')}")
            date_header = response.headers.get("Date") if getattr(response, "headers", None) else None
            provider_timestamp_ms = _parse_time(date_header)
            body = response.read(MAX_RESPONSE_BYTES + 1)
        if len(body) > MAX_RESPONSE_BYTES:
            raise ValueError("Provider response exceeds the configured size limit.")
        with CACHE_LOCK:
            CACHE[url] = (now, body)
            CACHE_PROVIDER_TIMESTAMPS[url] = provider_timestamp_ms
        return body

    def _json(self, url: str, *, ttl_seconds: int = 30) -> Any:
        raw = self._fetch(url, ttl_seconds=ttl_seconds, accept="application/json")
        return json.loads(raw.decode("utf-8"))

    def _json_with_provider_time(
        self, url: str, *, ttl_seconds: int = 30
    ) -> tuple[Any, int | None]:
        raw = self._fetch(url, ttl_seconds=ttl_seconds, accept="application/json")
        with CACHE_LOCK:
            provider_timestamp_ms = CACHE_PROVIDER_TIMESTAMPS.get(url)
        return json.loads(raw.decode("utf-8")), provider_timestamp_ms

    def _post_json_with_provider_time(
        self, url: str, payload: dict[str, Any], *, ttl_seconds: int = 30
    ) -> tuple[Any, int | None]:
        cache_key = "POST:" + url + ":" + json.dumps(
            payload, sort_keys=True, separators=(",", ":")
        )
        now = time.time()
        with CACHE_LOCK:
            cached = CACHE.get(cache_key)
            if cached and now - cached[0] <= ttl_seconds:
                raw = cached[1]
                provider_timestamp_ms = CACHE_PROVIDER_TIMESTAMPS.get(cache_key)
            else:
                raw = None
                provider_timestamp_ms = None
        if raw is None:
            body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            request = urllib.request.Request(
                url,
                data=body,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                if int(getattr(response, "status", 200)) != 200:
                    raise RuntimeError(f"HTTP {getattr(response, 'status', 'unknown')}")
                date_header = response.headers.get("Date") if getattr(response, "headers", None) else None
                provider_timestamp_ms = _parse_time(date_header)
                raw = response.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                raise ValueError("Provider response exceeds the configured size limit.")
            with CACHE_LOCK:
                CACHE[cache_key] = (now, raw)
                CACHE_PROVIDER_TIMESTAMPS[cache_key] = provider_timestamp_ms
        return json.loads(raw.decode("utf-8")), provider_timestamp_ms

    def _collect_news(self) -> dict[str, Any]:
        items: list[dict[str, Any]] = []
        source_statuses: dict[str, str] = {}
        with ThreadPoolExecutor(max_workers=len(NEWS_FEEDS)) as pool:
            futures = {
                pool.submit(self._fetch, url, ttl_seconds=120, accept="application/rss+xml, application/atom+xml, application/xml, text/xml"): name
                for name, url in NEWS_FEEDS
            }
            for future in as_completed(futures):
                name = futures[future]
                try:
                    parsed = parse_rss(future.result(), source=name)
                    items.extend(parsed)
                    source_statuses[name] = "READY" if parsed else "EMPTY"
                except Exception as exc:
                    source_statuses[name] = f"ERROR_{type(exc).__name__}"
        unique = deduplicate_news_items(items)
        now_ms = int(time.time() * 1000)
        fresh = [
            item for item in unique
            if isinstance(item.get("published_at_ms"), int)
            and -2 * 60 * 60_000 <= now_ms - item["published_at_ms"] <= 72 * 60 * 60_000
        ]
        return {
            "status": "READY" if unique else "OFFLINE",
            "items": unique[:MAX_HEADLINES],
            "count": len(unique),
            "fresh_count_72h": len(fresh),
            "latest_published_at_ms": max((item["published_at_ms"] for item in fresh), default=None),
            "freshest_age_seconds": round((now_ms - max((item["published_at_ms"] for item in fresh), default=now_ms)) / 1000.0, 2) if fresh else None,
            "headline_source_count": len({source for item in fresh for source in (item.get("sources") or [item.get("source", "")]) if source}),
            "sources": source_statuses,
            "sentiment": score_news_items(fresh),
            "scope": "Deduplicated headlines and short RSS summaries; directional sentiment uses timestamps from the last 72 hours and distinct stories across publishers; no article body scraping or claim verification.",
        }

    def _collect_fear_greed(self, *, now_ms: int | None = None) -> dict[str, Any]:
        payload = self._json("https://api.alternative.me/fng/?limit=2&format=json", ttl_seconds=300)
        rows = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(rows, list) or not rows:
            raise ValueError("Fear and Greed provider returned no data rows.")
        latest = rows[0]
        value = _finite(latest.get("value"))
        stamp = _parse_time(latest.get("timestamp"))
        if value is None or not 0 <= value <= 100 or stamp is None:
            raise ValueError("Fear and Greed response is missing a valid value or timestamp.")
        captured = int(time.time() * 1000) if now_ms is None else int(now_ms)
        age_seconds = (captured - stamp) / 1000.0
        if age_seconds < -120.0:
            return {"status": "INVALID", "score": None, "confidence": 0.0,
                    "timestamp_ms": stamp, "freshness_age_seconds": round(age_seconds, 2),
                    "reason": "Fear & Greed provider timestamp is future-dated."}
        if age_seconds > MARKET_INTELLIGENCE_FEAR_GREED_MAX_AGE_SECONDS:
            return {"status": "STALE", "score": None, "confidence": 0.0,
                    "timestamp_ms": stamp, "freshness_age_seconds": round(age_seconds, 2),
                    "freshness_max_age_seconds": MARKET_INTELLIGENCE_FEAR_GREED_MAX_AGE_SECONDS,
                    "reason": "Fear & Greed observation is older than the configured daily-data freshness limit."}
        score = _clamp((50.0 - value) / 50.0)
        return {
            "status": "READY",
            "source": "Alternative.me Fear & Greed Index",
            "value": int(value),
            "classification": str(latest.get("value_classification", "UNKNOWN")),
            "timestamp_ms": stamp,
            "freshness_age_seconds": round(age_seconds, 2),
            "freshness_max_age_seconds": MARKET_INTELLIGENCE_FEAR_GREED_MAX_AGE_SECONDS,
            "score": round(score, 4),
            "confidence": 0.70,
            "interpretation": "Contrarian sentiment context only; extreme fear/greed is not a standalone trade signal.",
            "attribution": "Data from alternative.me",
        }

    def _collect_global_metrics(self) -> dict[str, Any]:
        payload = self._json("https://api.alternative.me/v1/global/", ttl_seconds=300)
        if not isinstance(payload, dict):
            raise ValueError("Global market metrics response is not an object.")
        updated = _parse_time(payload.get("last_updated"))
        captured = int(time.time() * 1000)
        age_seconds = (captured - updated) / 1000.0 if updated is not None else None
        metrics = {
            "total_market_cap_usd": _finite(payload.get("total_market_cap_usd")),
            "total_24h_volume_usd": _finite(payload.get("total_24h_volume_usd")),
            "bitcoin_dominance_pct": _finite(payload.get("bitcoin_percentage_of_market_cap")),
            "active_markets": _finite(payload.get("active_markets")),
        }
        if not any(value is not None for value in metrics.values()):
            raise ValueError("Global market metrics contain no usable fields.")
        if age_seconds is not None and age_seconds < -120.0:
            freshness = "INVALID"
        elif age_seconds is not None and age_seconds > MARKET_INTELLIGENCE_GLOBAL_METRICS_MAX_AGE_SECONDS:
            freshness = "STALE"
        elif age_seconds is None:
            freshness = "UNKNOWN"
        else:
            freshness = "FRESH"
        return {
            "status": "READY" if freshness == "FRESH" else "STALE" if freshness == "STALE" else "PARTIAL",
            "source": "Alternative.me global market data",
            "timestamp_ms": updated, "freshness_status": freshness,
            "freshness_age_seconds": round(age_seconds, 2) if age_seconds is not None else None,
            "freshness_max_age_seconds": MARKET_INTELLIGENCE_GLOBAL_METRICS_MAX_AGE_SECONDS,
            "metrics": metrics,
        }

    def _collect_binance_derivatives(self) -> dict[str, Any]:
        params = urllib.parse.urlencode({"symbol": self.symbol})
        base = "https://fapi.binance.com"
        urls = {
            "premium": f"{base}/fapi/v1/premiumIndex?{params}",
            "open_interest": f"{base}/fapi/v1/openInterest?{params}",
            "oi_history": f"{base}/futures/data/openInterestHist?{params}&period=5m&limit=8",
            "long_short": f"{base}/futures/data/globalLongShortAccountRatio?{params}&period=5m&limit=8",
        }
        values: dict[str, Any] = {}
        endpoint_errors: dict[str, str] = {}
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = {pool.submit(self._json, url, ttl_seconds=30 if key in {"premium", "open_interest"} else 120): key
                       for key, url in urls.items()}
            for future in as_completed(futures):
                key = futures[future]
                try:
                    values[key] = future.result()
                except Exception as exc:
                    values[key] = None
                    endpoint_errors[key] = f"{type(exc).__name__}: {str(exc)[:240]}"
        endpoint_statuses = {
            key: "OFFLINE" if value is None else (
                "API_ERROR" if isinstance(value, dict) and value.get("code") not in (None, 0, "0")
                and value.get("msg") else "RESPONSE"
            )
            for key, value in values.items()
        }
        for key, value in values.items():
            if (
                endpoint_statuses.get(key) == "API_ERROR"
                and isinstance(value, dict)
            ):
                endpoint_errors[key] = str(value.get("msg"))[:240]
        premium = values.get("premium") if isinstance(values.get("premium"), dict) else {}
        interest = values.get("open_interest") if isinstance(values.get("open_interest"), dict) else {}
        oi_history = values.get("oi_history") if isinstance(values.get("oi_history"), list) else []
        ratio_history = values.get("long_short") if isinstance(values.get("long_short"), list) else []
        funding = _finite(premium.get("lastFundingRate"))
        current_oi = _finite(interest.get("openInterest"))
        oi_change = None
        if len(oi_history) >= 2:
            first = _finite(oi_history[0].get("sumOpenInterest"))
            last = _finite(oi_history[-1].get("sumOpenInterest"))
            if first is not None and last is not None and first > 0:
                oi_change = (last - first) / first * 100.0
        ratio = _finite(ratio_history[-1].get("longShortRatio")) if ratio_history and isinstance(ratio_history[-1], dict) else None
        source_stamps = [
            _parse_time(premium.get("time")),
            _parse_time(interest.get("time")),
            *[_parse_time(row.get("timestamp")) for row in oi_history + ratio_history if isinstance(row, dict)],
        ]
        source_stamps = [stamp for stamp in source_stamps if stamp is not None]
        observed_at = int(time.time() * 1000)
        stamp = max(source_stamps) if source_stamps else observed_at
        funding_timestamp = _parse_time(premium.get("time")) if funding is not None else None
        ratio_timestamp = (
            _parse_time(ratio_history[-1].get("timestamp"))
            if ratio is not None and ratio_history and isinstance(ratio_history[-1], dict)
            else None
        )
        directional_stamps = [value for value in (funding_timestamp, ratio_timestamp) if value is not None]
        directional_stamp = min(directional_stamps) if directional_stamps else None
        status = "READY" if funding is not None or current_oi is not None else "OFFLINE"
        return {
            "status": status, "source": "Binance USD-M perpetual futures",
            "funding_rate": funding, "next_funding_time_ms": _parse_time(premium.get("nextFundingTime")),
            "mark_price": _finite(premium.get("markPrice")),
            "index_price": _finite(premium.get("indexPrice")),
            "open_interest": current_oi, "open_interest_change_pct_35m": round(oi_change, 5) if oi_change is not None else None,
            "long_short_ratio": ratio,
            "long_short_sample_count": len(ratio_history), "open_interest_sample_count": len(oi_history),
            "timestamp_ms": stamp,
            "directional_timestamp_ms": directional_stamp,
            "funding_timestamp_ms": funding_timestamp,
            "long_short_timestamp_ms": ratio_timestamp,
            "endpoint_statuses": endpoint_statuses,
            "endpoint_errors": endpoint_errors,
            "timestamp_basis": "PROVIDER_TIMESTAMP" if source_stamps else "LOCAL_FETCH_TIME",
            "observed_at_ms": observed_at,
        }

    def _collect_bybit_derivatives(self) -> dict[str, Any]:
        base = "https://api.bybit.com/v5/market"
        ticker_url = base + "/tickers?" + urllib.parse.urlencode({"category": "linear", "symbol": self.symbol})
        interest_url = base + "/open-interest?" + urllib.parse.urlencode({
            "category": "linear", "symbol": self.symbol, "intervalTime": "5min", "limit": 8,
        })
        ratio_url = base + "/account-ratio?" + urllib.parse.urlencode({
            "category": "linear", "symbol": self.symbol, "period": "5min", "limit": 8,
        })
        payloads: dict[str, Any] = {}
        endpoint_errors: dict[str, str] = {}
        requests = {
            ticker_url: ("ticker", 30),
            interest_url: ("interest", 120),
            ratio_url: ("account_ratio", 120),
        }
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = {
                pool.submit(self._json, url, ttl_seconds=ttl): key
                for url, (key, ttl) in requests.items()
            }
            for future in as_completed(futures):
                key = futures[future]
                try:
                    payloads[key] = future.result()
                except Exception as exc:
                    payloads[key] = None
                    endpoint_errors[key] = f"{type(exc).__name__}: {str(exc)[:240]}"

        endpoint_statuses: dict[str, str] = {}
        for key, payload in payloads.items():
            if payload is None:
                endpoint_statuses[key] = "OFFLINE"
            elif isinstance(payload, dict) and payload.get("retCode", 0) != 0:
                endpoint_statuses[key] = "API_ERROR"
                endpoint_errors[key] = str(payload.get("retMsg") or payload.get("retCode"))[:240]
            else:
                endpoint_statuses[key] = "RESPONSE"

        ticker_payload = payloads.get("ticker") if isinstance(payloads.get("ticker"), dict) else {}
        ticker_rows = ((ticker_payload.get("result") or {}).get("list") or [])
        row = ticker_rows[0] if ticker_payload.get("retCode") == 0 and ticker_rows else {}
        interest_payload = payloads.get("interest") if isinstance(payloads.get("interest"), dict) else {}
        interest_rows = ((interest_payload.get("result") or {}).get("list") or []) if interest_payload.get("retCode") == 0 else []
        ratio_payload = payloads.get("account_ratio") if isinstance(payloads.get("account_ratio"), dict) else {}
        ratio_rows = ((ratio_payload.get("result") or {}).get("list") or []) if ratio_payload.get("retCode") == 0 else []

        current_oi = _finite(row.get("openInterest"))
        if current_oi is None and interest_rows and isinstance(interest_rows[0], dict):
            current_oi = _finite(interest_rows[0].get("openInterest"))
        oi_change = None
        if len(interest_rows) >= 2:
            first = _finite(interest_rows[-1].get("openInterest"))
            last = _finite(interest_rows[0].get("openInterest"))
            if first is not None and last is not None and first > 0:
                oi_change = (last - first) / first * 100.0

        long_short_ratio = None
        if ratio_rows and isinstance(ratio_rows[0], dict):
            buy_ratio = _finite(ratio_rows[0].get("buyRatio"))
            sell_ratio = _finite(ratio_rows[0].get("sellRatio"))
            if buy_ratio is not None and sell_ratio is not None and sell_ratio > 0:
                long_short_ratio = buy_ratio / sell_ratio

        funding_rate = _finite(row.get("fundingRate"))
        observed_at = int(time.time() * 1000)
        funding_timestamp = None
        if funding_rate is not None:
            funding_timestamp = (
                _parse_time(ticker_payload.get("time"))
                or _parse_time(ticker_payload.get("retTime"))
                or _parse_time(row.get("ts"))
            )
        ratio_timestamp = None
        if long_short_ratio is not None:
            ratio_row = ratio_rows[0] if ratio_rows and isinstance(ratio_rows[0], dict) else {}
            ratio_timestamp = (
                _parse_time(ratio_row.get("timestamp"))
                or _parse_time(ratio_row.get("ts"))
                or _parse_time(ratio_payload.get("time"))
                or _parse_time(ratio_payload.get("retTime"))
            )
        directional_stamps = [value for value in (funding_timestamp, ratio_timestamp) if value is not None]
        directional_stamp = min(directional_stamps) if directional_stamps else None
        status = "READY" if funding_rate is not None or current_oi is not None or long_short_ratio is not None else "OFFLINE"
        return {
            "status": status,
            "source": "Bybit linear perpetual futures",
            "funding_rate": funding_rate,
            "next_funding_time_ms": _parse_time(row.get("nextFundingTime")),
            "mark_price": _finite(row.get("markPrice")),
            "index_price": _finite(row.get("indexPrice")),
            "open_interest": current_oi,
            "open_interest_value": _finite(row.get("openInterestValue")),
            "open_interest_change_pct_35m": round(oi_change, 5) if oi_change is not None else None,
            "long_short_ratio": round(long_short_ratio, 6) if long_short_ratio is not None else None,
            "long_short_sample_count": len(ratio_rows),
            "open_interest_sample_count": len(interest_rows),
            "turnover_24h": _finite(row.get("turnover24h")),
            "volume_24h": _finite(row.get("volume24h")),
            "directional_timestamp_ms": directional_stamp,
            "funding_timestamp_ms": funding_timestamp,
            "long_short_timestamp_ms": ratio_timestamp,
            "endpoint_statuses": endpoint_statuses,
            "endpoint_errors": endpoint_errors,
            "timestamp_ms": max(
                [stamp for stamp in (
                    _parse_time(ticker_payload.get("time")),
                    _parse_time(ticker_payload.get("retTime")),
                    _parse_time(row.get("ts")),
                    *[_parse_time(item.get("timestamp")) for item in interest_rows + ratio_rows if isinstance(item, dict)],
                ) if stamp is not None] or [int(time.time() * 1000)]
            ),
            "timestamp_basis": "PROVIDER_TIMESTAMP" if any(
                stamp is not None for stamp in (
                    _parse_time(ticker_payload.get("time")),
                    _parse_time(ticker_payload.get("retTime")),
                    _parse_time(row.get("ts")),
                    *[_parse_time(item.get("timestamp")) for item in interest_rows + ratio_rows if isinstance(item, dict)],
                )
            ) else "LOCAL_FETCH_TIME",
            "observed_at_ms": int(time.time() * 1000),
        }

    def _collect_okx_derivatives(self) -> dict[str, Any]:
        # OKX exposes public, unauthenticated market-data endpoints. Map the
        # configured BTCUSDT-style symbol to the matching perpetual contract.
        instrument_id = None
        base_currency = None
        for quote in ("USDT", "USDC", "USD"):
            if self.symbol.endswith(quote) and len(self.symbol) > len(quote):
                base_currency = self.symbol[:-len(quote)]
                instrument_id = f"{base_currency}-{quote}-SWAP"
                break
        if not instrument_id or not base_currency:
            return {
                "status": "OFFLINE",
                "source": "OKX public derivatives",
                "reason": f"Unsupported symbol mapping for {self.symbol}.",
                "endpoint_statuses": {
                    "funding": "NOT_REQUESTED",
                    "open_interest": "NOT_REQUESTED",
                    "account_ratio": "NOT_REQUESTED",
                },
                "endpoint_errors": {},
            }

        base = "https://openapi.okx.com/api/v5"
        urls = {
            "funding": base + "/public/funding-rate?" + urllib.parse.urlencode({"instId": instrument_id}),
            "open_interest": base + "/public/open-interest?" + urllib.parse.urlencode({
                "instType": "SWAP", "instId": instrument_id,
            }),
            # This is OKX's BTC-wide contract account ratio, not a single
            # instrument ratio; retain the scope in the returned evidence.
            "account_ratio": base + "/rubik/stat/contracts/long-short-account-ratio?" + urllib.parse.urlencode({
                "ccy": base_currency, "period": "5m", "limit": 8,
            }),
        }
        payloads: dict[str, Any] = {}
        endpoint_errors: dict[str, str] = {}
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = {
                pool.submit(self._json, url, ttl_seconds=30 if key != "account_ratio" else 120): key
                for key, url in urls.items()
            }
            for future in as_completed(futures):
                key = futures[future]
                try:
                    payloads[key] = future.result()
                except Exception as exc:
                    payloads[key] = None
                    endpoint_errors[key] = f"{type(exc).__name__}: {str(exc)[:240]}"

        endpoint_statuses: dict[str, str] = {}
        rows: dict[str, list[Any]] = {}
        for key, payload in payloads.items():
            if payload is None:
                endpoint_statuses[key] = "OFFLINE"
                rows[key] = []
                continue
            if not isinstance(payload, dict) or str(payload.get("code", "")) != "0":
                endpoint_statuses[key] = "API_ERROR"
                endpoint_errors[key] = str(
                    payload.get("msg", "Malformed OKX response.")
                    if isinstance(payload, dict) else "Malformed OKX response."
                )[:240]
                rows[key] = []
                continue
            data = payload.get("data")
            if not isinstance(data, list) or not data:
                endpoint_statuses[key] = "EMPTY"
                rows[key] = []
                continue
            endpoint_statuses[key] = "RESPONSE"
            rows[key] = data

        funding_row = rows["funding"][0] if rows["funding"] and isinstance(rows["funding"][0], dict) else {}
        # During settlement, settFundingRate is the rate actually used for
        # the current cycle. Otherwise fundingRate is the provider's next
        # settlement estimate; expose its basis rather than calling it a fill.
        settled_rate = _finite(funding_row.get("settFundingRate"))
        is_processing = str(funding_row.get("settState", "")).lower() == "processing"
        predicted_rate = _finite(funding_row.get("fundingRate"))
        if is_processing and settled_rate is not None:
            funding_rate = settled_rate
            funding_basis = "CURRENT_SETTLEMENT_RATE"
        else:
            funding_rate = predicted_rate
            funding_basis = "PREDICTED_NEXT_SETTLEMENT" if predicted_rate is not None else "UNAVAILABLE"
        funding_timestamp = _parse_time(funding_row.get("ts")) if funding_rate is not None else None

        oi_row = rows["open_interest"][0] if rows["open_interest"] and isinstance(rows["open_interest"][0], dict) else {}
        open_interest = _finite(oi_row.get("oi"))
        open_interest_usd = _finite(oi_row.get("oiUsd"))
        oi_timestamp = _parse_time(oi_row.get("ts")) if open_interest is not None or open_interest_usd is not None else None

        ratio_row = rows["account_ratio"][0] if rows["account_ratio"] else None
        long_short_ratio = None
        ratio_timestamp = None
        if isinstance(ratio_row, (list, tuple)) and len(ratio_row) >= 2:
            ratio_timestamp = _parse_time(ratio_row[0])
            long_short_ratio = _finite(ratio_row[1])
        elif isinstance(ratio_row, dict):
            ratio_timestamp = _parse_time(ratio_row.get("ts") or ratio_row.get("timestamp"))
            long_short_ratio = _finite(ratio_row.get("longShortAcctRatio") or ratio_row.get("longShortRatio"))

        observed_at = int(time.time() * 1000)
        status = "READY" if any(value is not None for value in (
            funding_rate, open_interest, open_interest_usd, long_short_ratio,
        )) else "OFFLINE"
        source_stamps = [stamp for stamp in (funding_timestamp, oi_timestamp, ratio_timestamp) if stamp is not None]
        return {
            "status": status,
            "source": "OKX USDT/USD perpetual futures",
            "instrument_id": instrument_id,
            "funding_rate": funding_rate,
            "funding_basis": funding_basis,
            "next_funding_time_ms": _parse_time(funding_row.get("nextFundingTime")),
            "open_interest": open_interest,
            "open_interest_usd": open_interest_usd,
            "long_short_ratio": long_short_ratio,
            "long_short_ratio_scope": f"OKX {base_currency} futures and perpetual contracts (currency aggregate)",
            "funding_timestamp_ms": funding_timestamp,
            "long_short_timestamp_ms": ratio_timestamp,
            "directional_timestamp_ms": min(
                [stamp for stamp in (funding_timestamp, ratio_timestamp) if stamp is not None],
                default=None,
            ),
            "timestamp_ms": max(source_stamps) if source_stamps else None,
            "timestamp_basis": "PROVIDER_TIMESTAMP" if source_stamps else "UNKNOWN",
            "endpoint_statuses": endpoint_statuses,
            "endpoint_errors": endpoint_errors,
            "observed_at_ms": observed_at,
        }

    def _collect_gateio_derivatives(self) -> dict[str, Any]:
        """Collect public Gate USDT-perpetual positioning as an independent venue.

        The contract-stat endpoint carries its own Unix-second timestamp.
        Ticker funding is retained for diagnostics only because that response
        does not provide an observation timestamp suitable for directional use.
        """
        base_currency = None
        contract = None
        if self.symbol.endswith("USDT") and len(self.symbol) > 4:
            base_currency = self.symbol[:-4]
            contract = f"{base_currency}_USDT"
        if not contract or not base_currency:
            return {
                "status": "OFFLINE",
                "source": "Gate.io USDT perpetual futures",
                "reason": f"Unsupported symbol mapping for {self.symbol}.",
                "endpoint_statuses": {
                    "ticker": "NOT_REQUESTED",
                    "contract_stats": "NOT_REQUESTED",
                },
                "endpoint_errors": {},
            }

        base = "https://api.gateio.ws/api/v4/futures/usdt"
        query = urllib.parse.urlencode({"contract": contract})
        urls = {
            "ticker": base + "/tickers?" + query,
            "contract_stats": base + "/contract_stats?" + query + "&interval=5m&limit=8",
        }
        payloads: dict[str, Any] = {}
        endpoint_errors: dict[str, str] = {}
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = {
                pool.submit(self._json, url, ttl_seconds=30 if key == "ticker" else 120): key
                for key, url in urls.items()
            }
            for future in as_completed(futures):
                key = futures[future]
                try:
                    payloads[key] = future.result()
                except Exception as exc:
                    payloads[key] = None
                    endpoint_errors[key] = f"{type(exc).__name__}: {str(exc)[:240]}"

        endpoint_statuses: dict[str, str] = {}
        ticker_payload = payloads.get("ticker")
        if ticker_payload is None:
            endpoint_statuses["ticker"] = "OFFLINE"
        elif not isinstance(ticker_payload, list):
            endpoint_statuses["ticker"] = "API_ERROR"
            endpoint_errors["ticker"] = "Malformed Gate ticker response."
        else:
            endpoint_statuses["ticker"] = "RESPONSE"

        stats_payload = payloads.get("contract_stats")
        if stats_payload is None:
            endpoint_statuses["contract_stats"] = "OFFLINE"
        elif not isinstance(stats_payload, list):
            endpoint_statuses["contract_stats"] = "API_ERROR"
            endpoint_errors["contract_stats"] = "Malformed Gate contract-statistics response."
        else:
            endpoint_statuses["contract_stats"] = "RESPONSE"

        ticker_rows = ticker_payload if isinstance(ticker_payload, list) else []
        ticker_row = next(
            (row for row in ticker_rows
             if isinstance(row, dict) and str(row.get("contract", "")).upper() == contract),
            {},
        )
        raw_stats = stats_payload if isinstance(stats_payload, list) else []
        stats_rows = [
            row for row in raw_stats
            if isinstance(row, dict) and _parse_time(row.get("time")) is not None
        ]
        stats_rows.sort(key=lambda row: _parse_time(row.get("time")) or 0)
        latest = stats_rows[-1] if stats_rows else {}
        first = stats_rows[0] if stats_rows else {}

        funding_rate = _finite(ticker_row.get("funding_rate"))
        current_oi = _finite(latest.get("open_interest"))
        current_oi_usd = _finite(latest.get("open_interest_usd"))
        oi_change = None
        first_oi = _finite(first.get("open_interest"))
        last_oi = _finite(latest.get("open_interest"))
        if len(stats_rows) >= 2 and first_oi is not None and last_oi is not None and first_oi > 0:
            oi_change = (last_oi - first_oi) / first_oi * 100.0

        # lsr_account is Gate's account-level long/short ratio. Top-trader
        # account/position and taker ratios remain separately labelled evidence.
        account_ratio = _finite(latest.get("lsr_account"))
        ratio_timestamp = _parse_time(latest.get("time")) if account_ratio is not None else None
        stat_timestamp = _parse_time(latest.get("time"))
        observed_at = int(time.time() * 1000)
        source_stamps = [stamp for stamp in (stat_timestamp,) if stamp is not None]
        status = "READY" if any(value is not None for value in (
            funding_rate, current_oi, account_ratio,
        )) else "OFFLINE"
        return {
            "status": status,
            "source": "Gate.io USDT perpetual futures",
            "contract": contract,
            "funding_rate": funding_rate,
            "funding_timestamp_ms": None,
            "funding_timestamp_basis": "UNSTAMPED_TICKER_SNAPSHOT_NOT_USED_DIRECTIONALLY",
            "mark_price": _finite(ticker_row.get("mark_price") or latest.get("mark_price")),
            "index_price": _finite(ticker_row.get("index_price")),
            "open_interest": current_oi,
            "open_interest_usd": current_oi_usd,
            "open_interest_change_pct_35m": round(oi_change, 5) if oi_change is not None else None,
            "long_short_ratio": account_ratio,
            "long_short_ratio_scope": "Gate USDT-perpetual account-level position-user ratio (lsr_account)",
            "long_short_sample_count": len(stats_rows),
            "long_short_timestamp_ms": ratio_timestamp,
            "directional_timestamp_ms": ratio_timestamp,
            "top_trader_long_short_account_ratio": _finite(latest.get("top_lsr_account")),
            "top_trader_long_short_position_ratio": _finite(latest.get("top_lsr_size")),
            "taker_long_short_ratio": _finite(latest.get("lsr_taker")),
            "long_liquidation_usd": _finite(latest.get("long_liq_usd_new") or latest.get("long_liq_usd")),
            "short_liquidation_usd": _finite(latest.get("short_liq_usd_new") or latest.get("short_liq_usd")),
            "timestamp_ms": max(source_stamps) if source_stamps else None,
            "timestamp_basis": "PROVIDER_TIMESTAMP" if source_stamps else "UNKNOWN",
            "endpoint_statuses": endpoint_statuses,
            "endpoint_errors": endpoint_errors,
            "observed_at_ms": observed_at,
        }

    def _collect_deribit_derivatives(self) -> dict[str, Any]:
        """Collect public BTC inverse-perpetual funding with the API provider timestamp."""
        base_currency = self.symbol.upper().replace("USDT", "").replace("USD", "")
        instrument = "BTC-PERPETUAL"
        if base_currency != "BTC":
            return {
                "status": "NOT_APPLICABLE",
                "source": "Deribit public BTC perpetual",
                "instrument": instrument,
                "reason": "Deribit fallback is currently defined only for BTC symbols.",
            }

        url = "https://www.deribit.com/api/v2/public/ticker?" + urllib.parse.urlencode({
            "instrument_name": instrument,
        })
        observed_at = int(time.time() * 1000)
        try:
            payload = self._json(url, ttl_seconds=30)
        except Exception as exc:
            return {
                "status": "OFFLINE",
                "source": "Deribit public BTC perpetual",
                "instrument": instrument,
                "funding_rate": None,
                "funding_timestamp_ms": None,
                "long_short_ratio": None,
                "long_short_timestamp_ms": None,
                "endpoint_statuses": {"ticker": "OFFLINE"},
                "endpoint_errors": {"ticker": f"{type(exc).__name__}: {str(exc)[:240]}"},
                "observed_at_ms": observed_at,
            }

        row = payload.get("result") if isinstance(payload, dict) else None
        if not isinstance(row, dict) or (isinstance(payload, dict) and payload.get("error")):
            error = payload.get("error") if isinstance(payload, dict) else None
            message = error.get("message", "Malformed Deribit ticker response.") if isinstance(error, dict) else "Malformed Deribit ticker response."
            return {
                "status": "OFFLINE",
                "source": "Deribit public BTC perpetual",
                "instrument": instrument,
                "funding_rate": None,
                "funding_timestamp_ms": None,
                "long_short_ratio": None,
                "long_short_timestamp_ms": None,
                "endpoint_statuses": {"ticker": "API_ERROR"},
                "endpoint_errors": {"ticker": str(message)[:240]},
                "observed_at_ms": observed_at,
            }

        # The REST JSON response uses snake_case. CamelCase remains only for
        # alternate wrappers; funding freshness always uses provider timestamp.
        provider_timestamp = _parse_time(row.get("timestamp"))
        if provider_timestamp is None:
            provider_timestamp = _parse_time(row.get("timestamp_ms"))
        funding_raw = row.get("funding_8h")
        if funding_raw is None:
            funding_raw = row.get("funding8h")
        funding = _finite(funding_raw)
        oi_raw = row.get("open_interest")
        if oi_raw is None:
            oi_raw = row.get("openInterest")
        open_interest = _finite(oi_raw)
        mark_raw = row.get("mark_price") if row.get("mark_price") is not None else row.get("markPrice")
        index_raw = row.get("index_price") if row.get("index_price") is not None else row.get("indexPrice")
        status = "READY" if funding is not None or open_interest is not None else "OFFLINE"
        return {
            "status": status,
            "source": "Deribit inverse BTC perpetual futures",
            "instrument": instrument,
            "funding_rate": funding,
            "funding_rate_basis": "8H_RATE" if funding is not None else "UNAVAILABLE",
            "funding_timestamp_ms": provider_timestamp if funding is not None else None,
            "long_short_ratio": None,
            "long_short_timestamp_ms": None,
            "open_interest": open_interest,
            "open_interest_unit": "BTC_CONTRACTS",
            "mark_price": _finite(mark_raw),
            "index_price": _finite(index_raw),
            "timestamp_ms": provider_timestamp,
            "timestamp_basis": "PROVIDER_TIMESTAMP" if provider_timestamp is not None else "UNKNOWN",
            "endpoint_statuses": {"ticker": "RESPONSE"},
            "endpoint_errors": {},
            "observed_at_ms": observed_at,
            "directional_scope": "Funding-only directional input; open interest remains context, not a vote.",
        }

    def _collect_hyperliquid_derivatives(self) -> dict[str, Any]:
        """Collect public BTC perpetual funding; convert the hourly rate to an 8h equivalent."""
        base_currency = self.symbol.upper().replace("USDT", "").replace("USD", "")
        if base_currency != "BTC":
            return {
                "status": "NOT_APPLICABLE",
                "source": "Hyperliquid public perpetuals",
                "reason": "Hyperliquid fallback is currently defined only for BTC symbols.",
            }
        url = "https://api.hyperliquid.xyz/info"
        observed_at = int(time.time() * 1000)
        try:
            payload, provider_timestamp = self._post_json_with_provider_time(
                url, {"type": "metaAndAssetCtxs"}, ttl_seconds=20
            )
        except Exception as exc:
            return {
                "status": "OFFLINE",
                "source": "Hyperliquid public perpetuals",
                "funding_rate": None,
                "funding_timestamp_ms": None,
                "long_short_ratio": None,
                "long_short_timestamp_ms": None,
                "endpoint_statuses": {"meta_and_asset_contexts": "OFFLINE"},
                "endpoint_errors": {
                    "meta_and_asset_contexts": f"{type(exc).__name__}: {str(exc)[:240]}"
                },
                "observed_at_ms": observed_at,
            }

        if not isinstance(payload, list) or len(payload) != 2:
            return {
                "status": "OFFLINE",
                "source": "Hyperliquid public perpetuals",
                "funding_rate": None,
                "funding_timestamp_ms": None,
                "long_short_ratio": None,
                "long_short_timestamp_ms": None,
                "endpoint_statuses": {"meta_and_asset_contexts": "INVALID"},
                "endpoint_errors": {"meta_and_asset_contexts": "Malformed metaAndAssetCtxs response."},
                "observed_at_ms": observed_at,
            }
        metadata, contexts = payload
        universe = metadata.get("universe") if isinstance(metadata, dict) else None
        if not isinstance(universe, list) or not isinstance(contexts, list) or len(universe) != len(contexts):
            return {
                "status": "OFFLINE",
                "source": "Hyperliquid public perpetuals",
                "funding_rate": None,
                "funding_timestamp_ms": None,
                "long_short_ratio": None,
                "long_short_timestamp_ms": None,
                "endpoint_statuses": {"meta_and_asset_contexts": "INVALID"},
                "endpoint_errors": {"meta_and_asset_contexts": "Universe and asset-context arrays do not align."},
                "observed_at_ms": observed_at,
            }
        index = next(
            (i for i, item in enumerate(universe)
             if isinstance(item, dict) and str(item.get("name", "")).upper() == "BTC"),
            None,
        )
        if index is None or not isinstance(contexts[index], dict):
            return {
                "status": "OFFLINE",
                "source": "Hyperliquid public perpetuals",
                "funding_rate": None,
                "funding_timestamp_ms": None,
                "long_short_ratio": None,
                "long_short_timestamp_ms": None,
                "endpoint_statuses": {"meta_and_asset_contexts": "BTC_NOT_FOUND"},
                "endpoint_errors": {},
                "observed_at_ms": observed_at,
            }

        row = contexts[index]
        hourly_funding = _finite(row.get("funding"))
        # Hyperliquid pays funding hourly at one eighth of its 8-hour formula.
        # Convert to an 8-hour equivalent before applying cross-venue scoring.
        funding_8h_equivalent = hourly_funding * 8.0 if hourly_funding is not None else None
        open_interest = _finite(row.get("openInterest"))
        status = "READY" if funding_8h_equivalent is not None or open_interest is not None else "OFFLINE"
        return {
            "status": status,
            "source": "Hyperliquid public BTC perpetual futures",
            "instrument": "BTC",
            "funding_rate": funding_8h_equivalent,
            "funding_rate_hourly": hourly_funding,
            "funding_rate_basis": "8H_EQUIVALENT_FROM_HOURLY" if hourly_funding is not None else "UNAVAILABLE",
            "funding_timestamp_ms": provider_timestamp if funding_8h_equivalent is not None else None,
            "funding_timestamp_basis": "HTTP_PROVIDER_DATE" if provider_timestamp is not None else "UNKNOWN",
            "long_short_ratio": None,
            "long_short_timestamp_ms": None,
            "open_interest": open_interest,
            "open_interest_unit": "BTC",
            "mark_price": _finite(row.get("markPx")),
            "index_price": _finite(row.get("oraclePx")),
            "timestamp_ms": provider_timestamp,
            "timestamp_basis": "HTTP_PROVIDER_DATE" if provider_timestamp is not None else "UNKNOWN",
            "endpoint_statuses": {"meta_and_asset_contexts": "RESPONSE"},
            "endpoint_errors": {},
            "observed_at_ms": observed_at,
            "directional_scope": (
                "Hourly Hyperliquid funding is converted to an 8-hour equivalent; "
                "HTTP Date is required for directional freshness. Open interest is context only."
            ),
        }

    def _collect_derivatives(self) -> dict[str, Any]:
        venues: dict[str, Any] = {}
        collectors = {
            "Binance": self._collect_binance_derivatives,
            "Bybit": self._collect_bybit_derivatives,
            "OKX": self._collect_okx_derivatives,
            "Gate.io": self._collect_gateio_derivatives,
            "Deribit": self._collect_deribit_derivatives,
            "Hyperliquid": self._collect_hyperliquid_derivatives,
        }
        with ThreadPoolExecutor(max_workers=len(collectors)) as pool:
            futures = {pool.submit(fn): name for name, fn in collectors.items()}
            for future in as_completed(futures):
                name = futures[future]
                try:
                    venues[name] = future.result()
                except Exception as exc:
                    venues[name] = {"status": "OFFLINE", "reason": f"{type(exc).__name__}: {exc}"}
        observed_at = int(time.time() * 1000)
        score = score_derivatives(venues, now_ms=observed_at)
        return {**score, "venue_scores": score.get("venues", {}), "venues": venues}

    def _collect_public_calendar(self, *, now_ms: int | None = None) -> dict[str, Any]:
        """Read public macro releases with provider timestamps and a 15-minute cache."""
        params = urllib.parse.urlencode({
            "currency": "USD,EUR,GBP,JPY,AUD,CAD,CHF,CNY,NZD",
            "impact": "high,medium,low", "days": 7, "format": "json",
        })
        payload = self._json(
            "https://showmytrades.com/api/public/calendar/v1?" + params,
            ttl_seconds=900,
        )
        if not isinstance(payload, dict):
            raise ValueError("Public economic calendar response is not an object.")
        captured = int(time.time() * 1000) if now_ms is None else int(now_ms)
        server_stamp = _parse_time(payload.get("server_time"))
        age = (captured - server_stamp) / 1000.0 if server_stamp is not None else None
        if server_stamp is None or age is None or age < -120.0 or age > 1800.0:
            return {
                "status": "STALE" if server_stamp is not None else "INVALID",
                "source": "ShowMyTrades public economic calendar",
                "server_time_ms": server_stamp,
                "freshness_age_seconds": round(age, 2) if age is not None else None,
                "freshness_max_age_seconds": 1800,
                "events": [],
                "reason": "Calendar provider clock is missing, future-dated or older than 30 minutes.",
            }
        rows = payload.get("events")
        if not isinstance(rows, list):
            raise ValueError("Public economic calendar response has no events array.")
        importance_map = {"HIGH": "HIGH", "MEDIUM": "MODERATE", "LOW": "LOW", "HOLIDAY": "HOLIDAY"}
        events = []
        for item in rows[:1000]:
            if not isinstance(item, dict):
                continue
            stamp = _parse_time(item.get("ts") or item.get("time"))
            name = str(item.get("title") or "").strip()
            impact = str(item.get("impact") or "").upper()
            if stamp is None or not name or impact not in importance_map:
                continue
            if stamp < server_stamp - 7 * 24 * 60 * 60_000 or stamp > server_stamp + 31 * 24 * 60 * 60_000:
                continue
            events.append({
                "event_id": str(item.get("id") or ""),
                "event_time_utc_ms": stamp,
                "name": name[:240],
                "country": str(item.get("country") or ""),
                "currency": str(item.get("currency") or "").upper()[:8],
                "importance": importance_map[impact],
                "forecast": item.get("forecast") or None,
                "previous": item.get("previous") or None,
                "actual": item.get("actual") or None,
                "provider": "ShowMyTrades",
                "source_url": "https://showmytrades.com/tools/economic-calendar",
                "provider_confidence": item.get("confidence"),
                "provider_status": item.get("status"),
            })
        attribution = payload.get("attribution") if isinstance(payload.get("attribution"), dict) else {}
        return {
            "status": "READY" if events else "EMPTY",
            "source": "ShowMyTrades public economic calendar",
            "server_time_ms": server_stamp,
            "freshness_age_seconds": round(age, 2),
            "freshness_max_age_seconds": 1800,
            "event_count": len(events),
            "events": events,
            "attribution_required": bool(attribution.get("required", False)),
            "attribution": attribution.get("text"),
            "scope": "Public macro releases for USD, EUR, GBP, JPY, AUD, CAD, CHF, CNY and NZD; cached locally for 15 minutes.",
        }

    def _collect_forex_factory_calendar(self, *, now_ms: int | None = None) -> dict[str, Any]:
        """Collect the public weekly macro calendar with CDN HTTP-Date freshness."""
        url = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
        captured = int(time.time() * 1000) if now_ms is None else int(now_ms)
        try:
            payload, server_stamp = self._json_with_provider_time(url, ttl_seconds=900)
        except Exception as exc:
            return {
                "status": "OFFLINE",
                "source": "Forex Factory public weekly calendar",
                "events": [],
                "reason": f"{type(exc).__name__}: {str(exc)[:240]}",
            }
        age = (captured - server_stamp) / 1000.0 if server_stamp is not None else None
        if server_stamp is None or age is None or age < -120.0 or age > 1800.0:
            return {
                "status": "STALE" if server_stamp is not None else "INVALID",
                "source": "Forex Factory public weekly calendar",
                "server_time_ms": server_stamp,
                "freshness_age_seconds": round(age, 2) if age is not None else None,
                "freshness_max_age_seconds": 1800,
                "events": [],
                "reason": "CDN HTTP Date is missing, future-dated or older than 30 minutes.",
            }
        if not isinstance(payload, list):
            return {
                "status": "INVALID",
                "source": "Forex Factory public weekly calendar",
                "server_time_ms": server_stamp,
                "events": [],
                "reason": "Calendar response is not a list.",
            }
        importance_map = {
            "HIGH": "HIGH",
            "MEDIUM": "MODERATE",
            "LOW": "LOW",
            "HOLIDAY": "HOLIDAY",
        }
        events: list[dict[str, Any]] = []
        for item in payload[:1000]:
            if not isinstance(item, dict):
                continue
            stamp = _parse_time(item.get("date"))
            name = str(item.get("title") or "").strip()
            impact = str(item.get("impact") or "").strip().upper()
            if stamp is None or not name or impact not in importance_map:
                continue
            if stamp < server_stamp - 7 * 24 * 60 * 60_000 or stamp > server_stamp + 9 * 24 * 60 * 60_000:
                continue
            currency = str(item.get("country") or "").strip().upper()[:8]
            events.append({
                "event_id": str(item.get("id") or ""),
                "event_time_utc_ms": stamp,
                "name": name[:240],
                "country": currency,
                "currency": currency,
                "importance": importance_map[impact],
                "forecast": item.get("forecast") or None,
                "previous": item.get("previous") or None,
                "actual": item.get("actual") or None,
                "provider": "Forex Factory",
                "source_url": url,
            })
        events.sort(key=lambda row: row["event_time_utc_ms"])
        return {
            "status": "READY" if events else "EMPTY",
            "source": "Forex Factory public weekly calendar",
            "server_time_ms": server_stamp,
            "freshness_age_seconds": round(age, 2),
            "freshness_max_age_seconds": 1800,
            "event_count": len(events),
            "events": events,
            "scope": "Public weekly macro calendar; CDN HTTP Date is required and events are normalized to UTC.",
        }

    def _collect_trading_economics(self, *, now: datetime | None = None) -> dict[str, Any]:
        if not self.trading_economics_api_key:
            return {"status": "NOT_CONFIGURED", "source": "Trading Economics",
                    "countries": list(self.calendar_countries), "events": [],
                    "reason": "Optional API key is not configured."}
        from datetime import timedelta
        now = now or datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        now = now.astimezone(timezone.utc)
        start = now.replace(hour=0, minute=0, second=0, microsecond=0).date().isoformat()
        end = (now.date() + timedelta(days=7)).isoformat()
        # Trading Economics supports comma-separated country names in this route.
        # The API key is supplied via environment and never copied into snapshots.
        country_path = ",".join(urllib.parse.quote(country, safe="") for country in self.calendar_countries)
        url = (
            "https://api.tradingeconomics.com/calendar/country/" + country_path + "/"
            + start + "/" + end + "?"
            + urllib.parse.urlencode({"c": self.trading_economics_api_key})
        )
        raw = self._json(url, ttl_seconds=300)
        if not isinstance(raw, list):
            raise ValueError("Trading Economics calendar response is not a list.")
        events = []
        for item in raw[:500]:
            if not isinstance(item, dict):
                continue
            stamp = _parse_time(item.get("Date"))
            name = str(item.get("Event") or item.get("Category") or "").strip()
            if not stamp or not name:
                continue
            importance = _finite(item.get("Importance"))
            events.append({
                "event_id": str(item.get("CalendarId") or ""),
                "event_time_utc_ms": stamp,
                "name": name[:240],
                "country": str(item.get("Country") or "United States"),
                "currency": str(item.get("Currency") or "USD"),
                "importance": "HIGH" if importance is not None and importance >= 3 else "MODERATE" if importance is not None and importance >= 2 else "LOW",
                "forecast": item.get("Forecast") or item.get("TEForecast"),
                "te_forecast": item.get("TEForecast"),
                "previous": item.get("Previous"),
                "actual": item.get("Actual"),
                "category": str(item.get("Category") or "")[:160],
                "source": str(item.get("Source") or "")[:200],
                "provider": "Trading Economics",
                "source_url": item.get("SourceURL") or item.get("URL"),
            })
        return {"status": "READY" if events else "EMPTY", "source": "Trading Economics",
                "countries": list(self.calendar_countries), "events": events}

    @staticmethod
    def _calendar_context(sources: dict[str, Any], now_ms: int) -> dict[str, Any]:
        """Merge independent public macro-calendar providers owned by Engine 1."""
        events: list[dict[str, Any]] = []
        provider_statuses: dict[str, str] = {}
        for provider, raw in sources.items():
            raw = raw if isinstance(raw, dict) else {}
            provider_statuses[provider] = str(raw.get("status", "NOT_AVAILABLE")).upper()
            for item in raw.get("events", []) if isinstance(raw.get("events"), list) else []:
                if not isinstance(item, dict):
                    continue
                stamp = _parse_time(item.get("event_time_utc_ms"))
                name = str(item.get("name") or "").strip()
                importance = str(item.get("importance") or "NONE").upper()
                if not stamp or not name or importance not in {"HIGH", "MODERATE", "LOW", "NONE", "HOLIDAY"}:
                    continue
                normalized = {
                    "event_id": str(item.get("event_id") or ""),
                    "event_time_utc_ms": stamp,
                    "name": name[:240],
                    "country": str(item.get("country") or ""),
                    "currency": str(item.get("currency") or "").upper()[:8],
                    "importance": importance,
                    "forecast": item.get("forecast"),
                    "previous": item.get("previous"),
                    "actual": item.get("actual"),
                    "provider": str(item.get("provider") or provider),
                    "source_url": item.get("source_url"),
                }
                duplicate = any(
                    abs(int(existing["event_time_utc_ms"]) - stamp) <= 300_000
                    and str(existing["name"]).casefold() == name.casefold()
                    and str(existing.get("currency") or "").casefold()
                        == str(normalized.get("currency") or "").casefold()
                    for existing in events
                )
                if not duplicate:
                    events.append(normalized)
        events.sort(key=lambda row: row["event_time_utc_ms"])
        before_ms, after_ms = 15 * 60_000, 10 * 60_000
        active = []
        for item in events:
            delta = int(item["event_time_utc_ms"]) - now_ms
            if item["importance"] == "HIGH" and -after_ms <= delta <= before_ms:
                active.append({
                    "name": item["name"],
                    "provider": item.get("provider"),
                    "currency": item.get("currency"),
                    "event_time_utc_ms": item["event_time_utc_ms"],
                    "minutes_to_event": round(delta / 60_000, 1),
                })
        has_provider = any(value in {"READY", "EMPTY"} for value in provider_statuses.values())
        return {
            "status": "READY" if events else "EMPTY" if has_provider else "NOT_AVAILABLE",
            "source": "ENGINE1_INDEPENDENT_PUBLIC_CALENDARS",
            "events": events[:500],
            "event_count": len(events),
            "sources": provider_statuses,
            "high_impact_window_active": bool(active),
            "active_high_impact_events": active,
            "new_entry_gate": "WAIT" if active else "CLEAR",
            "gate_window_minutes": {"before": 15, "after": 10},
            "next_24h_high_impact_events": [
                {
                    "name": item["name"],
                    "country": item.get("country"),
                    "currency": item.get("currency"),
                    "provider": item.get("provider"),
                    "event_time_utc_ms": item["event_time_utc_ms"],
                    "minutes_to_event": round((int(item["event_time_utc_ms"]) - now_ms) / 60_000, 1),
                }
                for item in events
                if item["importance"] == "HIGH"
                and 0 <= int(item["event_time_utc_ms"]) - now_ms <= 24 * 60 * 60_000
            ][:30],
            "countries_covered": sorted({
                str(item.get("country") or item.get("currency") or "")
                for item in events if item.get("country") or item.get("currency")
            }),
            "scope": "Independent public macro calendars only; no MT5 or other-engine input is consumed.",
        }

    def collect(self, *, now_ms: int | None = None) -> dict[str, Any]:
        """Collect Engine 1 evidence from its own providers; accepts no engine payload."""
        captured = int(time.time() * 1000) if now_ms is None else int(now_ms)
        tasks = {
            "news": self._collect_news,
            "fear_greed": self._collect_fear_greed,
            "global_metrics": self._collect_global_metrics,
            "derivatives": self._collect_derivatives,
            "trading_economics": self._collect_trading_economics,
            "public_calendar": lambda: self._collect_public_calendar(now_ms=captured),
            "forex_factory_calendar": lambda: self._collect_forex_factory_calendar(now_ms=captured),
        }
        results: dict[str, dict[str, Any]] = {}
        with ThreadPoolExecutor(max_workers=len(tasks)) as pool:
            futures = {pool.submit(fn): name for name, fn in tasks.items()}
            for future in as_completed(futures):
                name = futures[future]
                try:
                    value = future.result()
                    results[name] = value if isinstance(value, dict) else {"status": "INVALID"}
                except Exception as exc:
                    results[name] = {"status": "OFFLINE", "reason": f"{type(exc).__name__}: {exc}"}
        news = results.get("news", {"status": "OFFLINE"})
        news_score = news.get("sentiment") if isinstance(news.get("sentiment"), dict) else {"status": "UNAVAILABLE"}
        fear_greed = results.get("fear_greed", {"status": "OFFLINE"})
        global_metrics = results.get("global_metrics", {"status": "OFFLINE"})
        derivatives = results.get("derivatives", {"status": "OFFLINE", "score": None, "confidence": 0.0})
        calendar = self._calendar_context({
            "showmytrades": results.get("public_calendar", {}),
            "trading_economics": results.get("trading_economics", {}),
            "forex_factory": results.get("forex_factory_calendar", {}),
        }, captured)
        composite = compose_directional_context(
            news=news_score,
            fear_greed=fear_greed,
            derivatives=derivatives,
        )
        source_statuses = {
            name: str(value.get("status", "NOT_REPORTED"))
            for name, value in results.items()
        }
        source_statuses["showmytrades_calendar"] = calendar["sources"]["showmytrades"]
        source_statuses["trading_economics_calendar"] = calendar["sources"]["trading_economics"]
        source_statuses["forex_factory_calendar"] = calendar["sources"]["forex_factory"]
        risk_assessment = assess_market_risk(
            news=news, fear_greed=fear_greed, derivatives=derivatives,
            calendar=calendar, now_ms=captured,
        )
        fresh_news = [
            item for item in (news.get("items", []) if isinstance(news.get("items"), list) else [])
            if isinstance(item, dict) and isinstance(item.get("published_at_ms"), int)
            and -2 * 60 * 60_000 <= captured - item["published_at_ms"] <= 72 * 60 * 60_000
        ]
        overall = composite["status"]
        return {
            "schema": ENGINE_SCHEMA,
            "engine": "engine_1_market_intelligence",
            "symbol": self.symbol,
            "captured_at_ms": captured,
            "status": overall,
            "direction": composite.get("direction", "UNKNOWN"),
            "directional_score": composite.get("directional_score"),
            "confidence": composite.get("confidence", 0.0),
            "evidence_coverage": composite.get("evidence_coverage", 0.0),
            "confidence_basis": composite["confidence_basis"],
            "scenario": composite.get("scenario", {
                "primary": "UNKNOWN", "label": "الأدلة غير كافية",
                "horizon": "context_only_no_calibrated_horizon",
            }),
            "components": composite["components"],
            "news": news,
            "fear_greed": fear_greed,
            "global_metrics": global_metrics,
            "derivatives": derivatives,
            "economic_calendar": calendar,
            "market_risk_assessment": risk_assessment,
            "outlook": {
                "directional_bias": composite.get("direction", "UNKNOWN"),
                "evidence_status": composite.get("status"),
                "risk_level": risk_assessment.get("level", "UNKNOWN"),
                "horizon": "CONTEXT_ONLY_NOT_CALIBRATED",
                "monitor_next": calendar.get("next_24h_high_impact_events", [])[:8],
                "interpretation": "Qualitative scenario context for Engine 4; not a price target or statistical forecast.",
            },
            "source_statuses": source_statuses,
            "risk_alerts": {
                "high_impact_event_window": calendar["high_impact_window_active"],
                "headline_risk_count": sum(bool(item.get("risk_flags")) for item in fresh_news),
                "headline_risk_items": [
                    {"title": item.get("title"), "source": item.get("source"),
                     "sources": item.get("sources", []), "published_at_ms": item.get("published_at_ms"),
                     "url": item.get("url"), "risk_flags": item.get("risk_flags", [])}
                    for item in fresh_news if item.get("risk_flags")
                ][:10],
                "market_risk_level": risk_assessment.get("level"),
                "market_risk_drivers": risk_assessment.get("drivers", []),
            },
            "boundaries": [
                "Engine 1 is standalone and accepts no MT5 market snapshot or payload from Engines 2, 3 or 5.",
                "No chart images, OHLC candles, swing highs/lows, EMA, RSI or ATR are read or calculated by Engine 1.",
                "Funding/long-short indicators are exchange-specific derivatives positioning, not spot order flow.",
                "Headline sentiment is a transparent keyword heuristic; duplicate headlines are grouped across publishers and the content is not fact-checked.",
                "Provider timestamps and maximum ages are checked before Fear & Greed and derivatives evidence contributes; stale evidence is excluded.",
                "Market risk classification and outlook are descriptive context only; the explicit macro event gate remains separate.",
                "Directional score and confidence are contextual evidence scores, not calibrated probabilities or profit forecasts.",
            ],
        }

