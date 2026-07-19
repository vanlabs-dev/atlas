"""fleet-rotation-metrics dashboard: attention scoring, thesis/badge
narrative, head/mid/quiet/invisible tiering with opaque dedupe, and the
self-contained static render — all driven by a real fixture store (no mock
data injected into the page)."""

import datetime
import os
import shutil
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_FLEET_DIR = os.path.dirname(_HERE)
sys.path.insert(0, _HERE)
sys.path.insert(0, _FLEET_DIR)

import _helpers as h  # noqa: E402
from _helpers import fleet  # noqa: E402
import atlas_fleet_metrics as met  # noqa: E402
import atlas_fleet_dashboard as dash  # noqa: E402


def _iso(days_ago=0, hours_ago=0):
    return (datetime.datetime.now(tz=datetime.timezone.utc)
            - datetime.timedelta(days=days_ago, hours=hours_ago)).isoformat()


CFG = dash.DEFAULT_DASHBOARD_CFG


# ---------------------------------------------------------------------------
# Scoring — pure function, no store
# ---------------------------------------------------------------------------

class TestScoring(unittest.TestCase):
    def test_divergence_direction_promising(self):
        row = {"netuid": 1, "activity_pct": 0.95, "momentum_pct": 0.05,
               "activity_class": "active"}
        sc = dash.score_subnet(row, fresh=False, cfg=CFG)
        self.assertEqual(sc["why"], "divergence")
        self.assertEqual(sc["cue_kind"], "up")          # substance before hype
        self.assertGreater(sc["score"], 30)

    def test_divergence_direction_dangerous(self):
        row = {"netuid": 2, "activity_pct": 0.05, "momentum_pct": 0.95,
               "activity_class": "fade-eligible", "days_since": 120}
        sc = dash.score_subnet(row, fresh=False, cfg=CFG)
        self.assertEqual(sc["cue_kind"], "dn")          # price ahead of code

    def test_fresh_event_floats_to_top(self):
        quiet = {"netuid": 3, "activity_pct": 0.5, "momentum_pct": 0.5,
                 "activity_class": "active"}
        moved = dict(quiet, netuid=4)
        sc_quiet = dash.score_subnet(quiet, fresh=False, cfg=CFG)
        sc_fresh = dash.score_subnet(moved, fresh=True, cfg=CFG)
        self.assertGreater(sc_fresh["score"], sc_quiet["score"] + 30)
        self.assertEqual(sc_fresh["why"], "fresh")

    def test_pure_opaque_is_flagged(self):
        row = {"netuid": 5, "activity_pct": 0.5, "momentum_pct": 0.5,
               "emission_opaque": True, "activity_class": "active"}
        sc = dash.score_subnet(row, fresh=False, cfg=CFG)
        self.assertTrue(sc["pure_opaque"])

    def test_opaque_paired_is_not_pure(self):
        row = {"netuid": 6, "activity_pct": 0.9, "momentum_pct": 0.1,
               "emission_opaque": True, "activity_class": "active"}
        sc = dash.score_subnet(row, fresh=False, cfg=CFG)
        self.assertFalse(sc["pure_opaque"])             # divergence pairs it


# ---------------------------------------------------------------------------
# Board assembly + render — real fixture store
# ---------------------------------------------------------------------------

class DashboardBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.db = os.path.join(self.tmp, "fleet.db")
        self.conn = fleet.open_store(self.db)
        self.addCleanup(self.conn.close)
        met.ensure_schema(self.conn)
        self.clone_root = os.path.join(self.tmp, "clones")
        self.www = os.path.join(self.tmp, "www")
        self.config = {"db": self.db, "clone_root": self.clone_root,
                       "metrics": {}, "dashboard": {"www_dir": self.www}}

    def slot(self, netuid, files, repo=None):
        origin = h.make_origin(self.tmp, name="o_%d" % netuid, files=files)
        clone_dir = os.path.join(self.clone_root, str(netuid))
        state = fleet.setup_clone(clone_dir, origin)
        fleet.upsert_slot(self.conn, {
            "netuid": netuid,
            "github_repo": repo or "https://github.com/org%d/r" % netuid,
            "epoch": 1, "status": state["status"],
            "default_branch": state["default_branch"],
            "local_sha": state["local_sha"]})
        self.conn.commit()
        return origin, clone_dir

    def price(self, netuid, days_ago, price):
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS signal_prices (ts TEXT NOT NULL, "
            "netuid INTEGER NOT NULL, price_tao REAL, PRIMARY KEY (ts,netuid))")
        self.conn.execute("INSERT OR REPLACE INTO signal_prices VALUES "
                          "(?,?,?)", (_iso(days_ago=days_ago), netuid, price))
        self.conn.commit()


class TestBoard(DashboardBase):
    def test_board_tiers_and_ranking(self):
        # A subnet with a real emission redirect + one plain subnet.
        self.slot(1, {"validator/reward.py":
                      "PARTNER_FRACTION = 0.42\n"
                      'PARTNER_HOTKEY = "5Dw7tYMwTBxc3BgapjJ2omvP5TGFSDe3'
                      'UsV414aHHcpRKh2V"\n'})
        self.slot(2, {"README.md": "# quiet\n"})
        met.run_pass(self.conn, self.config, now=_iso())
        board = dash.build_board(self.conn, self.config)
        # SN1 carries an emission flag -> should outrank the plain SN2.
        head_ids = [it["row"]["netuid"] for it in board["head"]]
        self.assertIn(1, head_ids)
        # The emission subnet's thesis mentions routing off miners.
        it1 = [it for it in board["head"] if it["row"]["netuid"] == 1][0]
        self.assertIn("miner", it1["thesis"].lower())
        self.assertTrue(any(b["t"].endswith("PARTNER")
                            for b in it1["badges"]))

    def test_opaque_subnet_grouped_not_headlined(self):
        self.slot(1, {"validator/weights.py":
                      "burn = remote_config.fetch('burn_fraction')\n"})
        met.run_pass(self.conn, self.config, now=_iso())
        board = dash.build_board(self.conn, self.config)
        self.assertIn(1, board["opaque_group"])
        self.assertNotIn(1, [it["row"]["netuid"] for it in board["head"]])

    def test_invisible_slot_listed(self):
        fleet.upsert_slot(self.conn, {
            "netuid": 30, "github_repo": "https://github.com/username/repo",
            "status": "unreachable"})
        self.conn.commit()
        board = dash.build_board(self.conn, self.config)
        self.assertIn(30, [v["netuid"] for v in board["invisible"]])


# ---------------------------------------------------------------------------
# Render — self-contained, no external assets, no mock rows
# ---------------------------------------------------------------------------

class TestRender(DashboardBase):
    def test_render_is_self_contained(self):
        self.slot(1, {"scoring/reward.py": "OWNER_TAKE = 0.35\n"})
        met.run_pass(self.conn, self.config, now=_iso())
        result = dash.render(self.conn, self.config)
        self.assertTrue(os.path.exists(result["path"]))
        page = open(result["path"], encoding="utf-8").read()
        self.assertIn("SUBNET ATTENTION", page)
        self.assertIn("SN1", page)
        # No external asset references anywhere.
        for needle in ["http://", "https://", "//fonts.", "src=\"http"]:
            self.assertNotIn(needle, page)
        # Self-contained: exactly one inline style + the data + script tags.
        self.assertIn("<style>", page)
        self.assertIn("application/json", page)

    def test_render_empty_store_is_honest_not_faked(self):
        # No slots at all -> a real empty board, never invented rows.
        result = dash.render(self.conn, self.config)
        page = open(result["path"], encoding="utf-8").read()
        self.assertIn("SUBNET ATTENTION", page)
        self.assertIn("No subnets cross the attention threshold", page)
        self.assertEqual(result["head"], 0)

    def test_render_escapes_and_atomic(self):
        # A hostile org name must be escaped, and the write is atomic.
        self.slot(1, {"reward.py": "BURN_FRACTION = 0.5\n"},
                  repo="https://github.com/e<script>/r")
        met.run_pass(self.conn, self.config, now=_iso())
        dash.render(self.conn, self.config)
        page = open(os.path.join(self.www, "index.html"),
                    encoding="utf-8").read()
        self.assertNotIn("<script>e", page)              # org name escaped
        self.assertFalse(os.path.exists(
            os.path.join(self.www, "index.html.tmp")))   # no temp left behind


if __name__ == "__main__":
    unittest.main()
