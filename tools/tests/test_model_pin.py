"""Every Atlas `claude -p` call pins one model (change: chain-grounding).

`--restricted` makes claude ignore the user, project and local settings
files, so a model set in ~/.claude/settings.json never applies. On
2026-11-27 the grounding runs fell back to the account default model and
hit its usage limit. Every caller now passes `--model` from
tools/claude-model.json. The id lives in config, not code: the
model-validation scan flags code that names the Hermes model id.
"""

import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "hermes"))
sys.path.insert(0, os.path.join(ROOT, "hermes", "modelval"))
sys.path.insert(0, os.path.join(ROOT, "upgrade"))

import atlas_oneshot  # noqa: E402
import atlas_upgrade  # noqa: E402
import atlas_modelval_score  # noqa: E402

with open(os.path.join(ROOT, "tools", "claude-model.json")) as _handle:
    PINNED = json.load(_handle)["model"]


class ModelPinTest(unittest.TestCase):
    def test_operator_choice_is_opus_5_5(self):
        # Operator decision 2026-11-27: every call uses Opus 5.5.
        self.assertEqual(PINNED, "claude-opus-5-5")

    def test_every_caller_reads_the_one_file(self):
        self.assertEqual(atlas_oneshot.pinned_model(), PINNED)
        self.assertEqual(atlas_upgrade.MODEL, PINNED)
        argv = atlas_oneshot.oneshot_argv("claude", "sys")
        self.assertEqual(argv[argv.index("--model") + 1], PINNED)
        with open(os.path.join(ROOT, "grounding", "config.json")) as handle:
            self.assertNotIn("model", json.load(handle))

    def test_upgrade_calls_carry_the_model(self):
        with open(os.path.join(ROOT, "upgrade", "atlas_upgrade.py")) as h:
            source = h.read()
        self.assertEqual(source.count('"--model", MODEL'), 2)
        self.assertEqual(source.count('self.claude, "-p"'), 2)

    def test_no_code_hard_codes_the_model_id(self):
        self.assertEqual(atlas_modelval_score.scan_repo_for_model_id(PINNED),
                         [])

    def test_missing_model_fails_closed(self):
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".json",
                                         delete=False) as handle:
            handle.write("{}")
        self.addCleanup(os.unlink, handle.name)
        with self.assertRaises(ValueError):
            atlas_oneshot.pinned_model(handle.name)


if __name__ == "__main__":
    unittest.main()
