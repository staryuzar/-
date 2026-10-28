"""Static safeguards for the MQL5 EA; compilation is verified separately by MetaEditor."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "mql5" / "GoldIntelligenceLabEA.mq5").read_text(encoding="utf-8")


class ExpertAdvisorContractTests(unittest.TestCase):
    def test_trading_is_off_by_default(self):
        self.assertIn("input bool   EnableTrading=false;", SOURCE)

    def test_real_account_guard_is_off_by_default_and_enforced(self):
        self.assertIn("input bool   AllowRealAccountTrading=false;", SOURCE)
        self.assertIn("mode==ACCOUNT_TRADE_MODE_REAL && !AllowRealAccountTrading", SOURCE)

    def test_signal_uses_closed_candle_and_excludes_it_from_breakout_level(self):
        self.assertIn("double close1=iClose(_Symbol,_Period,1);", SOURCE)
        self.assertIn("for(int shift=2;shift<2+DonchianPeriod;shift++)", SOURCE)

    def test_risk_size_uses_broker_profit_calculation_and_rounds_down(self):
        self.assertIn("OrderCalcProfit(orderType,_Symbol,1.0,entry,stop,loss)", SOURCE)
        self.assertIn("MathFloor((raw+1e-12)/step)*step", SOURCE)
        self.assertIn("lots+1e-10<minLot", SOURCE)

    def test_spread_and_trade_limits_are_enforced(self):
        self.assertIn("if(spreadPoints>MaxSpreadPoints)", SOURCE)
        self.assertIn("if(tradesToday>=MaxTradesPerDay)", SOURCE)
        self.assertIn("MaxDailyLossPercent", SOURCE)
        self.assertIn("MaxEquityDrawdownPercent", SOURCE)

    def test_order_result_code_is_checked_after_send(self):
        self.assertIn("OrderSend(request,result)", SOURCE)
        self.assertIn("uint rc=result.retcode;", SOURCE)
        self.assertIn("TRADE_RETCODE_DONE_PARTIAL", SOURCE)


    def test_risk_guards_persist_across_live_restarts(self):
        self.assertIn("GlobalVariableSet(gvInitialEquityKey,initialEquity)", SOURCE)
        self.assertIn("GlobalVariableSet(gvDayKeyKey,(double)currentDayKey)", SOURCE)
        self.assertIn("GlobalVariableSet(gvTradesTodayKey,(double)tradesToday)", SOURCE)
        self.assertIn("return SaveRiskState();", SOURCE)

    def test_strategy_tester_isolated_from_terminal_global_state(self):
        self.assertIn("if(MQLInfoInteger(MQL_TESTER)) return true;", SOURCE)
        self.assertIn("// Backtests should start from their own initial equity on each run.", SOURCE)

    def test_order_volume_and_stops_use_refreshed_execution_tick(self):
        self.assertIn("tick=executionTick;", SOURCE)
        self.assertIn("Blocked by refreshed spread guard", SOURCE)
        self.assertIn("double lots=LotsForRisk(orderType,entry,sl);", SOURCE)


    def test_signal_only_mode_keeps_direction_visible(self):
        self.assertIn('signal>0?"BUY":"SELL"', SOURCE)
        self.assertIn("signal-only mode (EnableTrading=false)", SOURCE)

    def test_loss_guards_do_not_claim_to_close_open_positions(self):
        self.assertIn("does not close open positions", SOURCE)


    def test_live_mode_requires_an_actual_demo_account(self):
        self.assertIn("input bool   RequireDemoAccount=true;", SOURCE)
        self.assertIn("accountMode!=ACCOUNT_TRADE_MODE_DEMO", SOURCE)
        self.assertIn("mode!=ACCOUNT_TRADE_MODE_DEMO", SOURCE)
        self.assertIn("GIL|SAFETY_BLOCK|reason=init_account_not_demo", SOURCE)

    def test_live_telemetry_records_bars_signals_and_orders(self):
        self.assertIn("GIL|INIT|", SOURCE)
        self.assertIn("GIL|BAR|", SOURCE)
        self.assertIn("GIL|SIGNAL|", SOURCE)
        self.assertIn("GIL|ORDER_ACCEPTED|", SOURCE)
        self.assertIn("GIL|ORDER_FAILED|", SOURCE)


if __name__ == "__main__":
    unittest.main()
