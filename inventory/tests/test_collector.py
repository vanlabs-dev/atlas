"""Collector runner tests (spec: Read-only operation, per-item status, coverage)."""

import unittest

from _helpers import ai, FakeExec, MappedExec


class CollectorTests(unittest.TestCase):
    def test_all_categories_present_even_when_no_tool_exists(self):
        # every cmd probe raises FileNotFoundError -> unsupported-on-device;
        # the run must still produce all 16 categories with explicit statuses
        report = ai.collect(execute=MappedExec({}))
        self.assertEqual(set(report["categories"]), set(ai.CATEGORIES))
        for category in report["categories"].values():
            for item in category["items"].values():
                self.assertIn(item["status"], ai.ALL_STATUSES)

    def test_single_probe_crash_does_not_abort_run(self):
        probes = (
            ai.Probe("boom", "hardware", "bogus-kind", ("x",)),
            ai.Probe("ok", "os_kernel", "cmd", ("uname", "-a"), parser="lines"),
        )
        report = ai.collect(execute=FakeExec(stdout=b"Linux test"), probes=probes)
        boom = report["categories"]["hardware"]["items"]["boom"]
        ok = report["categories"]["os_kernel"]["items"]["ok"]
        self.assertEqual(boom["status"], "error")
        self.assertEqual(ok["status"], "collected")

    def test_report_validates_against_schema(self):
        report = ai.collect(execute=MappedExec({}))
        self.assertEqual(ai.schema_validate(report, ai.REPORT_SCHEMA), [])

    def test_complete_flag_false_on_denied_or_error(self):
        report = ai.collect(execute=FakeExec(
            returncode=1, stderr=b"Permission denied"))
        self.assertFalse(report["run"]["complete"])

    def test_complete_flag_true_when_only_unsupported(self):
        # unsupported-on-device is a legitimate finding, not a failure
        probes = (ai.Probe("x", "hardware", "cmd", ("nonexistent-tool-abc",)),)
        report = ai.collect(execute=MappedExec({}), probes=probes)
        self.assertEqual(
            report["categories"]["hardware"]["items"]["x"]["status"],
            "unsupported-on-device")
        self.assertTrue(report["run"]["complete"])

    def test_run_metadata(self):
        report = ai.collect(execute=MappedExec({}))
        run = report["run"]
        self.assertEqual(run["schema_version"], ai.SCHEMA_VERSION)
        self.assertEqual(run["script_version"], ai.SCRIPT_VERSION)
        self.assertRegex(run["run_id"], r"^\d{8}T\d{6}Z-[0-9a-f]{8}$")
        self.assertTrue(run["executing_account"])
        self.assertTrue(run["hostname"])

    def test_status_summary_and_item_errors(self):
        report = ai.collect(execute=FakeExec(returncode=2, stderr=b"boom"))
        summary = ai.status_summary(report)
        self.assertEqual(sum(summary.values()),
                         sum(len(c["items"]) for c in report["categories"].values()))
        errors = ai.item_errors(report)
        self.assertTrue(errors)
        self.assertTrue(all("." in e["item"] for e in errors))


if __name__ == "__main__":
    unittest.main()
