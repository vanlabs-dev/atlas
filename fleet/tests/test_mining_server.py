"""Mining tools on the atlas-fleet MCP server (change: mining-triage):
read-only posture over a mode=ro connection, structured fail-closed errors,
insufficient-history honesty, unscanned distinct from infeasible, bounded
payloads, and dual timestamps on every response."""

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
from test_mining import inputs, panel_subnet  # noqa: E402


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

    def seed(self, subnets=None, when=None, **kwargs):
        conn = fleet.open_store(self.db)
        try:
            mine.ensure_schema(conn)
            config = {"db": self.db, "clone_root": self.clone_root,
                      "mining": {"enabled": True}}
            mine.run_econ(conn, config, now=when, inputs=inputs(
                subnets or [panel_subnet(1, price=0.05),
                            panel_subnet(4, burn=99.9),
                            panel_subnet(8, price=0.01)],
                incentive=kwargs.get("incentive",
                                     {1: [10, 5], 4: [2], 8: [1, 1]}),
                network_n=kwargs.get("network_n",
                                     {1: 256, 4: 256, 8: 256})))
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

    def test_board_carries_both_timestamps(self):
        self.seed()
        out = self.store.mining_board(10, False)
        self.assertIsNotNone(out["econ_observed_at"])
        self.assertIn("feasibility_scanned_at", out)

    def test_include_cut_returns_reasons(self):
        self.seed()
        out = self.store.mining_board(10, True)
        self.assertTrue(any("99.90" in (r.get("cut_detail") or "")
                            for r in out["cut"]))

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
        self.assertIn("feasibility_scanned_at", out)

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
        self.seed(subnets=[panel_subnet(1, price=0.01)], when=self.older(2),
                  incentive={1: [5]}, network_n={1: 256})
        self.seed(subnets=[panel_subnet(1, price=0.09)],
                  incentive={1: [5]}, network_n={1: 256})
        out = self.store.mining_history(1, "price_tao", 20)
        prices = [o["price_tao"] for o in out["observations"]]
        self.assertEqual(prices, [0.09, 0.01])

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
