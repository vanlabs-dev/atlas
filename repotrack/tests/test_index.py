"""Incremental indexing: filters, changed-subset, removal, rebuild."""

import json
import os
import tempfile
import unittest

from _helpers import (arp, change_ranges, commit_origin, git, query,
                      run_cli, set_meta, setup_tracking,
                      write_origin_file)


def indexed_paths(db):
    return sorted(row[0] for row in query(db, "SELECT path FROM files"))


def fts_hits(db, term):
    return sorted(row[0] for row in query(
        db, "SELECT f.path FROM files_fts JOIN files f "
            "ON f.id = files_fts.rowid WHERE files_fts MATCH ?", (term,)))


class InitialIndexTests(unittest.TestCase):
    def test_full_index_respects_filters(self):
        with tempfile.TemporaryDirectory() as tmp:
            tracking = setup_tracking(tmp)
            origin = tracking["origin"]
            write_origin_file(origin, "assets/blob.bin",
                              b"\x00\x01\x02binary", binary=True)
            write_origin_file(origin, "notes/skipped.xyz", "wrong ext\n")
            write_origin_file(origin, "docs/huge.md", "x" * 8192)
            commit_origin(origin, "filter fixtures")
            run_cli(tracking["config_path"], "update", "--actor", "test")

            paths = indexed_paths(tracking["db"])
            self.assertIn("README.md", paths)
            self.assertIn("pallets/subtensor/src/lib.rs", paths)
            self.assertNotIn("assets/blob.bin", paths)      # binary sniff
            self.assertNotIn("notes/skipped.xyz", paths)    # extension
            self.assertNotIn("docs/huge.md", paths)         # size cap

    def test_fts_and_sha_provenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            tracking = setup_tracking(tmp)
            self.assertEqual(fts_hits(tracking["db"], "conviction"),
                             ["pallets/subtensor/src/lib.rs"])
            sha = git(tracking["clone"], "rev-parse", "HEAD")
            rows = query(tracking["db"],
                         "SELECT DISTINCT indexed_sha FROM files")
            self.assertEqual(rows, [(sha,)])
            meta = dict(query(tracking["db"],
                              "SELECT key, value FROM meta"))
            self.assertEqual(meta[arp.META_INDEXED_SHA], sha)
            self.assertEqual(meta[arp.META_INDEXER_SCHEMA],
                             arp.INDEXER_SCHEMA_VERSION)


class IncrementalTests(unittest.TestCase):
    def test_only_changed_files_touched(self):
        with tempfile.TemporaryDirectory() as tmp:
            tracking = setup_tracking(tmp)
            origin = tracking["origin"]
            untouched_before = query(
                tracking["db"], "SELECT indexed_at FROM files WHERE "
                "path = ?", ("scripts/run.sh",))

            write_origin_file(origin, "README.md",
                              "# Fixture subtensor\nrevised emission text\n")
            write_origin_file(origin, "docs/added.md", "brand new doc\n")
            os.remove(os.path.join(origin, "pallets", "subtensor", "src",
                                   "lib.rs"))
            commit_origin(origin, "modify, add, remove")
            self.assertEqual(run_cli(tracking["config_path"], "update",
                                     "--actor", "test"), 0)

            record = change_ranges(tracking["db"])[-1]
            outcome = json.loads(record["index_detail"])
            self.assertEqual(outcome["mode"], "incremental")

            paths = indexed_paths(tracking["db"])
            self.assertIn("docs/added.md", paths)
            self.assertNotIn("pallets/subtensor/src/lib.rs", paths)
            self.assertEqual(fts_hits(tracking["db"], "revised"),
                             ["README.md"])
            self.assertEqual(fts_hits(tracking["db"], "conviction"), [])
            untouched_after = query(
                tracking["db"], "SELECT indexed_at FROM files WHERE "
                "path = ?", ("scripts/run.sh",))
            self.assertEqual(untouched_before, untouched_after)

    def test_schema_bump_forces_recorded_rebuild(self):
        with tempfile.TemporaryDirectory() as tmp:
            tracking = setup_tracking(tmp)
            set_meta(tracking["db"], arp.META_INDEXER_SCHEMA, "0")
            write_origin_file(tracking["origin"], "docs/next.md", "next\n")
            commit_origin(tracking["origin"])
            self.assertEqual(run_cli(tracking["config_path"], "update",
                                     "--actor", "test"), 0)
            record = change_ranges(tracking["db"])[-1]
            outcome = json.loads(record["index_detail"])
            self.assertEqual(outcome["mode"], "rebuild")
            meta = dict(query(tracking["db"],
                              "SELECT key, value FROM meta"))
            self.assertEqual(meta[arp.META_INDEXER_SCHEMA],
                             arp.INDEXER_SCHEMA_VERSION)

    def test_rewrite_falls_back_to_full_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            tracking = setup_tracking(tmp)
            origin = tracking["origin"]
            anchor = git(origin, "rev-parse", "HEAD")
            write_origin_file(origin, "docs/x.md", "x\n")
            commit_origin(origin)
            run_cli(tracking["config_path"], "update", "--actor", "test")
            git(origin, "reset", "--hard", anchor)
            write_origin_file(origin, "docs/y.md", "y\n")
            commit_origin(origin)
            run_cli(tracking["config_path"], "update", "--actor", "test")
            record = change_ranges(tracking["db"])[-1]
            self.assertEqual(record["non_fast_forward"], 1)
            outcome = json.loads(record["index_detail"])
            self.assertEqual(outcome["mode"], "full")
            paths = indexed_paths(tracking["db"])
            self.assertIn("docs/y.md", paths)
            self.assertNotIn("docs/x.md", paths)


if __name__ == "__main__":
    unittest.main()
