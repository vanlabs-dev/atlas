"""Pins reused APIs, battery invariants, and generated-file freshness."""

import json
import os
import unittest

from _helpers import ahv, amb, ams, amv, inv

_MODULE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEMA_FILE = os.path.join(_MODULE_DIR, "schema",
                           "atlas-modelval-verification.v1.schema.json")
BATTERY_MD = os.path.join(_MODULE_DIR, "battery.md")
TESTTOOL = os.path.join(os.path.dirname(_MODULE_DIR), "testtool",
                        "atlas_test_tool.py")


class ImportSurfaceTests(unittest.TestCase):
    def test_pinned_reused_apis(self):
        for name in ("load_install_record", "check_install_record",
                     "compute_verdict", "build_audit", "CheckResult",
                     "_resolve", "_read_text", "_write_private",
                     "_utc_now", "_account", "_redact_tree",
                     "FatalVerificationError"):
            self.assertTrue(hasattr(ahv, name), name)
        self.assertTrue(callable(amv.parse_config_scalars))
        self.assertEqual(amv.SESSION_DB_NAME, "state.db")
        self.assertTrue(callable(inv.redact))
        self.assertTrue(callable(inv.schema_validate))

    def test_check_list_is_fixed(self):
        self.assertEqual(len(ams.CHECKS), 8)
        check_enum = ams.VERIFICATION_SCHEMA["properties"]["checks"][
            "items"]["properties"]["check"]["enum"]
        self.assertEqual(set(check_enum), set(ams.CHECKS))

    def test_battery_invariants(self):
        exchanges = amb.battery()
        self.assertEqual(len(exchanges), 35)
        tags = [exchange["tag"] for exchange in exchanges]
        self.assertEqual(len(tags), len(set(tags)), "tags must be unique")
        for exchange in exchanges:
            self.assertIn("[%s]" % exchange["tag"], exchange["prompt"],
                          "tag must be embedded in the prompt")
        grouped = amb.tags_by_set()
        self.assertEqual(len(grouped["tool-calling"]), amb.TC_COUNT)
        self.assertEqual(len(grouped["context-window"]), 3)
        self.assertEqual(len(grouped["refusal-to-invent"]), 6)
        self.assertEqual(len(grouped["latency"]), 6)

    def test_tool_expectations_match_testtool_source(self):
        # the battery's expected strings must be the test tool's actual
        # static identity — drift must fail here, not on the Pi
        with open(TESTTOOL, "r", encoding="utf-8") as handle:
            source = handle.read()
        for expected in amb.TOOL_EXPECTED_STRINGS:
            self.assertIn('"%s"' % expected, source, expected)
        self.assertIn('TOOL_NAME = "%s"' % amb.TOOL_NAME, source)

    def test_cx_prompts_plant_code_exactly_once(self):
        for probe in amb.CX_PROBES:
            prompt = amb._cx_prompt(str(probe["tag"]),
                                    int(probe["chars"]),
                                    str(probe["code"]))
            self.assertEqual(prompt.count(str(probe["code"])), 1)
            self.assertAlmostEqual(len(prompt), int(probe["chars"]),
                                   delta=200)

    def test_ri_green_answers_have_no_digits(self):
        # the fixture refusal answer must not trip the digit flag
        from _helpers import green_answer
        for exchange in amb.battery():
            if exchange["set"] == "refusal-to-invent":
                self.assertNotRegex(green_answer(exchange), r"\d")

    def test_schema_file_matches_embedded(self):
        with open(SCHEMA_FILE, "r", encoding="utf-8") as handle:
            self.assertEqual(json.load(handle), ams.VERIFICATION_SCHEMA,
                             "regenerate: python atlas_modelval_score.py "
                             "dump-schema > schema/...")

    def test_battery_md_matches_generated(self):
        with open(BATTERY_MD, "r", encoding="utf-8") as handle:
            self.assertEqual(handle.read(),
                             amb.render_markdown() + "\n",
                             "regenerate: python atlas_modelval_score.py "
                             "dump-battery > battery.md")

    def test_deferral_notice_names_phase_2(self):
        self.assertIn("DEFERRED to Phase 2", ams.DEFERRAL_NOTICE)
        self.assertIn("retrieval", ams.DEFERRAL_NOTICE.lower())


if __name__ == "__main__":
    unittest.main()
