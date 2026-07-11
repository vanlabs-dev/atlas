"""Pins the inventory API this module reuses (design D1) and structural invariants."""

import json
import os
import unittest

from _helpers import ah, inv

SCHEMA_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "schema", "hardening-assessment.v1.schema.json")


class ImportSurfaceTests(unittest.TestCase):
    def test_pinned_inventory_api(self):
        # a rename/refactor in atlas_inventory.py must fail HERE, not at runtime
        self.assertTrue(callable(inv.run_probe))
        self.assertTrue(callable(inv.redact))
        self.assertTrue(callable(inv.schema_validate))
        self.assertTrue(hasattr(inv, "Probe"))
        self.assertIsInstance(inv.REPORT_SCHEMA, dict)
        self.assertIsInstance(inv._ENVELOPE_SCHEMA, dict)
        for name in ("STATUS_COLLECTED", "STATUS_UNSUPPORTED",
                     "STATUS_DENIED", "STATUS_ERROR", "CATEGORIES", "PARSERS"):
            self.assertTrue(hasattr(inv, name), name)

    def test_every_area_has_an_evaluator_and_expectation(self):
        self.assertEqual(set(ah.EVALUATORS), set(ah.AREAS))
        self.assertEqual(set(ah.EXPECTATIONS), set(ah.AREAS))
        self.assertEqual(len(ah.AREAS), 11)

    def test_supplementary_probes_use_known_parsers(self):
        for probe in ah.SUPPLEMENTARY_PROBES:
            if probe.parser:
                self.assertIn(probe.parser, inv.PARSERS, probe.item_id)

    def test_schema_file_matches_embedded(self):
        with open(SCHEMA_FILE, "r", encoding="utf-8") as handle:
            self.assertEqual(json.load(handle), ah.ASSESSMENT_SCHEMA,
                             "regenerate: python atlas_hardening.py "
                             "dump-schema > schema/...")


if __name__ == "__main__":
    unittest.main()
