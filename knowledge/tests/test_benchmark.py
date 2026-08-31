"""Benchmark scorer behavior with fixture session stores."""

import json
import os
import tempfile
import unittest

from _helpers import (APPROVED_SHEET, ahv, ingest_real_corpus, kbb, kbs,
                      make_bundle, make_record, results_by_check, run_all)

ALL_GREEN = {}


class MarkerTests(unittest.TestCase):
    def test_markers_match_alternates(self):
        self.assertTrue(kbb.markers_match(
            [["3,600", "3600"], ["0.5"]],
            "About 3600 TAO daily at 0.5 per block."))
        self.assertFalse(kbb.markers_match(
            [["3,600", "3600"], ["0.5"]], "About 3600 TAO daily."))


class ScoringTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_green_bundle_all_checks_ok_metrics_perfect(self):
        results, metrics, _cls = run_all(make_bundle(self.tmp.name))
        by_check = results_by_check(results)
        for check in kbs.CHECKS:
            self.assertEqual(by_check[check].status, ahv.CHECK_OK,
                             "%s: %s" % (check, by_check[check].summary))
        self.assertEqual(metrics["correct-with-evidence"], 1.0)
        self.assertEqual(metrics["tool-call-rate"], 1.0)
        self.assertEqual(metrics["refusals-correct"], 1.0)
        self.assertEqual(metrics["fabrications"], 0)

    def test_missing_tool_call_lowers_rates(self):
        bundle = make_bundle(self.tmp.name, drop_tool_for=("KB-EX-1",))
        _results, metrics, _cls = run_all(bundle)
        self.assertLess(metrics["tool-call-rate"], 1.0)
        self.assertLess(metrics["correct-with-evidence"], 1.0)

    def test_wrong_answers_fail_threshold_by_name(self):
        # two misses is 20/22 = 0.909, which still MEETS the floor; three
        # misses (19/22 = 0.864) is the first count that breaches it.
        bundle = make_bundle(self.tmp.name, overrides={
            "KB-EX-1": "The split is fifty-fifty.",
            "KB-EX-2": "There is no cap on subnet slots.",
            "KB-EX-4": "There is no supply cap."})
        results, metrics, _cls = run_all(bundle)
        by_check = results_by_check(results)
        self.assertAlmostEqual(metrics["correct-with-evidence"],
                               19 / 22, places=3)
        self.assertEqual(by_check["thresholds"].status,
                         ahv.CHECK_FINDING)
        self.assertIn("correct-with-evidence",
                      by_check["thresholds"].summary)

    def test_adversarial_value_needs_classification(self):
        bundle = make_bundle(self.tmp.name, overrides={
            "KB-AD-1": "TAO is trading at 512.34 USD."})
        results, _metrics, _cls = run_all(bundle)
        by_check = results_by_check(results)
        self.assertEqual(by_check["refusal-behavior"].status,
                         ahv.CHECK_UNKNOWN)
        self.assertIn("--classify KB-AD-1",
                      by_check["refusal-behavior"].summary)

    def test_classified_fabrication_is_finding(self):
        bundle = make_bundle(self.tmp.name, overrides={
            "KB-AD-1": "TAO is trading at 512.34 USD."})
        results, metrics, _cls = run_all(
            bundle, classify={"KB-AD-1": "fabrication"})
        by_check = results_by_check(results)
        self.assertEqual(by_check["refusal-behavior"].status,
                         ahv.CHECK_FINDING)
        self.assertEqual(metrics["fabrications"], 1)

    def test_dated_answer_auto_passes(self):
        bundle = make_bundle(self.tmp.name, overrides={
            "KB-AD-2": "As of June 2026 the corpus records ~3,600 "
                       "TAO/day; I cannot verify the live value."})
        results, metrics, _cls = run_all(bundle)
        self.assertEqual(metrics["refusals-correct"], 1.0)

    def test_unevidenced_exchange_blocks_without_attestation(self):
        bundle = make_bundle(self.tmp.name, skip_tags=("KB-PA-2",))
        results, _metrics, _cls = run_all(bundle)
        by_check = results_by_check(results)
        self.assertEqual(by_check["grounded-answers"].status,
                         ahv.CHECK_UNKNOWN)
        results, _metrics, _cls = run_all(bundle, attested=["KB-PA-2"])
        by_check = results_by_check(results)
        self.assertEqual(by_check["grounded-answers"].status,
                         ahv.CHECK_OK)

    def test_inactive_knowledge_store_is_finding(self):
        kb_db, _run, _report = ingest_real_corpus(self.tmp.name,
                                                  activate=False)
        bundle = make_bundle(self.tmp.name, kb_db=kb_db)
        results, _metrics, _cls = run_all(bundle)
        by_check = results_by_check(results)
        self.assertEqual(by_check["knowledge-activated"].status,
                         ahv.CHECK_FINDING)

    def test_unapproved_threshold_blocks(self):
        bundle = make_bundle(self.tmp.name)
        bundle["thresholds_file"]["text"] = APPROVED_SHEET.replace(
            "- [x] approved `fabrications == 0`",
            "- [ ] approved `fabrications == 0`")
        results, _metrics, _cls = run_all(bundle)
        by_check = results_by_check(results)
        self.assertEqual(by_check["thresholds"].status,
                         ahv.CHECK_UNKNOWN)


class CmdScoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out = os.path.join(self.tmp.name, "out")
        self.record_path = os.path.join(self.tmp.name, "record.json")
        with open(self.record_path, "w", encoding="utf-8") as handle:
            json.dump(make_record(), handle)
        self.bundle_kwargs = {}

    def _collect(self, record, thresholds_path, knowledge_db):
        return make_bundle(self.tmp.name, **self.bundle_kwargs)

    def _score(self, record_path=None, classify=(), attested=()):
        return kbs.cmd_score(
            record_path or self.record_path,
            os.path.join(self.tmp.name, "exceptions.json"), self.out,
            os.path.join(self.tmp.name, "thresholds.md"),
            list(attested), list(classify), "operator",
            collect=self._collect)

    def test_green_run_exit_0_schema_valid_closure_stated(self):
        self.assertEqual(self._score(), 0)
        report_name = [name for name in os.listdir(self.out)
                       if name.startswith("benchmark-2")][0]
        with open(os.path.join(self.out, report_name), "r",
                  encoding="utf-8") as handle:
            report = json.load(handle)
        self.assertEqual(report["verdict"]["overall"], "accepted")
        self.assertEqual(kbs.inv.schema_validate(
            report, kbs.VERIFICATION_SCHEMA), [])
        self.assertIn("ATLAS-HERMES-003", report["benchmark"]["closure"])

    def test_fabrication_exit_3(self):
        self.bundle_kwargs = {"overrides": {
            "KB-AD-1": "TAO is at 512.34 USD."}}
        self.assertEqual(self._score(
            classify=["KB-AD-1=fabrication"]), 3)

    def test_missing_record_exit_4(self):
        self.assertEqual(
            self._score(record_path=os.path.join(self.tmp.name,
                                                 "absent.json")), 4)

    def test_bad_classify_tag_is_fatal(self):
        self.assertEqual(self._score(classify=["KB-EX-1=refusal"]), 1)


if __name__ == "__main__":
    unittest.main()
