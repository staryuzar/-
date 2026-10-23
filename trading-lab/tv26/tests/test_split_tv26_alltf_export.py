import csv
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from compare_tv26_csv import COMPONENTS, read_csv
from split_tv26_alltf_export import PACKED_LIMIT, decode_votes, split_file, InputError


def pack_votes(votes):
    return sum((vote + 1) * (4 ** i) for i, vote in enumerate(votes))


class TV26AllTimeframeExportTests(unittest.TestCase):
    def test_base4_decode_preserves_buy_sell_neutral_and_na(self):
        votes = [-1 if i % 3 == 0 else (0 if i % 3 == 1 else 1) for i in range(26)]
        packed = pack_votes(votes)
        decoded = decode_votes(packed)
        self.assertEqual([int(v) for v in decoded], votes)
        votes[7] = None
        packed = sum((3 if vote is None else vote + 1) * (4 ** i)
                     for i, vote in enumerate(votes))
        decoded = decode_votes(packed)
        self.assertEqual(decoded[7], "")
        self.assertEqual([int(v) for i, v in enumerate(decoded) if i != 7], [v for i, v in enumerate(votes) if i != 7])

    def make_alltf_fixture(self, folder: Path):
        path = folder / "TV26_AllTF.csv"
        fields = ["time"]
        for tf in ("M1", "M5", "M15", "M30", "H1"):
            fields += [f"TV26.{tf}.{name}" for name in (
                "packed", "total", "ma", "osc", "formula_total", "formula_ma",
                "formula_osc", "bar_open_time", "open", "high", "low", "close")]
        votes = [(-1 if i % 3 == 0 else (0 if i % 3 == 1 else 1)) for i in range(26)]
        packed = str(pack_votes(votes))
        row = {"time": "2026-09-01T00:01:00Z"}
        for tf in ("M1", "M5", "M15", "M30", "H1"):
            row.update({
                f"TV26.{tf}.packed": packed,
                f"TV26.{tf}.total": "0.1",
                f"TV26.{tf}.ma": "0.2",
                f"TV26.{tf}.osc": "0.0",
                f"TV26.{tf}.formula_total": "0.1",
                f"TV26.{tf}.formula_ma": "0.2",
                f"TV26.{tf}.formula_osc": "0.0",
                f"TV26.{tf}.bar_open_time": "1788220860000",
                f"TV26.{tf}.open": "2500.00",
                f"TV26.{tf}.high": "2501.00",
                f"TV26.{tf}.low": "2499.00",
                f"TV26.{tf}.close": "2500.50",
            })
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerow(row)
        return path, votes

    def test_splits_one_all_timeframe_csv_to_normalized_component_csv(self):
        with tempfile.TemporaryDirectory() as temp:
            source, votes = self.make_alltf_fixture(Path(temp))
            output = Path(temp) / "normalized_m5.csv"
            result = split_file(source, "M5", output)
            self.assertEqual(result["rows_written"], 1)
            self.assertEqual(result["rows_missing_pack"], 0)
            _, rows = read_csv(output)
            self.assertEqual(len(rows), 1)
            for name, vote in zip(COMPONENTS.keys(), votes):
                self.assertEqual(rows[0]["TV26." + name], str(vote))
            self.assertEqual(rows[0]["TV26.total"], "0.1")
            self.assertEqual(rows[0]["TV26.formula_total"], "0.1")

    def test_rejects_out_of_range_and_non_integer_packs(self):
        with self.assertRaises(InputError):
            decode_votes(PACKED_LIMIT)
        with self.assertRaises(InputError):
            decode_votes(12.5)


if __name__ == "__main__":
    unittest.main()
