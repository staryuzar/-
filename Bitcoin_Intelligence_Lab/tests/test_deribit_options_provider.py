import unittest
from unittest.mock import patch

from bitcoinlab.providers import deribit


class DeribitOptionsProviderTests(unittest.TestCase):
    @patch("bitcoinlab.providers.deribit.get_json")
    def test_fetch_btc_options_snapshot_uses_public_option_endpoints(self, get_json):
        get_json.side_effect = [
            {"result": [{
                "instrument_name": "BTC-30DEC26-70000-C",
                "kind": "option", "option_type": "call",
                "strike": 70000, "expiration_timestamp": 1_800_000_000_000,
                "is_active": True, "contract_size": 1.0,
            }]},
            {"result": [{
                "instrument_name": "BTC-30DEC26-70000-C",
                "underlying_price": 70000, "mark_iv": 60,
                "open_interest": 2.5,
            }]},
        ]

        result = deribit.fetch_btc_options_snapshot()

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["instrument_count"], 1)
        self.assertEqual(result["summary_count"], 1)
        self.assertEqual(get_json.call_count, 2)
        self.assertIn("public/get_instruments?", get_json.call_args_list[0].args[0])
        self.assertIn("kind=option", get_json.call_args_list[0].args[0])
        self.assertIn("public/get_book_summary_by_currency?", get_json.call_args_list[1].args[0])
        self.assertIn("kind=option", get_json.call_args_list[1].args[0])
        self.assertEqual(get_json.call_args_list[0].kwargs["timeout"], 15.0)

    @patch("bitcoinlab.providers.deribit.get_json")
    def test_invalid_rpc_error_is_rejected(self, get_json):
        get_json.side_effect = [
            {"error": {"code": 10028, "message": "too many requests"}},
            {"result": []},
        ]
        with self.assertRaisesRegex(ValueError, "instruments response was invalid"):
            deribit.fetch_btc_options_snapshot()

    @patch("bitcoinlab.providers.deribit.get_json")
    def test_option_summaries_must_be_result_lists(self, get_json):
        get_json.side_effect = [
            {"result": []},
            {"result": {"unexpected": "object"}},
        ]
        with self.assertRaisesRegex(ValueError, "did not contain a result list"):
            deribit.fetch_btc_options_snapshot()

    @patch("bitcoinlab.providers.deribit.get_json")
    def test_empty_option_market_is_reported_as_empty(self, get_json):
        get_json.side_effect = [{"result": []}, {"result": []}]
        result = deribit.fetch_btc_options_snapshot()
        self.assertEqual(result["status"], "empty")
        self.assertEqual(result["instruments"], [])
        self.assertEqual(result["summaries"], [])


if __name__ == "__main__":
    unittest.main()
