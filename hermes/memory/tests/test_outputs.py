"""Full-run behavior: verdicts, exit codes, output files, read-only-ness."""

import json
import os
import re
import stat
import sys
import tempfile
import unittest

from _helpers import (VERIFIER_SOURCE, amv, base_bundle, make_record,
                      results_by_check)

ALL_ATTESTS = list(amv.ATTESTATION_ITEMS)


class VerdictTests(unittest.TestCase):
    def _verdict(self, bundle=None, attested=ALL_ATTESTS, exceptions=()):
        results = amv.run_checks(make_record(), "record.json",
                                 bundle or base_bundle(), list(exceptions))
        attestations = amv.build_attestations(list(attested), "op", "t0")
        return amv.ahv.compute_verdict(results, attestations)

    def test_green_run_is_accepted(self):
        overall, blockers = self._verdict()
        self.assertEqual(blockers, [])
        self.assertEqual(overall, amv.ahv.VERDICT_ACCEPTED)

    def test_missing_attestation_blocks(self):
        overall, blockers = self._verdict(attested=ALL_ATTESTS[:-1])
        self.assertEqual(overall, amv.ahv.VERDICT_NOT_ACCEPTED)
        self.assertTrue(any("domain-separation" in blocker
                            for blocker in blockers))

    def test_unknown_check_blocks_by_name(self):
        from _helpers import store_item
        overall, blockers = self._verdict(
            bundle=base_bundle(session_store=store_item(marker_hits=0)))
        self.assertEqual(overall, amv.ahv.VERDICT_NOT_ACCEPTED)
        self.assertTrue(any("session-store" in blocker
                            for blocker in blockers))

    def test_documented_exception_unblocks_check(self):
        from _helpers import store_item
        overall, blockers = self._verdict(
            bundle=base_bundle(session_store=store_item(marker_hits=0)),
            exceptions=[{"check": "session-store",
                         "reason": "documented deviation"}])
        self.assertEqual(overall, amv.ahv.VERDICT_ACCEPTED)

    def test_unknown_attestation_name_is_fatal(self):
        with self.assertRaises(amv.ahv.FatalVerificationError):
            amv.build_attestations(["made-up"], "op", "t0")


class CmdVerifyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out = os.path.join(self.tmp.name, "out")
        self.record_path = os.path.join(self.tmp.name,
                                        "install-record.json")
        with open(self.record_path, "w", encoding="utf-8") as handle:
            json.dump(make_record(), handle)
        self.exceptions_path = os.path.join(self.tmp.name,
                                            "exceptions.json")

    def _verify(self, attested=ALL_ATTESTS, record_path=None,
                collect=None):
        return amv.cmd_verify(
            record_path or self.record_path, self.exceptions_path,
            self.out, list(attested), "operator",
            collect=collect or (lambda record: base_bundle()))

    def _outputs(self, prefix):
        return sorted(name for name in os.listdir(self.out)
                      if name.startswith(prefix))

    def test_green_run_exit_0_and_outputs(self):
        self.assertEqual(self._verify(), 0)
        for prefix in ("verification-", "summary-", "audit-"):
            self.assertEqual(len(self._outputs(prefix)), 1, prefix)
        report_path = os.path.join(self.out,
                                   self._outputs("verification-")[0])
        with open(report_path, "r", encoding="utf-8") as handle:
            report = json.load(handle)
        self.assertEqual(report["verdict"]["overall"], "accepted")
        self.assertEqual(amv.inv.schema_validate(
            report, amv.VERIFICATION_SCHEMA), [])
        if os.name == "posix":
            mode = stat.S_IMODE(os.stat(report_path).st_mode)
            self.assertEqual(mode, 0o600)

    def test_not_accepted_exit_3_names_blockers(self):
        self.assertEqual(self._verify(attested=[]), 3)
        report_path = os.path.join(self.out,
                                   self._outputs("verification-")[0])
        with open(report_path, "r", encoding="utf-8") as handle:
            report = json.load(handle)
        self.assertEqual(report["verdict"]["overall"], "not-accepted")
        self.assertEqual(len(report["verdict"]["blockers"]),
                         len(amv.ATTESTATION_ITEMS))

    def test_missing_record_exit_4_no_verdict(self):
        missing = os.path.join(self.tmp.name, "absent.json")
        self.assertEqual(self._verify(record_path=missing), 4)
        report_path = os.path.join(self.out,
                                   self._outputs("verification-")[0])
        with open(report_path, "r", encoding="utf-8") as handle:
            report = json.load(handle)
        self.assertEqual(report["verdict"]["overall"], "no-verdict")
        self.assertEqual(report["checks"], [])

    def test_invalid_exceptions_file_exit_4(self):
        with open(self.exceptions_path, "w", encoding="utf-8") as handle:
            handle.write('[{"check": "nope", "reason": "x"}]')
        self.assertEqual(self._verify(), 4)

    def test_no_writes_outside_output_dir(self):
        before = sorted(os.listdir(self.tmp.name))
        self.assertEqual(self._verify(), 0)
        after = sorted(os.listdir(self.tmp.name))
        self.assertEqual([name for name in after if name not in before],
                         ["out"])


class EndToEndTests(unittest.TestCase):
    """cmd_verify with the REAL collect_evidence over a fixture data dir
    shaped like the pinned v0.18.2 layout."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data_dir = os.path.join(self.tmp.name, ".hermes")
        os.makedirs(os.path.join(self.data_dir, "memories"))
        with open(os.path.join(self.data_dir, "memories", "MEMORY.md"),
                  "w", encoding="utf-8") as handle:
            handle.write("- Operator prefers concise answers.\n")
        with open(os.path.join(self.data_dir, "config.yaml"), "w",
                  encoding="utf-8") as handle:
            handle.write("memory:\n  write_approval: on\n"
                         "skills:\n  write_approval: on\n")
        from _helpers import make_session_db
        make_session_db(os.path.join(self.data_dir, "state.db"))
        self.record_path = os.path.join(self.tmp.name, "record.json")
        with open(self.record_path, "w", encoding="utf-8") as handle:
            json.dump(make_record(
                data_dir=self.data_dir,
                config_path=os.path.join(self.data_dir, "config.yaml")),
                handle)
        self.out = os.path.join(self.tmp.name, "out")

    def _verify(self, attested=ALL_ATTESTS):
        return amv.cmd_verify(
            self.record_path,
            os.path.join(self.tmp.name, "exceptions.json"),
            self.out, list(attested), "operator")

    def test_green_fixture_run_is_accepted(self):
        self.assertEqual(self._verify(), 0)

    def test_canary_in_memory_fails_the_real_run(self):
        with open(os.path.join(self.data_dir, "memories", "MEMORY.md"),
                  "a", encoding="utf-8") as handle:
            handle.write("- key: %s\n" % amv.CANARY_SECRET)
        self.assertEqual(self._verify(), 3)

    def test_run_leaves_fixture_untouched(self):
        snapshot = {}
        for root, _dirs, files in os.walk(self.data_dir):
            for name in files:
                path = os.path.join(root, name)
                snapshot[path] = os.stat(path).st_mtime_ns
        self.assertEqual(self._verify(), 0)
        for path, mtime in snapshot.items():
            self.assertEqual(os.stat(path).st_mtime_ns, mtime, path)


class ReadOnlySurfaceTests(unittest.TestCase):
    """The verifier's device surface must stay read-only by inspection."""

    def setUp(self):
        with open(VERIFIER_SOURCE, "r", encoding="utf-8") as handle:
            self.source = handle.read()

    def test_no_process_execution(self):
        for token in ("subprocess", "os.system", "os.popen", "os.exec",
                      "run_probe"):
            self.assertNotIn(token, self.source, token)

    def test_sqlite_opens_read_only(self):
        for match in re.finditer(r"sqlite3\.connect\(([^)]*)\)",
                                 self.source):
            self.assertIn("uri=True", match.group(1))
        self.assertIn("mode=ro", self.source)

    def test_only_private_report_writes(self):
        # every write goes through the baseline's 0600 writer; no direct
        # writable open() exists in this module
        self.assertNotIn('open(', self.source.replace(
            'open(path, "r"', '').replace('open(uri', ''))
        self.assertIn("_write_private", self.source)

    def test_import_allowlist(self):
        # no subprocess-capable or network module may enter this verifier;
        # with no process spawning and no writable opens, a Hermes
        # invocation is structurally impossible
        import ast
        allowed = {"argparse", "json", "os", "re", "socket", "sqlite3",
                   "sys", "time", "secrets", "typing", "urllib.request",
                   "atlas_hermes_verify", "__future__"}
        imported = set()
        for node in ast.walk(ast.parse(self.source)):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add(node.module or "")
        self.assertEqual(imported - allowed, set())


class SummaryRenderTests(unittest.TestCase):
    def test_summary_lists_attestations_and_exceptions(self):
        results = amv.run_checks(
            make_record(), "record.json", base_bundle(),
            [{"check": "session-store", "reason": "documented"}])
        attestations = amv.build_attestations(ALL_ATTESTS[:3], "op", "t0")
        overall, blockers = amv.ahv.compute_verdict(results, attestations)
        verification = amv.build_verification(
            make_record(), "record.json", True, [],
            "exceptions.json", True, [],
            [{"check": "session-store", "reason": "documented"}],
            results, attestations, overall, blockers, "run1", "t0")
        summary = amv.render_summary(verification)
        self.assertIn("NOT attested", summary)
        self.assertIn("attested by `op`", summary)
        self.assertIn("ATLAS-MEM-006", summary)


if __name__ == "__main__":
    unittest.main()
