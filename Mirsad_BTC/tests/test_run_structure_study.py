from __future__ import annotations

import unittest

from scripts.run_structure_study import (
    _parse_horizons,
    build_parser,
    validate_arguments,
)


class StructureStudyCliTests(unittest.TestCase):
    def _args(self, *extra: str):
        return build_parser().parse_args([
            "--venue", "Binance Spot",
            "--timeframe", "1h",
            "--as-of-ms", "1700072000000",
            "--data-split", "train",
            "--dataset-id", "btc-hourly-fixed-v1",
            "--split-start-ms", "1700000000000",
            "--split-end-ms", "1700036000000",
            *extra,
        ])

    def test_horizons_are_parsed_as_sorted_unique_positive_integers(self) -> None:
        self.assertEqual(_parse_horizons("5, 1, 3"), (1, 3, 5))

    def test_horizons_reject_duplicates_and_non_positive_values(self) -> None:
        with self.assertRaisesRegex(ValueError, "duplicates"):
            _parse_horizons("1,3,1")
        with self.assertRaisesRegex(ValueError, "positive"):
            _parse_horizons("1,0,5")

    def test_primary_horizon_must_be_in_requested_horizons(self) -> None:
        args = self._args("--horizons", "1,3", "--primary-horizon", "5")
        with self.assertRaisesRegex(ValueError, "included in --horizons"):
            validate_arguments(args)

    def test_as_of_must_cover_the_entire_split(self) -> None:
        args = self._args(
            "--as-of-ms", "1700030000000",
            "--split-end-ms", "1700036000000",
        )
        with self.assertRaisesRegex(ValueError, "at or after split-end-ms"):
            validate_arguments(args)

    def test_fee_and_slippage_must_be_supplied_together(self) -> None:
        args = self._args("--fee-bps-per-side", "8")
        with self.assertRaisesRegex(ValueError, "both be supplied"):
            validate_arguments(args)

    def test_default_horizon_configuration_is_valid(self) -> None:
        args = self._args()
        self.assertEqual(validate_arguments(args), (1, 3, 5, 10, 20))


if __name__ == "__main__":
    unittest.main()
