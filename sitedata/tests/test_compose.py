"""Static checks on the raw-row composer (sitedata/compose.py)."""

import json
import os
import re
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SITEDATA = os.path.dirname(HERE)
with open(os.path.join(SITEDATA, "compose.py"), encoding="utf-8") as handle:
    SOURCE = handle.read()


class ComposeTest(unittest.TestCase):
    def test_no_age_cutoff(self):
        # The latest stored pass of each input, never an age window
        # (change: subnt-site-honesty).
        self.assertIsNone(re.search(r"cutoff|AGE_DAYS|<= \?", SOURCE))
        self.assertIn("latest_feasibility", SOURCE)

    def test_bot_authors_and_post_pass_commits_drop(self):
        self.assertIn("is_bot_author(email, bots) or when > anchor", SOURCE)
        self.assertIn("metrics.activity_commit_log(f, cfg, nid, passes[nid]",
                      SOURCE)
        self.assertNotIn('--format=%cI"', SOURCE)

    def test_fleet_board_is_stamped_with_its_pass(self):
        self.assertIn("fleet_at = max(passes.values())", SOURCE)
        self.assertIn('"fleet_at": fleet_at', SOURCE)

    def test_shadow_signals_stay_on_the_pi(self):
        self.assertIn("tier != 'shadow'", SOURCE)

    def test_stores_open_read_only(self):
        connects = re.findall(r"sqlite3\.connect\(([^)]*)\)", SOURCE)
        self.assertEqual(connects, ['"file:%s?mode=ro" % path, uri=True'])

    def test_signal_classes_come_from_the_allowlist(self):
        with open(os.path.join(SITEDATA, "allowlist.json"),
                  encoding="utf-8") as handle:
            classes = json.load(handle)["signal_classes"]
        self.assertEqual(sorted(classes),
                         ["econ-code", "narrative-cluster", "signal-digest"])


if __name__ == "__main__":
    unittest.main()
