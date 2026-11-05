import unittest

from bitcoinlab.liquidation_stream import _is_bybit_pong
from bitcoinlab.trade_stream import BINANCE_USDM_TRADE_WS


class PublicStreamHeartbeatTests(unittest.TestCase):
    def test_binance_usdm_aggregate_trade_uses_current_market_path(self):
        self.assertEqual(
            BINANCE_USDM_TRADE_WS,
            "wss://fstream.binance.com/market/ws/{symbol}@aggTrade",
        )

    def test_bybit_json_pong_with_ret_msg_refreshes_heartbeat(self):
        self.assertTrue(_is_bybit_pong({
            "success": True, "ret_msg": "pong", "op": "ping",
        }))

    def test_bybit_json_pong_with_op_pong_is_recognized(self):
        self.assertTrue(_is_bybit_pong({"op": "pong", "data": ["123"]}))

    def test_bybit_non_pong_messages_do_not_refresh_heartbeat(self):
        self.assertFalse(_is_bybit_pong({
            "topic": "allLiquidation.BTCUSDT", "data": [],
        }))
        self.assertFalse(_is_bybit_pong("pong"))
        self.assertFalse(_is_bybit_pong(None))


if __name__ == "__main__":
    unittest.main()
