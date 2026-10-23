"""Offline contract/math tests for GoldLab v1.016 retry-only ATR cushion.

These tests do NOT emulate MT5 or prove OrderSend execution. They validate the
risk-distance and volume-normalization math and statically inspect the EA source.
Run with: python .github/scripts/goldlab_retry_math_selftest.py
"""
from __future__ import annotations

import math
import re
import sys
import unittest
from pathlib import Path


REPO_ROOT_ARG = sys.argv[1] if len(sys.argv) > 1 else None


def retry_risk_distance(
    original_risk_distance: float,
    spread: float,
    stops_level_distance: float,
    tick_size: float,
    atr: float,
    buffer_atr: float,
) -> tuple[float, float, float]:
    values = (original_risk_distance, spread, stops_level_distance, tick_size, atr, buffer_atr)
    if any(not math.isfinite(v) for v in values):
        raise ValueError("retry inputs must be finite")
    if original_risk_distance < 0 or spread < 0 or stops_level_distance < 0:
        raise ValueError("distances cannot be negative")
    if tick_size <= 0 or atr <= 0 or buffer_atr < 0 or buffer_atr > 2.0:
        raise ValueError("invalid tick, ATR, or buffer")
    base = max(original_risk_distance, spread + stops_level_distance + 2.0 * tick_size)
    buffer_distance = buffer_atr * atr
    return base, buffer_distance, base + buffer_distance


def normalized_lots(
    risk_budget: float,
    loss_per_lot: float,
    min_lot: float,
    max_lot: float,
    step: float,
) -> float:
    if not all(math.isfinite(v) for v in (risk_budget, loss_per_lot, min_lot, max_lot, step)):
        return 0.0
    if risk_budget <= 0 or loss_per_lot <= 0 or min_lot <= 0 or max_lot < min_lot or step <= 0:
        return 0.0
    raw = min(risk_budget / loss_per_lot, max_lot)
    lots = math.floor((raw + 1e-10) / step) * step
    if lots < min_lot:
        return 0.0
    decimals = 2 if step >= 0.01 else (3 if step >= 0.001 else 4)
    return round(lots, decimals)


def spread_allows_retry(spread_points: float, max_spread_points: float) -> bool:
    return (
        math.isfinite(spread_points)
        and math.isfinite(max_spread_points)
        and spread_points >= 0
        and max_spread_points > 0
        and spread_points <= max_spread_points
    )


class RetryMathTests(unittest.TestCase):
    def test_original_risk_distance_is_never_shrunk(self) -> None:
        base, buffer, total = retry_risk_distance(1.20, 0.10, 0.05, 0.01, 2.00, 0.50)
        self.assertAlmostEqual(base, 1.20)
        self.assertAlmostEqual(buffer, 1.00)
        self.assertAlmostEqual(total, 2.20)
        self.assertGreaterEqual(total, 1.20)

    def test_broker_spread_and_stops_floor_controls_base_distance(self) -> None:
        base, buffer, total = retry_risk_distance(0.10, 0.15, 0.20, 0.01, 1.50, 0.50)
        self.assertAlmostEqual(base, 0.37)
        self.assertAlmostEqual(buffer, 0.75)
        self.assertAlmostEqual(total, 1.12)

    def test_zero_buffer_keeps_safe_base_distance(self) -> None:
        base, buffer, total = retry_risk_distance(0.40, 0.25, 0.10, 0.01, 2.0, 0.0)
        self.assertAlmostEqual(base, 0.40)
        self.assertAlmostEqual(buffer, 0.0)
        self.assertAlmostEqual(total, base)

    def test_retry_volume_rounds_down_and_stays_within_risk_budget(self) -> None:
        budget, loss_per_lot = 2.50, 181.0
        lots = normalized_lots(budget, loss_per_lot, 0.01, 100.0, 0.01)
        self.assertEqual(lots, 0.01)
        self.assertLessEqual(lots * loss_per_lot, budget + 1e-9)
        self.assertAlmostEqual(lots / 0.01, round(lots / 0.01))

    def test_if_broker_minimum_exceeds_risk_budget_rejects_trade(self) -> None:
        lots = normalized_lots(1.00, 250.0, 0.01, 100.0, 0.01)
        self.assertEqual(lots, 0.0)

    def test_volume_never_rounds_up_to_exceed_budget(self) -> None:
        for budget, per_lot_loss in ((2.50, 99.0), (1.75, 50.0), (5.0, 123.45), (0.9, 80.0)):
            with self.subTest(budget=budget, per_lot_loss=per_lot_loss):
                lots = normalized_lots(budget, per_lot_loss, 0.01, 100.0, 0.01)
                if lots > 0:
                    self.assertLessEqual(lots * per_lot_loss, budget + 1e-8)
                    self.assertGreaterEqual(lots, 0.01)

    def test_spread_limit_is_inclusive_but_never_exceeded(self) -> None:
        self.assertTrue(spread_allows_retry(100.0, 100.0))
        self.assertFalse(spread_allows_retry(100.01, 100.0))
        self.assertFalse(spread_allows_retry(float("nan"), 100.0))

    def test_invalid_atr_or_buffer_is_rejected(self) -> None:
        for atr, buffer in ((0.0, 0.5), (-1.0, 0.5), (1.0, -0.01), (1.0, 2.01)):
            with self.subTest(atr=atr, buffer=buffer):
                with self.assertRaises(ValueError):
                    retry_risk_distance(0.5, 0.1, 0.0, 0.01, atr, buffer)

    def test_ea_uses_buffer_only_inside_invalid_stops_retry_path(self) -> None:
        root = Path(REPO_ROOT_ARG).resolve() if REPO_ROOT_ARG else Path(__file__).resolve().parents[2]
        ea_path = root / "trading-lab" / "gold-xauusd" / "GoldLabEA.mq5"
        self.assertTrue(ea_path.is_file(), f"EA source missing: {ea_path}")
        source = ea_path.read_text(encoding="utf-8", errors="strict")
        self.assertRegex(source, r'(?m)^#property version\s+"1\.016"\s*$')
        self.assertIn("input double           InpStopRetryBufferATR   = 0.50;", source)
        self.assertIn("if(!accepted && result.retcode==TRADE_RETCODE_INVALID_STOPS)", source)
        self.assertIn("double retryBufferDistance=InpStopRetryBufferATR*retryATR;", source)
        self.assertIn("double retryRiskDistance=retryBaseRiskDistance+retryBufferDistance;", source)
        self.assertIn("LotsForRisk(type,retryEntry,retrySL)", source)
        self.assertIn('PreflightTradeRequest(request,"open-retry")', source)
        self.assertRegex(source, r"stopDistance=MathMax\(InpStopATR\*atr,minStop\+2\.0\*_Point\)")
        self.assertEqual(source.count("if(!accepted && result.retcode==TRADE_RETCODE_INVALID_STOPS)"), 1)


if __name__ == "__main__":
    if REPO_ROOT_ARG:
        sys.argv = sys.argv[:1]
    unittest.main(verbosity=2)
