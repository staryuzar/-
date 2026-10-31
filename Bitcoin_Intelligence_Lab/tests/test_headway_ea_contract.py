from pathlib import Path
import re
import unittest


class HeadwayEAContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source_path = (
            Path(__file__).resolve().parents[1]
            / "mql5" / "BitcoinIntelligenceLabEA.mq5"
        )
        cls.source = cls.source_path.read_text(encoding="utf-8")

    def test_ea_is_self_contained_and_does_not_depend_on_trade_mqh(self):
        self.assertNotIn("#include <Trade/Trade.mqh>", self.source)
        self.assertIn("MqlTradeRequest request", self.source)
        self.assertIn("OrderSend(request,result)", self.source)
        self.assertNotIn("CTrade trade", self.source)

    def test_headway_demo_is_the_default_execution_gate(self):
        self.assertIn("input bool   RequireHeadwayDemo = true;", self.source)
        self.assertIn("ACCOUNT_TRADE_MODE_DEMO", self.source)
        self.assertIn("headway-demo", self.source.lower())
        self.assertIn("demo.trade-hw.online", self.source.lower())

    def test_headway_server_and_account_mode_are_published_to_python(self):
        self.assertIn("string accountServer=AccountInfoString(ACCOUNT_SERVER)", self.source)
        self.assertIn("int accountMode=(int)AccountInfoInteger(ACCOUNT_TRADE_MODE)", self.source)
        self.assertIn("accountServer,accountMode", self.source)
        self.assertIn('"TRADE_READY":"TRADE_BLOCKED"', self.source)

    def test_ea_does_not_generate_independent_orders_on_tick(self):
        on_tick = self.source.split("void OnTick()", 1)[1]
        self.assertNotIn("OrderSend", on_tick)
        self.assertIn("centralized board is the only decision authority", on_tick)

    def test_broker_fill_policy_is_not_guessed_when_market_execution_has_no_supported_mode(self):
        self.assertIn("bool PrepareTradeRequest(MqlTradeRequest &request)", self.source)
        self.assertIn("return false; // Market execution forbids RETURN", self.source)
        self.assertIn("if(!PrepareTradeRequest(request))", self.source)
        self.assertIn("request.type_filling=ORDER_FILLING_RETURN;", self.source)

    def test_status_record_ends_with_a_real_newline_for_python_bridge(self):
        self.assertIn('|%s|%s|%d\\n",', self.source)
        self.assertNotIn('|%s|%s|%d\\\\n",', self.source)

    def test_trade_requests_bind_to_actual_headway_chart_symbol_and_magic(self):
        self.assertIn("request.symbol=_Symbol", self.source)
        self.assertIn("request.magic=MagicNumber", self.source)
        self.assertIn("request.position=ticket", self.source)
        self.assertIn("PositionGetString(POSITION_SYMBOL)!=_Symbol", self.source)


if __name__ == "__main__":
    unittest.main()
