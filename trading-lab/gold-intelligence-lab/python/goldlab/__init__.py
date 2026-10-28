"""Gold Intelligence Lab analysis-only Python modules."""
from .live_mt5 import LiveMT5Error, analyze_live_mt5, read_mt5_snapshot
from .pattern_scanner import scan_market_structure
from .technical_rating import (
    ADXProfile,
    COMPONENTS,
    MA_COMPONENTS,
    OSCILLATOR_COMPONENTS,
    DataQualityError,
    TechnicalRatingError,
    analyze_ohlcv,
    rating_category,
    vote_category,
)

__all__ = [
    "scan_market_structure",
    "LiveMT5Error",
    "analyze_live_mt5",
    "read_mt5_snapshot",
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
