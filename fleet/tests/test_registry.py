"""Registry-layer units: URL normalization, fingerprinting, and the
SQLite registry store. Pure logic and a temp-file store — no network."""

import os
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

from _helpers import fleet  # noqa: E402


class NormalizeRepoUrlTests(unittest.TestCase):
    def test_plain_github_https_is_canonical(self):
        url, reason = fleet.normalize_repo_url(
            "https://github.com/macrocosm-os/apex")
        self.assertEqual(url, "https://github.com/macrocosm-os/apex")
        self.assertEqual(reason, "ok")

    def test_trailing_git_and_slash_normalize_equal(self):
        a, _ = fleet.normalize_repo_url("https://github.com/Org/Repo.git")
        b, _ = fleet.normalize_repo_url("https://github.com/Org/Repo/")
        self.assertEqual(a, b)
        self.assertEqual(a, "https://github.com/org/repo")

    def test_bare_owner_repo_assumes_github(self):
        url, reason = fleet.normalize_repo_url("macrocosm-os/apex")
        self.assertEqual(url, "https://github.com/macrocosm-os/apex")
        self.assertEqual(reason, "ok")

    def test_http_is_upgraded_to_https(self):
        url, _ = fleet.normalize_repo_url("http://github.com/o/r")
        self.assertEqual(url, "https://github.com/o/r")

    def test_subdir_or_tree_link_reduces_to_repo_root(self):
        url, _ = fleet.normalize_repo_url(
            "https://github.com/o/r/tree/main/pkg")
        self.assertEqual(url, "https://github.com/o/r")

    def test_case_is_normalized_consistently(self):
        a, _ = fleet.normalize_repo_url("https://GitHub.com/Macrocosm-OS/Apex")
        b, _ = fleet.normalize_repo_url("https://github.com/macrocosm-os/apex")
        self.assertEqual(a, b)

    def test_www_host_prefix_is_stripped(self):
        url, reason = fleet.normalize_repo_url("https://www.github.com/o/r")
        self.assertEqual(url, "https://github.com/o/r")
        self.assertEqual(reason, "ok")

    def test_empty_is_rejected(self):
        url, reason = fleet.normalize_repo_url("   ")
        self.assertIsNone(url)
        self.assertEqual(reason, "empty")

    def test_none_is_rejected(self):
        url, reason = fleet.normalize_repo_url(None)
        self.assertIsNone(url)
        self.assertEqual(reason, "empty")

    def test_non_github_host_rejected(self):
        url, reason = fleet.normalize_repo_url("https://gitlab.com/o/r")
        self.assertIsNone(url)
        self.assertEqual(reason, "unsupported-host")

    def test_ssh_scp_form_rejected(self):
        url, reason = fleet.normalize_repo_url("git@github.com:o/r.git")
        self.assertIsNone(url)
        self.assertEqual(reason, "unparsable")

    def test_whitespace_inside_rejected(self):
        url, reason = fleet.normalize_repo_url("not a url at all")
        self.assertIsNone(url)
        self.assertEqual(reason, "unparsable")

    def test_github_org_root_without_repo_rejected(self):
        url, reason = fleet.normalize_repo_url("https://github.com/only-owner")
        self.assertIsNone(url)
        self.assertEqual(reason, "unparsable")


class FingerprintTests(unittest.TestCase):
    def test_same_owner_and_url_is_stable(self):
        a = fleet.fingerprint("5Owner", "https://github.com/o/r")
        b = fleet.fingerprint("5Owner", "https://github.com/o/r")
        self.assertEqual(a, b)

    def test_changed_repo_changes_fingerprint(self):
        a = fleet.fingerprint("5Owner", "https://github.com/o/r")
        b = fleet.fingerprint("5Owner", "https://github.com/o/other")
        self.assertNotEqual(a, b)

    def test_changed_owner_changes_fingerprint(self):
        a = fleet.fingerprint("5OwnerA", "https://github.com/o/r")
        b = fleet.fingerprint("5OwnerB", "https://github.com/o/r")
        self.assertNotEqual(a, b)

    def test_fingerprint_takes_only_owner_and_url(self):
        # The signature itself excludes the subnet name: a rename cannot
        # change the fingerprint because the name is never an input.
        self.assertEqual(fleet.fingerprint.__code__.co_argcount, 2)


class RegistryStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = os.path.join(self.tmp, "fleet.db")

    def test_open_store_is_idempotent(self):
        conn = fleet.open_store(self.db)
        conn.close()
        conn = fleet.open_store(self.db)  # second open must not error
        conn.close()
        self.assertTrue(os.path.exists(self.db))

    def test_upsert_then_read_slot_roundtrips(self):
        conn = fleet.open_store(self.db)
        try:
            fleet.upsert_slot(conn, {
                "netuid": 23,
                "github_repo": "https://github.com/o/r",
                "owner_ss58": "5Owner",
                "fingerprint": "fp1",
                "epoch": 1,
                "default_branch": "main",
                "status": "active",
                "local_sha": "abc123",
                "clone_size_bytes": 4096,
                "first_seen_block": 100,
            })
            conn.commit()
            slot = fleet.get_slot(conn, 23)
        finally:
            conn.close()
        self.assertEqual(slot["netuid"], 23)
        self.assertEqual(slot["fingerprint"], "fp1")
        self.assertEqual(slot["status"], "active")
        self.assertEqual(slot["epoch"], 1)

    def test_upsert_updates_existing_slot(self):
        conn = fleet.open_store(self.db)
        try:
            fleet.upsert_slot(conn, {"netuid": 5, "status": "pending",
                                     "fingerprint": "fp1", "epoch": 1})
            fleet.upsert_slot(conn, {"netuid": 5, "status": "active",
                                     "fingerprint": "fp1", "epoch": 1,
                                     "local_sha": "deadbeef"})
            conn.commit()
            slot = fleet.get_slot(conn, 5)
        finally:
            conn.close()
        self.assertEqual(slot["status"], "active")
        self.assertEqual(slot["local_sha"], "deadbeef")

    def test_all_slots_returns_every_row(self):
        conn = fleet.open_store(self.db)
        try:
            for netuid in (1, 2, 3):
                fleet.upsert_slot(conn, {"netuid": netuid, "status": "active",
                                         "fingerprint": "fp", "epoch": 1})
            conn.commit()
            rows = fleet.all_slots(conn)
        finally:
            conn.close()
        self.assertEqual(sorted(row["netuid"] for row in rows), [1, 2, 3])

    def test_get_missing_slot_returns_none(self):
        conn = fleet.open_store(self.db)
        try:
            self.assertIsNone(fleet.get_slot(conn, 999))
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
