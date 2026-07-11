#!/usr/bin/env python3
"""Atlas repository MCP server — read-only subtensor evidence for Hermes.

Exactly four READ-ONLY tools over the repotrack store and clone
(ATLAS-REPO-003/007/008, ATLAS-TOOL-001/002/003/004):

- repo_search(query, max_results?)          — indexed files w/ SHA + snippets
- repo_file(path, start_line?, end_line?)   — bounded file read, SHA-guarded
- repo_changes(limit?)                      — recorded change ranges
- repo_status()                             — every ATLAS-REPO-007 field

Guarantees:
- The store opens `mode=ro` per request; the server's git use is a fixed
  read-only set (rev-parse / status / count-objects via atlas_repo
  helpers) — no mutating git command exists in this process, and the
  clone's push URL is disabled at setup anyway.
- `repo_file` serves content only while the working tree is clean AND
  the index SHA matches the local SHA — otherwise a structured
  staleness refusal, never mixed state (ATLAS-REPO-008).
- Zero-hit searches return structured `no-repository-evidence`.
- Missing store/clone/config fails closed as
  `repository-tracking-unavailable` — the server never claims currency
  it cannot prove.
- Every error is structured (category, component, retry_safe, user-safe
  message, correlation id); the only write is an append-only redacted
  audit line (size-capped) beside the store.

Implementation: stdlib-only JSON-RPC 2.0 over newline-delimited stdio,
the same minimal MCP surface as the accepted atlas-kb server.

Hermes registration (stdio MCP server, alongside atlas-kb):
    command: python3
    args:    [<repo>/repotrack/atlas_repo_server.py]
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
sys.path.insert(0, _MODULE_DIR)

import atlas_repo as arp  # noqa: E402  (stdlib-pure at import time)

SERVER_NAME = "atlas-repo"
SERVER_VERSION = "0.1.0"
PROTOCOL_VERSION = "2025-06-18"
SUPPORTED_PROTOCOL_VERSIONS = ("2024-11-05", "2025-03-26", "2025-06-18")

PARSE_ERROR = -32700
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602

AUDIT_FILE_NAME = "tool-audit.jsonl"
AUDIT_MAX_BYTES = 5 * 1024 * 1024
DEFAULT_MAX_RESULTS = 3
MAX_MAX_RESULTS = 10
DEFAULT_CHANGES_LIMIT = 5
MAX_CHANGES_LIMIT = 20
MAX_FILE_LINES = 400

_TOKEN = re.compile(r"[A-Za-z0-9_]+")

TOOLS: List[Dict[str, Any]] = [
    {
        "name": "repo_search",
        "description": (
            "Full-text search over the tracked subtensor repository's "
            "indexed files. USE THIS for questions about subtensor source "
            "code, protocol implementation, parameters, or recent code "
            "changes. Returns file paths with the commit SHA they were "
            "indexed at plus matching snippets — cite both. This is the "
            "local tracked clone, NOT live chain state."),
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
        "name": "repo_file",
        "description": (
            "Read a bounded slice of one tracked repository file at the "
            "current local commit (path from a repo_search result). "
            "Refuses with a staleness error if the clone and index "
            "disagree — never serves mixed state."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "start_line": {"type": "integer", "minimum": 1},
                "end_line": {"type": "integer", "minimum": 1},
            },
            "required": ["path"],
            "additionalProperties": False,
        },
    },
    {
        "name": "repo_changes",
        "description": (
            "Recent recorded change ranges of the tracked repository: "
            "previous/new commit SHAs, commit list, changed files, tags, "
            "and a machine-generated summary (labelled — it is not "
            "verified effect). Use for 'what changed recently' questions."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "minimum": 1,
                          "maximum": MAX_CHANGES_LIMIT},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "repo_status",
        "description": (
            "Tracked-repository freshness: local/remote SHAs, last fetch "
            "attempt/success, last detected update, working-tree clean, "
            "index-matches-SHA, and stale-per-policy. ALWAYS check/report "
            "staleness before presenting repository facts as current."),
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


class RepoStore:
    """Read-only view over the repotrack store + clone."""

    def __init__(self, config_path: str):
        self.config_path = config_path

    def _load(self) -> Dict[str, Any]:
        config = arp.load_config(self.config_path)
        return {
            "config": config,
            "db": arp._resolve(_REPO_ROOT, config["db"]),
            "clone": arp._resolve(_REPO_ROOT, config["clone_dir"]),
        }

    def _connect(self, db_path: str) -> sqlite3.Connection:
        uri = "file:%s?mode=ro" % db_path.replace("\\", "/")
        return sqlite3.connect(uri, uri=True, timeout=5)

    def _guarded(self) -> Any:
        """Return context or a structured error (fail closed)."""
        try:
            context = self._load()
        except arp.FatalRepoError as exc:
            return structured_error("repository-tracking-unavailable",
                                    str(exc), retry_safe=False)
        if not os.path.exists(context["db"]):
            return structured_error(
                "repository-tracking-unavailable",
                "repotrack store not found — run atlas_repo.py setup + "
                "index first", retry_safe=False)
        if not os.path.isdir(os.path.join(context["clone"], ".git")):
            return structured_error(
                "repository-tracking-unavailable",
                "tracked clone not found — run atlas_repo.py setup first",
                retry_safe=False)
        return context

    # -- tools ------------------------------------------------------------

    def search(self, query: str, max_results: int) -> Dict[str, Any]:
        context = self._guarded()
        if "error" in context:
            return context
        tokens = _TOKEN.findall(query)[:12]
        if not tokens:
            return structured_error("invalid", "query has no searchable "
                                    "terms", retry_safe=False)
        fts_query = " OR ".join('"%s"' % token for token in tokens)
        try:
            connection = self._connect(context["db"])
            try:
                rows = connection.execute(
                    "SELECT f.path, f.indexed_sha, "
                    "snippet(files_fts, 1, '>>', '<<', ' … ', 24) "
                    "FROM files_fts JOIN files f ON f.id = files_fts.rowid "
                    "WHERE files_fts MATCH ? ORDER BY bm25(files_fts) "
                    "LIMIT ?", (fts_query, max_results)).fetchall()
            finally:
                connection.close()
        except sqlite3.Error as exc:
            return structured_error("store-error", str(exc),
                                    retry_safe=True)
        if not rows:
            return {
                "status": "no-repository-evidence",
                "query": query,
                "message": "No indexed repository file matches this query. "
                           "The tracked repository cannot support an "
                           "answer — say so rather than filling the gap.",
            }
        return {
            "status": "ok",
            "query": query,
            "results": [{"path": path, "indexed_sha": sha,
                         "snippet": snippet}
                        for path, sha, snippet in rows],
            "note": "Content as of each file's indexed commit SHA — cite "
                    "path and SHA. This is the tracked clone, not live "
                    "chain state; check repo_status for staleness.",
        }

    def file(self, path: str, start_line: Optional[int],
             end_line: Optional[int]) -> Dict[str, Any]:
        context = self._guarded()
        if "error" in context:
            return context
        clone = context["clone"]
        rel = path.replace("\\", "/").strip().lstrip("/")
        parts = rel.split("/")
        if not rel or ".." in parts or parts[0] == ".git":
            return structured_error("invalid", "path must be a relative "
                                    "repository path", retry_safe=False)
        real_clone = os.path.realpath(clone)
        abs_path = os.path.realpath(os.path.join(real_clone, rel))
        if not abs_path.startswith(real_clone + os.sep):
            return structured_error("invalid", "path escapes the tracked "
                                    "clone", retry_safe=False)
        try:
            sha = arp.local_sha(clone)
            dirty = arp.working_tree_dirty(clone)
            connection = self._connect(context["db"])
            try:
                indexed_sha = dict(connection.execute(
                    "SELECT key, value FROM meta").fetchall()
                ).get(arp.META_INDEXED_SHA)
            finally:
                connection.close()
        except (arp.FatalRepoError, sqlite3.Error) as exc:
            return structured_error("store-error", str(exc),
                                    retry_safe=True)
        if dirty or indexed_sha != sha:
            return structured_error(
                "stale-state",
                "clone/index state is inconsistent (tree %s, indexed SHA "
                "%s vs local %s) — run atlas_repo.py update/index; "
                "refusing to serve mixed state"
                % ("dirty" if dirty else "clean",
                   (indexed_sha or "none")[:12], sha[:12]),
                retry_safe=True)
        if not os.path.isfile(abs_path):
            return structured_error(
                "not-found", "no file %r at the tracked commit — use a "
                "path from a repo_search result" % rel, retry_safe=False)
        try:
            with open(abs_path, "r", encoding="utf-8",
                      errors="replace") as handle:
                lines = handle.read().splitlines()
        except OSError as exc:
            return structured_error("store-error", str(exc),
                                    retry_safe=True)
        total = len(lines)
        start = max(1, start_line or 1)
        end = min(total, end_line or (start + MAX_FILE_LINES - 1))
        end = min(end, start + MAX_FILE_LINES - 1)
        return {
            "status": "ok",
            "path": rel,
            "commit_sha": sha,
            "total_lines": total,
            "lines": [start, end],
            "content": "\n".join(lines[start - 1:end]),
            "note": "Content at the local tracked commit — cite path and "
                    "commit_sha.",
        }

    def changes(self, limit: int) -> Dict[str, Any]:
        context = self._guarded()
        if "error" in context:
            return context
        try:
            connection = self._connect(context["db"])
            try:
                rows = connection.execute(
                    "SELECT run_id, prev_sha, new_sha, retrieved_at, "
                    "non_fast_forward, commits_json, files_json, "
                    "tags_json, index_status, summary FROM change_ranges "
                    "ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
            finally:
                connection.close()
        except sqlite3.Error as exc:
            return structured_error("store-error", str(exc),
                                    retry_safe=True)
        if not rows:
            return {
                "status": "no-repository-evidence",
                "message": "No change ranges recorded yet — the tracked "
                           "branch has not changed since setup, or no "
                           "update has run.",
            }
        ranges = []
        for (run_id, prev_sha, new_sha, retrieved_at, non_ff,
             commits_json, files_json, tags_json, index_status,
             summary) in rows:
            commits = json.loads(commits_json)
            files = json.loads(files_json)
            ranges.append({
                "run_id": run_id,
                "prev_sha": prev_sha,
                "new_sha": new_sha,
                "retrieved_at": retrieved_at,
                "non_fast_forward": bool(non_ff),
                "commit_count": len(commits["commits"]),
                "commits": commits["commits"][:20],
                "commits_truncated": (commits["truncated"]
                                      or len(commits["commits"]) > 20),
                "changed_file_count": len(files["files"]),
                "changed_files": [item["path"]
                                  for item in files["files"][:50]],
                "files_truncated": (files["truncated"]
                                    or len(files["files"]) > 50),
                "tags": json.loads(tags_json),
                "index_status": index_status,
                "summary": summary,
            })
        return {"status": "ok", "ranges": ranges,
                "note": "Summaries are machine-generated and labelled — "
                        "they are not verified effect."}

    def repo_status(self) -> Dict[str, Any]:
        context = self._guarded()
        if "error" in context:
            return context
        try:
            info = arp.freshness(context["db"], context["clone"],
                                 context["config"])
        except (arp.FatalRepoError, sqlite3.Error) as exc:
            return structured_error("repository-tracking-unavailable",
                                    str(exc), retry_safe=True)
        info["status"] = "stale" if info["stale"] else "ok"
        info["note"] = ("stale=true means the last successful fetch is "
                        "older than the configured policy — do NOT present "
                        "repository facts as current; say when they were "
                        "last fetched.")
        return info


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


def handle_tool_call(store: RepoStore, audit: AuditLog, name: str,
                     arguments: Dict[str, Any]) -> Dict[str, Any]:
    if name == "repo_search":
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
    elif name == "repo_file":
        path = arguments.get("path")
        start_line = arguments.get("start_line")
        end_line = arguments.get("end_line")
        if not isinstance(path, str) or not path.strip():
            payload = structured_error(
                "invalid", "path must be a non-empty string",
                retry_safe=False)
        elif any(value is not None and (not isinstance(value, int)
                                        or value < 1)
                 for value in (start_line, end_line)):
            payload = structured_error(
                "invalid", "start_line/end_line must be positive integers",
                retry_safe=False)
        else:
            payload = store.file(path, start_line, end_line)
    elif name == "repo_changes":
        limit = arguments.get("limit", DEFAULT_CHANGES_LIMIT)
        if not isinstance(limit, int) or not 1 <= limit <= MAX_CHANGES_LIMIT:
            limit = DEFAULT_CHANGES_LIMIT
        payload = store.changes(limit)
    elif name == "repo_status":
        payload = store.repo_status()
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


def handle_message(store: RepoStore, audit: AuditLog,
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


def _audit_path(config_path: str) -> str:
    try:
        config = arp.load_config(config_path)
        base = os.path.dirname(arp._resolve(_REPO_ROOT, config["db"]))
    except arp.FatalRepoError:
        base = os.path.join(_REPO_ROOT, "var", "repotrack")
    return os.path.join(base, AUDIT_FILE_NAME)


def serve(config_path: str = arp.CONFIG_FILE, stdin: Any = None,
          stdout: Any = None) -> None:
    stdin = stdin if stdin is not None else sys.stdin
    stdout = stdout if stdout is not None else sys.stdout
    store = RepoStore(config_path)
    audit = AuditLog(_audit_path(config_path))
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
    config_file = sys.argv[sys.argv.index("--config") + 1] \
        if "--config" in sys.argv else arp.CONFIG_FILE
    serve(config_file)
