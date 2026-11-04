from __future__ import annotations

import unittest

from mirsad.engines.decision import (
    ENGINE1_DECISION_WEIGHT,
    ENGINE2_DECISION_WEIGHT,
    ENGINE3_DECISION_WEIGHT,
    _weighted_three_engine_score,
)
from mirsad.engines.indicators import (
    INDICATOR_SIGNAL_FEATURE_WEIGHTS,
    INDICATOR_SIGNAL_GROUP_WEIGHTS,
    TIMEFRAME_WEIGHTS as ENGINE3_TIMEFRAME_WEIGHTS,
    _timeframe_indicator_signal,
)
from mirsad.engines.market_intelligence import (
    COMPONENT_WEIGHTS,
    DERIVATIVE_SIGNAL_WEIGHTS,
    score_derivatives,
)
from mirsad.engines.mt5_price_action import (
    DIRECTIONAL_EVIDENCE_WEIGHTS,
    TIMEFRAME_WEIGHTS as ENGINE2_TIMEFRAME_WEIGHTS,
    _directional_evidence_score,
)
from mirsad.storage import DECISION_CALIBRATION_PROFILE_VERSION


class MirsadWeightProfileV6Tests(unittest.TestCase):
    def test_every_configured_weight_family_sums_to_one(self) -> None:
        families = (
            COMPONENT_WEIGHTS,
            DERIVATIVE_SIGNAL_WEIGHTS,
            DIRECTIONAL_EVIDENCE_WEIGHTS,
            INDICATOR_SIGNAL_GROUP_WEIGHTS,
            {"engine_1": ENGINE1_DECISION_WEIGHT,
             "engine_2": ENGINE2_DECISION_WEIGHT,
             "engine_3": ENGINE3_DECISION_WEIGHT},
        )
        for family in families:
            self.assertAlmostEqual(sum(family.values()), 1.0, places=8)
        for family in INDICATOR_SIGNAL_FEATURE_WEIGHTS.values():
            self.assertAlmostEqual(sum(family.values()), 1.0, places=8)

    def test_engine_two_and_three_share_the_same_multi_timeframe_prior(self) -> None:
        expected = {
            "1m": 4.0, "5m": 8.0, "15m": 18.0,
            "1h": 25.0, "4h": 30.0, "1d": 15.0,
        }
        self.assertEqual(ENGINE2_TIMEFRAME_WEIGHTS, expected)
        self.assertEqual(ENGINE3_TIMEFRAME_WEIGHTS, expected)

    def test_engine_two_price_action_weights_are_applied(self) -> None:
        score, detail = _directional_evidence_score(
            {
                "swing": {"direction": "BEARISH"},
                "bos_choch_events": [{
                    "event": "BOS_BULLISH", "confirmation_time_utc_ms": 1000,
                }],
                "liquidity_sweeps": [{
                    "event": "HIGH_LIQUIDITY_SWEEP", "confirmation_time_utc_ms": 2000,
                }],
            },
            {"latest_pattern_bias": "BEARISH"},
        )
        self.assertAlmostEqual(score, -0.60, places=8)
        self.assertEqual(detail["configured_weights"], DIRECTIONAL_EVIDENCE_WEIGHTS)
        self.assertAlmostEqual(detail["evidence_coverage"], 1.0)

    def test_engine_one_derivative_input_weights_are_applied(self) -> None:
        stamp = 1_798_000_000_000
        result = score_derivatives({
            "Binance": {
                "status": "READY",
                "funding_rate": 0.0005,
                "long_short_ratio": 1.0,
                "funding_timestamp_ms": stamp,
                "long_short_timestamp_ms": stamp,
            },
        }, now_ms=stamp)
        self.assertEqual(result["directional_input_weights"], DERIVATIVE_SIGNAL_WEIGHTS)
        self.assertAlmostEqual(result["venues"]["Binance"]["directional_score"], -0.55, places=8)

    def test_engine_three_weighted_feature_coverage_uses_feature_weights(self) -> None:
        signal = _timeframe_indicator_signal(
            candles=[],
            trend={"status": "READY", "trend": "BULLISH"},
            values={
                "atr14": 2.0,
                "bollinger_middle": None, "bollinger_upper": None, "bollinger_lower": None,
                "macd_main": 0.4, "osma": 0.2, "rsi14": 60.0, "momentum14": 102.0,
                "adx14": 30.0, "plus_di14": 25.0, "minus_di14": 10.0,
                "stochastic_k": 60.0, "stochastic_d": 55.0, "cci20": 100.0,
                "wpr14": -25.0, "mfi14": 70.0,
            },
        )
        self.assertEqual(signal["status"], "READY")
        self.assertAlmostEqual(signal["groups"]["trend"]["coverage"], 0.70)
        self.assertAlmostEqual(signal["groups"]["trend"]["effective_weight"], 0.21)
        self.assertAlmostEqual(signal["groups"]["volume_flow"]["coverage"], 0.55)
        self.assertAlmostEqual(signal["groups"]["volume_flow"]["effective_weight"], 0.055)
        self.assertAlmostEqual(signal["quality"], 0.865)

    def test_engine_four_keeps_fixed_shares_without_redistributing_missing_weight(self) -> None:
        score, effective = _weighted_three_engine_score(
            engine1_score=None,
            engine2_score=1.0,
            engine3_score=-1.0,
            engine1_quality=0.0,
            engine2_quality=1.0,
            engine3_quality=1.0,
        )
        self.assertAlmostEqual(score, 0.30)
        self.assertAlmostEqual(effective["engine_1_market_intelligence"], 0.0)
        self.assertAlmostEqual(effective["engine_2_price_action"], 0.55)
        self.assertAlmostEqual(effective["engine_3_indicators"], 0.25)

    def test_weight_changes_use_a_new_calibration_profile(self) -> None:
        self.assertEqual(
            DECISION_CALIBRATION_PROFILE_VERSION,
            "mirsad-engine-weights-fixed-share-v6-2026-11-04",
        )


if __name__ == "__main__":
    unittest.main()
