"""Reconcile driver: wires the plan builder + bound + executor and
persists slot transitions, epochs, change ranges, and audit. Tested
end-to-end against real local git origins (no mocks); the injected
executor only maps the canonical github URL used by the identity/plan
logic to the local fixture remote a real clone fetches from."""

import json
import os
import sys
import tempfile
import shutil
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

import _helpers as h  # noqa: E402
from _helpers import fleet  # noqa: E402


def subnet(netuid, repo, owner="5Own", name=None):
    return {"netuid": netuid, "github_repo": repo, "owner_ss58": owner,
            "subnet_name": name or ("sn%d" % netuid)}


def identity_result(subnets, complete=True, status="ok",
                    freshness="fresh", block=1000):
    return {"status": status, "freshness_status": freshness,
            "block_reference": block,
            "values": {"subnets": subnets, "count": len(subnets),
                       "complete": complete}}


class DriverTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.db = os.path.join(self.tmp, "fleet.db")
        self.clone_root = os.path.join(self.tmp, "fleet")
        self.conn = fleet.open_store(self.db)
        self.addCleanup(self.conn.close)
        self.origin_a = h.make_origin(self.tmp, name="origin_a")
        self.origin_b = h.make_origin(self.tmp, name="origin_b",
                                      files={"lib.py": "b = 2\n"})
        self.url_map = {"https://github.com/test/a": self.origin_a,
                        "https://github.com/test/b": self.origin_b}
        self.config = {"clone_root": self.clone_root,
                       "max_new_clones_per_pass": None, "caps": None}

    def _setup(self, clone_dir, url, token=None, caps=None):
        return fleet.setup_clone(clone_dir, self.url_map[url], token=token,
                                 caps=caps)

    def reconcile(self, result, config=None):
        return fleet.reconcile(self.conn, result, config or self.config,
                               setup=self._setup, update=fleet.update_clone)

    def q(self, sql, params=()):
        return self.conn.execute(sql, params).fetchall()


class BasicReconcileTests(DriverTestBase):
    def test_new_subnet_is_cloned_active_with_epoch_and_audit(self):
        self.reconcile(identity_result([subnet(1, "https://github.com/test/a")]))
        slot = fleet.get_slot(self.conn, 1)
        self.assertEqual(slot["status"], "active")
        self.assertEqual(slot["epoch"], 1)
        self.assertTrue(slot["local_sha"])
        self.assertTrue(os.path.isdir(os.path.join(self.clone_root, "1")))
        epochs = self.q("SELECT netuid, epoch FROM epochs")
        self.assertIn((1, 1), epochs)
        self.assertTrue(self.q("SELECT 1 FROM audit WHERE action='clone'"))

    def test_missing_github_repo_recorded_no_repo_no_clone(self):
        self.reconcile(identity_result([subnet(2, None)]))
        slot = fleet.get_slot(self.conn, 2)
        self.assertEqual(slot["status"], "no-repo")
        self.assertFalse(os.path.isdir(os.path.join(self.clone_root, "2")))

    def test_invalid_url_recorded_invalid_no_clone(self):
        self.reconcile(identity_result(
            [subnet(3, "https://gitlab.com/o/r")]))
        slot = fleet.get_slot(self.conn, 3)
        self.assertEqual(slot["status"], "invalid-url")
        self.assertFalse(os.path.isdir(os.path.join(self.clone_root, "3")))

    def test_second_pass_records_change_range(self):
        self.reconcile(identity_result([subnet(1, "https://github.com/test/a")]))
        h.add_commit(self.origin_a, "src/x.py", "x = 1\n", "feat: add x")
        self.reconcile(identity_result([subnet(1, "https://github.com/test/a")]))
        ranges = self.q("SELECT netuid, epoch, commits_json, files_json "
                        "FROM change_ranges WHERE netuid=1")
        self.assertEqual(len(ranges), 1)
        self.assertEqual((ranges[0][0], ranges[0][1]), (1, 1))
        subjects = [c["subject"]
                    for c in json.loads(ranges[0][2])["commits"]]
        self.assertIn("feat: add x", subjects)

    def test_no_change_pass_records_no_range(self):
        self.reconcile(identity_result([subnet(1, "https://github.com/test/a")]))
        self.reconcile(identity_result([subnet(1, "https://github.com/test/a")]))
        self.assertEqual(
            self.q("SELECT count(*) FROM change_ranges WHERE netuid=1")[0][0],
            0)


class ChurnTests(DriverTestBase):
    def test_repoint_discards_bumps_epoch_and_keeps_old_history(self):
        self.reconcile(identity_result([subnet(1, "https://github.com/test/a")]))
        h.add_commit(self.origin_a, "src/x.py", "x = 1\n", "feat: x")
        self.reconcile(identity_result([subnet(1, "https://github.com/test/a")]))
        self.assertEqual(  # a range exists under epoch 1
            self.q("SELECT count(*) FROM change_ranges WHERE netuid=1 "
                   "AND epoch=1")[0][0], 1)

        # Owner re-points the slot to a different repository.
        self.reconcile(identity_result([subnet(1, "https://github.com/test/b")]))
        slot = fleet.get_slot(self.conn, 1)
        self.assertEqual(slot["epoch"], 2)
        self.assertEqual(slot["github_repo"], "https://github.com/test/b")
        # old clone replaced by origin_b's head
        self.assertEqual(slot["local_sha"],
                         h.git(self.origin_b, "rev-parse", "HEAD"))
        # epoch 1 closed, epoch 2 open, and epoch-1 history preserved
        self.assertTrue(self.q("SELECT closed_at FROM epochs WHERE netuid=1 "
                               "AND epoch=1")[0][0])
        self.assertEqual(
            self.q("SELECT count(*) FROM change_ranges WHERE netuid=1 "
                   "AND epoch=1")[0][0], 1)

    def test_rename_only_does_not_repoint(self):
        self.reconcile(identity_result(
            [subnet(1, "https://github.com/test/a", name="Old Name")]))
        first = fleet.get_slot(self.conn, 1)
        self.reconcile(identity_result(
            [subnet(1, "https://github.com/test/a", name="New Name")]))
        second = fleet.get_slot(self.conn, 1)
        self.assertEqual(second["epoch"], first["epoch"])
        self.assertEqual(second["fingerprint"], first["fingerprint"])

    def test_deregistration_discards_clone_keeps_provenance(self):
        self.reconcile(identity_result([subnet(1, "https://github.com/test/a")]))
        h.add_commit(self.origin_a, "src/x.py", "x = 1\n", "feat: x")
        self.reconcile(identity_result([subnet(1, "https://github.com/test/a")]))

        self.reconcile(identity_result([]))  # subnet 1 deregistered
        self.assertIsNone(fleet.get_slot(self.conn, 1))
        self.assertFalse(os.path.isdir(os.path.join(self.clone_root, "1")))
        # provenance survives the discard
        self.assertEqual(
            self.q("SELECT count(*) FROM change_ranges WHERE netuid=1")[0][0],
            1)


class GuardAndBoundTests(DriverTestBase):
    def test_degraded_fetch_never_discards(self):
        self.reconcile(identity_result([subnet(1, "https://github.com/test/a")]))
        # An incomplete map (complete=False) with subnet 1 absent must NOT
        # be read as a deregistration.
        self.reconcile(identity_result([], complete=False))
        self.assertIsNotNone(fleet.get_slot(self.conn, 1))
        self.assertTrue(os.path.isdir(os.path.join(self.clone_root, "1")))

    def test_degraded_fetch_still_updates_active_slot(self):
        self.reconcile(identity_result([subnet(1, "https://github.com/test/a")]))
        h.add_commit(self.origin_a, "src/x.py", "x = 1\n", "feat: x")
        self.reconcile(identity_result([], complete=False))
        # the active slot advanced despite the degraded identity fetch
        self.assertEqual(
            self.q("SELECT count(*) FROM change_ranges WHERE netuid=1")[0][0],
            1)

    def test_disk_ceiling_marks_disk_limited_then_recovers(self):
        config = dict(self.config, min_free_bytes=1_000_000_000)
        result = identity_result([subnet(1, "https://github.com/test/a")])
        summary = fleet.reconcile(self.conn, result, config, setup=self._setup,
                                  update=fleet.update_clone,
                                  disk_free=lambda: 10)
        self.assertEqual(summary["disk-limited"], 1)
        self.assertEqual(fleet.get_slot(self.conn, 1)["status"], "disk-limited")
        self.assertFalse(os.path.isdir(os.path.join(self.clone_root, "1")))

        fleet.reconcile(self.conn, result, config, setup=self._setup,
                        update=fleet.update_clone,
                        disk_free=lambda: 2_000_000_000)
        self.assertEqual(fleet.get_slot(self.conn, 1)["status"], "active")

    def test_bound_defers_excess_then_converges(self):
        config = dict(self.config, max_new_clones_per_pass=1)
        result = identity_result([subnet(1, "https://github.com/test/a"),
                                  subnet(2, "https://github.com/test/b")])
        summary = self.reconcile(result, config)
        self.assertEqual(summary["deferred"], 1)
        statuses = {row[0]: row[1]
                    for row in self.q("SELECT netuid, status FROM slots")}
        self.assertEqual(sorted(statuses.values()), ["active", "pending"])

        self.reconcile(result, config)  # second pass converges
        statuses = {row[0]: row[1]
                    for row in self.q("SELECT netuid, status FROM slots")}
        self.assertEqual(set(statuses.values()), {"active"})


if __name__ == "__main__":
    unittest.main()
