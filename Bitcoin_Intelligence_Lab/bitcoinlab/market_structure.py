from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import math
import statistics
from typing import Mapping, Sequence

from .indicators import true_ranges
from .models import Bar


def _finite_positive(value: object, field: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{field} must be numeric.") from exc
    if not math.isfinite(parsed) or parsed <= 0:
        raise ValueError(f"{field} must be finite and positive.")
    return parsed


def trade_volume_profile(
    trades: Sequence[Mapping[str, object]],
    *,
    bin_size: float | None = None,
    value_area_fraction: float = 0.70,
    max_bins: int = 600,
) -> dict:
    """
    Build a sampled trade-at-price profile from exchange aggregate trades.

    Binance aggTrade m=True means buyer was maker (aggressive sell).
    The profile is explicitly scoped to the supplied trade sample, not a
    full session unless the caller has supplied the full session.
    """
    if not trades:
        return {
            "status": "unavailable",
            "reason": "No recent executed trades were supplied.",
            "scope": "recent_sample_not_full_session",
        }
    if not 0.50 <= float(value_area_fraction) <= 0.90:
        raise ValueError("value_area_fraction must be within [0.50, 0.90].")
    if isinstance(max_bins, bool) or not isinstance(max_bins, int) or max_bins < 10:
        raise ValueError("max_bins must be an integer >= 10.")

    parsed: list[tuple[float, float, bool, int | None]] = []
    prices: list[float] = []
    for row in trades:
        price = _finite_positive(row.get("p", row.get("price")), "trade price")
        quantity = _finite_positive(row.get("q", row.get("qty", row.get("quantity"))), "trade quantity")
        maker = row.get("m")
        if not isinstance(maker, bool):
            raise ValueError("Binance aggregate trade is missing the buyer-maker flag.")
        timestamp_value = row.get("T", row.get("time"))
        timestamp = int(timestamp_value) if timestamp_value is not None else None
        if timestamp is not None and timestamp <= 0:
            raise ValueError("Trade timestamp must be positive.")
        parsed.append((price, quantity, maker, timestamp))
        prices.append(price)

    if bin_size is None:
        low, high = min(prices), max(prices)
        bin_size = max((high - low) / min(120, max_bins), statistics.median(prices) * 0.00005)
    bin_size = _finite_positive(bin_size, "bin_size")

    levels: dict[float, dict[str, float | int]] = defaultdict(
        lambda: {"buy_base": 0.0, "sell_base": 0.0, "buy_quote": 0.0, "sell_quote": 0.0, "trades": 0}
    )
    total_buy = total_sell = total_quote = 0.0
    timestamps: list[int] = []
    for price, quantity, buyer_is_maker, timestamp in parsed:
        level = math.floor(price / bin_size) * bin_size
        row = levels[level]
        notional = price * quantity
        if buyer_is_maker:
            row["sell_base"] = float(row["sell_base"]) + quantity
            row["sell_quote"] = float(row["sell_quote"]) + notional
            total_sell += quantity
        else:
            row["buy_base"] = float(row["buy_base"]) + quantity
            row["buy_quote"] = float(row["buy_quote"]) + notional
            total_buy += quantity
        row["trades"] = int(row["trades"]) + 1
        total_quote += notional
        if timestamp is not None:
            timestamps.append(timestamp)

    ordered = sorted(levels)
    quote_by_level = {
        price: float(levels[price]["buy_quote"]) + float(levels[price]["sell_quote"])
        for price in ordered
    }
    poc = max(ordered, key=lambda price: (quote_by_level[price], price))
    target_quote = total_quote * value_area_fraction
    left = right = ordered.index(poc)
    accumulated = quote_by_level[poc]
    while accumulated < target_quote and (left > 0 or right < len(ordered) - 1):
        left_quote = quote_by_level[ordered[left - 1]] if left > 0 else -1.0
        right_quote = quote_by_level[ordered[right + 1]] if right < len(ordered) - 1 else -1.0
        if right_quote > left_quote:
            right += 1
            accumulated += right_quote
        elif left > 0:
            left -= 1
            accumulated += left_quote
        else:
            break

    bins = []
    for price in ordered:
        row = levels[price]
        buy_quote, sell_quote = float(row["buy_quote"]), float(row["sell_quote"])
        bins.append({
            "price_low": round(price, 8),
            "price_high": round(price + bin_size, 8),
            "buy_volume_btc": round(float(row["buy_base"]), 8),
            "sell_volume_btc": round(float(row["sell_base"]), 8),
            "buy_notional_usd": round(buy_quote, 2),
            "sell_notional_usd": round(sell_quote, 2),
            "total_notional_usd": round(quote_by_level[price], 2),
            "trade_count": int(row["trades"]),
        })

    delta = total_buy - total_sell
    duration_seconds = (
        (max(timestamps) - min(timestamps)) / 1000.0
        if len(timestamps) >= 2 else None
    )
    return {
        "status": "ok",
        "scope": "recent_sample_not_full_session",
        "sample_trade_count": len(parsed),
        "sample_window_seconds": round(duration_seconds, 3) if duration_seconds is not None else None,
        "bin_size": bin_size,
        "value_area_fraction": value_area_fraction,
        "poc": round(poc + bin_size / 2, 8),
        "vah": round(ordered[right] + bin_size, 8),
        "val": round(ordered[left], 8),
        "total_buy_volume_btc": round(total_buy, 8),
        "total_sell_volume_btc": round(total_sell, 8),
        "delta_btc": round(delta, 8),
        "delta_ratio": round(delta / (total_buy + total_sell), 6) if total_buy + total_sell else 0.0,
        "total_notional_usd": round(total_quote, 2),
        "bins": bins,
        "coverage_start_utc": datetime.fromtimestamp(min(timestamps) / 1000, timezone.utc).isoformat() if timestamps else None,
        "coverage_end_utc": datetime.fromtimestamp(max(timestamps) / 1000, timezone.utc).isoformat() if timestamps else None,
        "limitations": [
            "This is a bounded sample of recent aggregate trades, not a complete exchange session.",
            "Aggressor-side classification follows the exchange buyer-maker flag.",
            "Price bins depend on the selected bin_size and do not reconstruct individual resting orders.",
        ],
    }


def bar_market_structure(bars: Sequence[Bar], *, lookback_bars: int = 60) -> dict:
    """Calculate bar-based VWAP, relative volume, realized volatility and range expansion."""
    completed = [bar for bar in bars if bar.is_closed]
    if len(completed) < 22:
        return {
            "status": "incomplete",
            "reason": "At least 22 completed bars are required for volume baseline metrics.",
        }
    if isinstance(lookback_bars, bool) or not isinstance(lookback_bars, int) or lookback_bars < 2:
        raise ValueError("lookback_bars must be an integer >= 2.")

    current = completed[-1]
    prior = completed[-21:-1]
    baseline_volume = statistics.fmean(bar.volume for bar in prior)
    relative_volume = current.volume / baseline_volume if baseline_volume > 0 else None

    utc_day_start = datetime.fromtimestamp(current.close_time_ms / 1000, timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0,
    )
    day_start_ms = int(utc_day_start.timestamp() * 1000)
    session = [bar for bar in completed if bar.open_time_ms >= day_start_ms]
    if not session:
        session = [current]
    session_volume = sum(bar.volume for bar in session)
    session_vwap = (
        sum(((bar.high + bar.low + bar.close) / 3.0) * bar.volume for bar in session) / session_volume
        if session_volume > 0 else None
    )
    session_coverage_minutes = max(
        0.0, (current.close_time_ms - session[0].open_time_ms) / 60_000.0,
    )

    returns = [
        math.log(completed[index].close / completed[index - 1].close)
        for index in range(max(1, len(completed) - lookback_bars), len(completed))
        if completed[index - 1].close > 0
    ]
    realized_volatility_pct = (
        statistics.pstdev(returns) * 100.0 if len(returns) >= 2 else None
    )

    ranges = true_ranges(completed)
    previous_ranges = ranges[-21:-1]
    median_range = statistics.median(previous_ranges) if previous_ranges else 0.0
    range_expansion = ranges[-1] / median_range if median_range > 0 else None

    return {
        "status": "ok",
        "last_close": current.close,
        "session_vwap_utc": session_vwap,
        "session_vwap_coverage_minutes": round(session_coverage_minutes, 2),
        "session_vwap_bars": len(session),
        "relative_volume_20": round(relative_volume, 4) if relative_volume is not None else None,
        "volume_baseline_20": round(baseline_volume, 8),
        "realized_volatility_pct_per_bar": round(realized_volatility_pct, 6) if realized_volatility_pct is not None else None,
        "realized_volatility_bars": len(returns),
        "range_expansion_vs_prior_median": round(range_expansion, 4) if range_expansion is not None else None,
        "last_true_range": ranges[-1],
        "prior_median_true_range": median_range,
        "limitations": [
            "VWAP is calculated from completed candle typical prices, not tick-level trade prices.",
            "Realized volatility is the non-annualized standard deviation of log returns per bar.",
            "Relative volume compares the latest completed candle with the prior 20 completed candles.",
        ],
    }


def market_structure_profile(
    bars: Sequence[Bar],
    trades: Sequence[Mapping[str, object]],
    *,
    bin_size: float | None = None,
) -> dict:
    bar_metrics = bar_market_structure(bars)
    try:
        volume_profile = trade_volume_profile(trades, bin_size=bin_size)
    except (TypeError, ValueError) as exc:
        volume_profile = {
            "status": "incomplete",
            "reason": f"{type(exc).__name__}: {exc}"[:220],
            "scope": "recent_sample_not_full_session",
        }
    return {
        "status": "ok" if bar_metrics.get("status") == "ok" else "incomplete",
        "bars": bar_metrics,
        "volume_profile": volume_profile,
        "interpretation": (
            "VWAP/relative-volume/range metrics describe the closed-bar structure; "
            "the trade-at-price profile describes only the supplied recent trade sample."
        ),
    }
