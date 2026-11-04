"""Corpus polarity lint (change: kb-battery-honesty, audit A10)."""

import json
import os
import re
import shutil
import tempfile
import unittest

from _helpers import CORPUS_DIR, akb

RULES_FILE = os.path.join(os.path.dirname(CORPUS_DIR), "polarity-rules.json")
_CLAUSE = re.compile(r"[.;:!?](?:\s|$)")


def load_rules(path=RULES_FILE):
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    negation = re.compile(r"(?i)\b(%s)\b" % "|".join(
        re.escape(word) for word in data["negations"]))
    return data["rules"], negation


def violations(files, rules, negation):
    """(rule id, unit id, clause) for each forbidden clause in a fact unit."""
    kinds = akb.load_kinds()
    found = []
    for filename, text in files.items():
        for unit in akb.split_units(filename, text):
            if akb.kind_for(unit["heading_path"], kinds) != "fact":
                continue
            content = unit["content"].replace("\n", " ")
            for rule in rules:
                if not re.search(rule["subject"], content):
                    continue
                for clause in _CLAUSE.split(content):
                    match = re.search(rule["forbidden"], clause)
                    if match and not negation.search(clause[:match.end()]):
                        found.append((rule["id"], unit["unit_id"],
                                      clause.strip()[:120]))
    return found


def corpus_files(directory=CORPUS_DIR):
    names = ("ground-truth.md", "fact-patterns.md", "negative-claim-rules.md")
    files = {}
    for name in names:
        with open(os.path.join(directory, name), "r", encoding="utf-8") as h:
            files[name] = h.read()
    return files


class PolarityLintTests(unittest.TestCase):
    def test_rules_are_well_formed(self):
        rules, _ = load_rules()
        self.assertGreaterEqual(len(rules), 5)
        for rule in rules:
            for key in ("id", "subject", "forbidden", "source"):
                self.assertTrue(rule.get(key), (rule.get("id"), key))
            re.compile(rule["subject"])
            re.compile(rule["forbidden"])

    def test_corpus_has_no_refuted_claim(self):
        rules, negation = load_rules()
        self.assertEqual(violations(corpus_files(), rules, negation), [])

    def test_pre_wp13_lock_wording_fails(self):
        files = corpus_files()
        text = files["ground-truth.md"]
        fixed = ("None of the TAO paid to create the subnet is recycled or "
                 "burned")
        self.assertIn(fixed, text)
        files["ground-truth.md"] = text.replace(
            fixed, "This TAO is recycled, not destroyed. Nothing")
        rules, negation = load_rules()
        found = violations(files, rules, negation)
        self.assertIn("subnet-lock-not-recycled", {f[0] for f in found})

    def test_negated_clause_passes(self):
        rules, negation = load_rules()
        files = {"x.md": "## S\n\n- Creating a subnet costs TAO. The TAO is "
                         "not recycled.\n"}
        self.assertEqual(violations(files, rules, negation), [])

    def test_correction_units_are_exempt(self):
        rules, negation = load_rules()
        files = {"x.md": "## Common Mistakes to Avoid\n\n- \"Staking: the "
                         "TAO is burned\" --> WRONG.\n"}
        self.assertEqual(violations(files, rules, negation), [])

    def test_conviction_half_life_wording_fails(self):
        rules, negation = load_rules()
        files = {"x.md": "## C\n\n- The time constant (MaturityRate) is "
                         "currently a 90-day half-life.\n"}
        found = violations(files, rules, negation)
        self.assertEqual([f[0] for f in found],
                         ["conviction-rate-is-a-time-constant"])


if __name__ == "__main__":
    unittest.main()
