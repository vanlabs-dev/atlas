"""Pins the inventory API this module reuses and structural invariants."""

import json
import os
import unittest

from _helpers import ahv, inv

SCHEMA_FILE = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "schema",
    "hermes-baseline-verification.v1.schema.json")


class ImportSurfaceTests(unittest.TestCase):
    def test_pinned_inventory_api(self):
        # a rename/refactor in atlas_inventory.py must fail HERE, not at runtime
        self.assertTrue(callable(inv.run_probe))
        self.assertTrue(callable(inv.redact))
        self.assertTrue(callable(inv.schema_validate))
        self.assertTrue(hasattr(inv, "Probe"))
        self.assertIsInstance(inv.REDACTION_MARKER, str)
        for name in ("STATUS_COLLECTED", "STATUS_UNSUPPORTED",
                     "STATUS_DENIED", "STATUS_ERROR"):
            self.assertTrue(hasattr(inv, name), name)

    def test_check_lists_are_fixed(self):
        self.assertEqual(len(ahv.CHECKS), 6)
        self.assertEqual(len(ahv.ATTESTATION_CHECKS), 3)
        self.assertEqual(len(ahv.REQUIRED_RECORD_FIELDS), 8)
        # every check is representable in the report schema
        check_enum = ahv.VERIFICATION_SCHEMA["properties"]["checks"][
            "items"]["properties"]["check"]["enum"]
        self.assertEqual(set(check_enum), set(ahv.CHECKS))

    def test_status_vocabulary_reuses_inventory_statuses(self):
        self.assertEqual(ahv.CHECK_DENIED, inv.STATUS_DENIED)
        self.assertEqual(ahv.CHECK_UNSUPPORTED, inv.STATUS_UNSUPPORTED)

    def test_schema_file_matches_embedded(self):
        with open(SCHEMA_FILE, "r", encoding="utf-8") as handle:
            self.assertEqual(json.load(handle), ahv.VERIFICATION_SCHEMA,
                             "regenerate: python atlas_hermes_verify.py "
                             "dump-schema > schema/...")


if __name__ == "__main__":
    unittest.main()
