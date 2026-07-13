"""Safe update pipeline: every ATLAS-REPO-004/005/008 path over fixtures."""

import json
import os
import tempfile
import unittest

from _helpers import (arp, change_ranges, commit_origin, git, last_run,
                      make_config, make_origin, query, run_cli,
                      setup_tracking, write_origin_file)


class SetupTests(unittest.TestCase):
    def test_setup_full_clone_verified_and_push_disabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            tracking = setup_tracking(tmp)
            clone = tracking["clone"]
            self.assertEqual(
                git(clone, "rev-parse", "--is-shallow-repository"), "false")
            self.assertEqual(
                git(clone, "remote", "get-url", "--push", "origin"),
                arp.PUSH_URL_DISABLED)
            self.assertEqual(git(clone, "rev-parse", "--abbrev-ref",
                                 "HEAD"), "main")
            self.assertEqual(git(clone, "rev-parse", "HEAD"),
                             git(tracking["origin"], "rev-parse", "HEAD"))

    def test_setup_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            tracking = setup_tracking(tmp)
            self.assertEqual(run_cli(tracking["config_path"], "setup",
                                     "--actor", "test"), 0)

    def test_unconfirmed_identity_blocks_setup_and_update(self):
        with tempfile.TemporaryDirectory() as tmp:
            origin = make_origin(tmp)
            config_path, config = make_config(tmp, origin, confirmed=False)
            self.assertEqual(run_cli(config_path, "setup"), 1)
            self.assertFalse(os.path.exists(config["clone_dir"]))
            self.assertEqual(run_cli(config_path, "update"), 1)


class UpdateTests(unittest.TestCase):
    def test_normal_fast_forward_update(self):
        with tempfile.TemporaryDirectory() as tmp:
            tracking = setup_tracking(tmp)
            prev = git(tracking["clone"], "rev-parse", "HEAD")
            write_origin_file(tracking["origin"], "docs/new.md",
                              "conviction activation notes\n")
            new = commit_origin(tracking["origin"], "add activation notes")
            git(tracking["origin"], "tag", "v9.9.9")

            self.assertEqual(run_cli(tracking["config_path"], "update",
                                     "--actor", "test"), 0)
            run = last_run(tracking["db"])
            self.assertEqual(run["status"], "ok")
            self.assertEqual(run["prev_sha"], prev)
            self.assertEqual(run["new_sha"], new)
            self.assertEqual(run["fast_forward"], 1)
            self.assertEqual(git(tracking["clone"], "rev-parse", "HEAD"),
                             new)

            ranges = change_ranges(tracking["db"])
            self.assertEqual(len(ranges), 1)
            record = ranges[0]
            self.assertEqual((record["prev_sha"], record["new_sha"]),
                             (prev, new))
            self.assertEqual(record["non_fast_forward"], 0)
            commits = json.loads(record["commits_json"])["commits"]
            self.assertEqual(commits[0]["subject"],
                             "add activation notes")
            files = json.loads(record["files_json"])["files"]
            self.assertIn("docs/new.md",
                          [item["path"] for item in files])
            self.assertIsNotNone(files[0]["additions"])
            self.assertIn("v9.9.9", json.loads(record["tags_json"]))
            self.assertTrue(record["summary"].startswith(
                arp.SUMMARY_LABEL))
            self.assertEqual(record["index_status"], "ok")

    def test_no_change_run_recorded_without_change_range(self):
        with tempfile.TemporaryDirectory() as tmp:
            tracking = setup_tracking(tmp)
            self.assertEqual(run_cli(tracking["config_path"], "update",
                                     "--actor", "test"), 0)
            self.assertEqual(last_run(tracking["db"])["status"],
                             "no-change")
            self.assertEqual(change_ranges(tracking["db"]), [])

    def test_upstream_rewrite_deterministic_reset(self):
        with tempfile.TemporaryDirectory() as tmp:
            tracking = setup_tracking(tmp)
            origin = tracking["origin"]
            first = git(origin, "rev-parse", "HEAD~0")
            write_origin_file(origin, "docs/a.md", "will be rewritten\n")
            commit_origin(origin, "doomed commit")
            self.assertEqual(run_cli(tracking["config_path"], "update",
                                     "--actor", "test"), 0)
            # rewrite upstream history: drop the commit, add another
            git(origin, "reset", "--hard", first)
            write_origin_file(origin, "docs/b.md", "replacement line\n")
            rewritten = commit_origin(origin, "replacement commit")

            self.assertEqual(run_cli(tracking["config_path"], "update",
                                     "--actor", "test"), 0)
            run = last_run(tracking["db"])
            self.assertEqual(run["status"], "ok")
            self.assertEqual(run["fast_forward"], 0)
            self.assertEqual(git(tracking["clone"], "rev-parse", "HEAD"),
                             rewritten)
            record = change_ranges(tracking["db"])[-1]
            self.assertEqual(record["non_fast_forward"], 1)
            self.assertIn("NON-FAST-FORWARD", record["summary"])
            # no merge commit was ever created
            self.assertEqual(git(tracking["clone"], "rev-list", "--merges",
                                 "--count", "HEAD"), "0")

    def test_dirty_tree_aborts_and_preserves(self):
        with tempfile.TemporaryDirectory() as tmp:
            tracking = setup_tracking(tmp)
            prev = git(tracking["clone"], "rev-parse", "HEAD")
            marker = os.path.join(tracking["clone"], "README.md")
            with open(marker, "a", encoding="utf-8") as handle:
                handle.write("local drift\n")
            write_origin_file(tracking["origin"], "docs/c.md", "x\n")
            commit_origin(tracking["origin"])

            self.assertEqual(run_cli(tracking["config_path"], "update",
                                     "--actor", "test"), 1)
            run = last_run(tracking["db"])
            self.assertEqual(run["status"], "local-modifications")
            self.assertEqual(git(tracking["clone"], "rev-parse", "HEAD"),
                             prev)
            with open(marker, "r", encoding="utf-8") as handle:
                self.assertIn("local drift", handle.read())

    def test_remote_identity_mismatch_aborts_before_fetch(self):
        with tempfile.TemporaryDirectory() as tmp:
            tracking = setup_tracking(tmp)
            git(tracking["clone"], "remote", "set-url", "origin",
                tracking["origin"] + "-elsewhere")
            self.assertEqual(run_cli(tracking["config_path"], "update",
                                     "--actor", "test"), 1)
            run = last_run(tracking["db"])
            self.assertEqual(run["status"], "identity-mismatch")
            self.assertIsNone(run["new_sha"])

    def test_fetch_failure_preserves_last_good_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            tracking = setup_tracking(tmp)
            prev = git(tracking["clone"], "rev-parse", "HEAD")
            # move (not delete: Windows read-only .git objects) the origin
            # away so the fetch fails while the pinned URL still matches
            os.rename(tracking["origin"], tracking["origin"] + "-moved")
            self.assertEqual(run_cli(tracking["config_path"], "update",
                                     "--actor", "test"), 1)
            run = last_run(tracking["db"])
            self.assertEqual(run["status"], "fetch-failed")
            self.assertEqual(git(tracking["clone"], "rev-parse", "HEAD"),
                             prev)
            meta = dict(query(tracking["db"],
                              "SELECT key, value FROM meta"))
            self.assertIn(arp.META_LAST_FETCH_ATTEMPT, meta)
            self.assertNotIn(arp.META_LAST_FETCH_SUCCESS, meta)

    def test_update_never_invokes_build_or_push(self):
        source = open(os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "atlas_repo.py"),
            encoding="utf-8").read()
        for banned in ('"push"', '"commit"', '"rebase"', '"cargo"',
                       '"make"', '"filter-branch"'):
            self.assertNotIn(banned, source)


class SpecVersionTests(unittest.TestCase):
    """Runtime spec_version facts on change records (spec-tiering)."""

    MANIFEST = ("pub const VERSION: RuntimeVersion = RuntimeVersion {\n"
                "    spec_name: \"node-subtensor\",\n"
                "    spec_version: %d,\n"
                "};\n")

    def test_spec_bump_recorded_on_both_heads(self):
        with tempfile.TemporaryDirectory() as tmp:
            origin = make_origin(tmp, files={
                "runtime/src/lib.rs": self.MANIFEST % 428,
                "docs/a.md": "notes\n"})
            config_path, config = make_config(tmp, origin)
            self.assertEqual(run_cli(config_path, "setup",
                                     "--actor", "test"), 0)
            write_origin_file(origin, "runtime/src/lib.rs",
                              self.MANIFEST % 429)
            commit_origin(origin, "bump spec_version to 429")
            self.assertEqual(run_cli(config_path, "update",
                                     "--actor", "test"), 0)
            record = change_ranges(config["db"])[0]
            self.assertEqual(record["prev_spec"], 428)
            self.assertEqual(record["new_spec"], 429)

    def test_manifest_absent_recorded_unknown_update_succeeds(self):
        with tempfile.TemporaryDirectory() as tmp:
            tracking = setup_tracking(tmp)  # fixture has no runtime manifest
            write_origin_file(tracking["origin"], "docs/b.md", "more\n")
            commit_origin(tracking["origin"], "docs only")
            self.assertEqual(run_cli(tracking["config_path"], "update",
                                     "--actor", "test"), 0)
            record = change_ranges(tracking["db"])[0]
            self.assertIsNone(record["prev_spec"])
            self.assertIsNone(record["new_spec"])
            self.assertEqual(last_run(tracking["db"])["status"], "ok")

    def test_malformed_field_recorded_unknown_update_succeeds(self):
        with tempfile.TemporaryDirectory() as tmp:
            origin = make_origin(tmp, files={
                "runtime/src/lib.rs":
                    "// spec_version moved elsewhere, no numeric field\n",
                "docs/a.md": "notes\n"})
            config_path, config = make_config(tmp, origin)
            self.assertEqual(run_cli(config_path, "setup",
                                     "--actor", "test"), 0)
            write_origin_file(origin, "docs/a.md", "changed\n")
            commit_origin(origin, "docs change")
            self.assertEqual(run_cli(config_path, "update",
                                     "--actor", "test"), 0)
            record = change_ranges(config["db"])[0]
            self.assertIsNone(record["prev_spec"])
            self.assertIsNone(record["new_spec"])
            self.assertEqual(last_run(config["db"])["status"], "ok")

    def test_existing_store_migrates_additively(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "repotrack.db")
            legacy = ("CREATE TABLE change_ranges (id INTEGER PRIMARY KEY, "
                      "run_id TEXT NOT NULL, prev_sha TEXT NOT NULL, "
                      "new_sha TEXT NOT NULL, retrieved_at TEXT NOT NULL, "
                      "non_fast_forward INTEGER NOT NULL, "
                      "commits_json TEXT NOT NULL, files_json TEXT NOT NULL, "
                      "tags_json TEXT NOT NULL, index_status TEXT NOT NULL, "
                      "index_detail TEXT, summary TEXT NOT NULL);")
            import sqlite3
            conn = sqlite3.connect(db)
            conn.executescript(legacy)
            conn.execute(
                "INSERT INTO change_ranges (run_id, prev_sha, new_sha, "
                "retrieved_at, non_fast_forward, commits_json, files_json, "
                "tags_json, index_status, summary) VALUES "
                "('r1','a','b','t',0,'{}','{}','[]','ok','s')")
            conn.commit()
            conn.close()
            store = arp.open_store(db)
            row = store.execute("SELECT prev_spec, new_spec FROM "
                                "change_ranges").fetchone()
            store.close()
            self.assertEqual(row, (None, None))


class FreshnessTests(unittest.TestCase):
    def test_status_answers_every_field(self):
        with tempfile.TemporaryDirectory() as tmp:
            tracking = setup_tracking(tmp)
            run_cli(tracking["config_path"], "update", "--actor", "test")
            info = arp.freshness(tracking["db"], tracking["clone"],
                                 tracking["config"])
            for key in ("local_sha", "remote_sha_last_fetch",
                        "last_fetch_attempt", "last_fetch_success",
                        "last_detected_update", "working_tree_clean",
                        "index_matches_local_sha", "stale",
                        "stale_policy_hours", "clone_size_bytes"):
                self.assertIn(key, info)
            self.assertTrue(info["working_tree_clean"])
            self.assertTrue(info["index_matches_local_sha"])
            self.assertFalse(info["stale"])
            self.assertEqual(info["stale_policy_hours"], 48.0)

    def test_never_fetched_reports_stale(self):
        with tempfile.TemporaryDirectory() as tmp:
            tracking = setup_tracking(tmp)
            info = arp.freshness(tracking["db"], tracking["clone"],
                                 tracking["config"])
            self.assertTrue(info["stale"])
            self.assertIsNone(info["last_fetch_success"])


if __name__ == "__main__":
    unittest.main()
