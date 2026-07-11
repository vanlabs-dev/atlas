"""Full-run behavior: verdicts, exit codes, outputs, read-only surface."""

import ast
import json
import os
import re
import stat
import tempfile
import unittest

from _helpers import (SCORER_SOURCE, ams, make_bundle, make_record)


class CmdScoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out = os.path.join(self.tmp.name, "out")
        self.record_path = os.path.join(self.tmp.name, "record.json")
        with open(self.record_path, "w", encoding="utf-8") as handle:
            json.dump(make_record(), handle)
        self.exceptions_path = os.path.join(self.tmp.name,
                                            "exceptions.json")
        self.thresholds_path = os.path.join(self.tmp.name, "t.md")
        self.bundle_kwargs = {}

    def _collect(self, record, thresholds_path):
        return make_bundle(self.tmp.name, **self.bundle_kwargs)

    def _score(self, record_path=None, attested=(), classify=()):
        return ams.cmd_score(
            record_path or self.record_path, self.exceptions_path,
            self.out, self.thresholds_path, list(attested),
            list(classify), "operator", collect=self._collect)

    def _outputs(self, prefix):
        return sorted(name for name in os.listdir(self.out)
                      if name.startswith(prefix))

    def _report(self):
        path = os.path.join(self.out, self._outputs("verification-")[0])
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle), path

    def test_green_run_exit_0_schema_valid(self):
        self.assertEqual(self._score(), 0)
        report, path = self._report()
        self.assertEqual(report["verdict"]["overall"], "accepted")
        self.assertEqual(ams.inv.schema_validate(
            report, ams.VERIFICATION_SCHEMA), [])
        self.assertIn("DEFERRED to Phase 2",
                      report["battery"]["deferral"])
        self.assertEqual(report["battery"]["model_id"],
                         "fixture-model-9000")
        for prefix in ("verification-", "summary-", "audit-"):
            self.assertEqual(len(self._outputs(prefix)), 1, prefix)
        if os.name == "posix":
            mode = stat.S_IMODE(os.stat(path).st_mode)
            self.assertEqual(mode, 0o600)

    def test_metric_failure_exit_3_names_threshold(self):
        self.bundle_kwargs = {"store_overrides": {
            "MV-CX-2": "no idea about any code"}}
        self.assertEqual(self._score(), 3)
        report, _path = self._report()
        self.assertTrue(any("context-recall-MV-CX-2" in blocker
                            for blocker in
                            report["verdict"]["blockers"]))

    def test_unsigned_reviews_exit_3(self):
        self.bundle_kwargs = {"reviews_signed": False}
        self.assertEqual(self._score(), 3)

    def test_pending_classification_blocks_with_guidance(self):
        self.bundle_kwargs = {"store_overrides": {
            "MV-RI-3": "The latest block is 4200000."}}
        self.assertEqual(self._score(), 3)
        report, _path = self._report()
        self.assertTrue(any("--classify MV-RI-3" in blocker
                            for blocker in
                            report["verdict"]["blockers"]))
        self.assertEqual(report["classifications"][0]["classification"],
                         "pending")

    def test_classified_fabrication_exit_3(self):
        self.bundle_kwargs = {"store_overrides": {
            "MV-RI-3": "The latest block is 4200000."}}
        self.assertEqual(self._score(classify=["MV-RI-3=fabrication"]), 3)

    def test_classified_refusal_is_accepted(self):
        self.bundle_kwargs = {"store_overrides": {
            "MV-RI-3": "Historically around block 3 million in 2025; I "
                       "cannot verify the current number."}}
        self.assertEqual(self._score(classify=["MV-RI-3=refusal"]), 0)

    def test_missing_record_exit_4(self):
        missing = os.path.join(self.tmp.name, "absent.json")
        self.assertEqual(self._score(record_path=missing), 4)
        report, _path = self._report()
        self.assertEqual(report["verdict"]["overall"], "no-verdict")

    def test_invalid_exceptions_exit_4(self):
        with open(self.exceptions_path, "w", encoding="utf-8") as handle:
            handle.write('[{"check": "bogus", "reason": "x"}]')
        self.assertEqual(self._score(), 4)

    def test_summary_carries_deferral_and_metrics(self):
        self.assertEqual(self._score(), 0)
        summary_path = os.path.join(self.out, self._outputs("summary-")[0])
        with open(summary_path, "r", encoding="utf-8") as handle:
            summary = handle.read()
        self.assertIn("DEFERRED to Phase 2", summary)
        self.assertIn("tool-call-success", summary)
        self.assertIn("fixture-model-9000", summary)


class ReadOnlySurfaceTests(unittest.TestCase):
    def setUp(self):
        with open(SCORER_SOURCE, "r", encoding="utf-8") as handle:
            self.source = handle.read()

    def test_import_allowlist(self):
        # the SCORER must not be able to spawn processes or reach the
        # network; run_battery.py is the separate, operator-invoked file
        allowed = {"argparse", "json", "os", "re", "socket", "sqlite3",
                   "statistics", "sys", "time", "secrets", "typing",
                   "urllib.request", "atlas_hermes_verify",
                   "atlas_memory_verify", "atlas_modelval_battery",
                   "__future__"}
        imported = set()
        for node in ast.walk(ast.parse(self.source)):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add(node.module or "")
        self.assertEqual(imported - allowed, set())
        self.assertNotIn("subprocess", imported)

    def test_sqlite_opens_read_only(self):
        for match in re.finditer(r"sqlite3\.connect\(([^)]*)\)",
                                 self.source):
            self.assertIn("uri=True", match.group(1))
        self.assertIn("mode=ro", self.source)

    def test_only_private_report_writes(self):
        stripped = self.source.replace('open(path, "r"', "")
        self.assertNotIn('open(', re.sub(r'_read_text\([^)]*\)', '',
                                         stripped))
        self.assertIn("_write_private", self.source)


class BatteryPurityTests(unittest.TestCase):
    def test_battery_module_is_pure(self):
        from _helpers import BATTERY_SOURCE
        with open(BATTERY_SOURCE, "r", encoding="utf-8") as handle:
            source = handle.read()
        imported = set()
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add(node.module or "")
        self.assertEqual(imported - {"typing", "__future__"}, set(),
                         "battery must stay pure data + pure functions")


if __name__ == "__main__":
    unittest.main()
