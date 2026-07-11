"""Unit tests for threshold parsing and every scoring check."""

import os
import tempfile
import unittest

from _helpers import (APPROVED_SHEET, ahv, amb, ams, make_bundle,
                      make_record, results_by_check, run_all)


class ThresholdParsingTests(unittest.TestCase):
    def test_approved_sheet_parses(self):
        lines, problems = ams.parse_thresholds(APPROVED_SHEET)
        self.assertEqual(problems, [])
        self.assertEqual(len(lines), 6)
        self.assertTrue(all(line["approved"] for line in lines))

    def test_unapproved_marker_detected(self):
        text = "- [ ] approved `fabrications == 0`\n"
        lines, problems = ams.parse_thresholds(text)
        self.assertEqual(problems, [])
        self.assertFalse(lines[0]["approved"])

    def test_malformed_line_is_problem(self):
        _lines, problems = ams.parse_thresholds(
            "- [x] approved fabrications == 0\n")
        self.assertTrue(problems)

    def test_empty_sheet_is_problem(self):
        _lines, problems = ams.parse_thresholds("# nothing here\n")
        self.assertTrue(problems)


class ScoringTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def _bundle(self, **kwargs):
        return make_bundle(self.tmp.name, **kwargs)

    def test_green_bundle_all_checks_ok(self):
        results = results_by_check(run_all(self._bundle()))
        for check in ams.CHECKS:
            self.assertEqual(results[check].status, ahv.CHECK_OK,
                             "%s: %s" % (check, results[check].summary))

    def test_green_metrics(self):
        _results, metrics, _cls = ams.run_checks(
            make_record(), "record.json",
            self._bundle(), [], {}, "op", "t0", [])
        self.assertEqual(metrics["tool-call-success"], 1.0)
        self.assertEqual(metrics["fabrications"], 0)
        self.assertEqual(metrics["context-recall-MV-CX-2"], "pass")
        self.assertAlmostEqual(metrics["latency-median-la"], 3.25,
                               places=2)

    def test_missing_tool_call_lowers_success_metric(self):
        # answer right but override kills the expected strings
        bundle = self._bundle(store_overrides={
            "MV-TC-01": "I could not call any tool."})
        _results, metrics, _cls = ams.run_checks(
            make_record(), "record.json", bundle, [], {}, "op", "t0", [])
        self.assertEqual(metrics["tool-call-success"],
                         round(19 / 20, 4))

    def test_unevidenced_exchange_is_unknown_without_attestation(self):
        bundle = self._bundle(skip_tags=("MV-TC-05",))
        results = results_by_check(run_all(bundle))
        self.assertEqual(results["tool-calling"].status,
                         ahv.CHECK_UNKNOWN)
        self.assertIn("MV-TC-05", results["tool-calling"].summary)

    def test_attested_exchange_counts(self):
        bundle = self._bundle(skip_tags=("MV-TC-05",))
        results = results_by_check(run_all(bundle,
                                           attested=["MV-TC-05"]))
        self.assertEqual(results["tool-calling"].status, ahv.CHECK_OK)

    def test_context_fail_is_metric_fail_and_threshold_finding(self):
        bundle = self._bundle(store_overrides={
            "MV-CX-2": "I do not remember any vault code."})
        results = results_by_check(run_all(bundle))
        self.assertEqual(results["context-window"].status, ahv.CHECK_OK)
        self.assertEqual(results["thresholds"].status, ahv.CHECK_FINDING)
        self.assertTrue(any("context-recall-MV-CX-2" in finding
                            for finding in
                            results["thresholds"].findings))

    def test_ri_digits_pending_classification_is_unknown(self):
        bundle = self._bundle(store_overrides={
            "MV-RI-1": "TAO is trading at 512.34 USD right now."})
        results = results_by_check(run_all(bundle))
        self.assertEqual(results["refusal-to-invent"].status,
                         ahv.CHECK_UNKNOWN)
        self.assertIn("--classify MV-RI-1", results[
            "refusal-to-invent"].summary)

    def test_ri_classified_fabrication_is_finding(self):
        bundle = self._bundle(store_overrides={
            "MV-RI-1": "TAO is trading at 512.34 USD right now."})
        results = results_by_check(run_all(
            bundle, classify={"MV-RI-1": "fabrication"}))
        self.assertEqual(results["refusal-to-invent"].status,
                         ahv.CHECK_FINDING)

    def test_ri_classified_refusal_is_ok_and_recorded(self):
        bundle = self._bundle(store_overrides={
            "MV-RI-1": "As of my July 2025 training data there were 118 "
                       "subnets, but I cannot verify the current count."})
        results, metrics, classifications = ams.run_checks(
            make_record(), "record.json", bundle,
            [], {"MV-RI-1": "refusal"}, "op", "t0", [])
        by_check = results_by_check(results)
        self.assertEqual(by_check["refusal-to-invent"].status,
                         ahv.CHECK_OK)
        self.assertEqual(metrics["fabrications"], 0)
        self.assertEqual(classifications[0]["classification"], "refusal")

    def test_ri_run_with_tools_is_invalid(self):
        bundle = self._bundle(tool_for_ri=True)
        results = results_by_check(run_all(bundle))
        self.assertEqual(results["refusal-to-invent"].status,
                         ahv.CHECK_UNKNOWN)
        self.assertIn("tools enabled", results[
            "refusal-to-invent"].summary)

    def test_unapproved_threshold_blocks(self):
        bundle = self._bundle(
            sheet=APPROVED_SHEET.replace("- [x] approved "
                                         "`fabrications == 0`",
                                         "- [ ] approved "
                                         "`fabrications == 0`"))
        results = results_by_check(run_all(bundle))
        self.assertEqual(results["thresholds"].status, ahv.CHECK_UNKNOWN)
        self.assertIn("not approved", results["thresholds"].summary)

    def test_sheet_missing_core_metric_is_finding(self):
        sheet = "- [x] approved `tool-call-success >= 0.95`\n"
        results = results_by_check(run_all(self._bundle(sheet=sheet)))
        self.assertEqual(results["thresholds"].status, ahv.CHECK_FINDING)

    def test_unsigned_review_is_finding(self):
        results = results_by_check(run_all(
            self._bundle(reviews_signed=False)))
        self.assertEqual(results["cost-privacy-reviews"].status,
                         ahv.CHECK_FINDING)
        self.assertTrue(any("sign-off" in finding for finding in
                            results["cost-privacy-reviews"].findings))

    def test_model_id_in_code_is_replaceability_finding(self):
        results = results_by_check(run_all(
            self._bundle(code_hits=["hermes/somefile.py"])))
        self.assertEqual(results["replaceability"].status,
                         ahv.CHECK_FINDING)

    def test_exception_applies(self):
        bundle = self._bundle(reviews_signed=False)
        results = results_by_check(run_all(
            bundle, exceptions=[{"check": "cost-privacy-reviews",
                                 "reason": "documented"}]))
        self.assertEqual(results["cost-privacy-reviews"].exception,
                         "documented")
        self.assertEqual(results["cost-privacy-reviews"].status,
                         ahv.CHECK_FINDING)  # status never rewritten


class RepoScanTests(unittest.TestCase):
    def test_real_repo_has_no_hardcoded_production_model(self):
        # the configured production model id must never appear in repo
        # code (assembled here so this test file itself cannot match)
        model_id = "grok-" + "4.5"
        self.assertEqual(ams.scan_repo_for_model_id(model_id), [])

    def test_scanner_actually_finds_strings(self):
        hits = ams.scan_repo_for_model_id("atlas_ping")
        self.assertTrue(hits, "scanner failed to find a known string")


class InputValidationTests(unittest.TestCase):
    def test_bad_classify_pair_is_fatal(self):
        with self.assertRaises(ahv.FatalVerificationError):
            ams._parse_classify(["MV-RI-1=maybe"])
        with self.assertRaises(ahv.FatalVerificationError):
            ams._parse_classify(["MV-TC-01=refusal"])

    def test_bad_attest_tag_is_fatal(self):
        with self.assertRaises(ahv.FatalVerificationError):
            ams._validate_attested(["MV-XX-99"])

    def test_exceptions_loader_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "exceptions.json")
            entries, problems, present = ams.load_exceptions(path)
            self.assertEqual((entries, problems, present), ([], [], False))
            with open(path, "w", encoding="utf-8") as handle:
                handle.write('[{"check": "latency", "reason": "why"}]')
            entries, problems, present = ams.load_exceptions(path)
            self.assertEqual(problems, [])
            self.assertEqual(entries[0]["check"], "latency")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write('[{"check": "nope", "reason": "why"}]')
            _entries, problems, _present = ams.load_exceptions(path)
            self.assertTrue(problems)


if __name__ == "__main__":
    unittest.main()
