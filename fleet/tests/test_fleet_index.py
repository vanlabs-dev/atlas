"""Shared fleet FTS index: schema, index_slot (full/incremental guard),
purge, freshness, and search — generalizing repotrack's files/files_fts
pattern across the ~104-clone fleet, scoped by (netuid, epoch)."""

import os
import sys
import tempfile
import shutil
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_FLEET_DIR = os.path.dirname(_HERE)
sys.path.insert(0, _HERE)
sys.path.insert(0, _FLEET_DIR)

import _helpers as h  # noqa: E402
from _helpers import fleet  # noqa: E402
import atlas_fleet_index as idx  # noqa: E402

INDEX_CFG = {"extensions": [".py", ".md", ".rs", ".ts", ".go", ".sol"],
             "max_file_bytes": 4096}


def _table_names(conn):
    return {row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type IN ('table','view')")}


def _indexed_paths(conn, netuid):
    return sorted(row[0] for row in conn.execute(
        "SELECT path FROM fleet_files WHERE netuid=?", (netuid,)))


def _fts_hits(conn, term, netuid=None):
    sql = ("SELECT ff.netuid, ff.path FROM fleet_files_fts "
           "JOIN fleet_files ff ON ff.id = fleet_files_fts.rowid "
           "WHERE fleet_files_fts MATCH ?")
    params = [term]
    if netuid is not None:
        sql += " AND ff.netuid = ?"
        params.append(netuid)
    return sorted(tuple(row) for row in conn.execute(sql, params))


class IndexBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.db = os.path.join(self.tmp, "fleet.db")
        self.conn = fleet.open_store(self.db)
        self.addCleanup(self.conn.close)
        idx.ensure_schema(self.conn)

    def clone_of(self, netuid, files):
        origin = h.make_origin(self.tmp, name="origin_%s" % netuid, files=files)
        clone_dir = os.path.join(self.tmp, "clone_%s" % netuid)
        state = fleet.setup_clone(clone_dir, origin)
        self.assertEqual(state["status"], "active", state)
        return origin, clone_dir

    def state_of(self, netuid):
        row = self.conn.execute(
            "SELECT epoch, indexed_sha, indexer_schema, files FROM "
            "index_state WHERE netuid=?", (netuid,)).fetchone()
        return dict(zip(("epoch", "indexed_sha", "indexer_schema", "files"),
                        row)) if row else None


class SchemaTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.db = os.path.join(self.tmp, "fleet.db")
        self.conn = fleet.open_store(self.db)
        self.addCleanup(self.conn.close)

    def test_ensure_schema_creates_index_tables_idempotently(self):
        idx.ensure_schema(self.conn)
        idx.ensure_schema(self.conn)  # idempotent
        names = _table_names(self.conn)
        self.assertIn("fleet_files", names)
        self.assertIn("fleet_files_fts", names)
        self.assertIn("index_state", names)

    def test_reconcile_tables_untouched(self):
        # The indexer owns its tables; it must not disturb the reconcile store.
        idx.ensure_schema(self.conn)
        names = _table_names(self.conn)
        for reconcile_table in ("slots", "epochs", "change_ranges", "audit"):
            self.assertIn(reconcile_table, names)


class IndexSlotTests(IndexBase):
    def test_full_walk_respects_filters_and_records_state(self):
        _origin, clone = self.clone_of(1, {
            "README.md": "# subnet one\nemission logic\n",
            "src/lib.rs": "// conviction\npub fn go() {}\n",
            "notes/skip.xyz": "wrong ext\n",
            "big.md": "x" * 8192,
            "blob.bin": "\x00\x01\x02okay",
        })
        out = idx.index_slot(self.conn, 1, 1, clone, INDEX_CFG)
        self.assertEqual(out["mode"], "full")
        paths = _indexed_paths(self.conn, 1)
        self.assertIn("README.md", paths)
        self.assertIn("src/lib.rs", paths)
        self.assertNotIn("notes/skip.xyz", paths)   # extension
        self.assertNotIn("big.md", paths)            # size cap
        self.assertNotIn("blob.bin", paths)          # binary sniff
        sha = h.git(clone, "rev-parse", "HEAD")
        st = self.state_of(1)
        self.assertEqual(st["indexed_sha"], sha)
        self.assertEqual(st["epoch"], 1)
        self.assertEqual(st["indexer_schema"], idx.INDEXER_SCHEMA_VERSION)
        rows = self.conn.execute("SELECT DISTINCT indexed_sha, epoch FROM "
                                 "fleet_files WHERE netuid=1").fetchall()
        self.assertEqual(rows, [(sha, 1)])

    def test_two_netuids_sharing_a_path_do_not_collide(self):
        _o1, c1 = self.clone_of(1, {"README.md": "alpha one\n"})
        _o2, c2 = self.clone_of(2, {"README.md": "beta two\n"})
        idx.index_slot(self.conn, 1, 1, c1, INDEX_CFG)
        idx.index_slot(self.conn, 2, 1, c2, INDEX_CFG)
        self.assertEqual(_fts_hits(self.conn, "alpha"), [(1, "README.md")])
        self.assertEqual(_fts_hits(self.conn, "beta"), [(2, "README.md")])
        self.assertEqual(_indexed_paths(self.conn, 1), ["README.md"])
        self.assertEqual(_indexed_paths(self.conn, 2), ["README.md"])

    def test_incremental_touches_only_changed_paths(self):
        origin, clone = self.clone_of(1, {
            "README.md": "one\noriginal\n", "keep.py": "k = 1\n",
            "gone.py": "g = 1\n"})
        idx.index_slot(self.conn, 1, 1, clone, INDEX_CFG)
        keep_before = self.conn.execute(
            "SELECT indexed_at FROM fleet_files WHERE netuid=1 AND path=?",
            ("keep.py",)).fetchone()

        h.add_commit(origin, "README.md", "one\nrevised body\n")
        os.remove(os.path.join(origin, "gone.py"))
        h.add_commit(origin, "added.py", "a = 1\n")
        fleet.update_clone(clone, "main", h.git(clone, "rev-parse", "HEAD"))
        new_sha = h.git(clone, "rev-parse", "HEAD")
        out = idx.index_slot(self.conn, 1, 1, clone, INDEX_CFG,
                             changed_paths=["README.md", "gone.py", "added.py"],
                             local_sha=new_sha)
        self.assertEqual(out["mode"], "incremental")
        paths = _indexed_paths(self.conn, 1)
        self.assertIn("added.py", paths)
        self.assertNotIn("gone.py", paths)
        self.assertEqual(_fts_hits(self.conn, "revised"), [(1, "README.md")])
        self.assertEqual(_fts_hits(self.conn, "original"), [])
        keep_after = self.conn.execute(
            "SELECT indexed_at FROM fleet_files WHERE netuid=1 AND path=?",
            ("keep.py",)).fetchone()
        self.assertEqual(keep_before, keep_after)  # untouched row not rewritten
        self.assertEqual(self.state_of(1)["indexed_sha"], new_sha)


class IndexGuardTests(IndexBase):
    def test_noop_when_already_fresh(self):
        _o, clone = self.clone_of(1, {"README.md": "one\n"})
        idx.index_slot(self.conn, 1, 1, clone, INDEX_CFG)
        out = idx.index_slot(self.conn, 1, 1, clone, INDEX_CFG)
        self.assertEqual(out["mode"], "noop")

    def test_changed_paths_without_baseline_falls_back_to_full(self):
        # A slot cloned before the index existed (no index_state): an update's
        # changed-path list must NOT patch an absent baseline — full walk.
        _o, clone = self.clone_of(1, {"README.md": "one\n", "b.py": "b=1\n"})
        out = idx.index_slot(self.conn, 1, 1, clone, INDEX_CFG,
                             changed_paths=["README.md"])
        self.assertEqual(out["mode"], "full")
        self.assertEqual(_indexed_paths(self.conn, 1), ["README.md", "b.py"])

    def test_epoch_change_forces_full_and_purges_prior_rows(self):
        _o1, c1 = self.clone_of(1, {"README.md": "old project alpha\n"})
        idx.index_slot(self.conn, 1, 1, c1, INDEX_CFG)
        _o2, c2 = self.clone_of("1b", {"README.md": "new project beta\n"})
        # same netuid, new epoch (a re-point): a full walk that first purges.
        out = idx.index_slot(self.conn, 1, 2, c2, INDEX_CFG)
        self.assertEqual(out["mode"], "full")
        self.assertEqual(_fts_hits(self.conn, "alpha"), [])
        self.assertEqual(_fts_hits(self.conn, "beta"), [(1, "README.md")])
        self.assertEqual(self.state_of(1)["epoch"], 2)


class PurgeAndFreshnessTests(IndexBase):
    def test_purge_all_removes_rows_and_state(self):
        _o, clone = self.clone_of(1, {"README.md": "one\n", "a.py": "a=1\n"})
        idx.index_slot(self.conn, 1, 1, clone, INDEX_CFG)
        removed = idx.purge_slot(self.conn, 1)
        self.assertEqual(removed, 2)
        self.assertEqual(_indexed_paths(self.conn, 1), [])
        self.assertIsNone(self.state_of(1))
        self.assertEqual(_fts_hits(self.conn, "one"), [])

    def test_purge_one_epoch_leaves_the_other(self):
        # Two epochs' rows coexisting (crash-safety fixture): purging one epoch
        # leaves the other and leaves index_state intact.
        _o, clone = self.clone_of(1, {"README.md": "epoch one alpha\n"})
        idx.index_slot(self.conn, 1, 1, clone, INDEX_CFG)
        self.conn.execute(  # simulate a stray epoch-2 row for the same netuid
            "INSERT INTO fleet_files (netuid, epoch, path, indexed_sha, "
            "byte_size, indexed_at) VALUES (1, 2, 'ghost.py', 'deadbeef', 3, ?)",
            (idx._utc_now(),))
        idx.purge_slot(self.conn, 1, epoch=2)
        self.assertEqual(_indexed_paths(self.conn, 1), ["README.md"])
        self.assertIsNotNone(self.state_of(1))

    def test_freshness_tolerates_missing_index_tables(self):
        # A reconcile store that has never built the index (fresh deploy):
        # freshness must report zeros, never raise "no such table".
        bare = os.path.join(self.tmp, "bare.db")
        conn = fleet.open_store(bare)  # reconcile tables only, no index tables
        try:
            self.assertEqual(idx.index_freshness(conn),
                             {"indexed_slots": 0, "stale_slots": 0,
                              "total_indexed_files": 0})
            self.assertFalse(idx.index_freshness(conn, netuid=1)["indexed"])
        finally:
            conn.close()

    def test_freshness_reports_coverage_and_staleness(self):
        _o1, c1 = self.clone_of(1, {"README.md": "one\n"})
        _o2, c2 = self.clone_of(2, {"README.md": "two\n", "b.py": "b=1\n"})
        idx.index_slot(self.conn, 1, 1, c1, INDEX_CFG)
        idx.index_slot(self.conn, 2, 1, c2, INDEX_CFG)
        # slot rows the freshness join needs; slot 1's local_sha matches its
        # index, slot 2's clone has advanced past it (stale).
        fleet.upsert_slot(self.conn, {"netuid": 1, "status": "active",
                          "local_sha": idx._repotrack().local_sha(c1)})
        fleet.upsert_slot(self.conn, {"netuid": 2, "status": "active",
                          "local_sha": "advanced-past-index"})

        cov = idx.index_freshness(self.conn)
        self.assertEqual(cov["indexed_slots"], 2)
        self.assertEqual(cov["stale_slots"], 1)
        self.assertEqual(cov["total_indexed_files"], 3)

        one = idx.index_freshness(self.conn, netuid=1)
        self.assertTrue(one["indexed"])
        self.assertFalse(one["stale"])
        two = idx.index_freshness(self.conn, netuid=2)
        self.assertTrue(two["stale"])
        self.assertEqual(two["files"], 2)


class ShippedConfigTests(IndexBase):
    def test_shipped_config_index_block_drives_polyglot_filter(self):
        cfg = fleet.load_config().get("index")
        self.assertIsNotNone(cfg, "fleet/config.json needs an `index` block")
        for ext in (".ts", ".go", ".sol", ".py", ".rs"):
            self.assertIn(ext, cfg["extensions"])
        self.assertIn("max_file_bytes", cfg)
        _o, clone = self.clone_of(1, {
            "app.ts": "export const x = 1\n",
            "chain.go": "package main\n",
            "token.sol": "pragma solidity ^0.8;\n",
            "skip.xyz": "unlisted\n"})
        idx.index_slot(self.conn, 1, 1, clone, cfg)
        paths = _indexed_paths(self.conn, 1)
        self.assertIn("app.ts", paths)
        self.assertIn("chain.go", paths)
        self.assertIn("token.sol", paths)
        self.assertNotIn("skip.xyz", paths)


class SearchTests(IndexBase):
    def setUp(self):
        super().setUp()
        _o1, c1 = self.clone_of(1, {
            "src/emission.rs": "// emission schedule alpha\n"})
        _o2, c2 = self.clone_of(2, {
            "src/weights.py": "# weights and emission logic\n"})
        idx.index_slot(self.conn, 1, 1, c1, INDEX_CFG)
        idx.index_slot(self.conn, 2, 1, c2, INDEX_CFG)

    def test_global_search_spans_subnets(self):
        hits = idx.search(self.conn, "emission", max_results=10)
        netuids = sorted(hit["netuid"] for hit in hits)
        self.assertEqual(netuids, [1, 2])
        for hit in hits:
            self.assertIn("indexed_sha", hit)
            self.assertIn("snippet", hit)

    def test_netuid_scope_restricts(self):
        hits = idx.search(self.conn, "emission", netuid=1, max_results=10)
        self.assertEqual([hit["netuid"] for hit in hits], [1])

    def test_no_match_returns_empty(self):
        self.assertEqual(idx.search(self.conn, "nonexistentxyz"), [])

    def test_fts_operators_do_not_break_search(self):
        # A query full of FTS punctuation must reduce to safe tokens, not error.
        hits = idx.search(self.conn, 'emission OR (weights* "', max_results=10)
        self.assertTrue(hits)

    def test_tokenize_detects_empty_term_query(self):
        self.assertEqual(idx.tokenize("()* \"\" "), [])
        self.assertTrue(idx.tokenize("emission weights"))


if __name__ == "__main__":
    unittest.main()
