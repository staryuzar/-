import unittest
from unittest.mock import patch

from bitcoinlab.slow_context import build_slow_context


class SlowContextTests(unittest.TestCase):
    @patch("bitcoinlab.slow_context.deribit.fetch_btc_options_snapshot", side_effect=RuntimeError("options offline"))
    @patch("bitcoinlab.slow_context.deribit.fetch_dvol_history", side_effect=RuntimeError("offline"))
    @patch("bitcoinlab.slow_context.coinmetrics.fetch_community_metrics", return_value={"data": []})
    @patch("bitcoinlab.slow_context.cftc.fetch_bitcoin_cot", return_value={"rows": []})
    @patch("bitcoinlab.slow_context.mempool.fetch_network_snapshot", return_value={"mempool": {}})
    def test_each_slow_feed_is_independent(self, *_mocks):
        result = build_slow_context(now_ms=1_800_000_000_000)
        self.assertIn("network", result["data"])
        self.assertIn("cftc", result["data"])
        self.assertIn("coinmetrics", result["data"])
        self.assertNotIn("dvol", result["data"])
        self.assertNotIn("options", result["data"])
        self.assertEqual(result["source_states"]["dvol"]["status"], "error")
        self.assertEqual(result["source_states"]["options"]["status"], "error")
        self.assertIn("offline", result["errors"]["dvol"])
        self.assertIn("options offline", result["errors"]["options"])

    @patch("bitcoinlab.slow_context.deribit.fetch_btc_options_snapshot", return_value={"instruments": [], "summaries": [], "source": "Deribit public options", "instrument_count": 0, "summary_count": 0})
    @patch("bitcoinlab.slow_context.deribit.fetch_dvol_history", return_value={"data": []})
    @patch("bitcoinlab.slow_context.coinmetrics.fetch_community_metrics", return_value={"data": []})
    @patch("bitcoinlab.slow_context.cftc.fetch_bitcoin_cot", return_value={"rows": []})
    @patch("bitcoinlab.slow_context.mempool.fetch_network_snapshot", return_value={"mempool": {}})
    def test_slow_context_does_not_require_api_keys(self, *_mocks):
        result = build_slow_context(now_ms=1_800_000_000_000)
        self.assertEqual(set(result["data"]), {"network", "cftc", "coinmetrics", "dvol", "options"})
        self.assertEqual(result["data"]["options"]["status"], "empty")
        self.assertEqual(result["data"]["options"]["use"], "slow_context_only_not_intraday_directional_vote")
        self.assertEqual(result["errors"], {})


if __name__ == "__main__":
    unittest.main()
