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
        self.assertIn("trade.ResultRetcode()", SOURCE)
        self.assertIn("TRADE_RETCODE_DONE_PARTIAL", SOURCE)


if __name__ == "__main__":
    unittest.main()
