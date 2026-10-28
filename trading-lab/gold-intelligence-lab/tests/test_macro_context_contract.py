"""Public FRED macro feed contracts; parsing tests only, no simulated trading."""
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))

from goldlab.macro_context import MacroDataError, parse_fred_macro_csv, parse_treasury_yield_xml, SERIES, SOURCE_URL


class FREDMacroContracts(unittest.TestCase):
    NOW = datetime(2026, 10, 29, 0, 0, tzinfo=timezone.utc)

    def test_parses_series_independently_and_calculates_five_observation_change(self):
        dates = [
            "2026-10-20", "2026-10-21", "2026-10-22",
            "2026-10-23", "2026-10-26", "2026-10-27", "2026-10-28",
        ]
        rows = [
            "4.0,2.0,100,20", "4.1,2.1,101,21", "4.2,2.2,102,22",
            "4.3,2.3,103,23", "4.4,2.4,104,24", "4.5,2.5,105,25",
            "4.6,2.6,106,26",
        ]
        csv_text = "observation_date,DGS10,DFII10,DTWEXAFEGS,VIXCLS\n" + "\n".join(
            f"{d},{row}" for d, row in zip(dates, rows)
        )
        result = parse_fred_macro_csv(csv_text, fetched_at_utc=self.NOW)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["series"]["DGS10"]["latest_observation_date"], "2026-10-28")
        self.assertAlmostEqual(result["series"]["DGS10"]["latest_value"], 4.6)
        self.assertAlmostEqual(result["series"]["DGS10"]["change_5_display"], 50.0)
        self.assertAlmostEqual(result["series"]["DTWEXAFEGS"]["change_5_display"], 4.9504950495)
        self.assertEqual(result["series"]["VIXCLS"]["change_1_display"], 1.0)
        self.assertEqual(result["series"]["DGS10"]["age_days"], 1)

    def test_accepts_dot_missing_values_and_keeps_series_dates_independent(self):
        csv_text = (
            "DATE,DGS10,DFII10,DTWEXAFEGS,VIXCLS\n"
            "2026-10-26,4.0,.,100,20\n"
            "2026-10-27,.,2.5,101,.\n"
            "2026-10-28,4.2,2.6,.,22\n"
        )
        result = parse_fred_macro_csv(csv_text, fetched_at_utc=self.NOW)
        self.assertEqual(result["series"]["DGS10"]["latest_value"], 4.2)
        self.assertEqual(result["series"]["DFII10"]["latest_observation_date"], "2026-10-28")
        self.assertEqual(result["series"]["DTWEXAFEGS"]["latest_observation_date"], "2026-10-27")
        self.assertEqual(result["series"]["VIXCLS"]["latest_value"], 22.0)

    def test_future_observations_are_not_used(self):
        csv_text = (
            "observation_date,DGS10\n"
            "2026-10-27,4.1\n"
            "2026-10-28,4.2\n"
            "2026-10-30,9.9\n"
        )
        result = parse_fred_macro_csv(csv_text, fetched_at_utc=self.NOW)
        self.assertEqual(result["series"]["DGS10"]["latest_value"], 4.2)
        self.assertEqual(result["series"]["DGS10"]["latest_observation_date"], "2026-10-28")

    def test_stale_data_is_explicit_and_not_relabelled_current(self):
        csv_text = "observation_date,DGS10\n2026-10-01,4.1\n"
        result = parse_fred_macro_csv(csv_text, fetched_at_utc=self.NOW)
        self.assertEqual(result["status"], "stale")
        self.assertEqual(result["series"]["DGS10"]["status"], "stale")
        self.assertEqual(result["series"]["DGS10"]["age_days"], 28)

    def test_unknown_schema_empty_payload_and_duplicate_date_are_rejected(self):
        for payload in ("", "not,csv\na,b\n", "DATE,DGS10\n2026-10-28,4\n2026-10-28,4.1\n"):
            with self.subTest(payload=payload):
                with self.assertRaises(MacroDataError):
                    parse_fred_macro_csv(payload, fetched_at_utc=self.NOW)


    def test_official_treasury_nominal_and_real_xml(self):
        ns = 'http://schemas.microsoft.com/ado/2007/08/dataservices'
        meta = 'http://schemas.microsoft.com/ado/2007/08/dataservices/metadata'
        atom = 'http://www.w3.org/2005/Atom'
        def payload(field, values):
            entries = []
            for day, value in values:
                entries.append(
                    f'<entry xmlns="{atom}" xmlns:m="{meta}" xmlns:d="{ns}">'
                    f'<content type="application/xml"><m:properties>'
                    f'<d:NEW_DATE>{day}T00:00:00</d:NEW_DATE>'
                    f'<d:{field}>{value}</d:{field}>'
                    f'</m:properties></content></entry>'
                )
            return f'<feed xmlns="{atom}">' + ''.join(entries) + '</feed>'
        nominal = payload('BC_10YEAR', [('2026-10-26','4.30'),('2026-10-27','4.40'),('2026-10-28','4.50')])
        real = payload('TC_10YEAR', [('2026-10-26','2.00'),('2026-10-27','2.10'),('2026-10-28','2.20')])
        x = parse_treasury_yield_xml(nominal, curve_type='nominal', fetched_at_utc=self.NOW)
        y = parse_treasury_yield_xml(real, curve_type='real', fetched_at_utc=self.NOW)
        self.assertEqual(x['series_id'], 'DGS10')
        self.assertAlmostEqual(x['latest_value'], 4.5)
        self.assertAlmostEqual(x['change_1_display'], 10.0)
        self.assertEqual(x['latest_observation_date'], '2026-10-28')
        self.assertEqual(y['series_id'], 'DFII10')
        self.assertAlmostEqual(y['latest_value'], 2.2)
        self.assertAlmostEqual(y['change_1_display'], 10.0)

    def test_official_treasury_rejects_duplicate_dates_and_unknown_curve(self):
        ns = 'http://schemas.microsoft.com/ado/2007/08/dataservices'
        meta = 'http://schemas.microsoft.com/ado/2007/08/dataservices/metadata'
        atom = 'http://www.w3.org/2005/Atom'
        def entry(day, value):
            return (f'<entry xmlns="{atom}" xmlns:m="{meta}" xmlns:d="{ns}"><content><m:properties>'
                    f'<d:NEW_DATE>{day}T00:00:00</d:NEW_DATE><d:BC_10YEAR>{value}</d:BC_10YEAR>'
                    '</m:properties></content></entry>')
        xml = f'<feed xmlns="{atom}">' + entry('2026-10-28','4.5') + entry('2026-10-28','4.6') + '</feed>'
        with self.assertRaises(MacroDataError):
            parse_treasury_yield_xml(xml, curve_type='nominal', fetched_at_utc=self.NOW)
        with self.assertRaises(ValueError):
            parse_treasury_yield_xml(xml, curve_type='bad', fetched_at_utc=self.NOW)

    def test_arabic_labels_are_not_mojibake(self):
        for series_id, item in SERIES.items():
            label = item["label_ar"]
            with self.subTest(series_id=series_id):
                self.assertTrue(any(0x0600 <= ord(ch) <= 0x06FF for ch in label))
                self.assertFalse(any(0x00C0 <= ord(ch) <= 0x024F for ch in label))

    def test_public_source_ids_and_labels_are_explicit(self):
        self.assertEqual(set(SERIES), {"DGS10", "DFII10", "DTWEXAFEGS", "VIXCLS"})
        self.assertIn("home.treasury.gov", SOURCE_URL)
        src = (ROOT / "python" / "goldlab" / "macro_context.py").read_text(encoding="utf-8")
        self.assertNotIn("api_key", src.lower())
        self.assertNotIn("Authorization", src)


if __name__ == "__main__":
    unittest.main()

[executed on device: DESKTOP-BCGR98A (28de460a-0fbe-4532-90a8-ff34da68192c)]