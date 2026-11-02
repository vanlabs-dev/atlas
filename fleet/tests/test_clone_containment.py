"""Fleet clone containment (change: fleet-clone-containment): committed
symlinks are never read by any fleet reader, and the size and disk bounds
hold before checkout, before advance, and before each fetch."""

import os
import secrets
import shutil
import sys
import tempfile
import unittest
from unittest import mock

_HERE = os.path.dirname(os.path.abspath(__file__))
_FLEET_DIR = os.path.dirname(_HERE)
sys.path.insert(0, _HERE)
sys.path.insert(0, _FLEET_DIR)

import _helpers as h  # noqa: E402
from _helpers import fleet  # noqa: E402
import atlas_fleet_index as idx  # noqa: E402
import atlas_fleet_metrics as met  # noqa: E402
import atlas_fleet_signals as sig  # noqa: E402
import test_driver as td  # noqa: E402
import test_fleet_server as ts  # noqa: E402

MARKER = "plantedsecretmarker"
INDEX_CFG = {"extensions": [".py", ".md", ".txt"], "max_file_bytes": 65536}


def plant_outside(tmp):
    """A secret directory outside every clone, and its absolute path."""
    outside = os.path.join(tmp, "outside")
    h.write_file(outside, "secret.md", "%s token\n" % MARKER)
    h.write_file(outside, "reward.py", "BURN_FRACTION = 0.99\n")
    h.write_file(outside, "requirements.txt", "%s==1.0\n" % MARKER)
    return outside


def make_linked_origin(tmp, name, outside):
    """Fixture remote that commits four link kinds plus decoys."""
    origin = h.make_origin(tmp, name=name, files={
        "AGENTS.md": "agents doc\n", "src/app.py": "x = 1\n"})
    links = {
        "notes.md": os.path.join(outside, "secret.md"),       # file, out
        "CLAUDE.md": "AGENTS.md",                              # in clone
        "linked": outside,                                     # folder
        "dangling.md": os.path.join(tmp, "missing.md"),        # dangling
        "validator/reward.py": os.path.join(outside, "reward.py"),
        "requirements.txt": os.path.join(outside, "requirements.txt"),
    }
    for rel, target in links.items():
        path = os.path.join(origin, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        os.symlink(target, path)
    h.git(origin, "add", "-A")
    h.git(origin, "commit", "-m", "plant links")
    return origin


class LinkedCloneBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.outside = plant_outside(self.tmp)
        self.origin = make_linked_origin(self.tmp, "origin", self.outside)
        self.clone = os.path.join(self.tmp, "clones", "5")
        state = fleet.setup_clone(self.clone, self.origin)
        self.assertEqual(state["status"], "active", state)
        self.assertTrue(os.path.islink(os.path.join(self.clone, "notes.md")))
        self.conn = fleet.open_store(os.path.join(self.tmp, "fleet.db"))
        self.addCleanup(self.conn.close)


class IndexContainmentTests(LinkedCloneBase):
    def setUp(self):
        super().setUp()
        idx.ensure_schema(self.conn)

    def paths(self):
        return sorted(r[0] for r in self.conn.execute(
            "SELECT path FROM fleet_files WHERE netuid=5"))

    def test_full_index_skips_every_link(self):
        idx.index_slot(self.conn, 5, 1, self.clone, INDEX_CFG)
        self.assertEqual(self.paths(), ["AGENTS.md",
                                        "src/app.py"])
        hits = self.conn.execute(
            "SELECT count(*) FROM fleet_files_fts WHERE fleet_files_fts "
            "MATCH ?", (MARKER,)).fetchone()[0]
        self.assertEqual(hits, 0)

    def test_incremental_pass_refuses_link_paths_and_drops_old_rows(self):
        idx.index_slot(self.conn, 5, 1, self.clone, INDEX_CFG)
        # an old row for a path that is now a link, or under a folder link
        for rel in ("notes.md", "linked/secret.md"):
            self.conn.execute(
                "INSERT INTO fleet_files (netuid, epoch, path, indexed_sha, "
                "byte_size, indexed_at) VALUES (5, 1, ?, 'x', 1, 'now')",
                (rel,))
        h.add_commit(self.origin, "src/app.py", "x = 2\n")
        result = fleet.update_clone(self.clone, "main",
                                    h.git(self.clone, "rev-parse", "HEAD"))
        self.assertEqual(result["status"], "ok", result)
        idx.index_slot(self.conn, 5, 1, self.clone, INDEX_CFG,
                       changed_paths=["src/app.py", "notes.md",
                                      "linked/secret.md", "CLAUDE.md"],
                       local_sha=result["local_sha"])
        self.assertEqual(self.paths(), ["AGENTS.md",
                                        "src/app.py"])


class ScanAndSeedContainmentTests(LinkedCloneBase):
    def test_econ_scan_does_not_read_a_linked_file(self):
        out = met.scan_clone_emissions(self.clone, met.DEFAULT_METRICS_CFG)
        self.assertEqual(out["routes"], [])

    def test_signals_seed_does_not_read_a_linked_manifest(self):
        sig.ensure_schema(self.conn)
        sig.seed_epoch(self.conn, sig.DEFAULT_SIGNALS_CFG, [], 5, 1,
                       self.clone, "2026-11-03T00:00:00+00:00", True,
                       "2026-11-03T00:00:00+00:00")
        terms = [r[0] for r in self.conn.execute(
            "SELECT term FROM signal_adoptions")]
        self.assertNotIn(MARKER, " ".join(terms))


class FleetFileContainmentTests(ts.ServerBase):
    def setUp(self):
        super().setUp()
        outside = plant_outside(self.tmp)
        self.url_map["https://github.com/test/l"] = make_linked_origin(
            self.tmp, "origin_l", outside)
        self.clone(3, "https://github.com/test/l")

    def test_links_are_refused_and_plain_files_served(self):
        for rel in ("notes.md", "CLAUDE.md", "linked/secret.md",
                    "dangling.md"):
            out = self.ask("fleet_file", {"netuid": 3, "path": rel})
            self.assertEqual(out["error"]["category"], "invalid", rel)
        out = self.ask("fleet_file", {"netuid": 3, "path": "AGENTS.md"})
        self.assertEqual(out["status"], "ok", out)


class TreeStatsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_sums_blob_sizes_from_a_blobless_clone_in_one_fetch(self):
        origin = h.make_origin(self.tmp, files={
            "a.txt": "x" * 100, "b/c.txt": "y" * 50})
        clone = os.path.join(self.tmp, "c")
        h.git(self.tmp, "clone", "-q", "--filter=blob:none",
              "--no-checkout", "file://" + origin, clone)
        calls = []
        real = fleet._run_git

        def spy(cwd, args, **kw):
            calls.append(args)
            return real(cwd, args, **kw)
        with mock.patch.object(fleet, "_run_git", spy):
            stats = fleet._head_tree_stats(clone)
        self.assertEqual(stats, (2, 150))
        fetches = [a for a in calls if "fetch" in a]
        self.assertEqual(len(fetches), 1)


class SizeAndDiskBoundTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.origin = h.make_origin(self.tmp)
        self.clone = os.path.join(self.tmp, "fleet", "1")

    def test_oversized_tree_is_quarantined_before_checkout(self):
        big = h.make_origin(self.tmp, name="big",
                            files={"data.txt": secrets.token_hex(5000)})
        calls = []
        real = fleet._run_git

        def spy(cwd, args, **kw):
            calls.append(args)
            return real(cwd, args, **kw)
        with mock.patch.object(fleet, "_run_git", spy):
            state = fleet.setup_clone(self.clone, big,
                                      caps={"max_bytes": 4096})
        self.assertEqual(state["status"], "quarantined")
        self.assertFalse(os.path.isdir(self.clone))
        self.assertFalse(any(a and a[0] == "checkout" for a in calls))

    def test_low_disk_holds_checkout(self):
        with mock.patch.object(fleet, "_default_disk_free",
                               return_value=10):
            state = fleet.setup_clone(self.clone, self.origin,
                                      caps={"min_free_bytes": 1000})
        self.assertEqual(state["status"], "disk-limited")
        self.assertFalse(os.path.isdir(self.clone))

    def test_oversized_update_is_quarantined_at_last_good_head(self):
        state = fleet.setup_clone(self.clone, self.origin)
        prev = state["local_sha"]
        h.add_commit(self.origin, "big.txt", secrets.token_hex(5000))
        result = fleet.update_clone(self.clone, "main", prev,
                                    caps={"max_bytes": 4096})
        self.assertEqual(result["status"], "quarantined", result)
        self.assertEqual(h.git(self.clone, "rev-parse", "HEAD"), prev)
        self.assertFalse(os.path.exists(os.path.join(self.clone,
                                                     "big.txt")))

    def test_low_disk_holds_advance(self):
        state = fleet.setup_clone(self.clone, self.origin)
        prev = state["local_sha"]
        h.add_commit(self.origin, "n.txt", "n\n")
        with mock.patch.object(fleet, "_default_disk_free",
                               return_value=10):
            result = fleet.update_clone(self.clone, "main", prev,
                                        caps={"min_free_bytes": 1000})
        self.assertEqual(result["status"], "disk-limited")
        self.assertEqual(h.git(self.clone, "rev-parse", "HEAD"), prev)


class ReconcileBoundTests(td.DriverTestBase):
    def test_low_disk_holds_update_fetch_and_keeps_slot_active(self):
        result = td.identity_result([td.subnet(1,
                                               "https://github.com/test/a")])
        self.reconcile(result)
        before = fleet.get_slot(self.conn, 1)
        h.add_commit(self.origin_a, "n.txt", "n\n")
        cfg = dict(self.config, min_free_bytes=1000)
        with mock.patch.object(fleet, "update_clone") as update:
            summary = fleet.reconcile(self.conn, result, cfg,
                                      setup=self._setup, update=update,
                                      disk_free=lambda: 10)
        update.assert_not_called()
        self.assertEqual(summary["disk-limited"], 1)
        after = fleet.get_slot(self.conn, 1)
        self.assertEqual(after["status"], "active")
        self.assertEqual(after["local_sha"], before["local_sha"])

    def test_oversized_update_marks_slot_quarantined(self):
        result = td.identity_result([td.subnet(1,
                                               "https://github.com/test/a")])
        self.reconcile(result)
        before = fleet.get_slot(self.conn, 1)
        h.add_commit(self.origin_a, "big.txt", secrets.token_hex(5000))
        cfg = dict(self.config, caps={"max_bytes": 4096})
        fleet.reconcile(self.conn, result, cfg, setup=self._setup,
                        update=fleet.update_clone)
        after = fleet.get_slot(self.conn, 1)
        self.assertEqual(after["status"], "quarantined")
        self.assertEqual(after["local_sha"], before["local_sha"])


if __name__ == "__main__":
    unittest.main()
