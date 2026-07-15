"""Standalone `fleet index` backfill/repair: indexes already-cloned slots
(the deployed 104 that will not re-clone), repairs stale ones, and rebuilds."""

import json
import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

from _helpers import fleet  # noqa: E402
import atlas_fleet_index as idx  # noqa: E402
import test_driver as td  # noqa: E402


class BackfillTests(td.DriverTestBase):
    def cfg(self, **over):
        base = {"clone_root": self.clone_root, "db": self.db, "index": None}
        base.update(over)
        return base

    def cfg_file(self):
        path = os.path.join(self.tmp, "fleetcfg.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({"db": self.db, "clone_root": self.clone_root,
                       "index": {"extensions": [".py", ".md"],
                                 "max_file_bytes": 4096}}, handle)
        return path

    def clone1(self):
        self.reconcile(td.identity_result(
            [td.subnet(1, "https://github.com/test/a")]))

    def test_backfill_indexes_a_clone_that_predates_the_index(self):
        self.clone1()
        idx.purge_slot(self.conn, 1)  # simulate an unindexed pre-fleet-search clone
        self.assertEqual(idx.search(self.conn, "fixture", netuid=1), [])

        summary = fleet.backfill_index(self.conn, self.cfg())
        self.assertGreaterEqual(summary["indexed"], 1)
        self.assertTrue(idx.search(self.conn, "fixture", netuid=1))

    def test_fresh_slot_is_a_noop_unless_rebuild(self):
        self.clone1()  # inline-indexed, so already fresh
        self.assertEqual(fleet.backfill_index(self.conn, self.cfg())["indexed"], 0)
        self.assertGreaterEqual(
            fleet.backfill_index(self.conn, self.cfg(), rebuild=True)["indexed"],
            1)

    def test_netuid_scope_limits_backfill(self):
        self.reconcile(td.identity_result([
            td.subnet(1, "https://github.com/test/a"),
            td.subnet(2, "https://github.com/test/b")]))
        idx.purge_slot(self.conn, 1)
        idx.purge_slot(self.conn, 2)
        fleet.backfill_index(self.conn, self.cfg(), netuid=1)
        self.assertTrue(idx.search(self.conn, "fixture", netuid=1))   # README of a
        self.assertEqual(idx.search(self.conn, "lib", netuid=2), [])  # 2 untouched

    def test_cli_index_command_returns_zero(self):
        self.clone1()
        self.assertEqual(fleet.main(["--config", self.cfg_file(), "index"]), 0)


if __name__ == "__main__":
    unittest.main()
