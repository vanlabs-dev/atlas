"""Pins reused APIs, battery/corpus invariants, generated files."""

import inspect
import json
import os
import unittest

from _helpers import CORPUS_DIR, ahv, akb, ams, kbb, kbs

SCHEMA_FILE = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "benchmark", "schema",
    "atlas-kb-benchmark.v1.schema.json")


def _corpus_text():
    text = ""
    for name in ("ground-truth.md", "fact-patterns.md",
                 "negative-claim-rules.md"):
        with open(os.path.join(CORPUS_DIR, name), "r",
                  encoding="utf-8") as handle:
            text += handle.read().lower()
    return text


class ImportSurfaceTests(unittest.TestCase):
    def test_pinned_reused_apis(self):
        for name in ("load_install_record", "check_install_record",
                     "compute_verdict", "build_audit", "CheckResult",
                     "_resolve", "_read_text", "_scan_for_secrets",
                     "_write_private", "FatalVerificationError"):
            self.assertTrue(hasattr(ahv, name), name)
        for name in ("extract_exchanges", "load_exceptions",
                     "parse_thresholds", "_store_gate", "_tool_rows",
                     "_final_answer"):
            self.assertTrue(hasattr(ams, name), name)

    def test_generalized_signatures_pinned(self):
        # the widened modelval signatures this module depends on
        self.assertIn("battery",
                      inspect.signature(ams.extract_exchanges).parameters)
        self.assertIn("valid_checks",
                      inspect.signature(ams.load_exceptions).parameters)
        import run_battery  # noqa: F401  (from hermes/modelval on path)
        self.assertTrue(callable(run_battery.load_battery_module))
        self.assertIn("battery_mod",
                      inspect.signature(run_battery.run_battery)
                      .parameters)

    def test_check_list_is_fixed(self):
        self.assertEqual(len(kbs.CHECKS), 5)
        check_enum = kbs.VERIFICATION_SCHEMA["properties"]["checks"][
            "items"]["properties"]["check"]["enum"]
        self.assertEqual(set(check_enum), set(kbs.CHECKS))

    def test_battery_invariants(self):
        exchanges = kbb.battery()
        self.assertEqual(len(exchanges), 26)
        tags = [str(exchange["tag"]) for exchange in exchanges]
        self.assertEqual(len(tags), len(set(tags)))
        for exchange in exchanges:
            self.assertIn("[%s]" % exchange["tag"],
                          str(exchange["prompt"]))
        grouped = kbb.tags_by_set()
        self.assertEqual(set(grouped),
                         set(kbb.GROUNDED_SETS) | set(kbb.REFUSAL_SETS))
        grounded = sum(len(grouped[name]) for name in kbb.GROUNDED_SETS)
        refusal = sum(len(grouped[name]) for name in kbb.REFUSAL_SETS)
        self.assertEqual((grounded, refusal), (17, 9))

    def test_expected_markers_pinned_against_corpus(self):
        # every marker group must have at least one alternate present in
        # the corpus snapshot — evidence markers may not drift from the
        # knowledge they are supposed to evidence
        corpus = _corpus_text()
        for exchange in kbb.battery():
            if exchange["set"] in ("exact", "paraphrase", "historical"):
                for group in exchange["expected"]:  # type: ignore[union-attr]
                    self.assertTrue(
                        any(alternate.lower() in corpus
                            for alternate in group),
                        "%s marker group %r not found in corpus"
                        % (exchange["tag"], group))

    def test_corpus_snapshot_hashes_match(self):
        # the recorded hashes must match the snapshot files (load_corpus
        # raises on mismatch)
        corpus = akb.load_corpus()
        self.assertEqual(len(corpus["files"]), 3)

    def test_refusal_fixture_answer_passes_auto_check(self):
        self.assertTrue(kbb.is_honest_refusal(
            "I cannot verify live data right now."))
        self.assertTrue(kbb.is_honest_refusal(
            "As of June 2026 the corpus says ~3,600 TAO/day."))
        self.assertFalse(kbb.is_honest_refusal(
            "TAO is trading at 512 USD."))

    def test_closure_notice_names_both_gates(self):
        self.assertIn("ATLAS-HERMES-003", kbs.CLOSURE_NOTICE)
        self.assertIn("MV-RI-4", kbs.CLOSURE_NOTICE)

    def test_schema_file_matches_embedded(self):
        with open(SCHEMA_FILE, "r", encoding="utf-8") as handle:
            self.assertEqual(json.load(handle), kbs.VERIFICATION_SCHEMA,
                             "regenerate: python atlas_kb_score.py "
                             "dump-schema > schema/...")


if __name__ == "__main__":
    unittest.main()
