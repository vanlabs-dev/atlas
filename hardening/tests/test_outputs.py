"""Output tests: schema validity, plan rendering, redaction, audit, exit codes."""

import glob
import json
import os
import tempfile
import unittest

from _helpers import (ah, inv, envelope, pi_baseline_inventory,
                      pi_baseline_probes)


class FakeSupplementaryExec:
    """Feeds the two supplementary cmd probes realistic output."""

    def __call__(self, argv, timeout):
        if argv[0] == "timedatectl":
            return 0, b"NTP=yes\nNTPSynchronized=yes\nTimezone=UTC\n", b""
        if argv[0] == "systemctl":
            return 0, b"Restart=on-failure\n", b""
        raise FileNotFoundError(argv[0])


def write_report(directory, report):
    path = os.path.join(directory, "report-20260711T062206Z-5be02d8f.json")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(report, handle)
    return path


def read_single(pattern):
    matches = glob.glob(pattern)
    assert len(matches) == 1, (pattern, matches)
    with open(matches[0], "r", encoding="utf-8") as handle:
        return matches[0], handle.read()


class AssessmentJsonTests(unittest.TestCase):
    def test_assessment_validates_against_schema(self):
        results = ah.assess(pi_baseline_inventory(), pi_baseline_probes())
        assessment = ah.build_assessment(
            {"run_id": "x", "path": "p", "age_hours": 1.0, "stale": False},
            pi_baseline_probes(), results, "2026-07-11T00:00:00+00:00",
            "runid-1")
        self.assertEqual(
            inv.schema_validate(assessment, ah.ASSESSMENT_SCHEMA), [])

    def test_complete_flag_tracks_evidence(self):
        report = pi_baseline_inventory()
        report["categories"]["remote_access"]["items"]["sshd_config"] = \
            envelope(status="permission-denied", error="x")
        results = ah.assess(report, pi_baseline_probes())
        assessment = ah.build_assessment(
            {"run_id": "x", "path": "p", "age_hours": 1.0, "stale": False},
            {}, results, "t", "r")
        self.assertFalse(assessment["run"]["complete"])


class PlanRenderTests(unittest.TestCase):
    def render_baseline(self):
        results = ah.assess(pi_baseline_inventory(), pi_baseline_probes())
        assessment = ah.build_assessment(
            {"run_id": "inv-1", "path": "p", "age_hours": 1.0, "stale": False},
            pi_baseline_probes(), results, "2026-07-11T00:00:00+00:00", "run-1")
        return ah.render_plan(assessment)

    def test_plan_contains_firewall_and_ssh_items_unchecked(self):
        plan = self.render_baseline()
        self.assertIn("Nothing in this plan has been executed", plan)
        self.assertIn("default-deny inbound", plan)
        self.assertIn("PasswordAuthentication no", plan)
        self.assertIn("- [ ] approved", plan)
        self.assertNotIn("- [x] approved", plan)

    def test_plan_lists_decisions_and_evidence(self):
        plan = self.render_baseline()
        self.assertIn("Decisions required", plan)
        self.assertIn("Q10", plan)
        self.assertIn("inventory:20260711T062206Z-5be02d8f:", plan)
        self.assertIn("Rollback", plan)

    def test_stale_inventory_flagged_in_plan(self):
        results = ah.assess(pi_baseline_inventory(), pi_baseline_probes())
        assessment = ah.build_assessment(
            {"run_id": "inv-1", "path": "p", "age_hours": 200.0, "stale": True},
            {}, results, "t", "r")
        self.assertIn("STALE", ah.render_plan(assessment))


class CmdAssessTests(unittest.TestCase):
    def test_full_run_exit_0_with_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            report_path = write_report(tmp, pi_baseline_inventory())
            out = os.path.join(tmp, "out")
            code = ah.cmd_assess(report_path, out, 1e9,
                                 execute=FakeSupplementaryExec())
            self.assertEqual(code, 0)
            _, assessment_text = read_single(
                os.path.join(out, "assessment-*.json"))
            read_single(os.path.join(out, "hardening-plan-*.md"))
            _, audit_text = read_single(os.path.join(out, "audit-*.json"))
        assessment = json.loads(assessment_text)
        self.assertEqual(
            inv.schema_validate(assessment, ah.ASSESSMENT_SCHEMA), [])
        audit = json.loads(audit_text)
        self.assertIsNone(audit["fatal"])
        self.assertEqual(sum(audit["verdict_counts"].values()), len(ah.AREAS))

    def test_incomplete_evidence_exit_3(self):
        report = pi_baseline_inventory()
        report["categories"]["remote_access"]["items"]["sshd_config"] = \
            envelope(status="permission-denied", error="x")
        with tempfile.TemporaryDirectory() as tmp:
            report_path = write_report(tmp, report)
            code = ah.cmd_assess(report_path, os.path.join(tmp, "out"), 1e9,
                                 execute=FakeSupplementaryExec())
        self.assertEqual(code, 3)

    def test_invalid_inventory_fatal_exit_1_with_audit(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = os.path.join(tmp, "report-bad.json")
            with open(bad, "w", encoding="utf-8") as handle:
                json.dump({"nope": 1}, handle)
            out = os.path.join(tmp, "out")
            code = ah.cmd_assess(bad, out, 1e9)
            self.assertEqual(code, 1)
            self.assertEqual(glob.glob(os.path.join(out, "assessment-*")), [])
            _, audit_text = read_single(os.path.join(out, "audit-*.json"))
        self.assertIn("schema validation", json.loads(audit_text)["fatal"])

    def test_missing_report_fatal(self):
        with tempfile.TemporaryDirectory() as tmp:
            code = ah.cmd_assess(os.path.join(tmp, "nope.json"),
                                 os.path.join(tmp, "out"), 1e9)
        self.assertEqual(code, 1)

    def test_outputs_are_redacted(self):
        report = pi_baseline_inventory()
        report["categories"]["remote_access"]["items"]["sshd_config"] = \
            envelope(data={"directives": {
                "x11forwarding": ["yes"],
                "allowusers": ["api_key=PLANTEDPLAN01"]},
                "note": "n"})
        with tempfile.TemporaryDirectory() as tmp:
            report_path = write_report(tmp, report)
            out = os.path.join(tmp, "out")
            ah.cmd_assess(report_path, out, 1e9,
                          execute=FakeSupplementaryExec())
            for path in glob.glob(os.path.join(out, "*")):
                with open(path, "r", encoding="utf-8") as handle:
                    self.assertNotIn("PLANTEDPLAN01", handle.read(), path)

    @unittest.skipUnless(os.name == "posix", "POSIX file modes")
    def test_outputs_private_0600(self):
        with tempfile.TemporaryDirectory() as tmp:
            report_path = write_report(tmp, pi_baseline_inventory())
            out = os.path.join(tmp, "out")
            ah.cmd_assess(report_path, out, 1e9,
                          execute=FakeSupplementaryExec())
            for path in glob.glob(os.path.join(out, "*")):
                self.assertEqual(os.stat(path).st_mode & 0o777, 0o600, path)


if __name__ == "__main__":
    unittest.main()
