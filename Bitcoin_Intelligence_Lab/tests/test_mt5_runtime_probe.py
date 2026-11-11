import unittest

from scripts.mt5_runtime_probe import select_btc_symbol_name


class MT5RuntimeProbeTests(unittest.TestCase):
    def test_prefers_exact_btcusd_symbol(self):
        self.assertEqual(
            select_btc_symbol_name(["BTCUSD.r", "BTCUSDT", "BTCUSD"]),
            "BTCUSD",
        )

    def test_prefers_btcusd_broker_suffix_over_other_btc_markets(self):
        self.assertEqual(
            select_btc_symbol_name(["BTCUSDT", "BTCUSDm", "BTCEUR"]),
            "BTCUSDm",
        )

    def test_selection_is_deterministic_when_only_btc_prefixed_symbols_exist(self):
        self.assertEqual(
            select_btc_symbol_name(["BTCX", "BTCABC", "BTC"]),
            "BTC",
        )

    def test_rejects_terminal_without_a_btc_symbol(self):
        with self.assertRaisesRegex(ValueError, "no BTC instrument"):
            select_btc_symbol_name(["XAUUSD", "EURUSD"])


if __name__ == "__main__":
    unittest.main()
