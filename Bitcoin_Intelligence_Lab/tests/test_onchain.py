import unittest
from datetime import datetime, timedelta, timezone

from bitcoinlab.onchain import build_onchain_context


NOW = 1_800_000_000_000


def stamp(days_ago=0):
    value = datetime.fromtimestamp(NOW / 1000, timezone.utc) - timedelta(days=days_ago)
    return value.isoformat().replace("+00:00", "Z")


class OnchainContextTests(unittest.TestCase):
    def test_mvrv_nupl_and_market_cap_are_normalized_without_directional_vote(self):
        payload = {
            "source": "Coin Metrics Community API",
            "data": [{
                "asset": "btc", "time": stamp(),
                "AdrActCnt": "510000", "BlkHgt": "920000",
            }],
            "onchain_data": [{
                "asset": "btc", "time": stamp(),
                "CapMVRVCur": "2.0",
                "CapMrktCurUSD": "1000000000000",
                "CapRealUSD": "500000000000",
            }],
            "mvrv_z_data": [{
                "asset": "btc", "time": stamp(), "CapMVRVZ": "1.5",
            }],
        }
        result = build_onchain_context(payload, now_ms=NOW)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["freshness"], "fresh")
        self.assertAlmostEqual(result["mvrv"], 2.0)
        self.assertAlmostEqual(result["nupl_derived"], 0.5)
        self.assertAlmostEqual(result["mvrv_zscore"], 1.5)
        self.assertEqual(result["active_addresses"], 510000)
        self.assertEqual(result["block_height"], 920000)
        self.assertEqual(result["use"], "slow_daily_context_only_not_an_intraday_vote")
        self.assertIn("SOPR", " ".join(result["limitations"]))

    def test_mvrv_can_be_derived_from_market_cap_and_realized_cap(self):
        result = build_onchain_context({
            "data": [],
            "onchain_data": [{
                "asset": "btc", "time": stamp(),
                "CapMrktCurUSD": "900", "CapRealUSD": "600",
            }],
        }, now_ms=NOW)
        self.assertAlmostEqual(result["mvrv"], 1.5)
        self.assertAlmostEqual(result["nupl_derived"], 1 / 3)

    def test_seven_day_changes_need_a_valid_historical_baseline(self):
        rows = []
        for days, mvrv in ((8, 1.8), (7, 1.9), (0, 2.0)):
            rows.append({
                "asset": "btc", "time": stamp(days),
                "CapMVRVCur": str(mvrv),
                "CapMrktCurUSD": str(1000 + (8 - days) * 10),
                "CapRealUSD": str(600 + (8 - days) * 2),
            })
        result = build_onchain_context({
            "data": [],
            "onchain_data": rows,
        }, now_ms=NOW)
        self.assertAlmostEqual(result["seven_day_changes_pct"]["mvrv"], (2.0 / 1.9 - 1) * 100, places=3)
        self.assertIsNotNone(result["seven_day_changes_pct"]["market_cap"])

    def test_stale_daily_data_is_marked_stale_not_used_as_live_input(self):
        result = build_onchain_context({
            "data": [],
            "onchain_data": [{
                "asset": "btc", "time": stamp(5),
                "CapMVRVCur": "2", "CapMrktCurUSD": "100", "CapRealUSD": "50",
            }],
        }, now_ms=NOW)
        self.assertEqual(result["status"], "stale")
        self.assertEqual(result["freshness"], "stale")
        self.assertIn("coinmetrics_daily_onchain_data_stale", result["warnings"])

    def test_missing_optional_metrics_preserve_active_address_context(self):
        result = build_onchain_context({
            "data": [{"asset": "btc", "time": stamp(), "AdrActCnt": "400000"}],
            "onchain_data": [],
            "onchain_errors": {"market_value_realized_value": "not in community tier"},
        }, now_ms=NOW)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["active_addresses"], 400000)
        self.assertIsNone(result["mvrv"])
        self.assertEqual(result["optional_errors"]["market_value_realized_value"], "not in community tier")

    def test_invalid_rows_and_non_btc_rows_are_ignored(self):
        result = build_onchain_context({
            "data": [{"asset": "eth", "time": stamp(), "AdrActCnt": "10"}],
            "onchain_data": [{"asset": "btc", "time": "bad", "CapMVRVCur": "2"}],
        }, now_ms=NOW)
        self.assertEqual(result["status"], "unavailable")
        self.assertIsNone(result["mvrv"])

    def test_invalid_age_configuration_is_rejected(self):
        with self.assertRaises(ValueError):
            build_onchain_context({}, now_ms=NOW, max_age_hours=0)


if __name__ == "__main__":
    unittest.main()
