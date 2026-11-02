"""Clone containment (change: fleet-clone-containment): the shared
`contained_file` check, the link-free walk, the indexer skipping links,
and the disk ceiling before the subtensor fetch."""

import os
import tempfile
import unittest
from unittest import mock

from _helpers import (arp, commit_origin, git, last_run, query, run_cli,
                      setup_tracking)

MARKER = "plantedsecretmarker"


class ContainedFileTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        tmp = self._tmp.name
        self.root = os.path.join(tmp, "clone")
        outside = os.path.join(tmp, "outside")
        os.makedirs(os.path.join(self.root, "src"))
        os.makedirs(outside)
        for path in (os.path.join(self.root, "src", "a.md"),
                     os.path.join(outside, "secret.md")):
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("x\n")
        os.symlink(os.path.join(outside, "secret.md"),
                   os.path.join(self.root, "out.md"))
        os.symlink("src/a.md", os.path.join(self.root, "in.md"))
        os.symlink(outside, os.path.join(self.root, "dirlink"))
        os.symlink("src", os.path.join(self.root, "srclink"))
        os.symlink(os.path.join(tmp, "missing"),
                   os.path.join(self.root, "dangling.md"))

    def test_plain_file_resolves_inside_the_clone(self):
        self.assertEqual(arp.contained_file(self.root, "src/a.md"),
                         os.path.join(os.path.realpath(self.root), "src",
                                      "a.md"))

    def test_every_link_kind_is_refused(self):
        for rel in ("out.md", "in.md", "dirlink/secret.md",
                    "srclink/a.md", "dangling.md", "dirlink"):
            self.assertIsNone(arp.contained_file(self.root, rel), rel)

    def test_traversal_and_git_paths_are_refused(self):
        for rel in ("", "../outside/secret.md", "src/../../outside",
                    "./src/a.md", ".git/config", "src//a.md"):
            self.assertIsNone(arp.contained_file(self.root, rel), rel)

    def test_walk_lists_no_links(self):
        self.assertEqual(arp._walk_tree(self.root), ["src/a.md"])


class IndexContainmentTests(unittest.TestCase):
    def test_index_skips_committed_links(self):
        with tempfile.TemporaryDirectory() as tmp:
            outside = os.path.join(tmp, "outside.md")
            with open(outside, "w", encoding="utf-8") as handle:
                handle.write("%s\n" % MARKER)
            tracking = setup_tracking(tmp)
            os.symlink(outside, os.path.join(tracking["origin"], "notes.md"))
            os.symlink("README.md", os.path.join(tracking["origin"],
                                                 "CLAUDE.md"))
            commit_origin(tracking["origin"], "plant links")
            self.assertEqual(run_cli(tracking["config_path"], "update",
                                     "--actor", "test"), 0)
            self.assertTrue(os.path.islink(os.path.join(tracking["clone"],
                                                        "notes.md")))
            for full in (False, True):  # incremental (update), then full
                if full:
                    connection = arp.open_store(tracking["db"])
                    try:
                        self.assertEqual(arp.run_index(
                            connection, tracking["clone"],
                            tracking["config"]["index"])["mode"], "full")
                        connection.commit()
                    finally:
                        connection.close()
                paths = [r[0] for r in query(tracking["db"],
                                             "SELECT path FROM files")]
                self.assertNotIn("notes.md", paths)
                self.assertNotIn("CLAUDE.md", paths)
                self.assertIn("README.md", paths)
            hits = query(tracking["db"], "SELECT count(*) FROM files_fts "
                         "WHERE files_fts MATCH ?", (MARKER,))
            self.assertEqual(hits[0][0], 0)


class DiskCeilingTests(unittest.TestCase):
    def test_low_disk_stops_the_fetch(self):
        with tempfile.TemporaryDirectory() as tmp:
            tracking = setup_tracking(tmp, min_free_bytes=1000)
            prev = git(tracking["clone"], "rev-parse", "HEAD")
            with open(os.path.join(tracking["origin"], "n.md"), "w",
                      encoding="utf-8") as handle:
                handle.write("n\n")
            commit_origin(tracking["origin"])
            with mock.patch.object(arp, "_disk_free", return_value=10):
                self.assertEqual(run_cli(tracking["config_path"], "update",
                                         "--actor", "test"), 1)
            self.assertEqual(last_run(tracking["db"])["status"],
                             "disk-limited")
            self.assertEqual(git(tracking["clone"], "rev-parse", "HEAD"),
                             prev)
            self.assertNotEqual(
                git(tracking["clone"], "rev-parse", "origin/main"),
                git(tracking["origin"], "rev-parse", "HEAD"))


if __name__ == "__main__":
    unittest.main()
