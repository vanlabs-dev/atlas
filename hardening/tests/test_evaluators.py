"""Per-area evaluator tests (spec: coverage, verdicts, no assumptions)."""

import unittest

from _helpers import (ah, envelope, pi_baseline_inventory, pi_baseline_probes,
                      hardened_inventory, hardened_probes, results_by_area)


class PiBaselineTests(unittest.TestCase):
    """The real clean-baseline Pi must produce these exact verdicts."""

    def setUp(self):
        self.results = ah.assess(pi_baseline_inventory(), pi_baseline_probes())
        self.by_area = results_by_area(self.results)

    def test_all_11_areas_present_in_order(self):
        self.assertEqual([r.area for r in self.results], list(ah.AREAS))

    def test_all_evidence_complete_on_baseline(self):
        self.assertTrue(all(r.evidence_complete for r in self.results))

    def test_ssh_area_findings(self):
        result = self.by_area["ssh-authentication-and-exposed-ports"]
        self.assertEqual(result.verdict, "finding")
        issues = [issue.issue for issue in result.issues]
        self.assertTrue(any("password authentication" in i.lower()
                            for i in issues))
        self.assertTrue(any("default: yes" in i for i in issues))  # observed, not assumed
        self.assertTrue(any("X11" in i for i in issues))
        self.assertTrue(any("rpcbind" in i for i in issues))
        self.assertTrue(any("mDNS" in i for i in issues))
        for issue in result.issues:
            self.assertTrue(issue.evidence, issue.issue)

    def test_firewall_finding(self):
        result = self.by_area["firewall-rules"]
        self.assertEqual(result.verdict, "finding")
        self.assertIn("default-deny", result.issues[0].proposal)
        self.assertTrue(any("nftables" in c for c in result.issues[0].commands))

    def test_unattended_updates_finding(self):
        self.assertEqual(self.by_area["unattended-security-updates"].verdict,
                         "finding")

    def test_ok_areas(self):
        for area in ("secret-file-permissions", "log-permissions",
                     "service-restart-policy", "time-synchronization"):
            self.assertEqual(self.by_area[area].verdict, "ok", area)

    def test_public_cert_store_not_flagged(self):
        result = self.by_area["secret-file-permissions"]
        self.assertEqual(result.issues, [])  # snakeoil.pem excluded as public

    def test_decision_required_areas_name_the_decision(self):
        backup = self.by_area["backup-encryption-and-destination"]
        self.assertEqual(backup.verdict, "decision-required")
        self.assertIn("Q10", backup.decision)
        disk = self.by_area["disk-space-thresholds"]
        self.assertEqual(disk.verdict, "decision-required")
        self.assertIn("80%", disk.summary)
        self.assertIn("3%", disk.summary)  # observed usage quoted

    def test_not_applicable_areas_state_reassess_trigger(self):
        services = self.by_area["unprivileged-service-execution"]
        self.assertEqual(services.verdict, "not-applicable-yet")
        self.assertIn("Phase 1", services.reassess_when)
        frontend = self.by_area["remote-frontend-exposure"]
        self.assertEqual(frontend.verdict, "not-applicable-yet")
        self.assertIn("Phase 6", frontend.reassess_when)


class HardenedFixtureTests(unittest.TestCase):
    def setUp(self):
        self.by_area = results_by_area(
            ah.assess(hardened_inventory(), hardened_probes()))

    def test_hardened_areas_become_ok(self):
        for area in ("ssh-authentication-and-exposed-ports", "firewall-rules",
                     "unattended-security-updates"):
            result = self.by_area[area]
            self.assertEqual(result.verdict, "ok", "%s: %s" % (area, result.summary))
            self.assertEqual(result.issues, [])


class MissingEvidenceTests(unittest.TestCase):
    def test_denied_evidence_is_explicit_never_assumed(self):
        report = pi_baseline_inventory()
        report["categories"]["remote_access"]["items"]["sshd_config"] = \
            envelope(status="permission-denied", error="nope")
        by_area = results_by_area(ah.assess(report, pi_baseline_probes()))
        result = by_area["ssh-authentication-and-exposed-ports"]
        self.assertFalse(result.evidence_complete)
        self.assertIn("No state was assumed", result.summary)
        self.assertIn("insufficient evidence", result.issues[0].issue)

    def test_missing_probe_evidence(self):
        probes = pi_baseline_probes()
        probes["time_sync"] = envelope(status="unsupported-on-device",
                                       error="tool not present")
        by_area = results_by_area(ah.assess(pi_baseline_inventory(), probes))
        result = by_area["time-synchronization"]
        self.assertFalse(result.evidence_complete)
        self.assertEqual(result.verdict, "finding")

    def test_crashing_evaluator_does_not_sink_the_run(self):
        broken = pi_baseline_inventory()
        # sockets data with a non-string entry crashes the ssh evaluator parse
        broken["categories"]["listening_ports"]["items"]["sockets"] = \
            envelope(data={"text_lines": [None]})
        results = ah.assess(broken, pi_baseline_probes())
        self.assertEqual(len(results), len(ah.AREAS))
        ssh = results_by_area(results)["ssh-authentication-and-exposed-ports"]
        self.assertFalse(ssh.evidence_complete)

    def test_empty_report_yields_no_assumptions(self):
        from _helpers import base_inventory
        results = ah.assess(base_inventory(), {})
        for result in results:
            if result.verdict == "ok":
                self.fail("ok verdict without evidence: %s" % result.area)


if __name__ == "__main__":
    unittest.main()
