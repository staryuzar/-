from __future__ import annotations

from dataclasses import dataclass
import math


@dataclass(frozen=True)
class Bar:
    """One UTC-timestamped OHLCV candle. Only completed bars enter analysis."""
    open_time_ms: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    close_time_ms: int
    is_closed: bool = True

    def __post_init__(self) -> None:
        values = (self.open, self.high, self.low, self.close, self.volume)
        if self.open_time_ms <= 0 or self.close_time_ms < self.open_time_ms:
            raise ValueError("Invalid candle timestamps.")
        if not all(math.isfinite(float(x)) for x in values):
            raise ValueError("OHLCV values must be finite.")
        if min(self.open, self.high, self.low, self.close) <= 0 or self.volume < 0:
            raise ValueError("Prices must be positive and volume non-negative.")
        if self.high < max(self.open, self.close, self.low):
            raise ValueError("High is below another candle field.")
        if self.low > min(self.open, self.close, self.high):
            raise ValueError("Low is above another candle field.")


def finite_number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None
