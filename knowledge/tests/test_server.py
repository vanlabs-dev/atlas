"""MCP server behavior over real pipes against a real ingested store."""

import ast
import json
import os
import re
import tempfile
import unittest

from _helpers import (CORPUS_DIR, SERVER_SOURCE, akb, call_server,
                      ingest_real_corpus, tool_call)


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.db, cls.run_id, _report = ingest_real_corpus(cls.tmp.name)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_handshake_and_tools_list(self):
        payloads = call_server(self.db, [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize",
             "params": {"protocolVersion": "2025-06-18"}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        ])
        self.assertEqual(payloads[1]["serverInfo"]["name"], "atlas-kb")
        self.assertEqual(
            sorted(tool["name"] for tool in payloads[2]["tools"]),
            ["knowledge_get_evidence", "knowledge_search",
             "knowledge_status"])

    def test_search_is_source_bound(self):
        payloads = call_server(self.db, [tool_call(
            1, "knowledge_search",
            {"query": "emission distribution split owners miners "
                      "validators"})])
        result = payloads[1]
        self.assertEqual(result["status"], "ok")
        top = result["results"][0]
        for field in ("unit_id", "kind", "source_file", "heading_path",
                      "lines", "temporal_scope", "evidence_state",
                      "content"):
            self.assertIn(field, top)
        # run-level fields once per response (change: knowledge-retrieval)
        with open(os.path.join(CORPUS_DIR, "hashes.json"),
                  encoding="utf-8") as handle:
            coverage_date = json.load(handle)["coverage_date"]
        self.assertEqual(result["coverage_date"], coverage_date)
        self.assertEqual(result["run_id"], self.run_id)
        self.assertNotIn("coverage_date", top)

    def test_conflict_surfaced(self):
        # The real corpus has no markers since the 2026-08-06 re-sync;
        # verify surfacing behavior with a synthetic marker instead.
        import json as _json
        with tempfile.TemporaryDirectory() as tmp:
            markers = os.path.join(tmp, "markers.json")
            with open(markers, "w", encoding="utf-8") as handle:
                _json.dump([{"match": "staking tao on a subnet",
                             "state": "conflicting",
                             "note": "synthetic test marker"}], handle)
            db, _run, _report = ingest_real_corpus(
                tmp, markers_file=markers)
            payloads = call_server(db, [tool_call(
                1, "knowledge_search", {"query": "staking"})])
            # block units: the marker marks each block whose text holds
            # the phrase, and every such result carries state and note
            marked = [unit for unit in payloads[1]["results"]
                      if "staking tao on a subnet" in
                      unit["content"].lower()]
            self.assertTrue(marked)
            for unit in marked:
                self.assertEqual(unit["evidence_state"], "conflicting")
                self.assertEqual(unit["conflict_note"],
                                 "synthetic test marker")

    def test_insufficient_evidence_is_structured(self):
        payloads = call_server(self.db, [tool_call(
            1, "knowledge_search", {"query": "zzqx vlorpt frabnitz"})])
        self.assertEqual(payloads[1]["status"], "insufficient-evidence")

    def test_get_evidence_roundtrip(self):
        payloads = call_server(self.db, [
            tool_call(1, "knowledge_search", {"query": "tempo blocks"}),
        ])
        unit_id = payloads[1]["results"][0]["unit_id"]
        payloads = call_server(self.db, [
            tool_call(2, "knowledge_get_evidence", {"unit_id": unit_id}),
        ])
        self.assertEqual(payloads[2]["status"], "ok")
        self.assertEqual(payloads[2]["unit"]["unit_id"], unit_id)

    def test_status_reports_run_and_states(self):
        payloads = call_server(self.db, [tool_call(1, "knowledge_status")])
        result = payloads[1]
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["active_run"], self.run_id)
        self.assertIn("confirmed", result["units_by_state"])

    def test_structured_errors(self):
        payloads = call_server(self.db, [
            tool_call(1, "knowledge_get_evidence", {"unit_id": "nope"}),
            tool_call(2, "knowledge_search", {"query": "   "}),
            tool_call(3, "unknown_tool"),
        ])
        for request_id, category in ((1, "not-found"), (2, "invalid"),
                                     (3, "invalid")):
            error = payloads[request_id]["error"]
            self.assertEqual(error["category"], category)
            self.assertIn("correlation_id", error)
            self.assertIn("retry_safe", error)

    def test_audit_lines_written(self):
        call_server(self.db, [tool_call(1, "knowledge_status")])
        audit_path = os.path.join(os.path.dirname(self.db),
                                  "tool-audit.jsonl")
        self.assertTrue(os.path.exists(audit_path))


class StagedNewerRunTests(unittest.TestCase):
    """A3: status names the served run, and a newer staged one apart."""

    def test_newer_staged_run_is_flagged_not_reported_as_active(self):
        with tempfile.TemporaryDirectory() as tmp:
            db, active_run, _report = ingest_real_corpus(tmp)
            payloads = call_server(db, [tool_call(1, "knowledge_status")])
            self.assertIsNone(payloads[1]["staged_newer_run"])
            newer_run, _ = akb.ingest(db, tmp)
            payloads = call_server(db, [tool_call(1, "knowledge_status")])
            result = payloads[1]
            self.assertEqual(result["active_run"], active_run)
            self.assertEqual(result["staged_newer_run"]["run_id"], newer_run)


class NotActivatedTests(unittest.TestCase):
    def test_staged_only_store_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            db, _run, _report = ingest_real_corpus(tmp, activate=False)
            payloads = call_server(db, [
                tool_call(1, "knowledge_search", {"query": "emission"}),
                tool_call(2, "knowledge_status"),
            ])
            for request_id in (1, 2):
                self.assertEqual(
                    payloads[request_id]["error"]["category"],
                    "unavailable")

    def test_missing_store_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            payloads = call_server(os.path.join(tmp, "absent.db"), [
                tool_call(1, "knowledge_search", {"query": "emission"}),
            ])
            self.assertEqual(payloads[1]["error"]["category"],
                             "unavailable")


class ReadOnlySurfaceTests(unittest.TestCase):
    def setUp(self):
        with open(SERVER_SOURCE, "r", encoding="utf-8") as handle:
            self.source = handle.read()

    def test_import_allowlist(self):
        allowed = {"datetime", "json", "os", "re", "sqlite3", "sys",
                   "secrets", "typing", "__future__"}
        imported = set()
        for node in ast.walk(ast.parse(self.source)):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add(node.module or "")
        self.assertEqual(imported - allowed, set())
        for banned in ("subprocess", "urllib", "socket", "http"):
            self.assertNotIn(banned, imported)

    def test_store_opened_read_only(self):
        for match in re.finditer(r"sqlite3\.connect\(([^)]*)\)",
                                 self.source):
            self.assertIn("uri=True", match.group(1))
        self.assertIn("mode=ro", self.source)

    def test_no_raw_sql_surface(self):
        # tool inputs never reach SQL unparameterized: every execute uses
        # placeholders, and FTS queries are built from tokenized terms
        self.assertNotIn("format(query", self.source)
        self.assertIn("_TOKEN.findall", self.source)


if __name__ == "__main__":
    unittest.main()
