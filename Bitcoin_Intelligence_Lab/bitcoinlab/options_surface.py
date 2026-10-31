from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import math
import statistics
from typing import Any, Mapping, Sequence


_YEAR_MS = 365.25 * 24 * 60 * 60 * 1000


def _positive(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(number) or number <= 0:
        return None
    return number


def _non_negative(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(number) or number < 0:
        return None
    return number


def _normal_cdf(value: float) -> float:
    return 0.5 * (1.0 + math.erf(value / math.sqrt(2.0)))


def black_scholes_option_greeks(
    *,
    spot: float,
    strike: float,
    time_years: float,
    volatility: float,
    option_type: str,
    risk_free_rate: float = 0.0,
) -> dict[str, float]:
    """European Black-Scholes delta/gamma used for descriptive option-chain analytics."""
    numbers = (spot, strike, time_years, volatility, risk_free_rate)
    if any(not math.isfinite(float(item)) for item in numbers):
        raise ValueError("Black-Scholes inputs must be finite.")
    if spot <= 0 or strike <= 0 or time_years <= 0 or volatility <= 0:
        raise ValueError("Spot, strike, time and volatility must be positive.")
    kind = option_type.lower()
    if kind not in {"call", "put"}:
        raise ValueError("option_type must be call or put.")
    root_t = math.sqrt(time_years)
    sigma_root_t = volatility * root_t
    d1 = (
        math.log(spot / strike)
        + (risk_free_rate + 0.5 * volatility * volatility) * time_years
    ) / sigma_root_t
    d2 = d1 - sigma_root_t
    pdf = math.exp(-0.5 * d1 * d1) / math.sqrt(2.0 * math.pi)
    discount = math.exp(-risk_free_rate * time_years)
    call_delta = _normal_cdf(d1)
    delta = call_delta if kind == "call" else call_delta - 1.0
    gamma = pdf / (spot * sigma_root_t)
    return {
        "delta": delta,
        "gamma": gamma,
        "d1": d1,
        "d2": d2,
        "discount_factor": discount,
    }


def _normalize_option_type(value: object) -> str | None:
    text = str(value or "").lower()
    if text in {"call", "c"}:
        return "call"
    if text in {"put", "p"}:
        return "put"
    return None


def build_btc_options_surface(
    instruments: Sequence[Mapping[str, Any]],
    summaries: Sequence[Mapping[str, Any]],
    *,
    now_ms: int,
    max_expiries: int = 12,
) -> dict[str, Any]:
    """Build expiry IV/skew/OI views and a non-directional gross gamma-OI map."""
    if now_ms <= 0:
        raise ValueError("now_ms must be positive.")
    if not 1 <= max_expiries <= 40:
        raise ValueError("max_expiries must be between 1 and 40.")

    metadata = {
        str(row.get("instrument_name")): row
        for row in instruments
        if isinstance(row, Mapping) and row.get("instrument_name")
    }
    parsed: list[dict[str, Any]] = []
    rejected = 0
    for summary in summaries:
        if not isinstance(summary, Mapping):
            rejected += 1
            continue
        name = str(summary.get("instrument_name") or "")
        instrument = metadata.get(name)
        if not instrument:
            rejected += 1
            continue
        kind = _normalize_option_type(instrument.get("option_type"))
        strike = _positive(instrument.get("strike"))
        expiry = _positive(instrument.get("expiration_timestamp"))
        spot = _positive(summary.get("underlying_price"))
        mark_iv = _positive(summary.get("mark_iv"))
        open_interest = _non_negative(summary.get("open_interest"))
        if (
            kind is None or strike is None or expiry is None
            or spot is None or mark_iv is None or open_interest is None
            or instrument.get("is_active") is False
        ):
            rejected += 1
            continue
        # Deribit mark_iv is expressed in volatility percentage points.
        volatility = mark_iv / 100.0
        if not 0.01 <= volatility <= 5.0:
            rejected += 1
            continue
        time_years = (int(expiry) - now_ms) / _YEAR_MS
        if time_years <= 0:
            rejected += 1
            continue
        try:
            greeks = black_scholes_option_greeks(
                spot=spot, strike=strike, time_years=time_years,
                volatility=volatility, option_type=kind,
            )
        except ValueError:
            rejected += 1
            continue
        parsed.append({
            "instrument_name": name,
            "option_type": kind,
            "strike": strike,
            "expiration_timestamp": int(expiry),
            "expiry_utc": datetime.fromtimestamp(
                int(expiry) / 1000, timezone.utc,
            ).date().isoformat(),
            "days_to_expiry": time_years * 365.25,
            "spot": spot,
            "mark_iv_pct": mark_iv,
            "open_interest_btc": open_interest,
            "contract_size": _positive(instrument.get("contract_size")),
            "delta": greeks["delta"],
            "gamma_per_spot_unit": greeks["gamma"],
            "gamma_oi_proxy_btc_weighted": greeks["gamma"] * open_interest,
        })

    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for item in parsed:
        grouped[item["expiration_timestamp"]].append(item)

    expiry_rows: list[dict[str, Any]] = []
    gamma_by_strike: dict[float, float] = defaultdict(float)
    for expiry_ms, rows in sorted(grouped.items())[:max_expiries]:
        spot = statistics.median(item["spot"] for item in rows)
        calls = [item for item in rows if item["option_type"] == "call"]
        puts = [item for item in rows if item["option_type"] == "put"]
        call_oi = sum(item["open_interest_btc"] for item in calls)
        put_oi = sum(item["open_interest_btc"] for item in puts)
        total_oi = call_oi + put_oi

        near_atm = sorted(
            rows,
            key=lambda item: abs(math.log(item["strike"] / spot)),
        )[:4]
        atm_iv = statistics.median(item["mark_iv_pct"] for item in near_atm) if near_atm else None

        call_25 = min(calls, key=lambda item: abs(item["delta"] - 0.25), default=None)
        put_25 = min(puts, key=lambda item: abs(item["delta"] + 0.25), default=None)
        rr25 = (
            call_25["mark_iv_pct"] - put_25["mark_iv_pct"]
            if call_25 is not None and put_25 is not None else None
        )
        if call_25 is None or put_25 is None:
            rr_status = "incomplete_25_delta_pair"
        else:
            rr_status = "ok"

        gamma_group: dict[float, float] = defaultdict(float)
        for item in rows:
            gamma_group[item["strike"]] += item["gamma_oi_proxy_btc_weighted"]
            gamma_by_strike[item["strike"]] += item["gamma_oi_proxy_btc_weighted"]

        expiry_rows.append({
            "expiry_utc": datetime.fromtimestamp(
                expiry_ms / 1000, timezone.utc,
            ).date().isoformat(),
            "expiration_timestamp": expiry_ms,
            "days_to_expiry": round(statistics.median(item["days_to_expiry"] for item in rows), 3),
            "underlying_price": round(spot, 2),
            "atm_iv_pct": round(atm_iv, 3) if atm_iv is not None else None,
            "risk_reversal_25d_vol_points": round(rr25, 3) if rr25 is not None else None,
            "risk_reversal_status": rr_status,
            "call_open_interest_btc": round(call_oi, 8),
            "put_open_interest_btc": round(put_oi, 8),
            "put_call_oi_ratio": round(put_oi / call_oi, 4) if call_oi > 0 else None,
            "total_open_interest_btc": round(total_oi, 8),
            "option_count": len(rows),
            "unsigned_gamma_open_interest_btc_proxy_by_strike": [
                {
                    "strike": strike,
                    "gamma_oi_proxy_btc_weighted": round(value, 12),
                }
                for strike, value in sorted(
                    gamma_group.items(), key=lambda pair: pair[1], reverse=True,
                )[:10]
            ],
            "limitations": [
                "ATM IV uses the four strikes closest to spot, not a fitted arbitrage-free surface.",
                "25-delta skew uses Black-Scholes spot delta with zero rates as a descriptive approximation.",
                "Open interest is reported in BTC for BTC options and is aggregate, not dealer inventory.",
            ],
        })

    if not parsed:
        return {
            "status": "empty",
            "currency": "BTC",
            "fetched_at_utc": datetime.fromtimestamp(now_ms / 1000, timezone.utc).isoformat(),
            "option_count": 0,
            "rejected_count": rejected,
            "expiries": [],
            "unsigned_gamma_open_interest_btc_proxy_by_strike": [],
            "warnings": ["no_valid_active_BTC_option_summaries"],
        }

    return {
        "status": "ok",
        "currency": "BTC",
        "fetched_at_utc": datetime.fromtimestamp(now_ms / 1000, timezone.utc).isoformat(),
        "option_count": len(parsed),
        "expiry_count": len(expiry_rows),
        "rejected_count": rejected,
        "expiries": expiry_rows,
        "unsigned_gamma_open_interest_btc_proxy_by_strike": [
            {"strike": strike, "gamma_oi_proxy_btc_weighted": round(value, 12)}
            for strike, value in sorted(
                gamma_by_strike.items(), key=lambda pair: pair[1], reverse=True,
            )[:20]
        ],
        "interpretation": (
            "Descriptive option-market context: implied-volatility term structure, "
            "25-delta risk reversal, put/call OI and unsigned gamma-weighted OI concentration."
        ),
        "limitations": [
            "Open interest for BTC options is reported in underlying BTC units and does not identify net dealer positioning.",
            "Gamma-weighted BTC open interest is unsigned and must not be labelled dealer GEX or net dealer exposure.",
            "Black-Scholes Greeks use zero rates and spot as a simplified forward proxy.",
            "Only active options with valid mark IV, OI, strike and expiry are included.",
            "No-arbitrage SVI fitting, historical surface replay and dealer inventory inference are not implemented.",
        ],
    }
