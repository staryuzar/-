"""Independent TV26-style technical-rating engine.

This module accepts caller-supplied OHLCV bars (normally from MT5/broker data).
It does not connect to a platform, access TradingView data, make network calls,
or execute trades. The caller must provide chronologically ordered CLOSED bars.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import numpy as np
import pandas as pd

ADXProfile = Literal["official_help", "technicalrating_v3"]

@dataclass(frozen=True)
class ComponentSpec:
    key: str
    label_ar: str
    group: Literal["moving_average", "oscillator"]

MA_COMPONENTS: tuple[ComponentSpec, ...] = (
    ComponentSpec("SMA10", "متوسط بسيط 10", "moving_average"),
    ComponentSpec("SMA20", "متوسط بسيط 20", "moving_average"),
    ComponentSpec("SMA30", "متوسط بسيط 30", "moving_average"),
    ComponentSpec("SMA50", "متوسط بسيط 50", "moving_average"),
    ComponentSpec("SMA100", "متوسط بسيط 100", "moving_average"),
    ComponentSpec("SMA200", "متوسط بسيط 200", "moving_average"),
    ComponentSpec("EMA10", "متوسط أسي 10", "moving_average"),
    ComponentSpec("EMA20", "متوسط أسي 20", "moving_average"),
    ComponentSpec("EMA30", "متوسط أسي 30", "moving_average"),
    ComponentSpec("EMA50", "متوسط أسي 50", "moving_average"),
    ComponentSpec("EMA100", "متوسط أسي 100", "moving_average"),
    ComponentSpec("EMA200", "متوسط أسي 200", "moving_average"),
    ComponentSpec("HMA9", "متوسط هال 9", "moving_average"),
    ComponentSpec("VWMA20", "متوسط مرجح بالحجم 20", "moving_average"),
    ComponentSpec("Ichimoku", "إيشيموكو", "moving_average"),
)

OSCILLATOR_COMPONENTS: tuple[ComponentSpec, ...] = (
    ComponentSpec("RSI14", "القوة النسبية RSI", "oscillator"),
    ComponentSpec("Stochastic", "ستوكاستك 14/3/3", "oscillator"),
    ComponentSpec("CCI20", "قناة السلع CCI", "oscillator"),
    ComponentSpec("ADX", "مؤشر الاتجاه ADX", "oscillator"),
    ComponentSpec("AO", "المذبذب الرائع AO", "oscillator"),
    ComponentSpec("Momentum10", "الزخم Momentum", "oscillator"),
    ComponentSpec("MACD", "تقارب/تباعد المتوسطات MACD", "oscillator"),
    ComponentSpec("StochRSI", "ستوكاستك RSI", "oscillator"),
    ComponentSpec("WilliamsR", "ويليامز %R", "oscillator"),
    ComponentSpec("BullBearPower", "قوة الثيران والدببة", "oscillator"),
    ComponentSpec("UltimateOscillator", "المذبذب النهائي", "oscillator"),
)

COMPONENTS: tuple[ComponentSpec, ...] = MA_COMPONENTS + OSCILLATOR_COMPONENTS
MA_KEYS = tuple(x.key for x in MA_COMPONENTS)
OSCILLATOR_KEYS = tuple(x.key for x in OSCILLATOR_COMPONENTS)
COMPONENT_BY_KEY = {x.key: x for x in COMPONENTS}
SUPPORTED_TIMEFRAMES = frozenset({"M1", "M5", "M15", "M30", "H1"})

class DataQualityError(ValueError):
    """Raised when the supplied market data cannot be safely analysed."""

class TechnicalRatingError(ValueError):
    """Raised for unsupported analysis settings."""

def rating_category(score: float | None) -> str:
    """Map a normalized rating to the current published help-page categories."""
    if score is None or not np.isfinite(float(score)):
        return "غير متاح"
    value = float(score)
    if value < -0.5:
        return "بيع قوي"
    if value < -0.1:
        return "بيع"
    if value <= 0.1:
        return "حياد"
    if value <= 0.5:
        return "شراء"
    return "شراء قوي"

def vote_category(vote: int | None) -> str:
    if vote is None:
        return "غير متاح"
    if vote > 0:
        return "شراء (+1)"
    if vote < 0:
        return "بيع (-1)"
    return "حياد (0)"

def _normalise_ohlcv(frame: pd.DataFrame, timeframe: str) -> tuple[pd.DataFrame, str, str | None]:
    if timeframe not in SUPPORTED_TIMEFRAMES:
        raise TechnicalRatingError(
            f"Unsupported timeframe {timeframe!r}; expected one of {sorted(SUPPORTED_TIMEFRAMES)}."
        )
    if not isinstance(frame, pd.DataFrame):
        raise DataQualityError("OHLCV input must be a pandas DataFrame.")
    columns = {str(name).strip().lower(): name for name in frame.columns}
    volume_name = "volume" if "volume" in columns else ("tick_volume" if "tick_volume" in columns else None)
    required = ("open", "high", "low", "close")
    missing = [name for name in required if name not in columns]
    if volume_name is None:
        missing.append("volume or tick_volume")
    if missing:
        raise DataQualityError("Missing required OHLCV columns: " + ", ".join(missing))
    if frame.empty:
        raise DataQualityError("No market bars were supplied.")
    time_name = next((columns[k] for k in ("time", "timestamp", "datetime") if k in columns), None)
    data = pd.DataFrame({
        "open": pd.to_numeric(frame[columns["open"]], errors="raise"),
        "high": pd.to_numeric(frame[columns["high"]], errors="raise"),
        "low": pd.to_numeric(frame[columns["low"]], errors="raise"),
        "close": pd.to_numeric(frame[columns["close"]], errors="raise"),
        "volume": pd.to_numeric(frame[columns[volume_name]], errors="raise"),
    }).reset_index(drop=True)
    numeric = data[["open", "high", "low", "close", "volume"]].to_numpy(dtype=float)
    if not np.isfinite(numeric).all():
        raise DataQualityError("OHLCV contains a missing or non-finite numeric value; data was not filled or guessed.")
    if (data[["open", "high", "low", "close"]] <= 0).any().any():
        raise DataQualityError("Gold OHLC prices must be positive.")
    if (data["volume"] < 0).any():
        raise DataQualityError("Volume cannot be negative.")
    body_high = data[["open", "close"]].max(axis=1)
    body_low = data[["open", "close"]].min(axis=1)
    if (data["high"] < body_high - 1e-12).any():
        raise DataQualityError("A candle high is below its open or close.")
    if (data["low"] > body_low + 1e-12).any():
        raise DataQualityError("A candle low is above its open or close.")
    if (data["high"] < data["low"]).any():
        raise DataQualityError("A candle high is below its low.")
    bar_time: str | None = None
    if time_name is not None:
        raw_time = frame[time_name].reset_index(drop=True)
        try:
            if pd.api.types.is_numeric_dtype(raw_time):
                parsed = pd.to_datetime(raw_time, unit="s", utc=True, errors="raise")
            else:
                parsed = pd.to_datetime(raw_time, errors="raise")
        except (TypeError, ValueError, OverflowError) as exc:
            raise DataQualityError(f"Invalid bar timestamp: {exc}") from exc
        if parsed.isna().any():
            raise DataQualityError("A bar timestamp is missing.")
        if parsed.duplicated().any():
            raise DataQualityError("Duplicate bar timestamps detected; input was not deduplicated automatically.")
        if not parsed.is_monotonic_increasing:
            raise DataQualityError("Bars must be supplied oldest-to-newest; input was not silently sorted.")
        data["time"] = parsed
        bar_time = str(parsed.iloc[-1])
    volume_source = "tick_volume" if volume_name == "tick_volume" else "volume"
    return data, volume_source, bar_time

def _ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False, min_periods=1).mean()

def _rma(series: pd.Series, period: int) -> pd.Series:
    """Wilder RMA: seed from the first SMA of period valid values."""
    values = series.to_numpy(dtype=float)
    result = np.full(len(values), np.nan, dtype=float)
    valid_positions = np.flatnonzero(np.isfinite(values))
    if len(valid_positions) < period:
        return pd.Series(result, index=series.index)
    seed_pos = int(valid_positions[period - 1])
    seed = float(np.mean(values[valid_positions[:period]]))
    result[seed_pos] = seed
    previous = seed
    alpha = 1.0 / float(period)
    for pos in range(seed_pos + 1, len(values)):
        if np.isfinite(values[pos]):
            previous = alpha * values[pos] + (1.0 - alpha) * previous
        result[pos] = previous
    return pd.Series(result, index=series.index)

def _wma(series: pd.Series, period: int) -> pd.Series:
    weights = np.arange(1, period + 1, dtype=float)
    denominator = float(weights.sum())
    return series.rolling(period, min_periods=period).apply(
        lambda values: float(np.dot(values, weights) / denominator), raw=True
    )

def _sign_price_level(price: pd.Series, level: pd.Series, epsilon: float) -> pd.Series:
    difference = price - level
    valid = price.notna() & level.notna()
    result = pd.Series(np.nan, index=price.index, dtype=float)
    values = difference.loc[valid]
    result.loc[valid] = np.where(values.abs() <= epsilon, 0.0, np.sign(values))
    return result

def _conditional_vote(
    readiness: tuple[pd.Series, ...],
    bullish: pd.Series,
    bearish: pd.Series,
) -> pd.Series:
    index = readiness[0].index
    valid = pd.Series(True, index=index, dtype=bool)
    for series in readiness:
        valid &= series.notna()
    result = pd.Series(np.nan, index=index, dtype=float)
    if valid.any():
        up = bullish.fillna(False).astype(bool)
        down = bearish.fillna(False).astype(bool)
        result.loc[valid] = np.where(up.loc[valid], 1.0, np.where(down.loc[valid], -1.0, 0.0))
    return result

def _compute_components(frame: pd.DataFrame, adx_profile: ADXProfile, price_epsilon: float) -> dict[str, dict[str, Any]]:
    high, low, close, volume = (frame[k].astype(float) for k in ("high", "low", "close", "volume"))
    result: dict[str, dict[str, Any]] = {}

    def add(key: str, vote: pd.Series, **raw: pd.Series) -> None:
        result[key] = {"vote": vote, "raw": raw}

    for period in (10, 20, 30, 50, 100, 200):
        sma = close.rolling(period, min_periods=period).mean()
        exponential = _ema(close, period)
        add(f"SMA{period}", _sign_price_level(close, sma, price_epsilon), average=sma, close=close)
        add(f"EMA{period}", _sign_price_level(close, exponential, price_epsilon), average=exponential, close=close)

    hma = _wma(2.0 * _wma(close, 4) - _wma(close, 9), 3)
    add("HMA9", _sign_price_level(close, hma, price_epsilon), average=hma, close=close)
    volume_denominator = volume.rolling(20, min_periods=20).sum()
    vwma = (close * volume).rolling(20, min_periods=20).sum() / volume_denominator.replace(0, np.nan)
    add("VWMA20", _sign_price_level(close, vwma, price_epsilon), average=vwma, close=close)

    tenkan = (high.rolling(9, min_periods=9).max() + low.rolling(9, min_periods=9).min()) / 2.0
    kijun = (high.rolling(26, min_periods=26).max() + low.rolling(26, min_periods=26).min()) / 2.0
    span_a = (tenkan + kijun) / 2.0
    span_b = (high.rolling(52, min_periods=52).max() + low.rolling(52, min_periods=52).min()) / 2.0
    lead_a, lead_b = span_a.shift(26), span_b.shift(26)
    ichi_vote = _conditional_vote(
        (lead_a, lead_b, kijun, tenkan, close),
        (lead_a > lead_b) & (kijun > lead_a) & (tenkan > kijun) & (close > tenkan),
        (lead_a < lead_b) & (kijun < lead_a) & (tenkan < kijun) & (close < tenkan),
    )
    add("Ichimoku", ichi_vote, conversion=tenkan, base=kijun, leading_span_a=lead_a, leading_span_b=lead_b, close=close)

    rsi_delta = close.diff()
    average_gain = _rma(rsi_delta.clip(lower=0), 14)
    average_loss = _rma((-rsi_delta).clip(lower=0), 14)
    relative_strength = average_gain / average_loss
    rsi_value = 100.0 - (100.0 / (1.0 + relative_strength))
    rsi_value.loc[(average_loss == 0) & (average_gain > 0)] = 100.0
    rsi_value.loc[(average_gain == 0) & (average_loss > 0)] = 0.0
    rsi_value.loc[(average_gain == 0) & (average_loss == 0)] = 50.0
    rsi_previous = rsi_value.shift(1)
    rsi_vote = _conditional_vote(
        (rsi_value, rsi_previous),
        (rsi_value < 30) & (rsi_value > rsi_previous),
        (rsi_value > 70) & (rsi_value < rsi_previous),
    )
    add("RSI14", rsi_vote, value=rsi_value, previous=rsi_previous)

    stochastic_low = low.rolling(14, min_periods=14).min()
    stochastic_high = high.rolling(14, min_periods=14).max()
    raw_k = 100.0 * (close - stochastic_low) / (stochastic_high - stochastic_low).replace(0, np.nan)
    stochastic_k = raw_k.rolling(3, min_periods=3).mean()
    stochastic_d = stochastic_k.rolling(3, min_periods=3).mean()
    stochastic_vote = _conditional_vote(
        (stochastic_k, stochastic_d, stochastic_d.shift(1)),
        (stochastic_k < 20) & (stochastic_d < 20) & (stochastic_k > stochastic_d),
        (stochastic_k > 80) & (stochastic_d > 80) & (stochastic_k < stochastic_d),
    )
    add("Stochastic", stochastic_vote, k=stochastic_k, d=stochastic_d)

    # The pinned TechnicalRating v3 reference uses close as the CCI source.
    # This differs from the common textbook HLC3 default; keep it explicit.
    cci_mean = close.rolling(20, min_periods=20).mean()
    mean_deviation = close.rolling(20, min_periods=20).apply(
        lambda values: float(np.mean(np.abs(values - np.mean(values))),), raw=True
    )
    cci_value = (close - cci_mean) / (0.015 * mean_deviation.replace(0, np.nan))
    cci_previous = cci_value.shift(1)
    cci_vote = _conditional_vote(
        (cci_value, cci_previous),
        (cci_value < -100) & (cci_value > cci_previous),
        (cci_value > 100) & (cci_value < cci_previous),
    )
    add("CCI20", cci_vote, value=cci_value, previous=cci_previous)

    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = pd.Series(np.where((up_move > down_move) & (up_move > 0), up_move, 0.0), index=frame.index)
    minus_dm = pd.Series(np.where((down_move > up_move) & (down_move > 0), down_move, 0.0), index=frame.index)
    plus_dm.loc[up_move.isna() | down_move.isna()] = np.nan
    previous_close = close.shift(1)
    true_range = pd.Series(
        np.maximum(
            (high - low).to_numpy(),
            np.maximum((high - previous_close).abs().to_numpy(), (low - previous_close).abs().to_numpy()),
        ),
        index=frame.index,
    )
    atr = _rma(true_range, 14)
    plus_di = 100.0 * _rma(plus_dm, 14) / atr
    minus_di = 100.0 * _rma(minus_dm, 14) / atr
    di_sum = (plus_di + minus_di).replace(0, 1)
    dx = 100.0 * (plus_di - minus_di).abs() / di_sum
    adx = _rma(dx, 14)
    adx_previous = adx.shift(1)
    bullish_adx = (adx > 20) & (adx > adx_previous) & (plus_di > minus_di)
    if adx_profile == "official_help":
        bearish_adx = (adx > 20) & (adx < adx_previous) & (plus_di < minus_di)
    elif adx_profile == "technicalrating_v3":
        bearish_adx = (adx > 20) & (adx > adx_previous) & (plus_di < minus_di)
    else:
        raise TechnicalRatingError(f"Unsupported ADX profile {adx_profile!r}.")
    adx_vote = _conditional_vote((adx, adx_previous, plus_di, minus_di), bullish_adx, bearish_adx)
    add("ADX", adx_vote, value=adx, previous=adx_previous, plus_di=plus_di, minus_di=minus_di, atr=atr)

    midpoint = (high + low) / 2.0
    ao = midpoint.rolling(5, min_periods=5).mean() - midpoint.rolling(34, min_periods=34).mean()
    ao_previous, ao_two_back = ao.shift(1), ao.shift(2)
    ao_bullish = ((ao > 0) & (ao_previous <= 0)) | ((ao > 0) & (ao_previous > 0) & (ao > ao_previous) & (ao_two_back > ao_previous))
    ao_bearish = ((ao < 0) & (ao_previous >= 0)) | ((ao < 0) & (ao_previous < 0) & (ao < ao_previous) & (ao_two_back < ao_previous))
    ao_vote = _conditional_vote((ao, ao_previous, ao_two_back), ao_bullish, ao_bearish)
    add("AO", ao_vote, value=ao, previous=ao_previous, two_bars_back=ao_two_back)

    momentum = close - close.shift(10)
    momentum_previous = momentum.shift(1)
    momentum_vote = _conditional_vote(
        (momentum, momentum_previous), momentum > momentum_previous, momentum < momentum_previous
    )
    add("Momentum10", momentum_vote, value=momentum, previous=momentum_previous, close=close, close_10_bars_ago=close.shift(10))

    macd_line = _ema(close, 12) - _ema(close, 26)
    macd_signal = _ema(macd_line, 9)
    macd_vote = _conditional_vote(
        (macd_line, macd_signal), macd_line > macd_signal, macd_line < macd_signal
    )
    add("MACD", macd_vote, line=macd_line, signal=macd_signal)

    rsi_min = rsi_value.rolling(14, min_periods=14).min()
    rsi_max = rsi_value.rolling(14, min_periods=14).max()
    raw_stoch_rsi = 100.0 * (rsi_value - rsi_min) / (rsi_max - rsi_min).replace(0, np.nan)
    stoch_rsi_k = raw_stoch_rsi.rolling(3, min_periods=3).mean()
    stoch_rsi_d = stoch_rsi_k.rolling(3, min_periods=3).mean()
    ema50 = _ema(close, 50)
    downtrend = close < ema50
    uptrend = close > ema50
    stoch_rsi_vote = _conditional_vote(
        (stoch_rsi_k, stoch_rsi_d, ema50),
        downtrend & (stoch_rsi_k < 20) & (stoch_rsi_d < 20) & (stoch_rsi_k > stoch_rsi_d),
        uptrend & (stoch_rsi_k > 80) & (stoch_rsi_d > 80) & (stoch_rsi_k < stoch_rsi_d),
    )
    add("StochRSI", stoch_rsi_vote, k=stoch_rsi_k, d=stoch_rsi_d, close=close, ema50=ema50)

    highest_14 = high.rolling(14, min_periods=14).max()
    lowest_14 = low.rolling(14, min_periods=14).min()
    williams_r = -100.0 * (highest_14 - close) / (highest_14 - lowest_14).replace(0, np.nan)
    williams_previous = williams_r.shift(1)
    williams_vote = _conditional_vote(
        (williams_r, williams_previous),
        (williams_r < -80) & (williams_r > williams_previous),
        (williams_r > -20) & (williams_r < williams_previous),
    )
    add("WilliamsR", williams_vote, value=williams_r, previous=williams_previous)

    bull_power = high - _ema(close, 13)
    bear_power = low - _ema(close, 13)
    bull_previous, bear_previous = bull_power.shift(1), bear_power.shift(1)
    bull_bear_vote = _conditional_vote(
        (bull_power, bear_power, bull_previous, bear_previous, ema50),
        uptrend & (bear_power < 0) & (bear_power > bear_previous),
        downtrend & (bull_power > 0) & (bull_power < bull_previous),
    )
    add("BullBearPower", bull_bear_vote, bull=bull_power, bull_previous=bull_previous, bear=bear_power, bear_previous=bear_previous, ema50=ema50)

    previous_close = close.shift(1)
    upper_bound = pd.Series(np.maximum(high.to_numpy(), previous_close.to_numpy()), index=frame.index)
    lower_bound = pd.Series(np.minimum(low.to_numpy(), previous_close.to_numpy()), index=frame.index)
    uo_tr = upper_bound - lower_bound
    buying_pressure = close - lower_bound
    avg_7 = buying_pressure.rolling(7, min_periods=7).sum() / uo_tr.rolling(7, min_periods=7).sum().replace(0, np.nan)
    avg_14 = buying_pressure.rolling(14, min_periods=14).sum() / uo_tr.rolling(14, min_periods=14).sum().replace(0, np.nan)
    avg_28 = buying_pressure.rolling(28, min_periods=28).sum() / uo_tr.rolling(28, min_periods=28).sum().replace(0, np.nan)
    ultimate = 100.0 * (4.0 * avg_7 + 2.0 * avg_14 + avg_28) / 7.0
    ultimate_vote = _conditional_vote((ultimate,), ultimate > 70, ultimate < 30)
    add("UltimateOscillator", ultimate_vote, value=ultimate)

    if set(result) != set(COMPONENT_BY_KEY):
        missing = sorted(set(COMPONENT_BY_KEY) - set(result))
        extra = sorted(set(result) - set(COMPONENT_BY_KEY))
        raise RuntimeError(f"Internal component inventory mismatch; missing={missing}, extra={extra}")
    return result

def analyze_ohlcv(
    frame: pd.DataFrame,
    timeframe: str,
    *,
    adx_profile: ADXProfile = "official_help",
    tick_size: float | None = None,
    source_label: str | None = None,
) -> dict[str, Any]:
    """Calculate the 26 votes from supplied OHLCV and return an analysis-only report.

    The final input row must be a completed candle. This function deliberately
    does not connect to MT5, query TradingView, issue alerts, or send orders.
    """
    if adx_profile not in ("official_help", "technicalrating_v3"):
        raise TechnicalRatingError(f"Unsupported ADX profile {adx_profile!r}.")
    if tick_size is not None and (not np.isfinite(float(tick_size)) or float(tick_size) <= 0):
        raise TechnicalRatingError("tick_size must be a finite positive number when supplied.")
    data, volume_source, bar_time = _normalise_ohlcv(frame, timeframe)
    epsilon = float(tick_size) * 1.0e-7 if tick_size is not None else 1.0e-9
    calculated = _compute_components(data, adx_profile, epsilon)

    component_rows: list[dict[str, Any]] = []
    last_index = data.index[-1]
    votes: dict[str, int | None] = {}
    for spec in COMPONENTS:
        row = calculated[spec.key]
        raw_values: dict[str, float | None] = {}
        for key, series in row["raw"].items():
            value = series.loc[last_index]
            raw_values[key] = float(value) if pd.notna(value) and np.isfinite(float(value)) else None
        raw_vote = row["vote"].loc[last_index]
        vote: int | None = int(raw_vote) if pd.notna(raw_vote) and np.isfinite(float(raw_vote)) else None
        votes[spec.key] = vote
        component_rows.append({
            "key": spec.key,
            "name_ar": spec.label_ar,
            "group": spec.group,
            "group_ar": "المتوسطات" if spec.group == "moving_average" else "المذبذبات",
            "ready": vote is not None,
            "status_ar": "جاهز" if vote is not None else "غير جاهز",
            "vote": vote,
            "vote_label_ar": vote_category(vote),
            "raw_values": raw_values,
            "reason_ar": "تم حساب التصويت من الشموع المقدمة." if vote is not None else "بيانات التاريخ غير كافية أو أن قيمة لازمة غير متاحة؛ لم يتم تعويضها.",
        })

    ma_values = [votes[key] for key in MA_KEYS if votes[key] is not None]
    osc_values = [votes[key] for key in OSCILLATOR_KEYS if votes[key] is not None]
    ma_rating = float(np.mean(ma_values)) if ma_values else None
    oscillator_rating = float(np.mean(osc_values)) if osc_values else None
    if ma_rating is not None and oscillator_rating is not None:
        overall_rating = (ma_rating + oscillator_rating) / 2.0
    elif ma_rating is not None:
        overall_rating = ma_rating
    else:
        overall_rating = oscillator_rating

    ready_ma = len(ma_values)
    ready_oscillator = len(osc_values)
    complete = ready_ma == len(MA_COMPONENTS) and ready_oscillator == len(OSCILLATOR_COMPONENTS)
    return {
        "engine": "Gold Intelligence Lab TV26 analysis engine",
        "engine_version": "0.1.0",
        "mode": "analysis_only",
        "source_label": source_label,
        "symbol_source": "caller_supplied_OHLCV",
        "timeframe": timeframe,
        "bar_time": bar_time,
        "input_rows": int(len(data)),
        "volume_source": volume_source,
        "price_epsilon": epsilon,
        "adx_profile": adx_profile,
        "adx_rule_note_ar": (
            "القاعدة الحالية المنشورة: البيع يتطلب ADX هابطًا."
            if adx_profile == "official_help"
            else "ملف التوافق القديم TechnicalRating v3: البيع يتطلب ADX صاعدًا مثل الشراء؛ يختلف عن صفحة المساعدة الحالية."
        ),
        "bar_policy_ar": "يجب أن يكون الصف الأخير شمعة مكتملة من مصدر البيانات؛ المحرك لا يحدد الشمعة المفتوحة تلقائيًا.",
        "execution": "لا يوجد تنفيذ صفقات أو اتصال خارجي في هذا المحرك.",
        "readiness": {
            "moving_averages_ready": ready_ma,
            "moving_averages_total": len(MA_COMPONENTS),
            "oscillators_ready": ready_oscillator,
            "oscillators_total": len(OSCILLATOR_COMPONENTS),
            "total_ready": ready_ma + ready_oscillator,
            "total_components": len(COMPONENTS),
            "complete": complete,
        },
        "ratings": {
            "moving_averages": ma_rating,
            "moving_averages_category_ar": rating_category(ma_rating),
            "oscillators": oscillator_rating,
            "oscillators_category_ar": rating_category(oscillator_rating),
            "overall": overall_rating,
            "overall_category_ar": rating_category(overall_rating),
            "is_complete": complete,
        },
        "components": component_rows,
        "limitations_ar": [
            "هذا محرك حساب مستقل يعتمد على قواعد منشورة وبيانات OHLCV يمررها المستدعي؛ لا يقرأ بيانات TradingView ولا يضمن التطابق العددي مع مزود بيانات مختلف.",
            "لا يثبت هذا التقرير ربحية استراتيجية ولا يصدر أمر شراء أو بيع للتنفيذ.",
            "يجب مراجعة مصدر الصيغ وإصدار ADX المحدد قبل ادعاء المطابقة مع أي إصدار من TradingView.",
        ],
    }

__all__ = [
    "ADXProfile",
    "COMPONENTS",
    "MA_COMPONENTS",
    "OSCILLATOR_COMPONENTS",
    "DataQualityError",
    "TechnicalRatingError",
    "analyze_ohlcv",
    "rating_category",
    "vote_category",
]
