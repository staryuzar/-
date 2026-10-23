"""Offline contract/math tests for GoldLab v1.018 risk-capped tester-only retry.

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


def cap_retry_buffer_distance(
    base_distance: float,
    requested_buffer: float,
    risk_budget: float,
    min_lot: float = 0.01,
    max_lot: float = 100.0,
    step: float = 0.01,
    loss_per_lot_per_distance: float = 100.0,
) -> float | None:
    """Return the largest affordable extra distance, or None if the base itself is unaffordable."""
    values = (base_distance, requested_buffer, risk_budget, min_lot, max_lot, step, loss_per_lot_per_distance)
    if not all(math.isfinite(v) for v in values):
        raise ValueError("risk-cap inputs must be finite")
    if base_distance < 0 or requested_buffer < 0 or risk_budget <= 0 or loss_per_lot_per_distance <= 0:
        raise ValueError("invalid risk-cap distance or budget")
    if normalized_lots(risk_budget, base_distance * loss_per_lot_per_distance, min_lot, max_lot, step) < min_lot:
        return None
    if normalized_lots(risk_budget, (base_distance + requested_buffer) * loss_per_lot_per_distance, min_lot, max_lot, step) >= min_lot:
        return requested_buffer
    affordable, unaffordable = 0.0, requested_buffer
    for _ in range(24):
        candidate = (affordable + unaffordable) * 0.5
        candidate_lots = normalized_lots(
            risk_budget,
            (base_distance + candidate) * loss_per_lot_per_distance,
            min_lot,
            max_lot,
            step,
        )
        if candidate_lots >= min_lot:
            affordable = candidate
        else:
            unaffordable = candidate
    return affordable


def spread_allows_retry(spread_points: float, max_spread_points: float) -> bool:
    return (
        math.isfinite(spread_points)
        and math.isfinite(max_spread_points)
        and spread_points >= 0
        and max_spread_points > 0
        and spread_points <= max_spread_points
    )


def retry_outcomes_valid(
    trigger_ids: list[str],
    recovered_ids: set[str],
    safe_aborted_ids: set[str],
    rejected_ids: set[str],
) -> bool:
    """Require exactly one terminal outcome for every original invalid-stop trigger."""
    triggers = set(trigger_ids)
    if len(triggers) != len(trigger_ids):
        return False
    outcomes = (recovered_ids, safe_aborted_ids, rejected_ids)
    if any(not outcome.issubset(triggers) for outcome in outcomes):
        return False
    if (recovered_ids & safe_aborted_ids) or (recovered_ids & rejected_ids) or (safe_aborted_ids & rejected_ids):
        return False
    observed = recovered_ids | safe_aborted_ids | rejected_ids
    return observed == triggers


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

    def test_adaptive_buffer_caps_requested_cushion_to_minimum_lot_budget(self) -> None:
        effective = cap_retry_buffer_distance(2.11, 0.50 * 3.91, 2.50)
        self.assertIsNotNone(effective)
        assert effective is not None
        self.assertAlmostEqual(effective, 0.39, delta=0.0002)
        self.assertLessEqual(2.11 + effective, 2.50 + 1e-8)
        self.assertLess(effective, 0.50 * 3.91)

    def test_adaptive_buffer_keeps_request_when_fully_affordable(self) -> None:
        requested = 0.05 * 3.91
        effective = cap_retry_buffer_distance(2.11, requested, 2.50)
        self.assertAlmostEqual(effective if effective is not None else -1.0, requested, places=8)

    def test_adaptive_buffer_refuses_when_base_risk_already_exceeds_budget(self) -> None:
        self.assertIsNone(cap_retry_buffer_distance(2.60, 0.25, 2.50))

    def test_spread_limit_is_inclusive_but_never_exceeded(self) -> None:
        self.assertTrue(spread_allows_retry(100.0, 100.0))
        self.assertFalse(spread_allows_retry(100.01, 100.0))
        self.assertFalse(spread_allows_retry(float("nan"), 100.0))

    def test_invalid_atr_or_buffer_is_rejected(self) -> None:
        for atr, buffer in ((0.0, 0.5), (-1.0, 0.5), (1.0, -0.01), (1.0, 2.01)):
            with self.subTest(atr=atr, buffer=buffer):
                with self.assertRaises(ValueError):
                    retry_risk_distance(0.5, 0.1, 0.0, 0.01, atr, buffer)

    def test_safe_pre_send_abort_counts_as_a_terminal_failure_outcome(self) -> None:
        self.assertTrue(retry_outcomes_valid(["223"], set(), {"223"}, set()))

    def test_each_trigger_must_have_exactly_one_terminal_outcome(self) -> None:
        self.assertTrue(
            retry_outcomes_valid(
                ["101", "202", "303"],
                {"101"},
                {"202"},
                {"303"},
            )
        )
        self.assertFalse(retry_outcomes_valid(["101"], {"101"}, {"101"}, set()))
        self.assertFalse(retry_outcomes_valid(["101"], set(), set(), set()))
        self.assertFalse(retry_outcomes_valid(["101"], set(), {"999"}, set()))
        self.assertFalse(retry_outcomes_valid(["101", "101"], set(), {"101"}, set()))

    def test_ea_logs_retry_outcomes_against_original_trigger_id(self) -> None:
        root = Path(REPO_ROOT_ARG).resolve() if REPO_ROOT_ARG else Path(__file__).resolve().parents[2]
        ea = (root / "trading-lab" / "gold-xauusd" / "GoldLabEA.mq5").read_text(encoding="utf-8", errors="strict")
        harness = (root / ".github" / "scripts" / "goldlab_sltp_race_diagnostic.ps1").read_text(encoding="utf-8", errors="strict")
        self.assertIn("ulong retryTriggerRequestId=result.request_id;", ea)
        self.assertIn('outcome=safe_no_retry_send', ea)
        self.assertIn('outcome=recovered', ea)
        self.assertIn('outcome=retry_send_rejected', ea)
        self.assertIn("$safeAbortedOpenRequestIds", harness)
        self.assertIn("$recoveredOpenRequestIds", harness)
        self.assertIn("$rejectedOpenRetryTriggerRequestIds", harness)
        for reason in (
            "fresh_quote_unavailable",
            "spread_guard_exceeded",
            "atr_unavailable",
            "volume_below_minimum",
            "retry_ordercheck_failed",
        ):
            self.assertIn("reason=" + reason, ea)

    def test_retry_outcome_log_shapes_preserve_the_original_trigger_id(self) -> None:
        patterns = (
            (
                re.compile(r"GoldLab\|OPEN_STOP_RETRY_SUCCESS\|[^|]+\|trigger_request_id=(\d+);outcome=recovered;"),
                "GoldLab|OPEN_STOP_RETRY_SUCCESS|XAUUSD|trigger_request_id=223;outcome=recovered;retcode=10009",
            ),
            (
                re.compile(r"GoldLab\|OPEN_STOP_RETRY_ABORT\|[^|]+\|trigger_request_id=(\d+);outcome=safe_no_retry_send;reason=[^;]+"),
                "GoldLab|OPEN_STOP_RETRY_ABORT|XAUUSD|trigger_request_id=223;outcome=safe_no_retry_send;reason=volume_below_minimum;risk_budget=2.58",
            ),
            (
                re.compile(r"GoldLab\|OPEN_STOP_RETRY_FAIL\|[^|]+\|trigger_request_id=(\d+);outcome=retry_send_rejected;retcode=\d+"),
                "GoldLab|OPEN_STOP_RETRY_FAIL|XAUUSD|trigger_request_id=223;outcome=retry_send_rejected;retcode=10016",
            ),
        )
        for pattern, line in patterns:
            with self.subTest(line=line):
                match = pattern.search(line)
                self.assertIsNotNone(match)
                self.assertEqual(match.group(1), "223")

    def test_ea_uses_buffer_only_inside_invalid_stops_retry_path(self) -> None:
        root = Path(REPO_ROOT_ARG).resolve() if REPO_ROOT_ARG else Path(__file__).resolve().parents[2]
        ea_path = root / "trading-lab" / "gold-xauusd" / "GoldLabEA.mq5"
        self.assertTrue(ea_path.is_file(), f"EA source missing: {ea_path}")
        source = ea_path.read_text(encoding="utf-8", errors="strict")
        self.assertRegex(source, r'(?m)^#property version\s+"1\.018"\s*$')
        self.assertIn("input double           InpStopRetryBufferATR   = 0.50;", source)
        self.assertIn("input bool             InpTestForceInvalidStopsOnce = false;", source)
        self.assertIn("if(InpTestForceInvalidStopsOnce && !testerMode)", source)
        self.assertIn("(bool)MQLInfoInteger(MQL_TESTER)", source)
        self.assertIn('outcome=confirmed;request_id=', source)
        self.assertIn("if(!accepted && result.retcode==TRADE_RETCODE_INVALID_STOPS)", source)
        self.assertIn("double requestedRetryBufferDistance=InpStopRetryBufferATR*retryATR;", source)
        self.assertIn("double retryBufferDistance=requestedRetryBufferDistance;", source)
        self.assertIn("for(int capIteration=0;capIteration<24;capIteration++)", source)
        self.assertIn("double candidateLots=LotsForRisk(type,retryEntry,candidateSL);", source)
        self.assertIn("if(candidateLots>=minLot)", source)
        self.assertIn("if(retryLots<minLot && retryBufferDistance>0.0)", source)
        self.assertIn("if(zeroBufferLots>=minLot)", source)
        self.assertIn("double affordableBuffer=0.0;", source)
        self.assertIn("retryBufferDistance=affordableBuffer;", source)
        self.assertIn("retryBufferCapped=(retryLots>=minLot", source)
        self.assertIn("if(zeroBufferLots>=minLot)", source)
        self.assertIn("if(retryLots<minLot || retryLots<=0.0)", source)
        self.assertIn('LogEvent("OPEN_STOP_RETRY_BUFFER_CAPPED"', source)
        self.assertIn("requested_buffer_atr=", source)
        self.assertIn("effective_buffer_atr=", source)
        self.assertIn("retryBufferCapped=(retryLots>=minLot", source)
        self.assertIn("double retryRiskDistance=retryBaseRiskDistance+retryBufferDistance;", source)
        self.assertIn("LotsForRisk(type,retryEntry,retrySL)", source)
        self.assertIn('PreflightTradeRequest(request,"open-retry")', source)
        self.assertLess(source.index('PreflightTradeRequest(request,"open")'), source.index('request.sl=request.price;'))
        self.assertLess(source.index('request.sl=request.price;'), source.index('bool sent=OrderSend(request,result);'))
        self.assertIn("request.sl=plannedSL;", source)
        self.assertIn("request.tp=plannedTP;", source)
        self.assertRegex(source, r"stopDistance=MathMax\(InpStopATR\*atr,minStop\+2\.0\*_Point\)")
        self.assertEqual(source.count("if(!accepted && result.retcode==TRADE_RETCODE_INVALID_STOPS)"), 2)


if __name__ == "__main__":
    if REPO_ROOT_ARG:
        sys.argv = sys.argv[:1]
    unittest.main(verbosity=2)
