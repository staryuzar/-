#!/usr/bin/env python3
"""Static contract tests for TV26's three-summary entry and rule-based exit behavior.

These tests are a fast guardrail, not a substitute for compiling the EA or running MT5.
"""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[2]
SOURCE_PATH = ROOT / "trading-lab" / "tv26" / "TV26_FiveTF_Arabic_CANDIDATE.mq5"
SOURCE = SOURCE_PATH.read_text(encoding="utf-8")


def function_body(signature: str, next_signature: str) -> str:
    start = SOURCE.find(signature)
    if start < 0:
        raise AssertionError(f"Function not found: {signature}")
    end = SOURCE.find(next_signature, start + len(signature))
    if end < 0:
        raise AssertionError(f"Boundary not found after {signature}: {next_signature}")
    return SOURCE[start:end]


class TV26ExitContractTests(unittest.TestCase):
    def test_entry_requires_only_m5_m15_m30_and_all_three_strong(self):
        body = function_body("int AlignedSignal()", "string DetailSignal(")
        self.assertRegex(body, r"const int frames\[3\]\s*=\s*\{1,2,3\}")
        self.assertIn("g_rating[1]>STRONG && g_rating[2]>STRONG && g_rating[3]>STRONG", body)
        self.assertIn("g_rating[1]<-STRONG && g_rating[2]<-STRONG && g_rating[3]<-STRONG", body)
        self.assertIn("if(g_ready[t]!=N_RATINGS || g_maReady[t]!=15 || g_oscReady[t]!=11)", body)
        self.assertIn("#define STRONG 0.50", SOURCE)

    def test_any_opposite_non_neutral_summary_can_trigger_exit(self):
        body = function_body("int OppositeSummaryTimeframe(", "bool ConfirmedM1PriceReversal(")
        self.assertRegex(body, r"const int frames\[3\]\s*=\s*\{1,2,3\}")
        self.assertIn("g_rating[t]<-0.10", body)
        self.assertIn("g_rating[t]>0.10", body)
        self.assertIn("g_ready[t]!=N_RATINGS || g_maReady[t]!=15 || g_oscReady[t]!=11", body)

    def test_m1_reversal_requires_opposite_close_breaking_three_prior_bars(self):
        body = function_body("bool ConfirmedM1PriceReversal(", "bool ManageOpenPositionExit(")
        self.assertIn("iOpen(_Symbol,PERIOD_M1,1)", body)
        self.assertIn("iClose(_Symbol,PERIOD_M1,1)", body)
        self.assertIn("for(int sh=2;sh<=4;sh++)", body)
        self.assertIn("side==POSITION_TYPE_BUY && cl<o && cl<priorLow", body)
        self.assertIn("side==POSITION_TYPE_SELL && cl>o && cl>priorHigh", body)

    def test_exit_is_logged_and_close_is_verified(self):
        body = function_body("bool ManageOpenPositionExit()", "void TradeIfAligned(")
        self.assertIn("Print(\"TV26_EXIT_TRIGGER;", body)
        self.assertIn("Print(\"TV26_EXIT_COMPLETED;", body)
        self.assertIn("Print(\"TV26_EXIT_FAILED;", body)
        self.assertIn('reason="OPPOSITE_SUMMARY"', body)
        self.assertIn('reason="REAL_M1_REVERSAL"', body)
        close_body = function_body("bool CloseTicket(", "// In netting/exchange accounts")
        self.assertIn("TRADE_RETCODE_DONE_PARTIAL", close_body)
        self.assertIn("return !PositionSelectByTicket(ticket)", close_body)

    def test_exit_manager_runs_before_new_entry_on_new_m1_bar(self):
        body = function_body("void OnTick()", "}")
        self.assertRegex(body, r"if\(!IsNewM1Bar\(\)\)\s*return;")
        self.assertIn("EvaluateAll();DrawPanel();ExportAuditIfNeeded();TradeIfAligned();", body)
        decision = function_body("void TradeIfAligned()", "int OnInit(")
        self.assertIn("if(ManageOpenPositionExit()) return;", decision)

    def test_early_exit_toggle_preserves_open_position_and_sl_tp(self):
        self.assertIn("input bool   InpUseRuleBasedEarlyExit = true;", SOURCE)
        body = function_body("bool ManageOpenPositionExit()", "void TradeIfAligned(")
        self.assertIn("if(!InpUseRuleBasedEarlyExit)", body)
        skip = body.index("if(!InpUseRuleBasedEarlyExit)")
        summary_check = body.index("int oppositeFrame=OppositeSummaryTimeframe(side);")
        self.assertLess(skip, summary_check)
        self.assertIn("return true;", body[skip:summary_check])
        self.assertIn("input double InpStopATR", SOURCE)
        self.assertIn("input double InpTargetATR", SOURCE)

    def test_exit_events_include_bar_identity_for_exact_pairing(self):
        body = function_body("bool ManageOpenPositionExit()", "void TradeIfAligned(")
        self.assertGreaterEqual(body.count('";bar=",TimeToString(iTime(_Symbol,PERIOD_M1,1),TIME_DATE|TIME_MINUTES)'), 3)
        compare_path = ROOT / "trading-lab" / "tv26" / "compare_tv26_exit_ab.py"
        compare = compare_path.read_text(encoding="utf-8")
        self.assertIn("def event_key(line: str):", compare)
        self.assertIn('ticket = re.search(r"ticket=(\\d+)", line)', compare)
        self.assertIn('return (ticket.group(1), reason.group(1), bar.group(1))', compare)
        self.assertIn("key in done_keys", compare)

    def test_m1_price_reversal_exit_is_separately_gated_for_summary_only_study(self):
        self.assertIn("input bool   InpUseM1PriceReversalExit = false;", SOURCE)
        body = function_body("bool ManageOpenPositionExit()", "void TradeIfAligned(")
        self.assertIn("else if(InpUseM1PriceReversalExit && ConfirmedM1PriceReversal(side,reason))", body)

    def test_timeframe_input_order_matches_rating_contract(self):
        body = function_body("int OnInit()", "void OnDeinit(")
        self.assertRegex(
            body,
            r"if\\(g_tfs\\[0\\]!=PERIOD_M1\\s*\\|\\|\\s*g_tfs\\[1\\]!=PERIOD_M5\\s*\\|\\|\\s*g_tfs\\[2\\]!=PERIOD_M15\\s*\\|\\|\\s*g_tfs\\[3\\]!=PERIOD_M30\\s*\\|\\|\\s*g_tfs\\[4\\]!=PERIOD_H1\\)"
        )
        self.assertIn("INIT_PARAMETERS_INCORRECT", body)
        self.assertIn("M1/M5/M15/M30/H1", body)

    def test_candidate_keeps_demo_guard_and_risk_ceiling(self):
        self.assertIn("input bool   InpDemoOnly            = true;", SOURCE)
        self.assertIn("InpRiskPercent>2.0", SOURCE)
        self.assertIn("InpTesterOnly", SOURCE)


if __name__ == "__main__":
    unittest.main(verbosity=2)
