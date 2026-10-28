"""Product capability catalogue consistency checks."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))

from goldlab.feature_catalog import FEATURES, STATUS_LABELS_AR, get_feature_catalog, summarize_feature_catalog


class FeatureCatalogContracts(unittest.TestCase):
    def test_feature_ids_are_unique_and_required_fields_are_present(self):
        ids = [feature["id"] for feature in FEATURES]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertGreaterEqual(len(ids), 30)
        for feature in FEATURES:
            with self.subTest(feature=feature["id"]):
                self.assertTrue(feature["category_ar"])
                self.assertTrue(feature["name_ar"])
                self.assertTrue(feature["detail_ar"])
                self.assertIn(feature["status"], STATUS_LABELS_AR)
                self.assertTrue(feature["sources"])
                self.assertTrue(all(source.startswith("https://") for source in feature["sources"]))

    def test_summary_counts_match_catalog(self):
        summary = summarize_feature_catalog()
        self.assertEqual(summary["total"], len(FEATURES))
        self.assertEqual(summary["total"], sum(summary["counts"].values()))
        self.assertEqual(summary["implemented"], summary["counts"].get("implemented", 0))

    def test_returned_catalog_cannot_mutate_module_constant(self):
        returned = get_feature_catalog()
        returned[0]["name_ar"] = "changed"
        returned[0]["sources"].append("https://example.invalid")
        self.assertNotEqual(FEATURES[0]["name_ar"], "changed")
        self.assertNotIn("https://example.invalid", FEATURES[0]["sources"])


if __name__ == "__main__":
    unittest.main()

[executed on device: DESKTOP-BCGR98A (28de460a-0fbe-4532-90a8-ff34da68192c)]