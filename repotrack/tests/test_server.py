"""MCP server contract over real pipes against a real tracked fixture."""

import ast
import os
import re
import tempfile
import unittest

from _helpers import (SERVER_SOURCE, arp, call_server, commit_origin, git,
                      make_config, run_cli, set_meta, setup_tracking,
                      tool_call, write_origin_file)


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.tracking = setup_tracking(cls.tmp.name)
        write_origin_file(cls.tracking["origin"], "docs/change.md",
                          "recorded change fixture\n")
        commit_origin(cls.tracking["origin"], "one recorded change")
        assert run_cli(cls.tracking["config_path"], "update",
                       "--actor", "test") == 0
        cls.config_path = cls.tracking["config_path"]

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_handshake_and_tools_list(self):
        payloads = call_server(self.config_path, [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize",
             "params": {"protocolVersion": "2025-06-18"}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        ])
        self.assertEqual(payloads[1]["serverInfo"]["name"], "atlas-repo")
        self.assertEqual(
            sorted(tool["name"] for tool in payloads[2]["tools"]),
            ["repo_changes", "repo_file", "repo_search", "repo_status"])

    def test_search_carries_sha_and_path_provenance(self):
        payloads = call_server(self.config_path, [tool_call(
            1, "repo_search", {"query": "conviction pallet"})])
        result = payloads[1]
        self.assertEqual(result["status"], "ok")
        top = result["results"][0]
        self.assertEqual(top["path"], "pallets/subtensor/src/lib.rs")
        self.assertEqual(top["indexed_sha"],
                         git(self.tracking["clone"], "rev-parse", "HEAD"))
        self.assertIn("snippet", top)

    def test_no_match_is_structured_no_evidence(self):
        payloads = call_server(self.config_path, [tool_call(
            1, "repo_search", {"query": "zzqx quantum spaghetti"})])
        self.assertEqual(payloads[1]["status"], "no-repository-evidence")

    def test_file_roundtrip_with_commit_sha(self):
        payloads = call_server(self.config_path, [tool_call(
            1, "repo_file", {"path": "docs/change.md"})])
        result = payloads[1]
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["commit_sha"],
                         git(self.tracking["clone"], "rev-parse", "HEAD"))
        self.assertIn("recorded change fixture", result["content"])
        self.assertEqual(result["lines"][0], 1)

    def test_file_path_guards(self):
        payloads = call_server(self.config_path, [
            tool_call(1, "repo_file", {"path": "../outside.txt"}),
            tool_call(2, "repo_file", {"path": ".git/config"}),
            tool_call(3, "repo_file", {"path": "docs/absent.md"}),
        ])
        self.assertEqual(payloads[1]["error"]["category"], "invalid")
        self.assertEqual(payloads[2]["error"]["category"], "invalid")
        self.assertEqual(payloads[3]["error"]["category"], "not-found")

    def test_changes_reports_recorded_range(self):
        payloads = call_server(self.config_path, [tool_call(
            1, "repo_changes")])
        result = payloads[1]
        self.assertEqual(result["status"], "ok")
        record = result["ranges"][0]
        self.assertFalse(record["non_fast_forward"])
        self.assertIn("docs/change.md", record["changed_files"])
        self.assertTrue(record["summary"].startswith(arp.SUMMARY_LABEL))
        self.assertEqual(record["index_status"], "ok")

    def test_status_answers_freshness_fields(self):
        payloads = call_server(self.config_path, [tool_call(
            1, "repo_status")])
        result = payloads[1]
        self.assertEqual(result["status"], "ok")
        for key in ("local_sha", "remote_sha_last_fetch",
                    "last_fetch_attempt", "last_fetch_success",
                    "last_detected_update", "working_tree_clean",
                    "index_matches_local_sha", "stale",
                    "stale_policy_hours"):
            self.assertIn(key, result)
        self.assertFalse(result["stale"])
        self.assertTrue(result["index_matches_local_sha"])


class InconsistentStateTests(unittest.TestCase):
    def test_dirty_tree_refuses_file_and_flags_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            tracking = setup_tracking(tmp)
            with open(os.path.join(tracking["clone"], "README.md"), "a",
                      encoding="utf-8") as handle:
                handle.write("drift\n")
            payloads = call_server(tracking["config_path"], [
                tool_call(1, "repo_file", {"path": "README.md"}),
                tool_call(2, "repo_status"),
            ])
            self.assertEqual(payloads[1]["error"]["category"],
                             "stale-state")
            self.assertFalse(payloads[2]["working_tree_clean"])

    def test_index_sha_mismatch_refuses_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            tracking = setup_tracking(tmp)
            set_meta(tracking["db"], arp.META_INDEXED_SHA, "deadbeef")
            payloads = call_server(tracking["config_path"], [
                tool_call(1, "repo_file", {"path": "README.md"})])
            self.assertEqual(payloads[1]["error"]["category"],
                             "stale-state")

    def test_old_fetch_reports_stale_never_current(self):
        with tempfile.TemporaryDirectory() as tmp:
            tracking = setup_tracking(tmp)
            run_cli(tracking["config_path"], "update", "--actor", "test")
            set_meta(tracking["db"], arp.META_LAST_FETCH_SUCCESS,
                     "2020-01-01T00:00:00+00:00")
            payloads = call_server(tracking["config_path"], [
                tool_call(1, "repo_status")])
            self.assertEqual(payloads[1]["status"], "stale")
            self.assertTrue(payloads[1]["stale"])


class UnavailableTests(unittest.TestCase):
    def test_missing_store_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            origin = os.path.join(tmp, "no-origin")
            config_path, _config = make_config(tmp, origin)
            payloads = call_server(config_path, [
                tool_call(1, "repo_search", {"query": "anything"}),
                tool_call(2, "repo_status"),
            ])
            for request_id in (1, 2):
                error = payloads[request_id]["error"]
                self.assertEqual(error["category"],
                                 "repository-tracking-unavailable")
                self.assertIn("correlation_id", error)
                self.assertIn("retry_safe", error)

    def test_missing_clone_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            origin = os.path.join(tmp, "no-origin")
            config_path, config = make_config(tmp, origin)
            arp.open_store(config["db"]).close()
            payloads = call_server(config_path, [
                tool_call(1, "repo_changes")])
            self.assertEqual(payloads[1]["error"]["category"],
                             "repository-tracking-unavailable")

    def test_audit_lines_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            tracking = setup_tracking(tmp)
            call_server(tracking["config_path"],
                        [tool_call(1, "repo_status")])
            audit_path = os.path.join(os.path.dirname(tracking["db"]),
                                      "tool-audit.jsonl")
            self.assertTrue(os.path.exists(audit_path))


class ReadOnlySurfaceTests(unittest.TestCase):
    def setUp(self):
        with open(SERVER_SOURCE, "r", encoding="utf-8") as handle:
            self.source = handle.read()

    def test_import_allowlist(self):
        allowed = {"datetime", "json", "os", "re", "sqlite3", "sys",
                   "secrets", "typing", "__future__", "atlas_repo"}
        imported = set()
        for node in ast.walk(ast.parse(self.source)):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add(node.module or "")
        self.assertEqual(imported - allowed, set())
        for banned in ("subprocess", "urllib", "socket", "http"):
            self.assertNotIn(banned, imported)

    def test_only_read_only_repo_helpers_used(self):
        # every atlas_repo call the server makes is read-only; the
        # mutating pipeline (setup/update/index) is unreachable from here
        allowed = {"load_config", "_resolve", "local_sha",
                   "working_tree_dirty", "freshness", "FatalRepoError",
                   "META_INDEXED_SHA", "CONFIG_FILE"}
        used = set(re.findall(r"\barp\.(\w+)", self.source))
        self.assertEqual(used - allowed, set())

    def test_store_opened_read_only(self):
        for match in re.finditer(r"sqlite3\.connect\(([^)]*)\)",
                                 self.source):
            self.assertIn("uri=True", match.group(1))
        self.assertIn("mode=ro", self.source)

    def test_no_raw_sql_surface(self):
        self.assertNotIn("format(query", self.source)
        self.assertIn("_TOKEN.findall", self.source)


if __name__ == "__main__":
    unittest.main()
