"""Gold Intelligence Lab analysis-only Python modules."""
from .cot_data import COTDataError, fetch_cftc_gold_cot, parse_cftc_cot_rows
from .advisor import build_advisory
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
    "COTDataError",
    "fetch_cftc_gold_cot",
    "parse_cftc_cot_rows",
    "build_advisory",
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
