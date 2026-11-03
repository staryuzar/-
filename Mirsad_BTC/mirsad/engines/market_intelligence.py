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
CACHE_LOCK = threading.Lock()
MAX_RESPONSE_BYTES = 2_000_000
MAX_HEADLINES = 40
COMPONENT_WEIGHTS = {"derivatives": 0.45, "news": 0.35, "fear_greed": 0.20}

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


def score_news_items(items: list[dict[str, Any]]) -> dict[str, Any]:
    directional = [
        item for item in items
        if _finite(item.get("sentiment_score")) not in (None, 0.0)
    ]
    if not directional:
        return {"status": "INSUFFICIENT", "score": None, "classified_count": 0,
                "confidence": 0.0, "scope": "Explainable headline keyword signal; not an AI fact-check or calibrated forecast."}
    values = [_clamp(float(item["sentiment_score"])) for item in directional]
    sources = {str(item.get("source", "")) for item in directional if item.get("source")}
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


def score_derivatives(venues: dict[str, Any]) -> dict[str, Any]:
    observations: list[tuple[float, float, str]] = []
    diagnostics: dict[str, Any] = {}
    for name, raw in venues.items():
        if not isinstance(raw, dict) or raw.get("status") not in {"READY", "PARTIAL"}:
            continue
        funding = _finite(raw.get("funding_rate"))
        ratio = _finite(raw.get("long_short_ratio"))
        venue_parts: list[float] = []
        if funding is not None:
            # Positive funding means longs pay shorts; extreme positive funding
            # is treated as crowded-long risk, not as a bullish momentum signal.
            venue_parts.append(_clamp(-funding / 0.0005) * 0.60)
        if ratio is not None and ratio > 0:
            venue_parts.append(_clamp(-math.log(ratio) / math.log(3.0)) * 0.40)
        if venue_parts:
            total_weight = 0.60 if funding is not None else 0.0
            if ratio is not None and ratio > 0:
                total_weight += 0.40
            score = sum(venue_parts) / max(0.0001, total_weight)
            confidence = 1.0 if funding is not None and ratio is not None else 0.55
            observations.append((score, confidence, name))
            diagnostics[name] = {**raw, "directional_score": round(_clamp(score), 4)}
    if not observations:
        return {"status": "UNAVAILABLE", "score": None, "confidence": 0.0,
                "venues": diagnostics, "scope": "Perpetual futures positioning; exchange-specific, not the full crypto market."}
    weights = [item[1] for item in observations]
    score = sum(item[0] * item[1] for item in observations) / sum(weights)
    confidence = min(1.0, len(observations) / 2.0) * (sum(weights) / len(weights))
    return {
        "status": "READY" if len(observations) >= 2 else "PARTIAL",
        "score": round(_clamp(score), 4),
        "confidence": round(confidence, 4),
        "venue_count": len(observations),
        "venues": diagnostics,
        "scope": "Funding and long/short positioning are interpreted contrarily; open-interest change is context/intensity, not direction by itself.",
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
    ) -> None:
        self.symbol = str(symbol or "BTCUSDT").strip().upper()
        self.timeout_seconds = max(2.0, min(15.0, float(timeout_seconds)))
        self.trading_economics_api_key = str(trading_economics_api_key or "").strip()

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
            body = response.read(MAX_RESPONSE_BYTES + 1)
        if len(body) > MAX_RESPONSE_BYTES:
            raise ValueError("Provider response exceeds the configured size limit.")
        with CACHE_LOCK:
            CACHE[url] = (now, body)
        return body

    def _json(self, url: str, *, ttl_seconds: int = 30) -> Any:
        raw = self._fetch(url, ttl_seconds=ttl_seconds, accept="application/json")
        return json.loads(raw.decode("utf-8"))

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
        seen: set[str] = set()
        unique: list[dict[str, Any]] = []
        for item in sorted(items, key=lambda value: value.get("published_at_ms") or 0, reverse=True):
            key = str(item.get("url") or item.get("title") or "").strip().casefold()
            if key and key not in seen:
                seen.add(key)
                unique.append(item)
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
            "sources": source_statuses,
            "sentiment": score_news_items(fresh),
            "scope": "Headlines and short RSS summaries; directional sentiment uses timestamps from the last 72 hours; no article body scraping or claim verification.",
        }

    def _collect_fear_greed(self) -> dict[str, Any]:
        payload = self._json("https://api.alternative.me/fng/?limit=2&format=json", ttl_seconds=300)
        rows = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(rows, list) or not rows:
            raise ValueError("Fear and Greed provider returned no data rows.")
        latest = rows[0]
        value = _finite(latest.get("value"))
        stamp = _parse_time(latest.get("timestamp"))
        if value is None or not 0 <= value <= 100 or stamp is None:
            raise ValueError("Fear and Greed response is missing a valid value or timestamp.")
        score = _clamp((50.0 - value) / 50.0)
        return {
            "status": "READY",
            "source": "Alternative.me Fear & Greed Index",
            "value": int(value),
            "classification": str(latest.get("value_classification", "UNKNOWN")),
            "timestamp_ms": stamp,
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
        metrics = {
            "total_market_cap_usd": _finite(payload.get("total_market_cap_usd")),
            "total_24h_volume_usd": _finite(payload.get("total_24h_volume_usd")),
            "bitcoin_dominance_pct": _finite(payload.get("bitcoin_percentage_of_market_cap")),
            "active_markets": _finite(payload.get("active_markets")),
        }
        if not any(value is not None for value in metrics.values()):
            raise ValueError("Global market metrics contain no usable fields.")
        return {"status": "READY", "source": "Alternative.me global market data",
                "timestamp_ms": updated, "metrics": metrics}

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
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = {pool.submit(self._json, url, ttl_seconds=30 if key in {"premium", "open_interest"} else 120): key
                       for key, url in urls.items()}
            for future in as_completed(futures):
                key = futures[future]
                try:
                    values[key] = future.result()
                except Exception:
                    values[key] = None
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
        stamp = _parse_time(premium.get("time")) or _parse_time(interest.get("time"))
        status = "READY" if funding is not None or current_oi is not None else "OFFLINE"
        return {
            "status": status, "source": "Binance USD-M perpetual futures",
            "funding_rate": funding, "next_funding_time_ms": _parse_time(premium.get("nextFundingTime")),
            "mark_price": _finite(premium.get("markPrice")),
            "index_price": _finite(premium.get("indexPrice")),
            "open_interest": current_oi, "open_interest_change_pct_35m": round(oi_change, 5) if oi_change is not None else None,
            "long_short_ratio": ratio, "timestamp_ms": stamp,
            "long_short_sample_count": len(ratio_history), "open_interest_sample_count": len(oi_history),
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
                except Exception:
                    payloads[key] = None

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
            "timestamp_ms": int(time.time() * 1000),
        }

    def _collect_derivatives(self) -> dict[str, Any]:
        venues: dict[str, Any] = {}
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = {
                pool.submit(self._collect_binance_derivatives): "Binance",
                pool.submit(self._collect_bybit_derivatives): "Bybit",
            }
            for future in as_completed(futures):
                name = futures[future]
                try:
                    venues[name] = future.result()
                except Exception as exc:
                    venues[name] = {"status": "OFFLINE", "reason": f"{type(exc).__name__}: {exc}"}
        score = score_derivatives(venues)
        return {**score, "venues": venues}

    def _collect_trading_economics(self) -> dict[str, Any]:
        if not self.trading_economics_api_key:
            return {"status": "NOT_CONFIGURED", "source": "Trading Economics",
                    "events": [], "reason": "Optional API key is not configured."}
        from datetime import timedelta
        now = datetime.now(timezone.utc)
        start = now.replace(hour=0, minute=0, second=0, microsecond=0).date().isoformat()
        end = (now.date() + timedelta(days=7)).isoformat()
        # TE calendar values are returned in UTC. The API key is supplied via
        # an environment variable and is never written into logs or snapshots.
        url = (
            "https://api.tradingeconomics.com/calendar/country/united%20states/"
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
                "forecast": item.get("Forecast"),
                "previous": item.get("Previous"),
                "actual": item.get("Actual"),
                "provider": "Trading Economics",
                "source_url": item.get("SourceURL"),
            })
        return {"status": "READY" if events else "EMPTY", "source": "Trading Economics",
                "events": events}

    @staticmethod
    def _calendar_context(market: dict[str, Any], external: dict[str, Any], now_ms: int) -> dict[str, Any]:
        context = market.get("market_context") if isinstance(market.get("market_context"), dict) else {}
        broker = context.get("economic_calendar") if isinstance(context.get("economic_calendar"), dict) else {}
        events: list[dict[str, Any]] = []
        for item in broker.get("events", []) if isinstance(broker.get("events"), list) else []:
            if not isinstance(item, dict):
                continue
            stamp = _parse_time(item.get("event_time_utc_ms"))
            name = str(item.get("name") or "").strip()
            if not stamp or not name:
                continue
            events.append({
                "event_id": str(item.get("event_id") or ""),
                "event_time_utc_ms": stamp,
                "name": name[:240],
                "country": str(item.get("country_code") or "US"),
                "currency": str(item.get("currency") or "USD"),
                "importance": str(item.get("importance") or "NONE").upper(),
                "provider": "MT5 Broker Calendar",
            })
        for item in external.get("events", []) if isinstance(external.get("events"), list) else []:
            if not isinstance(item, dict):
                continue
            # Avoid duplicate TE/MT5 events for the same release within 5 minutes.
            stamp = _parse_time(item.get("event_time_utc_ms"))
            name = str(item.get("name") or "").strip()
            if not stamp or not name:
                continue
            duplicate = any(
                abs(int(existing["event_time_utc_ms"]) - stamp) <= 300_000
                and str(existing["name"]).casefold() == name.casefold()
                for existing in events
            )
            if not duplicate:
                events.append(item)
        events.sort(key=lambda item: item["event_time_utc_ms"])
        before_ms = 15 * 60_000
        after_ms = 10 * 60_000
        active = []
        for item in events:
            importance = str(item.get("importance", "")).upper()
            high = importance in {"HIGH", "3"}
            delta = int(item["event_time_utc_ms"]) - now_ms
            if high and -after_ms <= delta <= before_ms:
                active.append({
                    "name": item["name"],
                    "provider": item.get("provider"),
                    "event_time_utc_ms": item["event_time_utc_ms"],
                    "minutes_to_event": round(delta / 60_000, 1),
                })
        return {
            "status": "READY" if events else (
                "NOT_AVAILABLE" if broker.get("status") == "NOT_AVAILABLE" else "EMPTY"
            ),
            "events": events[:500],
            "event_count": len(events),
            "sources": {
                "mt5_broker": broker.get("status", "NOT_REPORTED"),
                "trading_economics": external.get("status", "NOT_CONFIGURED"),
            },
            "high_impact_window_active": bool(active),
            "active_high_impact_events": active,
            "new_entry_gate": "WAIT" if active else "CLEAR",
            "gate_window_minutes": {"before": 15, "after": 10},
            "scope": "Macro releases from the connected MT5 broker calendar plus optional Trading Economics; not a crypto-project token unlock calendar.",
        }

    def collect(self, market: dict[str, Any] | None = None, *, now_ms: int | None = None) -> dict[str, Any]:
        market = market if isinstance(market, dict) else {}
        captured = int(time.time() * 1000) if now_ms is None else int(now_ms)
        tasks = {
            "news": self._collect_news,
            "fear_greed": self._collect_fear_greed,
            "global_metrics": self._collect_global_metrics,
            "derivatives": self._collect_derivatives,
            "trading_economics": self._collect_trading_economics,
        }
        results: dict[str, dict[str, Any]] = {}
        with ThreadPoolExecutor(max_workers=5) as pool:
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
        calendar = self._calendar_context(market, results.get("trading_economics", {}), captured)
        composite = compose_directional_context(
            news=news_score,
            fear_greed=fear_greed,
            derivatives=derivatives,
        )
        source_statuses = {
            name: str(value.get("status", "NOT_REPORTED"))
            for name, value in results.items()
        }
        source_statuses["mt5_broker_calendar"] = calendar["sources"]["mt5_broker"]
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
            "source_statuses": source_statuses,
            "risk_alerts": {
                "high_impact_event_window": calendar["high_impact_window_active"],
                "headline_risk_count": sum(bool(item.get("risk_flags")) for item in news.get("items", [])),
                "headline_risk_items": [
                    {"title": item.get("title"), "source": item.get("source"),
                     "url": item.get("url"), "risk_flags": item.get("risk_flags", [])}
                    for item in news.get("items", []) if item.get("risk_flags")
                ][:10],
            },
            "boundaries": [
                "No chart images, OHLC candles, swing highs/lows, EMA, RSI or ATR are read or calculated by Engine 1.",
                "Funding/long-short indicators are exchange-specific derivatives positioning, not spot order flow.",
                "Headline sentiment is a transparent keyword heuristic and is not article verification.",
                "Directional score and confidence are contextual evidence scores, not calibrated probabilities or profit forecasts.",
            ],
        }
