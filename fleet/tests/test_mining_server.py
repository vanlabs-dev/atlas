"""Mining tools on the atlas-fleet MCP server (changes: mining-triage,
mining-board-accuracy): read-only posture over a mode=ro connection,
structured fail-closed errors, the stored cut and rank on every view,
per-row observation times, the parity model with every entrant figure,
insufficient-history honesty, unscanned distinct from infeasible, and
bounded payloads. Fixtures come from the real writer."""

import datetime
import json
import os
import shutil
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_FLEET_DIR = os.path.dirname(_HERE)
sys.path.insert(0, _HERE)
sys.path.insert(0, _FLEET_DIR)

from _helpers import fleet  # noqa: E402
import atlas_fleet_mining as mine  # noqa: E402
import atlas_fleet_server as srv  # noqa: E402
import mining_fixtures as mf  # noqa: E402
from mining_fixtures import subnet, synthetic  # noqa: E402

BOARD = [subnet(1, [10, 5], tao_pool=125_000.0),
         subnet(4, [10, 5], burn=0.999),
         subnet(8, [10, 5, 5])]


class MiningServerBase(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.db = os.path.join(self.tmp, "fleet.db")
        self.clone_root = os.path.join(self.tmp, "clones")
        os.makedirs(self.clone_root, exist_ok=True)
        self.config_path = os.path.join(self.tmp, "config.json")
        with open(self.config_path, "w", encoding="utf-8") as handle:
            json.dump({"db": self.db, "clone_root": self.clone_root}, handle)
        self.store = srv.FleetStore(self.config_path)
        self.audit = None

    def seed(self, subnets=None, when=None):
        conn = fleet.open_store(self.db)
        try:
            config = {"db": self.db, "clone_root": self.clone_root,
                      "mining": {"enabled": True}}
            mf.seed_board(conn, config, synthetic(subnets or BOARD),
                          now=when)
        finally:
            conn.close()


class TestFailClosed(MiningServerBase):

    def test_absent_store_is_a_named_error_not_an_empty_result(self):
        out = self.store.mining_board(10, False)
        self.assertEqual(out["error"]["category"], srv.MINING_UNAVAILABLE)
        self.assertNotIn("ranked", out)

    def test_never_populated_store_is_a_named_error(self):
        conn = fleet.open_store(self.db)
        mine.ensure_schema(conn)
        conn.commit()
        conn.close()
        out = self.store.mining_board(10, False)
        self.assertEqual(out["error"]["category"], srv.MINING_UNAVAILABLE)

    def test_subnet_without_observations_reports_no_evidence(self):
        self.seed()
        out = self.store.mining_subnet(999)
        self.assertEqual(out["error"]["category"], "no-mining-evidence")


class TestBoard(MiningServerBase):

    def test_board_ranks_and_reports_cut_counts(self):
        self.seed()
        out = self.store.mining_board(10, False)
        self.assertEqual({r["netuid"] for r in out["ranked"]}, {1, 8})
        self.assertEqual(out["cut_summary"], {mine.CUT_BURN: 1})
        self.assertEqual(out["switch_block_ref"], 8789861)

    def test_board_carries_both_timestamps(self):
        self.seed()
        out = self.store.mining_board(10, False)
        self.assertIsNotNone(out["econ_observed_at"])
        self.assertEqual(out["econ_block"], 8789861)
        self.assertIn("feasibility_scanned_at", out)

    def test_include_cut_returns_reasons(self):
        self.seed()
        out = self.store.mining_board(10, True)
        self.assertTrue(any("99.90" in (r.get("cut_detail") or "")
                            for r in out["cut"]))
        self.assertEqual(out["cut_omitted"], 0)

    def test_include_cut_is_bounded_with_an_omitted_count(self):
        self.seed([subnet(n, [10, 5], burn=0.999) for n in range(1, 41)])
        out = self.store.mining_board(10, True)
        self.assertEqual(len(out["cut"]), srv.MAX_CUT_ROWS)
        self.assertEqual(out["cut_omitted"], 40 - srv.MAX_CUT_ROWS)

    def test_board_states_the_parity_model(self):
        self.seed()
        out = self.store.mining_board(10, False)
        self.assertIn("MODEL", out["parity_model"])

    def test_board_names_the_ranking_mechanism(self):
        self.seed()
        out = self.store.mining_board(10, False)
        self.assertEqual(out["ranked"][0]["rank_mecid"], 0)
        self.assertTrue(out["ranked"][0]["mechanisms"])

    def test_limit_bounds_the_payload(self):
        self.seed()
        self.assertEqual(len(self.store.mining_board(1, False)["ranked"]), 1)

    def test_dispatch_clamps_an_out_of_range_limit(self):
        self.seed()
        out = srv.handle_tool_call(self.store, _NullAudit(), "mining_board",
                                   {"limit": 9999})
        self.assertLessEqual(len(out["ranked"]), srv.MAX_BOARD_LIMIT)

    def test_board_is_read_only_over_a_ro_connection(self):
        """The server opens mode=ro; a write attempt would raise here."""
        self.seed()
        out = self.store.mining_board(10, False)
        self.assertIn("ranked", out)
        self.assertNotIn("error", out)


class TestSubnetDetail(MiningServerBase):

    def test_detail_carries_the_reference_block(self):
        self.seed()
        out = self.store.mining_subnet(1)
        self.assertEqual(out["status"], "ok")
        self.assertEqual(out["economics"]["block_ref"], 8789861)

    def test_unscanned_is_distinct_from_infeasible(self):
        self.seed()
        out = self.store.mining_subnet(1)
        self.assertTrue(out["feasibility"]["unscanned"])
        self.assertEqual(out["feasibility"]["verdict"], "unknown")
        self.assertNotIn(out["feasibility"]["verdict"],
                         mine.INFEASIBLE_VERDICTS)

    def test_detail_carries_both_timestamps(self):
        self.seed()
        out = self.store.mining_subnet(1)
        self.assertIsNotNone(out["econ_observed_at"])
        self.assertEqual(out["econ_block"], 8789861)
        self.assertIn("feasibility_scanned_at", out)

    def test_detail_carries_the_stored_cut_identical_to_the_board(self):
        self.seed()
        board = {r["netuid"]: r for r in
                 self.store.mining_board(10, True)["cut"]}
        out = self.store.mining_subnet(4)
        self.assertEqual(out["outcome"],
                         {"cut_reason": board[4]["cut_reason"],
                          "cut_detail": board[4]["cut_detail"]})

    def test_detail_carries_rank_and_mechanism(self):
        self.seed()
        out = self.store.mining_subnet(1)
        self.assertEqual(out["outcome"], {"rank": 1, "rank_mecid": 0})
        self.assertEqual(len(out["mechanisms"]), 1)
        self.assertIn("MODEL", out["parity_model"])

    def test_an_old_row_is_stamped_with_its_own_time(self):
        old = (datetime.datetime.now(tz=datetime.timezone.utc)
               - datetime.timedelta(days=2)).isoformat()
        self.seed([subnet(1, [10, 5]), subnet(2, [10, 5])], when=old)
        self.seed([subnet(1, [10, 5])])
        out = self.store.mining_subnet(2)
        self.assertEqual(out["econ_observed_at"], old)
        self.assertEqual(out["economics"]["ts"], old)

    def test_negative_netuid_is_rejected_by_dispatch(self):
        self.seed()
        out = srv.handle_tool_call(self.store, _NullAudit(), "mining_subnet",
                                   {"netuid": -1})
        self.assertEqual(out["error"]["category"], "invalid")


class TestHistory(MiningServerBase):

    def older(self, days):
        return (datetime.datetime.now(tz=datetime.timezone.utc)
                - datetime.timedelta(days=days)).isoformat()

    def test_single_observation_is_not_a_trend(self):
        self.seed()
        out = self.store.mining_history(1, None, 20)
        self.assertEqual(out["error"]["category"], "insufficient-history")
        self.assertEqual(len(out["observations"]), 1)

    def test_two_observations_are_returned_newest_first(self):
        self.seed(when=self.older(2))
        self.seed()
        out = self.store.mining_history(1, None, 20)
        self.assertEqual(out["status"], "ok")
        self.assertEqual(len(out["observations"]), 2)
        self.assertGreater(out["observations"][0]["ts"],
                           out["observations"][1]["ts"])

    def test_history_shows_a_real_change(self):
        self.seed(subnets=[subnet(1, [5, 5], tao_pool=30_000.0)],
                  when=self.older(2))
        self.seed(subnets=[subnet(1, [5, 5], tao_pool=270_000.0)])
        out = self.store.mining_history(1, "price_tao", 20)
        prices = [round(o["price_tao"], 4) for o in out["observations"]]
        self.assertEqual(prices, [0.09, 0.01])

    def test_history_carries_the_stored_outcome_and_mechanisms(self):
        self.seed(subnets=[subnet(1, [5, 5])], when=self.older(2))
        self.seed(subnets=[subnet(1, [5, 5], burn=0.999)])
        out = self.store.mining_history(1, None, 20)
        newest, oldest = out["observations"]
        self.assertEqual(newest["cut_reason"], mine.CUT_BURN)
        self.assertEqual(oldest["rank"], 1)
        self.assertEqual(oldest["rank_mecid"], 0)
        self.assertEqual(len(oldest["mechanisms"]), 1)
        self.assertIn("MODEL", out["parity_model"])

    def test_unknown_field_is_rejected(self):
        self.seed()
        out = self.store.mining_history(1, "definitely_not_a_column", 20)
        self.assertEqual(out["error"]["category"], "invalid")

    def test_history_carries_both_timestamps(self):
        self.seed(when=self.older(2))
        self.seed()
        out = self.store.mining_history(1, None, 20)
        self.assertIsNotNone(out["econ_observed_at"])
        self.assertIn("feasibility_scanned_at", out)


class TestToolContract(unittest.TestCase):

    def test_three_mining_tools_are_advertised(self):
        names = {tool["name"] for tool in srv.TOOLS}
        self.assertTrue({"mining_board", "mining_subnet",
                         "mining_history"} <= names)

    def test_existing_tools_are_unchanged(self):
        names = {tool["name"] for tool in srv.TOOLS}
        self.assertTrue({"fleet_search", "fleet_file",
                         "fleet_status"} <= names)

    def test_no_mining_tool_advertises_a_write(self):
        for tool in srv.TOOLS:
            if not tool["name"].startswith("mining_"):
                continue
            blob = json.dumps(tool).lower()
            for banned in ("write", "delete", "update", "insert", "register"):
                self.assertNotIn(banned, blob, tool["name"])

    def test_schemas_reject_unknown_arguments(self):
        for tool in srv.TOOLS:
            if tool["name"].startswith("mining_"):
                self.assertFalse(
                    tool["inputSchema"].get("additionalProperties", True))

    def test_unknown_tool_is_rejected(self):
        out = srv.handle_tool_call(srv.FleetStore("nope.json"), _NullAudit(),
                                   "mining_delete", {})
        self.assertEqual(out["error"]["category"], "invalid")


class _NullAudit:
    def record(self, *args, **kwargs):
        return None


if __name__ == "__main__":
    unittest.main()
