"""MCP server behavior over real pipes against a real ingested store."""

import ast
import os
import re
import tempfile
import unittest

from _helpers import (SERVER_SOURCE, call_server, ingest_real_corpus,
                      tool_call)


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
        for field in ("unit_id", "source_file", "heading_path",
                      "coverage_date", "evidence_state", "content"):
            self.assertIn(field, top)
        self.assertEqual(top["coverage_date"], "2026-07-28")

    def test_conflict_surfaced(self):
        # The real corpus has no markers since the 2026-07-28 re-sync;
        # verify surfacing behavior with a synthetic marker instead.
        import json as _json
        with tempfile.TemporaryDirectory() as tmp:
            markers = os.path.join(tmp, "markers.json")
            with open(markers, "w", encoding="utf-8") as handle:
                _json.dump([{"match": "emission gate",
                             "state": "conflicting",
                             "note": "synthetic test marker"}], handle)
            db, _run, _report = ingest_real_corpus(
                tmp, markers_file=markers)
            payloads = call_server(db, [tool_call(
                1, "knowledge_search", {"query": "emission gate"})])
            top = payloads[1]["results"][0]
            self.assertEqual(top["evidence_state"], "conflicting")
            self.assertEqual(top["conflict_note"],
                             "synthetic test marker")

    def test_insufficient_evidence_is_structured(self):
        payloads = call_server(self.db, [tool_call(
            1, "knowledge_search", {"query": "zzqx quantum spaghetti"})])
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
