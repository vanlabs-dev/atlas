"""Pins the voice battery's shape and its mechanical next-action check.

The chat side of the next-action rule used to be judged by eye, one
generation at a time. These tests pin the predicate that replaced that,
and the replicate scheme that makes a rate measurable.
"""

import importlib.util
import os
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_SOURCE = os.path.join(os.path.dirname(_HERE), "atlas_voice_battery.py")

_spec = importlib.util.spec_from_file_location("atlas_voice_battery", _SOURCE)
avb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(avb)


class BatteryShapeTests(unittest.TestCase):
    def test_tags_are_unique(self):
        tags = [exchange["tag"] for exchange in avb.battery()]
        self.assertEqual(len(tags), len(set(tags)))

    def test_every_probe_runs_in_replicate_under_distinct_tags(self):
        # extract_exchanges() keeps only the latest session per tag, so
        # replicates sharing a tag would collapse to a single sample.
        probes = [exchange["tag"] for exchange in avb.battery()
                  if exchange["set"] == "voice-probe"]
        for base in ("MV-VP-1", "MV-VP-2", "MV-VP-3", "MV-VP-4"):
            replicates = [tag for tag in probes
                          if avb.base_tag(tag) == base]
            self.assertEqual(len(replicates), avb.REPLICATES)
            self.assertEqual(len(set(replicates)), avb.REPLICATES)

    def test_tag_is_embedded_in_every_prompt(self):
        for exchange in avb.battery():
            self.assertIn("[%s]" % exchange["tag"], exchange["prompt"])

    def test_both_arms_of_the_next_action_rule_are_probed(self):
        # A battery with only the presence arm scores a model that
        # appends a boilerplate action to every message at 100%.
        expectations = " ".join(
            str(exchange["expected"]) for exchange in avb.battery()
            if exchange["set"] == "voice-probe")
        self.assertIn("next-action presence", expectations)
        self.assertIn("next-action absence", expectations)

    def test_adversarial_set_is_carried_through(self):
        sets = avb.tags_by_set()
        self.assertTrue(sets["adversarial"])
        self.assertTrue(all(tag.startswith("KB-AD")
                            for tag in sets["adversarial"]))


class NextActionPredicateTests(unittest.TestCase):
    def test_closing_next_action_passes(self):
        self.assertTrue(avb.closes_with_next_action(
            "Emission collapses toward zero.\n\n"
            "The gate is a Hill function.\n"
            "next: read live demand share against the bar"))

    def test_trailing_source_line_fails(self):
        # The exact shape that failed 12 of 15 runs on the old canon.
        self.assertFalse(avb.closes_with_next_action(
            "Emission collapses toward zero.\n"
            "next: read live demand share against the bar\n"
            "Source: ground-truth.md, coverage 2026-08-06, confirmed."))

    def test_missing_next_action_fails(self):
        self.assertFalse(avb.closes_with_next_action(
            "Emission collapses toward zero.\n"
            "Source: ground-truth.md, coverage 2026-08-06."))

    def test_two_next_actions_fail(self):
        self.assertFalse(avb.closes_with_next_action(
            "Verdict.\nnext: read the bar\nnext: read the exponent"))

    def test_markdown_emphasis_and_bullets_are_normalised(self):
        self.assertTrue(avb.closes_with_next_action(
            "Verdict.\n- **next:** read the bar"))

    def test_capitalised_next_is_accepted(self):
        self.assertTrue(avb.closes_with_next_action(
            "Verdict.\nNext: read the bar"))

    def test_bare_next_without_an_action_is_not_a_next_action(self):
        self.assertFalse(avb.closes_with_next_action("Verdict.\nnext:"))

    def test_empty_answer_fails(self):
        self.assertFalse(avb.closes_with_next_action(""))
        self.assertFalse(avb.closes_with_next_action("   \n\n  "))

    def test_omission_arm(self):
        self.assertTrue(avb.omits_next_action(
            "The split is 18% owner, 41% miners, 41% validators.\n"
            "Source: ground-truth.md, coverage 2026-08-06."))
        self.assertFalse(avb.omits_next_action(
            "The split is fixed.\nnext: read the live tempo"))

    def test_omission_arm_catches_a_next_action_anywhere(self):
        self.assertFalse(avb.omits_next_action(
            "The split is fixed.\nnext: read the live tempo\nSource: x."))


if __name__ == "__main__":
    unittest.main()
