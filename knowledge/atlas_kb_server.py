#!/usr/bin/env python3
"""Atlas knowledge MCP server — the production Hermes↔Atlas tool path.

Replaces the inert `atlas-test` server (as the hermes-baseline spec
promised) with exactly three READ-ONLY tools over the activated knowledge
store:

- knowledge_search(query, max_results?) — ranked source-bound units
- knowledge_get_evidence(unit_id)       — full unit + provenance + conflicts
- knowledge_status()                    — active run, counts, corpus hashes

Guarantees (ATLAS-TOOL-001/002/003/004, ATLAS-RET-003/004/005):
- The store is opened via a `mode=ro` SQLite URI per request — writes
  through the server are impossible by construction.
- No SQL, shell, filesystem, or HTTP surface is exposed; queries are
  tokenized before touching FTS.
- Zero-hit searches return a structured `insufficient-evidence` result —
  never prose to fill from model memory.
- Conflicting units always carry their evidence state and conflict note.
- Every error is structured: category, component, retry_safe, user-safe
  message, correlation id. The server never crashes on bad input.
- Its only write is an append-only redacted audit line per call
  (size-capped) beside the store.

Implementation: stdlib-only JSON-RPC 2.0 over newline-delimited stdio,
the same minimal MCP surface the accepted test tool proved
(initialize, ping, tools/list, tools/call).

Hermes registration (stdio MCP server), replacing atlas-test:
    command: python3
    args:    [<repo>/knowledge/atlas_kb_server.py]
"""

from __future__ import annotations

import datetime
import json
import os
import re
import sqlite3
import sys
import secrets as secretsmod
from typing import Any, Dict, List, Optional

_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_MODULE_DIR)

SERVER_NAME = "atlas-kb"
SERVER_VERSION = "0.1.0"
PROTOCOL_VERSION = "2025-06-18"
SUPPORTED_PROTOCOL_VERSIONS = ("2024-11-05", "2025-03-26", "2025-06-18")

PARSE_ERROR = -32700
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602

DEFAULT_DB = os.path.join(_REPO_ROOT, "var", "knowledge", "knowledge.db")
AUDIT_FILE_NAME = "tool-audit.jsonl"
AUDIT_MAX_BYTES = 5 * 1024 * 1024
DEFAULT_MAX_RESULTS = 5
MAX_MAX_RESULTS = 10
MAX_QUERY_TERMS = 12
CONTENT_CAP = 1500  # equals atlas_kb.BLOCK_CAP
# heading column weighted over the body (change: knowledge-retrieval)
BM25_WEIGHTS = "8.0, 1.0"
SEARCHABLE_KINDS = ("fact", "correction")

_TOKEN = re.compile(r"[A-Za-z0-9_]+")
_SUBNET = re.compile(r"(?i)^sn(\d+)$")
# Stopwords and question words carry no domain meaning. Domain words that
# are also common English (take, stake, long, lock) are kept.
STOPWORDS = frozenset("""
a about above after again all also am an and any are as at be been before
being below between both but by can could did do does doing down during
each few for from further had has have having he her here hers him his
how i if in into is it its itself just me more most my no nor not now of
off on once only or other our out over own please right same she should
so some still such than that the their them then there these they this
those through to too under until up very was we were what when where
which while who whom why will with would you your
work works working worked happen happens happened happening mean means
meant explain explains tell give show go goes going went get gets
""".split())

TOOLS: List[Dict[str, Any]] = [
    {
        "name": "knowledge_search",
        "description": (
            "Search the validated Bittensor knowledge base (full-text). "
            "USE THIS FIRST for any Bittensor question — protocol "
            "mechanics, emissions, subnets, staking, conviction, "
            "validators, miners. Returns up to 5 short source-bound units "
            "(one fact or correction each) with provenance and evidence "
            "state. Write the question in plain words; subnet shorthand "
            "like SN82 works. This is curated knowledge as of its coverage "
            "date, NOT live data."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string",
                          "description": "search terms"},
                "max_results": {"type": "integer", "minimum": 1,
                                "maximum": MAX_MAX_RESULTS},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "knowledge_get_evidence",
        "description": (
            "Fetch one knowledge unit in full by unit_id (from a search "
            "result), plus the full text of its section and any linked "
            "conflicting units. Use for context, a truncated result, or "
            "when the user asks for sources."),
        "inputSchema": {
            "type": "object",
            "properties": {"unit_id": {"type": "string"}},
            "required": ["unit_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "knowledge_status",
        "description": (
            "Knowledge-base health: active ingest run, unit counts by "
            "evidence state, corpus files/hashes, coverage date."),
        "inputSchema": {"type": "object", "properties": {},
                        "additionalProperties": False},
    },
]


def _correlation_id() -> str:
    return secretsmod.token_hex(6)


def _utc_now() -> str:
    return datetime.datetime.now(tz=datetime.timezone.utc).isoformat()


def structured_error(category: str, message: str,
                     retry_safe: bool) -> Dict[str, Any]:
    """ATLAS-TOOL-002 error payload (returned as tool content)."""
    return {
        "error": {
            "category": category,
            "component": SERVER_NAME,
            "retry_safe": retry_safe,
            "message": message,
            "correlation_id": _correlation_id(),
        }
    }


def _subnet_group(number: str) -> str:
    """`SN82` as an FTS group: the corpus writes subnet 82, netuid 82,
    SN82, or the bare number in a list ("82 and 103 off")."""
    return '("subnet %s" OR "netuid %s" OR "sn%s" OR "%s")' % (
        number, number, number, number)


class KnowledgeStore:
    """Read-only view over the knowledge store."""

    def __init__(self, db_path: str):
        self.db_path = db_path

    def _connect(self) -> sqlite3.Connection:
        uri = "file:%s?mode=ro" % self.db_path.replace("\\", "/")
        return sqlite3.connect(uri, uri=True, timeout=5)

    def _guard(self) -> Optional[Dict[str, Any]]:
        if not os.path.exists(self.db_path):
            return structured_error(
                "unavailable",
                "knowledge store not found — run atlas_kb.py ingest + "
                "activate first", retry_safe=False)
        return None

    @staticmethod
    def _unit_payload(row: Any) -> Dict[str, Any]:
        (unit_id, source_file, heading_path, line_start, line_end,
         coverage_date, temporal_scope, evidence_state, conflict_note,
         content) = row
        return {
            "unit_id": unit_id,
            "source_file": source_file,
            "heading_path": heading_path,
            "lines": [line_start, line_end],
            "coverage_date": coverage_date,
            "temporal_scope": temporal_scope,
            "evidence_state": evidence_state,
            "conflict_note": conflict_note,
            "content": content,
        }

    _UNIT_FIELDS = ("unit_id", "source_file", "heading_path",
                    "line_start", "line_end", "coverage_date",
                    "temporal_scope", "evidence_state", "conflict_note",
                    "content")
    _UNIT_COLUMNS = ", ".join(_UNIT_FIELDS)
    # the FTS join needs qualification: units_fts also has heading_path
    _UNIT_COLUMNS_QUALIFIED = ", ".join("u." + f for f in _UNIT_FIELDS)

    @staticmethod
    def build_queries(query: str) -> List[str]:
        """FTS5 queries in rank order: all terms (AND), then any term (OR).
        Built from tokens only, so no user text reaches FTS syntax."""
        terms: List[str] = []
        for token in _TOKEN.findall(query):
            subnet = _SUBNET.match(token)
            if subnet:
                number = subnet.group(1)
                term = _subnet_group(number)
            elif token.isdigit() and terms and terms[-1].lower() == '"sn"':
                terms.pop()  # "SN 82" written with a space
                term = _subnet_group(token)
            elif token.lower() in STOPWORDS:
                continue
            else:
                term = '"%s"' % token
            if term not in terms:
                terms.append(term)
            if len(terms) >= MAX_QUERY_TERMS:
                break
        if not terms:
            return []
        if len(terms) == 1:
            return [terms[0]]
        return [" AND ".join(terms), " OR ".join(terms)]

    def _schema(self, connection: sqlite3.Connection) -> Dict[str, Any]:
        columns = {row[1] for row in connection.execute(
            "PRAGMA table_info(units)")}
        try:
            row = connection.execute(
                "SELECT value FROM kb_meta WHERE key = 'index_version'"
            ).fetchone()
        except sqlite3.OperationalError:
            row = None
        return {"has_kind": "kind" in columns,
                "index_version": int(row[0]) if row else None}

    def _result_payload(self, row: Any, has_kind: bool) -> Dict[str, Any]:
        unit = self._unit_payload(row[:10])
        kind = row[10] if has_kind else "fact"
        content = unit["content"]
        result: Dict[str, Any] = {
            "unit_id": unit["unit_id"],
            "kind": kind,
            "source_file": unit["source_file"],
            "heading_path": unit["heading_path"],
            "lines": unit["lines"],
            "temporal_scope": unit["temporal_scope"],
            "evidence_state": unit["evidence_state"],
            "content": content[:CONTENT_CAP],
        }
        if len(content) > CONTENT_CAP:
            result["truncated"] = True
        if unit["conflict_note"]:
            result["conflict_note"] = unit["conflict_note"]
        return result

    def search(self, query: str, max_results: int) -> Dict[str, Any]:
        guard = self._guard()
        if guard:
            return guard
        queries = self.build_queries(query)
        if not queries:
            return structured_error("invalid", "query has no searchable "
                                    "terms", retry_safe=False)
        try:
            connection = self._connect()
            try:
                if connection.execute(
                        "SELECT count(*) FROM units WHERE active = 1"
                        ).fetchone()[0] == 0:
                    return structured_error(
                        "unavailable", "knowledge base not activated: "
                        "an operator must approve and activate an ingest "
                        "run", retry_safe=False)
                schema = self._schema(connection)
                columns = self._UNIT_COLUMNS_QUALIFIED + (
                    ", u.kind" if schema["has_kind"] else "")
                kind_filter = (" AND u.kind IN (%s)" % ", ".join(
                    "'%s'" % kind for kind in SEARCHABLE_KINDS)
                    if schema["has_kind"] else "")
                weights = (BM25_WEIGHTS if schema["index_version"]
                           else "1.0, 1.0")
                rows: List[Any] = []
                seen = set()
                for fts_query in queries:
                    for row in connection.execute(
                            "SELECT %s FROM units u JOIN units_fts f "
                            "ON f.rowid = u.id WHERE units_fts MATCH ? "
                            "AND u.active = 1%s ORDER BY "
                            "bm25(units_fts, %s) LIMIT ?"
                            % (columns, kind_filter, weights),
                            (fts_query, max_results)):
                        if row[0] not in seen:
                            seen.add(row[0])
                            rows.append(row)
                    if len(rows) >= max_results:
                        break
                rows = rows[:max_results]
                run = connection.execute(
                    "SELECT run_id, coverage_date FROM units WHERE "
                    "active = 1 LIMIT 1").fetchone()
            finally:
                connection.close()
        except sqlite3.Error as exc:
            return structured_error("store-error", str(exc),
                                    retry_safe=True)
        if not rows:
            return {
                "status": "insufficient-evidence",
                "query": query,
                "message": "No active knowledge unit matches this query. "
                           "The knowledge base cannot support an answer: "
                           "say so rather than filling the gap.",
            }
        results = [self._result_payload(row, schema["has_kind"])
                   for row in rows]
        note = ("Knowledge as of coverage_date, not live data. Units with "
                "a conflict_note MUST have it surfaced.")
        if any(result.get("truncated") for result in results):
            note += (" A truncated result is cut at %d characters: call "
                     "knowledge_get_evidence for its full text."
                     % CONTENT_CAP)
        return {
            "status": "ok",
            "query": query,
            "run_id": run[0] if run else None,
            "coverage_date": run[1] if run else None,
            "results": results,
            "note": note,
        }

    def get_evidence(self, unit_id: str) -> Dict[str, Any]:
        guard = self._guard()
        if guard:
            return guard
        try:
            connection = self._connect()
            try:
                row = connection.execute(
                    "SELECT %s FROM units WHERE unit_id = ? AND "
                    "active = 1" % self._UNIT_COLUMNS,
                    (unit_id,)).fetchone()
                related: List[Any] = []
                section_text: List[str] = []
                section_rows: Optional[Any] = None
                if row is not None:
                    # the whole section: every active block with the same
                    # source and heading path, in line order
                    section_text = [item[0] for item in connection.execute(
                        "SELECT content FROM units WHERE active = 1 AND "
                        "source_file = ? AND heading_path = ? ORDER BY "
                        "line_start", (row[1], row[2]))]
                    if self._schema(connection)["has_kind"]:
                        section_rows = connection.execute(
                            "SELECT kind FROM units WHERE unit_id = ? AND "
                            "active = 1", (unit_id,)).fetchone()
                    related = connection.execute(
                        "SELECT %s FROM units WHERE active = 1 AND "
                        "conflict_note IS NOT NULL AND source_file = ? "
                        "AND unit_id != ?" % self._UNIT_COLUMNS,
                        (row[1], unit_id)).fetchall()
            finally:
                connection.close()
        except sqlite3.Error as exc:
            return structured_error("store-error", str(exc),
                                    retry_safe=True)
        if row is None:
            return structured_error(
                "not-found", "no active unit with unit_id %r — use a "
                "unit_id from a knowledge_search result" % unit_id,
                retry_safe=False)
        unit = self._unit_payload(row)
        if section_rows is not None:
            unit["kind"] = section_rows[0]
        return {
            "status": "ok",
            "unit": unit,
            "section": {
                "heading_path": unit["heading_path"],
                "content": "\n\n".join(section_text),
            },
            "conflicting_units_in_source": [
                self._unit_payload(item) for item in related],
        }

    def kb_status(self) -> Dict[str, Any]:
        guard = self._guard()
        if guard:
            return guard
        try:
            connection = self._connect()
            try:
                active = connection.execute(
                    "SELECT run_id, count(*) FROM units WHERE active = 1 "
                    "GROUP BY run_id").fetchall()
                states = connection.execute(
                    "SELECT evidence_state, count(*) FROM units "
                    "WHERE active = 1 GROUP BY evidence_state").fetchall()
                run = newer = None
                version = self._schema(connection)["index_version"]
                if active:
                    # The active run's own row, never simply the newest
                    # ingest: a staged run must not pose as the served one.
                    run = connection.execute(
                        "SELECT coverage_date, intake_date, files_json FROM "
                        "intake_runs WHERE run_id = ?",
                        (active[0][0],)).fetchone()
                if run:
                    newer = connection.execute(
                        "SELECT run_id, coverage_date FROM intake_runs "
                        "WHERE intake_date > ? ORDER BY intake_date DESC "
                        "LIMIT 1", (run[1],)).fetchone()
            finally:
                connection.close()
        except sqlite3.Error as exc:
            return structured_error("store-error", str(exc),
                                    retry_safe=True)
        if not active:
            return structured_error(
                "unavailable", "knowledge base not activated — an "
                "operator must approve and activate an ingest run",
                retry_safe=False)
        return {
            "status": "ok",
            "active_run": active[0][0],
            "active_units": active[0][1],
            "units_by_state": {state: count for state, count in states},
            "coverage_date": run[0] if run else None,
            "corpus_files": json.loads(run[2]) if run else None,
            "index_version": version,
            "staged_newer_run": ({"run_id": newer[0],
                                  "coverage_date": newer[1]}
                                 if newer else None),
            "note": "Knowledge is current as of coverage_date; live "
                    "chain/market data is NOT available through this "
                    "tool.",
        }


class AuditLog:
    """Append-only, size-capped, redacted call log (ATLAS-TOOL-004)."""

    def __init__(self, path: str):
        self.path = path

    def record(self, tool: str, params: Dict[str, Any],
               outcome: str) -> None:
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            if (os.path.exists(self.path)
                    and os.path.getsize(self.path) > AUDIT_MAX_BYTES):
                os.replace(self.path, self.path + ".1")
            with open(self.path, "a", encoding="utf-8") as handle:
                handle.write(json.dumps({
                    "timestamp": _utc_now(),
                    "tool": tool,
                    "params": {key: str(value)[:120]
                               for key, value in (params or {}).items()},
                    "outcome": outcome,
                }) + "\n")
        except OSError:
            pass  # auditing must never break the tool path


def handle_tool_call(store: KnowledgeStore, audit: AuditLog,
                     name: str, arguments: Dict[str, Any]
                     ) -> Dict[str, Any]:
    if name == "knowledge_search":
        query = arguments.get("query")
        if not isinstance(query, str) or not query.strip():
            payload: Dict[str, Any] = structured_error(
                "invalid", "query must be a non-empty string",
                retry_safe=False)
        else:
            max_results = arguments.get("max_results", DEFAULT_MAX_RESULTS)
            if not isinstance(max_results, int) \
                    or not 1 <= max_results <= MAX_MAX_RESULTS:
                max_results = DEFAULT_MAX_RESULTS
            payload = store.search(query.strip(), max_results)
    elif name == "knowledge_get_evidence":
        unit_id = arguments.get("unit_id")
        if not isinstance(unit_id, str) or not unit_id.strip():
            payload = structured_error(
                "invalid", "unit_id must be a non-empty string",
                retry_safe=False)
        else:
            payload = store.get_evidence(unit_id.strip())
    elif name == "knowledge_status":
        payload = store.kb_status()
    else:
        payload = structured_error(
            "invalid", "unknown tool: %r (available: %s)"
            % (name, ", ".join(tool["name"] for tool in TOOLS)),
            retry_safe=False)
    audit.record(name, arguments,
                 payload.get("status", "error")
                 if "error" not in payload else
                 payload["error"]["category"])
    return payload


def handle_message(store: KnowledgeStore, audit: AuditLog,
                   message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    method = message.get("method")
    request_id = message.get("id")
    if not isinstance(method, str):
        return None
    if method.startswith("notifications/"):
        return None
    if method == "initialize":
        params = message.get("params") or {}
        requested = params.get("protocolVersion")
        version = (requested if requested in SUPPORTED_PROTOCOL_VERSIONS
                   else PROTOCOL_VERSION)
        return _result(request_id, {
            "protocolVersion": version,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": SERVER_NAME,
                           "version": SERVER_VERSION},
        })
    if method == "ping":
        return _result(request_id, {})
    if method == "tools/list":
        return _result(request_id, {"tools": TOOLS})
    if method == "tools/call":
        params = message.get("params") or {}
        name = params.get("name")
        arguments = params.get("arguments") or {}
        if not isinstance(name, str) or not isinstance(arguments, dict):
            return _error(request_id, INVALID_PARAMS,
                          "tools/call needs a name and an arguments "
                          "object")
        payload = handle_tool_call(store, audit, name, arguments)
        return _result(request_id, {
            "content": [{"type": "text", "text": json.dumps(payload)}],
            "isError": "error" in payload,
        })
    if request_id is not None:
        return _error(request_id, METHOD_NOT_FOUND,
                      "method not supported: %s" % method)
    return None


def _result(request_id: Any, result: Dict[str, Any]) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error(request_id: Any, code: int, message: str) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id,
            "error": {"code": code, "message": message}}


def serve(db_path: str = DEFAULT_DB, stdin: Any = None,
          stdout: Any = None) -> None:
    stdin = stdin if stdin is not None else sys.stdin
    stdout = stdout if stdout is not None else sys.stdout
    store = KnowledgeStore(db_path)
    audit = AuditLog(os.path.join(os.path.dirname(db_path),
                                  AUDIT_FILE_NAME))
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except ValueError:
            response: Optional[Dict[str, Any]] = _error(
                None, PARSE_ERROR, "invalid JSON")
        else:
            response = (handle_message(store, audit, message)
                        if isinstance(message, dict) else
                        _error(None, PARSE_ERROR,
                               "expected a JSON-RPC object"))
        if response is not None:
            stdout.write(json.dumps(response) + "\n")
            stdout.flush()


if __name__ == "__main__":
    db = sys.argv[sys.argv.index("--db") + 1] if "--db" in sys.argv \
        else DEFAULT_DB
    serve(db)
