"""Schema tests (spec: Versioned machine-readable output schema)."""

import json
import os
import unittest

from _helpers import ai, make_report, make_envelope

SCHEMA_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "schema", "inventory-report.v1.schema.json")


class SchemaFileTests(unittest.TestCase):
    def test_schema_file_matches_embedded_schema(self):
        """schema/ file is generated from the script; they must never diverge."""
        with open(SCHEMA_FILE, "r", encoding="utf-8") as handle:
            on_disk = json.load(handle)
        self.assertEqual(on_disk, ai.REPORT_SCHEMA,
                         "regenerate with: python atlas_inventory.py dump-schema "
                         "> schema/inventory-report.v1.schema.json")

    def test_schema_declares_version_1(self):
        self.assertEqual(ai.SCHEMA_VERSION, 1)
        self.assertIn("v1", ai.REPORT_SCHEMA["$id"])


class ValidatorTests(unittest.TestCase):
    def test_minimal_report_is_valid(self):
        self.assertEqual(ai.schema_validate(make_report(), ai.REPORT_SCHEMA), [])

    def test_report_with_items_is_valid(self):
        report = make_report({"hardware": {"model": make_envelope(
            data={"files": [{"path": "x", "content": "Pi 5"}]})}})
        self.assertEqual(ai.schema_validate(report, ai.REPORT_SCHEMA), [])

    def test_bad_status_rejected(self):
        report = make_report({"hardware": {"model": make_envelope(status="fine")}})
        errors = ai.schema_validate(report, ai.REPORT_SCHEMA)
        self.assertTrue(any("enum" in e for e in errors))

    def test_missing_category_rejected(self):
        report = make_report()
        del report["categories"]["firewall"]
        errors = ai.schema_validate(report, ai.REPORT_SCHEMA)
        self.assertTrue(any("firewall" in e for e in errors))

    def test_unexpected_key_rejected(self):
        report = make_report()
        report["run"]["sneaky"] = True
        errors = ai.schema_validate(report, ai.REPORT_SCHEMA)
        self.assertTrue(any("sneaky" in e for e in errors))

    def test_wrong_schema_version_rejected(self):
        report = make_report()
        report["run"]["schema_version"] = 99
        errors = ai.schema_validate(report, ai.REPORT_SCHEMA)
        self.assertTrue(any("schema_version" in e for e in errors))

    def test_envelope_requires_status_and_command(self):
        report = make_report({"hardware": {"model": {"data": {}}}})
        errors = ai.schema_validate(report, ai.REPORT_SCHEMA)
        self.assertTrue(any("status" in e for e in errors))
        self.assertTrue(any("command" in e for e in errors))


if __name__ == "__main__":
    unittest.main()
