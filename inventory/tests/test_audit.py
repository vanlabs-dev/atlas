"""Audit record tests (spec: Run audit record) and cmd_run exit codes."""

import glob
import json
import os
import tempfile
import unittest
from unittest import mock

from _helpers import ai, FakeExec


def read_single(pattern):
    matches = glob.glob(pattern)
    assert len(matches) == 1, (pattern, matches)
    with open(matches[0], "r", encoding="utf-8") as handle:
        return matches[0], handle.read()


class CmdRunTests(unittest.TestCase):
    def test_partial_run_exit_3_with_full_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            code = ai.cmd_run(tmp, execute=FakeExec(
                returncode=1, stderr=b"Permission denied"))
            self.assertEqual(code, 3)
            _, report_text = read_single(os.path.join(tmp, "report-*.json"))
            _, audit_text = read_single(os.path.join(tmp, "audit-*.json"))
            read_single(os.path.join(tmp, "classification-worksheet-*.md"))
        report = json.loads(report_text)
        audit = json.loads(audit_text)
        self.assertFalse(report["run"]["complete"])
        self.assertEqual(audit["run_id"], report["run"]["run_id"])
        self.assertGreater(audit["status_summary"]["permission-denied"], 0)
        self.assertTrue(audit["errors"])
        self.assertIsNone(audit["fatal"])
        self.assertEqual(len(audit["outputs"]), 2)

    def test_audit_contains_no_planted_secret_from_probe_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            ai.cmd_run(tmp, execute=FakeExec(
                returncode=2,
                stderr=b"fatal: SECRET_TOKEN=PLANTEDAUDIT01 rejected"))
            _, audit_text = read_single(os.path.join(tmp, "audit-*.json"))
            _, report_text = read_single(os.path.join(tmp, "report-*.json"))
        self.assertNotIn("PLANTEDAUDIT01", audit_text)
        self.assertNotIn("PLANTEDAUDIT01", report_text)

    def test_fatal_run_still_writes_audit(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(
                    ai, "collect",
                    side_effect=RuntimeError("boom API_KEY=PLANTEDFATAL01")):
                code = ai.cmd_run(tmp, execute=FakeExec())
            self.assertEqual(code, 1)
            self.assertEqual(glob.glob(os.path.join(tmp, "report-*.json")), [])
            audit_path, audit_text = read_single(os.path.join(tmp, "audit-*.json"))
        audit = json.loads(audit_text)
        self.assertIn("unhandled failure", audit["fatal"])
        self.assertNotIn("PLANTEDFATAL01", audit_text)
        self.assertIsNone(audit["status_summary"])
        self.assertEqual(audit["outputs"], [])
        self.assertIn("unknown", audit_path)  # run id unknown before collect finished

    def test_invalid_report_is_never_written(self):
        broken = {"run": {}, "categories": {}}
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(ai, "collect", return_value=broken):
                code = ai.cmd_run(tmp, execute=FakeExec())
            self.assertEqual(code, 1)
            self.assertEqual(glob.glob(os.path.join(tmp, "report-*.json")), [])
            _, audit_text = read_single(os.path.join(tmp, "audit-*.json"))
        self.assertIn("schema validation", json.loads(audit_text)["fatal"])

    @unittest.skipUnless(os.name == "posix", "POSIX file modes")
    def test_outputs_are_private_0600(self):
        with tempfile.TemporaryDirectory() as tmp:
            ai.cmd_run(tmp, execute=FakeExec(stdout=b"x"))
            for path in glob.glob(os.path.join(tmp, "*")):
                mode = os.stat(path).st_mode & 0o777
                self.assertEqual(mode, 0o600, path)


class WorksheetSubcommandTests(unittest.TestCase):
    def test_regenerate_worksheet_from_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            ai.cmd_run(tmp, execute=FakeExec(stdout=b"x"))
            report_path = glob.glob(os.path.join(tmp, "report-*.json"))[0]
            worksheet_path = glob.glob(
                os.path.join(tmp, "classification-worksheet-*.md"))[0]
            os.remove(worksheet_path)
            code = ai.cmd_worksheet(report_path, None)
            self.assertEqual(code, 0)
            self.assertTrue(os.path.exists(worksheet_path))

    def test_rejects_invalid_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = os.path.join(tmp, "report-bad.json")
            with open(bad, "w", encoding="utf-8") as handle:
                json.dump({"not": "a report"}, handle)
            self.assertEqual(ai.cmd_worksheet(bad, None), 1)


if __name__ == "__main__":
    unittest.main()
