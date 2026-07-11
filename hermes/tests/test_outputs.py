"""Verdict logic, report outputs, and the zero-mutation surface."""

import json
import os
import re
import stat
import tempfile
import unittest

from _helpers import (VERIFIER_SOURCE, ahv, base_bundle, green_record,
                      inv)

ALL_ATTESTED = list(ahv.ATTESTATION_CHECKS)


class AttestationTests(unittest.TestCase):
    def test_attestations_recorded_with_operator_and_timestamp(self):
        attestations = ahv.build_attestations(
            ["chat"], "pi", "2026-07-12T10:00:00+00:00")
        by_check = {item["check"]: item for item in attestations}
        self.assertTrue(by_check["chat"]["attested"])
        self.assertEqual(by_check["chat"]["operator"], "pi")
        self.assertEqual(by_check["chat"]["timestamp"],
                         "2026-07-12T10:00:00+00:00")
        self.assertFalse(by_check["tool-call"]["attested"])
        self.assertIsNone(by_check["tool-call"]["operator"])

    def test_unknown_attestation_is_fatal(self):
        with self.assertRaises(ahv.FatalVerificationError):
            ahv.build_attestations(["chats"], "pi", "t")


class VerdictTests(unittest.TestCase):
    def run_verdict(self, bundle=None, record=None, attested=ALL_ATTESTED):
        record = record or green_record()
        results = ahv.run_checks(record, "/tmp/r.json",
                                 bundle or base_bundle())
        attestations = ahv.build_attestations(list(attested), "pi", "t")
        return ahv.compute_verdict(results, attestations)

    def test_green_run_is_accepted(self):
        overall, blockers = self.run_verdict()
        self.assertEqual(overall, ahv.VERDICT_ACCEPTED)
        self.assertEqual(blockers, [])

    def test_missing_attestation_blocks(self):
        overall, blockers = self.run_verdict(
            attested=["chat", "memory-session-search"])
        self.assertEqual(overall, ahv.VERDICT_NOT_ACCEPTED)
        self.assertTrue(any("tool-call" in blocker for blocker in blockers))

    def test_one_unknown_blocks_acceptance(self):
        bundle = base_bundle()
        bundle["config_file"] = dict(bundle["config_file"],
                                     text="model: grok\n")
        overall, blockers = self.run_verdict(bundle=bundle)
        self.assertEqual(overall, ahv.VERDICT_NOT_ACCEPTED)
        self.assertTrue(any("telemetry-disabled" in blocker
                            for blocker in blockers))

    def test_permission_denied_blocks_acceptance(self):
        bundle = base_bundle()
        bundle["etc_group"] = {"status": "permission-denied",
                               "path": "/etc/group",
                               "error": "permission denied"}
        overall, blockers = self.run_verdict(bundle=bundle)
        self.assertEqual(overall, ahv.VERDICT_NOT_ACCEPTED)

    def test_documented_exception_unblocks(self):
        record = green_record(diagnostics_command=None, exceptions=[
            {"check": "diagnostics",
             "reason": "this Hermes version ships no diagnostics command"}])
        bundle = base_bundle(diagnostics=None)
        overall, blockers = self.run_verdict(bundle=bundle, record=record)
        self.assertEqual(overall, ahv.VERDICT_ACCEPTED)


class CmdVerifyTests(unittest.TestCase):
    """Full-run integration through cmd_verify with a fake collector."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.record_path = os.path.join(self.tmp.name, "install-record.json")
        self.output_dir = os.path.join(self.tmp.name, "out")

    def write_record(self, record):
        with open(self.record_path, "w", encoding="utf-8") as handle:
            json.dump(record, handle)

    def run_verify(self, bundle, attested=ALL_ATTESTED):
        return ahv.cmd_verify(
            self.record_path, self.output_dir, list(attested), "pi",
            collect=lambda record, execute=None: bundle)

    def load_outputs(self):
        names = sorted(os.listdir(self.output_dir))
        verification_path = [name for name in names
                             if name.startswith("verification-")][0]
        with open(os.path.join(self.output_dir, verification_path),
                  encoding="utf-8") as handle:
            verification = json.load(handle)
        summary_path = [name for name in names
                        if name.startswith("summary-")][0]
        with open(os.path.join(self.output_dir, summary_path),
                  encoding="utf-8") as handle:
            summary = handle.read()
        return verification, summary, names

    def test_green_run_accepted_exit_0(self):
        self.write_record(green_record())
        self.assertEqual(self.run_verify(base_bundle()), 0)
        verification, summary, names = self.load_outputs()
        self.assertEqual(verification["verdict"]["overall"], "accepted")
        self.assertEqual(
            inv.schema_validate(verification, ahv.VERIFICATION_SCHEMA), [])
        self.assertIn("**Verdict:** accepted", summary)
        self.assertTrue(any(name.startswith("audit-") for name in names))

    def test_blocked_run_exit_3_names_blockers(self):
        self.write_record(green_record())
        bundle = base_bundle(diagnostics=probe_error())
        code = self.run_verify(bundle, attested=["chat"])
        self.assertEqual(code, 3)
        verification, summary, _ = self.load_outputs()
        self.assertEqual(verification["verdict"]["overall"], "not-accepted")
        blockers = "\n".join(verification["verdict"]["blockers"])
        self.assertIn("diagnostics", blockers)
        self.assertIn("memory-session-search", blockers)
        self.assertIn("tool-call", blockers)
        self.assertEqual(
            inv.schema_validate(verification, ahv.VERIFICATION_SCHEMA), [])

    def test_missing_record_exit_4_no_verdict(self):
        code = ahv.cmd_verify(self.record_path, self.output_dir,
                              ALL_ATTESTED, "pi",
                              collect=lambda record, execute=None:
                              self.fail("collect must not run"))
        self.assertEqual(code, 4)
        verification, summary, _ = self.load_outputs()
        self.assertEqual(verification["verdict"]["overall"], "no-verdict")
        self.assertEqual(verification["checks"], [])
        self.assertIn("no verdict issued", summary)
        self.assertEqual(
            inv.schema_validate(verification, ahv.VERIFICATION_SCHEMA), [])

    def test_outputs_only_in_output_dir_and_private(self):
        self.write_record(green_record())
        before = set(os.listdir(self.tmp.name))
        self.run_verify(base_bundle())
        after = set(os.listdir(self.tmp.name))
        self.assertEqual(before | {"out"}, after)
        if os.name == "posix":
            for name in os.listdir(self.output_dir):
                mode = stat.S_IMODE(os.stat(
                    os.path.join(self.output_dir, name)).st_mode)
                self.assertEqual(mode, 0o600, name)


def probe_error():
    return {"status": "error", "command": "hermes doctor",
            "duration_ms": 0.0, "error": "exit status 2"}


class ZeroMutationSurfaceTests(unittest.TestCase):
    """The verifier's complete external command surface is read-only."""

    def setUp(self):
        with open(VERIFIER_SOURCE, encoding="utf-8") as handle:
            self.source = handle.read()

    def test_no_direct_subprocess_use(self):
        # every external command must go through the reviewed inventory
        # probe machinery
        self.assertNotIn("subprocess", self.source)
        self.assertNotIn("os.system", self.source)
        self.assertNotIn("os.exec", self.source)

    def test_systemctl_only_ever_shows(self):
        occurrences = [match.start() for match
                       in re.finditer('"systemctl"', self.source)]
        self.assertTrue(occurrences)
        for start in occurrences:
            self.assertIn('"show"', self.source[start:start + 400],
                          "systemctl used without 'show' nearby")
        for verb in ("restart", "stop", "start", "enable", "disable",
                     "daemon-reload", "mask", "isolate", "kill"):
            self.assertNotIn('"%s"' % verb, self.source, verb)

    def test_no_write_helpers_beyond_private_report_writer(self):
        # os.open is the single write path (0600 report files)
        self.assertEqual(self.source.count("os.open"), 1)
        self.assertNotIn("shutil", self.source)


if __name__ == "__main__":
    unittest.main()
