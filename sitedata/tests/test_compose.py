"""Static checks on the raw-row composer (sitedata/compose.py)."""

import json
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SITEDATA = os.path.dirname(HERE)
with open(os.path.join(SITEDATA, "compose.py"), encoding="utf-8") as handle:
    SOURCE = handle.read()


sys.path.insert(0, SITEDATA)
import compose  # noqa: E402


class ComposeTest(unittest.TestCase):
    def test_netuids_follow_registrations_not_a_fixed_count(self):
        # A new subnet registers as netuid 129, then 130: each one joins the
        # list as it appears, root never does, and no count is assumed.
        slots = [{"netuid": n} for n in (0, 2, 1, 129, 128)]
        self.assertEqual(compose.registered_netuids(slots), [1, 2, 128, 129])
        slots.append({"netuid": 130})
        self.assertEqual(compose.registered_netuids(slots)[-2:], [129, 130])
        self.assertNotRegex(SOURCE, r"range\(1, 1[2-6]\d\)")

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
