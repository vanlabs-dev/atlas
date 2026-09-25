"""Store and surface agreement (change: mining-board-accuracy): the board,
the MCP tools, the pulse briefing and the subnt publisher all read the
ranking the pass stored, so they report identical counts and head. The
store is written by the real writer."""

import json
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_FLEET_DIR = os.path.dirname(_HERE)
_REPO_ROOT = os.path.dirname(_FLEET_DIR)
sys.path.insert(0, _HERE)
sys.path.insert(0, _FLEET_DIR)
sys.path.insert(0, os.path.join(_REPO_ROOT, "telegram"))
sys.path.insert(0, os.path.join(_REPO_ROOT, "subnt"))

from _helpers import fleet  # noqa: E402
import atlas_briefing as ab  # noqa: E402
import atlas_fleet_mining as mine  # noqa: E402
import atlas_fleet_server as srv  # noqa: E402
import atlas_subnt as sh  # noqa: E402
import mining_fixtures as mf  # noqa: E402
from mining_fixtures import subnet  # noqa: E402

# SN9 has the highest raw figure and is cut winner-take-all; SN4 heads.
BOARD = [subnet(9, [100, 0, 0], name="iota", tao_pool=900_000.0),
         subnet(4, [10, 9, 8], name="Targon", tao_pool=90_000.0),
         subnet(80, [10, 9, 8], name="OpenRoboto", tao_pool=60_000.0),
         subnet(3, [10, 9, 8], name="deprecated"),
         subnet(12, [10, 9, 8], owner_uids=None),
         subnet(59, [0, 40], owner_uids=[1], alpha_out=0, burn=0.0)]


class _Src:
    def __init__(self, fleet_conn):
        self.fleet = fleet_conn


class TestAgreement(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.db = os.path.join(self.tmp, "fleet.db")
        conn = fleet.open_store(self.db)
        self.config = {"db": self.db,
                       "clone_root": os.path.join(self.tmp, "clones"),
                       "dashboard": {"www_dir": os.path.join(self.tmp,
                                                             "www")},
                       "mining": {"enabled": True}}
        mf.seed_board(conn, self.config, mf.synthetic(BOARD))
        self.board = mine.report(conn, self.config, include_cut=True)
        mine.render(conn, self.config)
        conn.close()
        os.makedirs(self.config["clone_root"])
        path = os.path.join(self.tmp, "config.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(self.config, handle)
        self.mcp = srv.FleetStore(path).mining_board(10, True)
        self.ro = sqlite3.connect("file:%s?mode=ro" % self.db, uri=True)
        self.addCleanup(self.ro.close)

    def test_stored_counts_and_head(self):
        self.assertEqual(self.board["counts"], {"observed": 6, "ranked": 2,
                                                "cut": 3, "unrated": 1})
        self.assertEqual(self.board["ranked"][0]["netuid"], 4)
        cut = {e["netuid"]: e["cut_reason"] for e in self.board["cut"]}
        self.assertEqual(cut[9], mine.CUT_CONCENTRATION)
        self.assertEqual(cut[59], mine.CUT_NO_EARNER)

    def test_mcp_matches_the_board(self):
        self.assertEqual(self.mcp["counts"], self.board["counts"])
        self.assertEqual([e["netuid"] for e in self.mcp["ranked"]],
                         [e["netuid"] for e in self.board["ranked"]])

    def test_briefing_matches_the_board(self):
        lines, figures = ab._mining_section(_Src(self.ro), {}, "", {})
        self.assertEqual(lines[0], "board head: SN4 Targon")
        self.assertEqual(lines[1], "2 ranked · 3 cut · 1 unrated · 6 "
                                   "observed")
        self.assertEqual(figures["mining_top10"],
                         [e["netuid"] for e in self.board["ranked"]])

    def test_subnt_matches_the_board(self):
        items, figures = sh.mining_facts(_Src(self.ro), {}, {})
        self.assertEqual(figures["mining_head"], 4)
        self.assertEqual(figures["mining_ranked"], 2)
        self.assertEqual(figures["mining_cut"], 3)
        self.assertEqual(figures["mining_unrated"], 1)
        self.assertEqual(figures["mining_observed"], 6)
        text = " ".join(item[1] for item in items)
        self.assertIn("2 ranked, 3 cut, 1 unrated, 6 observed", text)
        self.assertNotIn("SN9,", text.split("Board head")[1][:12])

    def test_board_page_matches_the_store(self):
        with open(os.path.join(self.tmp, "www", "mining.html"),
                  encoding="utf-8") as handle:
            page = handle.read()
        self.assertIn("6 observed, 2 ranked, 1 unrated, 3 cut", page)

    def test_subnt_suppresses_deltas_across_a_model_change(self):
        items, _ = sh.mining_facts(_Src(self.ro), {},
                                   {"mining_top10": [120, 93]})
        text = " ".join(item[1] for item in items)
        self.assertIn("mining model changed", text)
        self.assertNotIn("Entered the top ten", text)


if __name__ == "__main__":
    unittest.main()
