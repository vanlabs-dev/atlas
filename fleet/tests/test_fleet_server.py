"""Read-only atlas-fleet MCP server: tool contract, provenance, staleness,
path-escape, query safety, fail-closed, and audit — mirroring the accepted
atlas-repo server contract, generalized across the fleet."""

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
import test_driver as td  # noqa: E402

SERVER = os.path.join(os.path.dirname(_HERE), "atlas_fleet_server.py")


def call_server(config_path, requests, timeout=60):
    stdin = "\n".join(json.dumps(request) for request in requests) + "\n"
    completed = subprocess_run(config_path, stdin, timeout)
    payloads = {}
    for line in completed.stdout.strip().splitlines():
        response = json.loads(line)
        result = response.get("result") or {}
        if "content" in result:
            payloads[response["id"]] = json.loads(result["content"][0]["text"])
        else:
            payloads[response["id"]] = result
    return payloads


def subprocess_run(config_path, stdin, timeout):
    import subprocess
    return subprocess.run(
        [sys.executable, SERVER, "--config", config_path],
        input=stdin, capture_output=True, text=True, timeout=timeout,
        encoding="utf-8", errors="replace")


def call(request_id, name, arguments=None):
    return {"jsonrpc": "2.0", "id": request_id, "method": "tools/call",
            "params": {"name": name, "arguments": arguments or {}}}


def write_config(path, db, clone_root):
    with open(path, "w", encoding="utf-8") as handle:
        json.dump({"db": db, "clone_root": clone_root,
                   "index": {"extensions": [".py", ".md"],
                             "max_file_bytes": 4096}}, handle)
    return path


class ServerBase(td.DriverTestBase):
    def setUp(self):
        super().setUp()
        self.config_path = os.path.join(self.tmp, "fleetcfg.json")
        write_config(self.config_path, self.db, self.clone_root)

    def clone(self, netuid, url):
        self.reconcile(td.identity_result([td.subnet(netuid, url)]))

    def ask(self, name, arguments=None):
        return call_server(self.config_path,
                           [call(1, name, arguments)])[1]


class ToolListTests(ServerBase):
    def test_lists_the_read_only_tool_set(self):
        """Three code-search tools plus the three mining-triage tools added
        by the mining-triage change. All read-only."""
        payloads = call_server(self.config_path, [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}])
        names = {tool["name"] for tool in payloads[2]["tools"]}
        self.assertEqual(names, {"fleet_search", "fleet_file", "fleet_status",
                                 "mining_board", "mining_subnet",
                                 "mining_history"})


class SearchTests(ServerBase):
    def setUp(self):
        super().setUp()
        self.clone(1, "https://github.com/test/a")   # README.md "fixture subnet repo"
        self.reconcile(td.identity_result([
            td.subnet(1, "https://github.com/test/a"),
            td.subnet(2, "https://github.com/test/b")]))  # origin_b lib.py

    def test_global_search_cites_provenance(self):
        out = self.ask("fleet_search", {"query": "fixture"})
        self.assertEqual(out["status"], "ok")
        hit = out["results"][0]
        for field in ("netuid", "github_repo", "path", "indexed_sha", "snippet"):
            self.assertIn(field, hit)
        self.assertEqual(hit["netuid"], 1)

    def test_netuid_scoped_search(self):
        out = self.ask("fleet_search", {"query": "fixture", "netuid": 1})
        self.assertTrue(all(r["netuid"] == 1 for r in out["results"]))

    def test_no_match_is_no_evidence(self):
        out = self.ask("fleet_search", {"query": "zzznotpresentzzz"})
        self.assertEqual(out["status"], "no-fleet-evidence")

    def test_fts_operators_are_handled_safely(self):
        out = self.ask("fleet_search", {"query": 'fixture OR ("* '})
        self.assertIn(out["status"], ("ok", "no-fleet-evidence"))

    def test_invalid_netuid_rejected(self):
        out = self.ask("fleet_search", {"query": "fixture", "netuid": -5})
        self.assertIn("error", out)


class FileTests(ServerBase):
    def setUp(self):
        super().setUp()
        self.clone(1, "https://github.com/test/a")

    def test_reads_a_bounded_slice(self):
        out = self.ask("fleet_file", {"netuid": 1, "path": "README.md"})
        self.assertEqual(out["status"], "ok")
        self.assertIn("fixture", out["content"])
        self.assertEqual(out["netuid"], 1)

    def test_path_escape_refused(self):
        out = self.ask("fleet_file", {"netuid": 1, "path": "../../etc/passwd"})
        self.assertIn("error", out)
        self.assertEqual(out["error"]["category"], "invalid")

    def test_unknown_netuid_refused(self):
        out = self.ask("fleet_file", {"netuid": 999, "path": "README.md"})
        self.assertIn("error", out)

    def test_staleness_refusal_when_clone_advances_past_index(self):
        clone_dir = os.path.join(self.clone_root, "1")
        indexed_sha = h.git(clone_dir, "rev-parse", "HEAD")
        # advance the clone without reindexing (index_state stays at indexed_sha)
        h.add_commit(self.origin_a, "src/new.py", "n = 1\n")
        fleet.update_clone(clone_dir, "main", indexed_sha)
        self.assertNotEqual(h.git(clone_dir, "rev-parse", "HEAD"), indexed_sha)
        out = self.ask("fleet_file", {"netuid": 1, "path": "README.md"})
        self.assertIn("error", out)
        self.assertEqual(out["error"]["category"], "stale-state")


class StatusTests(ServerBase):
    def test_coverage_and_per_netuid(self):
        self.clone(1, "https://github.com/test/a")
        overall = self.ask("fleet_status")
        self.assertIn("index", overall)
        self.assertGreaterEqual(overall["index"]["indexed_slots"], 1)
        one = self.ask("fleet_status", {"netuid": 1})
        self.assertTrue(one["indexed"])
        self.assertFalse(one["stale"])


class FailClosedTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.db = os.path.join(self.tmp, "fleet.db")
        # A reconcile store with NO index tables (fleet index never built).
        fleet.open_store(self.db).close()
        self.clone_root = os.path.join(self.tmp, "clones")
        os.makedirs(self.clone_root)
        self.config_path = write_config(
            os.path.join(self.tmp, "cfg.json"), self.db, self.clone_root)

    def test_every_tool_fails_closed_without_an_index(self):
        for name, args in (("fleet_search", {"query": "x"}),
                           ("fleet_file", {"netuid": 1, "path": "a"}),
                           ("fleet_status", {})):
            out = call_server(self.config_path, [call(1, name, args)])[1]
            self.assertIn("error", out, name)
            self.assertEqual(out["error"]["category"],
                             "fleet-search-unavailable", name)

    def test_calls_are_audited(self):
        call_server(self.config_path, [call(1, "fleet_search", {"query": "x"})])
        audit_path = os.path.join(os.path.dirname(self.db), "tool-audit.jsonl")
        self.assertTrue(os.path.exists(audit_path))
        with open(audit_path, encoding="utf-8") as handle:
            line = json.loads(handle.read().splitlines()[0])
        self.assertEqual(line["tool"], "fleet_search")


if __name__ == "__main__":
    unittest.main()
