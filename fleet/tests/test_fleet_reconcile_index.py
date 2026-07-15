"""Inline indexing on reconcile: the directive seam (pure update->directive
mapping) and integration (clone/update/repoint/discard keep the shared index
in step), with per-slot fail-closed, transaction-isolated indexing."""

import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

import _helpers as h  # noqa: E402
from _helpers import fleet  # noqa: E402
import atlas_fleet_index as idx  # noqa: E402
import test_driver as td  # noqa: E402


class UpdateDirectiveTests(unittest.TestCase):
    """Pure mapping from an update_clone result to an index directive."""

    def test_clean_fast_forward_is_incremental(self):
        result = {"status": "ok", "fast_forward": True, "new_sha": "n",
                  "range": {"files": [{"path": "a.py"}, {"path": "b.py"}],
                            "files_truncated": False}}
        spec = fleet._update_index_directive(result)
        self.assertEqual(spec, {"changed_paths": ["a.py", "b.py"],
                                "local_sha": "n"})

    def test_truncated_range_forces_full(self):
        result = {"status": "ok", "fast_forward": True, "new_sha": "n",
                  "range": {"files": [{"path": "a.py"}], "files_truncated": True}}
        self.assertEqual(fleet._update_index_directive(result),
                         {"changed_paths": None, "local_sha": "n"})

    def test_non_fast_forward_forces_full(self):
        result = {"status": "ok", "fast_forward": False, "new_sha": "n",
                  "range": {"files": [{"path": "a.py"}], "files_truncated": False}}
        self.assertEqual(fleet._update_index_directive(result),
                         {"changed_paths": None, "local_sha": "n"})

    def test_record_failed_forces_full(self):
        result = {"status": "record-failed", "new_sha": "n", "local_sha": "n"}
        self.assertEqual(fleet._update_index_directive(result),
                         {"changed_paths": None, "local_sha": "n"})

    def test_no_change_and_failures_yield_no_directive(self):
        for result in ({"status": "no-change"},
                       {"status": "fetch-failed"},
                       {"status": "advance-failed"},
                       {"status": "local-modifications"}):
            self.assertIsNone(fleet._update_index_directive(result))


class ReconcileIndexTests(td.DriverTestBase):
    def paths(self, netuid):
        return sorted(row[0] for row in self.conn.execute(
            "SELECT path FROM fleet_files WHERE netuid=?", (netuid,)))

    def _reconcile1(self, url="https://github.com/test/a"):
        self.reconcile(td.identity_result([td.subnet(1, url)]))

    def test_new_clone_is_fully_indexed(self):
        self._reconcile1()
        self.assertTrue(idx.search(self.conn, "fixture", netuid=1))
        self.assertIsNotNone(self.conn.execute(
            "SELECT 1 FROM index_state WHERE netuid=1").fetchone())

    def test_clean_fast_forward_indexes_incrementally(self):
        self._reconcile1()
        h.add_commit(self.origin_a, "src/new.py",
                     "emissionalpha = 1\n", "feat: add")
        self._reconcile1()
        hits = idx.search(self.conn, "emissionalpha", netuid=1)
        self.assertEqual([hit["path"] for hit in hits], ["src/new.py"])
        head = h.git(os.path.join(self.clone_root, "1"), "rev-parse", "HEAD")
        self.assertEqual(self.conn.execute(
            "SELECT indexed_sha FROM index_state WHERE netuid=1").fetchone()[0],
            head)

    def test_discard_purges_the_netuid(self):
        self._reconcile1()
        self.reconcile(td.identity_result([]))  # deregistered
        self.assertEqual(idx.search(self.conn, "fixture", netuid=1), [])
        self.assertIsNone(self.conn.execute(
            "SELECT 1 FROM index_state WHERE netuid=1").fetchone())

    def test_repoint_purges_old_project_and_indexes_new(self):
        self._reconcile1("https://github.com/test/a")   # README.md
        self.reconcile(td.identity_result(
            [td.subnet(1, "https://github.com/test/b")]))  # origin_b: lib.py
        self.assertEqual(self.paths(1), ["lib.py"])
        self.assertEqual(idx.search(self.conn, "fixture", netuid=1), [])

    def test_index_failure_preserves_advance_and_is_recorded(self):
        boom_calls = {"n": 0}

        def boom(*args, **kwargs):
            boom_calls["n"] += 1
            raise RuntimeError("disk gremlin")

        original = idx.index_slot
        idx.index_slot = boom
        self.addCleanup(setattr, idx, "index_slot", original)

        self._reconcile1()
        self.assertGreaterEqual(boom_calls["n"], 1)
        slot = fleet.get_slot(self.conn, 1)
        self.assertEqual(slot["status"], "active")    # clone survived
        self.assertTrue(slot["local_sha"])            # advance preserved
        self.assertEqual(self.paths(1), [])           # index rolled back
        self.assertTrue(self.conn.execute(
            "SELECT 1 FROM audit WHERE action='index-failed' AND netuid=1"
        ).fetchone())


if __name__ == "__main__":
    unittest.main()
