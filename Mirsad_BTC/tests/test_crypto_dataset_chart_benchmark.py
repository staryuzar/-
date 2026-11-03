from __future__ import annotations

import unittest
from unittest.mock import patch

import pyarrow as pa
import pyarrow.parquet as pq

from scripts.crypto_dataset_chart_benchmark import (
    _fetch_dataset_rows_from_parquet,
    unpack_image_info,
)


def parquet_fixture() -> bytes:
    image_type = pa.struct([
        pa.field("bytes", pa.binary()),
        pa.field("path", pa.string()),
    ])
    schema = pa.schema([
        pa.field("image", image_type),
        pa.field("label", pa.int64()),
        pa.field("ticker", pa.string()),
        pa.field("end_date", pa.string()),
        pa.field("pct_return", pa.float32()),
    ])
    rows = [
        {
            "image": {"bytes": b"\x89PNG\r\n\x1a\nBTC_IMAGE", "path": None},
            "label": 5,
            "ticker": "BTC-USD",
            "end_date": "2024-01-01",
            "pct_return": 8.5,
        },
        {
            "image": {"bytes": b"\x89PNG\r\n\x1a\nETH_IMAGE", "path": None},
            "label": 0,
            "ticker": "ETH-USD",
            "end_date": "2024-01-02",
            "pct_return": -8.0,
        },
    ]
    table = pa.Table.from_pylist(rows, schema=schema)
    output = pa.BufferOutputStream()
    pq.write_table(table, output)
    return output.getvalue().to_pybytes()


class CryptoDatasetParquetFallbackTests(unittest.TestCase):
    def test_parquet_fallback_filters_ticker_and_returns_embedded_image_bytes(self):
        payload = parquet_fixture()
        with patch(
            "scripts.crypto_dataset_chart_benchmark.request_bytes",
            return_value=payload,
        ) as download:
            rows, info = _fetch_dataset_rows_from_parquet(
                "test",
                "BTC-USD",
                1,
                viewer_error=RuntimeError("HTTP Error 503"),
            )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["ticker"], "BTC-USD")
        self.assertEqual(info["source_mode"], "DIRECT_HUB_PARQUET_FALLBACK")
        self.assertEqual(info["metadata_rows_selected"], 1)
        self.assertEqual(info["source_bytes"], len(payload))
        self.assertIn("/data/test-00000-of-00001.parquet", info["source_url"])
        download.assert_called_once()

        image_source, width, height = unpack_image_info(rows[0])
        self.assertEqual(image_source, b"\x89PNG\r\n\x1a\nBTC_IMAGE")
        self.assertIsNone(width)
        self.assertIsNone(height)

    def test_parquet_fallback_rejects_missing_required_columns(self):
        table = pa.table({
            "ticker": ["BTC-USD"],
            "label": [5],
        })
        output = pa.BufferOutputStream()
        pq.write_table(table, output)
        with patch(
            "scripts.crypto_dataset_chart_benchmark.request_bytes",
            return_value=output.getvalue().to_pybytes(),
        ):
            with self.assertRaisesRegex(RuntimeError, "missing required columns"):
                _fetch_dataset_rows_from_parquet(
                    "test",
                    None,
                    0,
                    viewer_error=RuntimeError("HTTP Error 503"),
                )


if __name__ == "__main__":
    unittest.main()
