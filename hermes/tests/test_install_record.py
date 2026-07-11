"""Install-record loading fails closed (ATLAS-HERMES-001 contract)."""

import json
import os
import tempfile
import unittest

from _helpers import ahv, make_record


class InstallRecordTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "install-record.json")

    def write(self, payload):
        with open(self.path, "w", encoding="utf-8") as handle:
            if isinstance(payload, str):
                handle.write(payload)
            else:
                json.dump(payload, handle)

    def test_missing_file_yields_no_record(self):
        record, problems, present = ahv.load_install_record(self.path)
        self.assertIsNone(record)
        self.assertFalse(present)
        self.assertIn("not found", problems[0])

    def test_complete_record_loads(self):
        self.write(make_record())
        record, problems, present = ahv.load_install_record(self.path)
        self.assertEqual(problems, [])
        self.assertTrue(present)
        self.assertEqual(record["service_user"], "hermes")

    def test_every_required_field_is_enforced(self):
        for field in ahv.REQUIRED_RECORD_FIELDS:
            self.write(make_record(**{field: None}))
            record, problems, _ = ahv.load_install_record(self.path)
            self.assertIsNone(record, field)
            self.assertTrue(any(field in problem for problem in problems),
                            field)

    def test_placeholder_value_is_a_problem(self):
        self.write(make_record(installed_version="TODO fill me in"))
        record, problems, _ = ahv.load_install_record(self.path)
        self.assertIsNone(record)
        self.assertTrue(any("placeholder" in problem for problem in problems))

    def test_invalid_json_is_a_problem_not_a_crash(self):
        self.write("{not json")
        record, problems, present = ahv.load_install_record(self.path)
        self.assertIsNone(record)
        self.assertTrue(present)
        self.assertIn("invalid", problems[0])

    def test_unknown_fields_rejected(self):
        self.write(make_record(surprise="x"))
        record, problems, _ = ahv.load_install_record(self.path)
        self.assertIsNone(record)
        self.assertTrue(any("unknown fields: surprise" in problem
                            for problem in problems))

    def test_exceptions_must_target_known_checks(self):
        self.write(make_record(exceptions=[
            {"check": "no-such-check", "reason": "because"}]))
        record, problems, _ = ahv.load_install_record(self.path)
        self.assertIsNone(record)
        self.assertTrue(any("no-such-check" in problem
                            for problem in problems))

    def test_exceptions_need_a_reason(self):
        self.write(make_record(exceptions=[{"check": "diagnostics",
                                            "reason": "  "}]))
        record, problems, _ = ahv.load_install_record(self.path)
        self.assertIsNone(record)
        self.assertTrue(any("exceptions[0]" in problem
                            for problem in problems))

    def test_valid_exceptions_accepted(self):
        self.write(make_record(exceptions=[
            {"check": "diagnostics", "reason": "this version ships none"}]))
        record, problems, _ = ahv.load_install_record(self.path)
        self.assertEqual(problems, [])
        self.assertEqual(record["exceptions"][0]["check"], "diagnostics")


if __name__ == "__main__":
    unittest.main()
