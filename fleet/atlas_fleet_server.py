#!/usr/bin/env python3
"""Atlas fleet MCP server — read-only subnet-repo-fleet code search for Hermes.

Three READ-ONLY tools over the shared fleet FTS index and the maintained
clones (change: fleet-search), the direct analogue of the accepted atlas-repo
server, generalized across the ~104-clone fleet:

- fleet_search(query, netuid?, max_results?)      — indexed files w/ provenance
- fleet_file(netuid, path, start_line?, end_line?) — bounded read, SHA-guarded
- fleet_status(netuid?)                            — fleet + index freshness

Guarantees (mirroring atlas-repo):
- The store opens `mode=ro` per request; the server has no mutating git path,
  and the clones' push URLs are disabled at setup anyway.
- Missing store or an unbuilt index fails closed as `fleet-search-unavailable`
  — the server never claims currency it cannot prove.
- `fleet_file` serves content only while the slot is active, its tree is clean,
  and the recorded indexed SHA equals the clone's live local SHA — otherwise a
  structured staleness refusal, never mixed state.
- Search never executes subnet code; results cite netuid, repository, path, and
  the commit SHA each file was indexed at. Zero hits return `no-fleet-evidence`.
- Every error is structured; the only write is an append-only redacted,
  size-capped audit line beside the store.

Hermes registration (stdio MCP server, alongside atlas-repo):
    command: python3
    args:    [<repo>/fleet/atlas_fleet_server.py]
"""

from __future__ import annotations

import datetime
import json
import os
import sqlite3
import sys
import secrets as secretsmod
from typing import Any, Dict, List, Optional

_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_MODULE_DIR)
sys.path.insert(0, _MODULE_DIR)
sys.path.insert(0, os.path.join(_REPO_ROOT, "repotrack"))

import atlas_fleet as flt  # noqa: E402  (stdlib-pure at import time)
import atlas_fleet_index as fidx  # noqa: E402
import atlas_fleet_mining as fmine  # noqa: E402  (pure read helpers)
import atlas_repo as arp  # noqa: E402  (pure helpers: local_sha, tree-dirty)


def _mining() -> Any:
    """The mining module's read-only view helpers. Imported directly: it is
    stdlib-pure at import time and opens nothing."""
    return fmine

SERVER_NAME = "atlas-fleet"
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
MAX_FILE_LINES = 400

# Mining triage (change: mining-triage). Bounded like every other surface.
DEFAULT_BOARD_LIMIT = 10
MAX_BOARD_LIMIT = 30
DEFAULT_HISTORY_ROWS = 20
MAX_HISTORY_ROWS = 100
MINING_UNAVAILABLE = "mining-screen-unavailable"

TOOLS: List[Dict[str, Any]] = [
    {
        "name": "fleet_search",
        "description": (
            "Full-text search over the tracked SUBNET code repositories "
            "(the maintained fleet of subnet github repos), across all subnets "
            "or scoped to one netuid. USE THIS for questions about a subnet's "
            "source code, miner/validator implementation, or parameters. "
            "Returns netuid, repository, file path, the commit SHA each file "
            "was indexed at, and matching snippets — cite them. This is the "
            "local tracked clones, NOT live chain state. For the subtensor "
            "chain runtime itself, use the atlas-repo tools instead."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "search terms"},
                "netuid": {"type": "integer", "minimum": 0,
                           "description": "restrict to one subnet"},
                "max_results": {"type": "integer", "minimum": 1,
                                "maximum": MAX_MAX_RESULTS},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "fleet_file",
        "description": (
            "Read a bounded slice of one file from a subnet's tracked clone at "
            "its current local commit (netuid + path from a fleet_search "
            "result). Refuses with a staleness error if the clone and index "
            "disagree — never serves mixed state."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "netuid": {"type": "integer", "minimum": 0},
                "path": {"type": "string"},
                "start_line": {"type": "integer", "minimum": 1},
                "end_line": {"type": "integer", "minimum": 1},
            },
            "required": ["netuid", "path"],
            "additionalProperties": False,
        },
    },
    {
        "name": "fleet_status",
        "description": (
            "Fleet and index freshness: overall slot counts by status, total "
            "clone bytes, and index coverage (indexed / stale slot counts, "
            "total indexed files); with a netuid, that slot's status, local "
            "and indexed SHAs, staleness, and file count. ALWAYS check/report "
            "staleness before presenting subnet-repo facts as current."),
        "inputSchema": {
            "type": "object",
            "properties": {"netuid": {"type": "integer", "minimum": 0}},
            "additionalProperties": False,
        },
    },
    {
        "name": "mining_board",
        "description": (
            "Ranked mining triage: which subnets a NEW INDEPENDENT MINER "
            "could earn on, with the reason every excluded subnet was cut. "
            "Each row carries net/gross TAO per month, alpha price, owner "
            "capture (miner burn), earner count and top-10 concentration, "
            "the declared hardware floor with the file it came from, and a "
            "confidence marker. Alpha DISTRIBUTED per block is a protocol "
            "constant, so ranking is driven by price, burn, and "
            "concentration — never by emission quantity. Always report both "
            "the economics and feasibility timestamps."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "minimum": 1,
                          "maximum": MAX_BOARD_LIMIT},
                "include_cut": {"type": "boolean",
                                "description": "also return excluded "
                                               "subnets with their reasons"},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "mining_subnet",
        "description": (
            "One subnet's full mining picture: every recorded economics "
            "field with its chain reference block, and every feasibility "
            "finding with its evidence path and the commit it was scanned "
            "at. Reports `unscanned` distinctly from infeasible."),
        "inputSchema": {
            "type": "object",
            "properties": {"netuid": {"type": "integer", "minimum": 0}},
            "required": ["netuid"],
            "additionalProperties": False,
        },
    },
    {
        "name": "mining_history",
        "description": (
            "Recorded mining observations for one subnet over time, so "
            "'what changed' is answered from stored passes rather than "
            "inferred. Reports insufficient-history until at least two "
            "observations exist; never presents a single observation as a "
            "trend."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "netuid": {"type": "integer", "minimum": 0},
                "field": {"type": "string",
                          "description": "restrict to one economics field"},
                "limit": {"type": "integer", "minimum": 2,
                          "maximum": MAX_HISTORY_ROWS},
            },
            "required": ["netuid"],
            "additionalProperties": False,
        },
    },
]


def _correlation_id() -> str:
    return secretsmod.token_hex(6)


def _utc_now() -> str:
    return datetime.datetime.now(tz=datetime.timezone.utc).isoformat()


def structured_error(category: str, message: str,
                     retry_safe: bool) -> Dict[str, Any]:
    return {
        "error": {
            "category": category,
            "component": SERVER_NAME,
            "retry_safe": retry_safe,
            "message": message,
            "correlation_id": _correlation_id(),
        }
    }


class FleetStore:
    """Read-only view over the fleet store + clones."""

    def __init__(self, config_path: str):
        self.config_path = config_path

    def _load(self) -> Dict[str, Any]:
        config = flt.load_config(self.config_path)
        return {"config": config, "db": config["db"],
                "clone_root": config["clone_root"]}

    def _connect(self, db_path: str) -> sqlite3.Connection:
        uri = "file:%s?mode=ro" % db_path.replace("\\", "/")
        return sqlite3.connect(uri, uri=True, timeout=5)

    def _guarded(self) -> Any:
        """Return context or a structured fail-closed error."""
        try:
            context = self._load()
        except flt.FleetError as exc:
            return structured_error("fleet-search-unavailable", str(exc),
                                    retry_safe=False)
        if not os.path.exists(context["db"]):
            return structured_error(
                "fleet-search-unavailable",
                "fleet store not found — run atlas_fleet.py reconcile + index "
                "first", retry_safe=False)
        try:
            connection = self._connect(context["db"])
            try:
                has_index = connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND "
                    "name='fleet_files'").fetchone() is not None
            finally:
                connection.close()
        except sqlite3.Error as exc:
            return structured_error("fleet-search-unavailable", str(exc),
                                    retry_safe=True)
        if not has_index:
            return structured_error(
                "fleet-search-unavailable",
                "fleet index not built — run atlas_fleet.py index first",
                retry_safe=False)
        return context

    # -- mining triage (change: mining-triage) ----------------------------

    def _mining_guarded(self) -> Any:
        """Context for the mining tools, or a structured fail-closed error.

        A missing or never-populated store is an explicit named error, never
        an empty successful result that reads like an answer.
        """
        try:
            context = self._load()
        except flt.FleetError as exc:
            return structured_error(MINING_UNAVAILABLE, str(exc),
                                    retry_safe=False)
        if not os.path.exists(context["db"]):
            return structured_error(
                MINING_UNAVAILABLE,
                "fleet store not found — run atlas_fleet_mining.py pass "
                "first", retry_safe=False)
        try:
            connection = self._connect(context["db"])
        except sqlite3.Error as exc:
            return structured_error(MINING_UNAVAILABLE, str(exc),
                                    retry_safe=True)
        try:
            present = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND "
                "name='mine_econ'").fetchone() is not None
            populated = present and connection.execute(
                "SELECT 1 FROM mine_econ LIMIT 1").fetchone() is not None
        except sqlite3.Error as exc:
            connection.close()
            return structured_error(MINING_UNAVAILABLE, str(exc),
                                    retry_safe=True)
        if not populated:
            connection.close()
            return structured_error(
                MINING_UNAVAILABLE,
                "mining screen has never been populated — run "
                "atlas_fleet_mining.py pass first", retry_safe=False)
        context["connection"] = connection
        return context

    @staticmethod
    def _stamps(connection: sqlite3.Connection) -> Dict[str, Any]:
        """Both clocks travel with every answer: economics move each pass,
        feasibility only when a clone moves."""
        econ = connection.execute(
            "SELECT MAX(ts) FROM mine_econ").fetchone()[0]
        try:
            feas = connection.execute(
                "SELECT value FROM mine_state WHERE key = "
                "'last_feasibility_ts'").fetchone()
        except sqlite3.Error:
            feas = None
        return {"econ_observed_at": econ,
                "feasibility_scanned_at": feas[0] if feas else None}

    def mining_board(self, limit: Optional[int],
                     include_cut: bool) -> Dict[str, Any]:
        context = self._mining_guarded()
        if "connection" not in context:
            return context
        connection = context["connection"]
        try:
            view = _mining().report(connection, context["config"],
                                    limit=limit, include_cut=include_cut)
        except sqlite3.Error as exc:
            return structured_error(MINING_UNAVAILABLE, str(exc),
                                    retry_safe=True)
        finally:
            connection.close()
        view.update(self._stamps_from_view(view))
        return view

    @staticmethod
    def _stamps_from_view(view: Dict[str, Any]) -> Dict[str, Any]:
        return {"econ_observed_at": view.get("econ_ts"),
                "feasibility_scanned_at": view.get("feasibility_ts")}

    def mining_subnet(self, netuid: int) -> Dict[str, Any]:
        context = self._mining_guarded()
        if "connection" not in context:
            return context
        connection = context["connection"]
        try:
            cursor = connection.execute(
                "SELECT * FROM mine_econ WHERE netuid = ? "
                "ORDER BY ts DESC LIMIT 1", (netuid,))
            columns = [d[0] for d in cursor.description]
            row = cursor.fetchone()
            if row is None:
                return dict(structured_error(
                    "no-mining-evidence",
                    "no mining observation recorded for netuid %s" % netuid,
                    retry_safe=False), **self._stamps(connection))
            econ = dict(zip(columns, row))
            feature = _mining().latest_feasibility(connection).get(
                int(netuid))
            stamps = self._stamps(connection)
        finally:
            connection.close()
        return {"status": "ok", "netuid": netuid, "economics": econ,
                "feasibility": feature or {"verdict": "unknown",
                                           "unscanned": True},
                **stamps}

    def mining_history(self, netuid: int, field: Optional[str],
                       limit: int) -> Dict[str, Any]:
        context = self._mining_guarded()
        if "connection" not in context:
            return context
        connection = context["connection"]
        try:
            columns = [d[1] for d in connection.execute(
                "PRAGMA table_info(mine_econ)")]
            if field is not None and field not in columns:
                return dict(structured_error(
                    "invalid", "unknown field %r (available: %s)"
                    % (field, ", ".join(sorted(columns))), retry_safe=False),
                    **self._stamps(connection))
            wanted = ["ts", "block_ref", "confidence"]
            if field and field not in wanted:
                wanted.append(field)
            elif not field:
                wanted += ["net_tao_month", "gross_tao_month", "price_tao",
                           "miner_burn_pct", "earner_count",
                           "top10_share_pct"]
            rows = connection.execute(
                "SELECT %s FROM mine_econ WHERE netuid = ? "
                "ORDER BY ts DESC LIMIT ?" % ", ".join(wanted),
                (netuid, limit)).fetchall()
            stamps = self._stamps(connection)
        except sqlite3.Error as exc:
            connection.close()
            return structured_error(MINING_UNAVAILABLE, str(exc),
                                    retry_safe=True)
        finally:
            try:
                connection.close()
            except sqlite3.Error:
                pass
        observations = [dict(zip(wanted, row)) for row in rows]
        if len(observations) < 2:
            return dict(structured_error(
                "insufficient-history",
                "netuid %s has %d recorded observation(s); at least two are "
                "needed before any change can be reported"
                % (netuid, len(observations)), retry_safe=True),
                observations=observations, **stamps)
        return {"status": "ok", "netuid": netuid,
                "observations": observations, **stamps}

    def _repos_for(self, connection: sqlite3.Connection,
                   netuids: List[int]) -> Dict[int, Optional[str]]:
        if not netuids:
            return {}
        marks = ",".join("?" for _ in netuids)
        return {row[0]: row[1] for row in connection.execute(
            "SELECT netuid, github_repo FROM slots WHERE netuid IN (%s)"
            % marks, netuids)}

    # -- tools ------------------------------------------------------------

    def search(self, query: str, netuid: Optional[int],
               max_results: int) -> Dict[str, Any]:
        context = self._guarded()
        if "error" in context:
            return context
        if netuid is not None and (not isinstance(netuid, int) or netuid < 0):
            return structured_error("invalid", "netuid must be a non-negative "
                                    "integer", retry_safe=False)
        if not fidx.tokenize(query):
            return structured_error("invalid", "query has no searchable terms",
                                    retry_safe=False)
        try:
            connection = self._connect(context["db"])
            try:
                hits = fidx.search(connection, query, netuid=netuid,
                                   max_results=max_results)
                repos = self._repos_for(
                    connection, sorted({hit["netuid"] for hit in hits}))
            finally:
                connection.close()
        except sqlite3.Error as exc:
            return structured_error("store-error", str(exc), retry_safe=True)
        if not hits:
            return {
                "status": "no-fleet-evidence",
                "query": query,
                "message": "No indexed subnet-repo file matches this query. "
                           "The tracked fleet cannot support an answer — say "
                           "so rather than filling the gap.",
            }
        return {
            "status": "ok",
            "query": query,
            "results": [{"netuid": hit["netuid"],
                         "github_repo": repos.get(hit["netuid"]),
                         "path": hit["path"],
                         "indexed_sha": hit["indexed_sha"],
                         "snippet": hit["snippet"]} for hit in hits],
            "note": "Content as of each file's indexed commit SHA — cite "
                    "netuid, repository, path, and SHA. This is the tracked "
                    "clones, not live chain state; check fleet_status for "
                    "staleness.",
        }

    def file(self, netuid: int, path: str, start_line: Optional[int],
             end_line: Optional[int]) -> Dict[str, Any]:
        context = self._guarded()
        if "error" in context:
            return context
        if not isinstance(netuid, int) or netuid < 0:
            return structured_error("invalid", "netuid must be a non-negative "
                                    "integer", retry_safe=False)
        clone = os.path.join(context["clone_root"], str(netuid))
        rel = path.replace("\\", "/").strip().lstrip("/")
        parts = rel.split("/")
        if not rel or ".." in parts or parts[0] == ".git":
            return structured_error("invalid", "path must be a relative "
                                    "repository path", retry_safe=False)
        try:
            connection = self._connect(context["db"])
            try:
                slot = flt.get_slot(connection, netuid)
                indexed_sha = self._indexed_sha(connection, netuid)
            finally:
                connection.close()
        except sqlite3.Error as exc:
            return structured_error("store-error", str(exc), retry_safe=True)
        if not slot or slot.get("status") != "active" or not os.path.isdir(
                os.path.join(clone, ".git")):
            return structured_error(
                "fleet-search-unavailable",
                "no active tracked clone for netuid %s" % netuid,
                retry_safe=False)
        real_clone = os.path.realpath(clone)
        abs_path = os.path.realpath(os.path.join(real_clone, rel))
        if not abs_path.startswith(real_clone + os.sep):
            return structured_error("invalid", "path escapes the tracked "
                                    "clone", retry_safe=False)
        try:
            sha = arp.local_sha(clone)
            dirty = arp.working_tree_dirty(clone)
        except arp.FatalRepoError as exc:
            return structured_error("store-error", str(exc), retry_safe=True)
        if dirty or indexed_sha != sha:
            return structured_error(
                "stale-state",
                "clone/index state is inconsistent for netuid %s (tree %s, "
                "indexed SHA %s vs local %s) — run atlas_fleet.py index; "
                "refusing to serve mixed state"
                % (netuid, "dirty" if dirty else "clean",
                   (indexed_sha or "none")[:12], sha[:12]),
                retry_safe=True)
        if not os.path.isfile(abs_path):
            return structured_error(
                "not-found", "no file %r at the tracked commit — use a path "
                "from a fleet_search result" % rel, retry_safe=False)
        try:
            with open(abs_path, "r", encoding="utf-8",
                      errors="replace") as handle:
                lines = handle.read().splitlines()
        except OSError as exc:
            return structured_error("store-error", str(exc), retry_safe=True)
        total = len(lines)
        start = max(1, start_line or 1)
        end = min(total, end_line or (start + MAX_FILE_LINES - 1))
        end = min(end, start + MAX_FILE_LINES - 1)
        return {
            "status": "ok",
            "netuid": netuid,
            "github_repo": slot.get("github_repo"),
            "path": rel,
            "commit_sha": sha,
            "total_lines": total,
            "lines": [start, end],
            "content": "\n".join(lines[start - 1:end]),
            "note": "Content at the subnet clone's local commit — cite netuid, "
                    "repository, path, and commit_sha.",
        }

    def _indexed_sha(self, connection: sqlite3.Connection,
                     netuid: int) -> Optional[str]:
        row = connection.execute(
            "SELECT indexed_sha FROM index_state WHERE netuid=?",
            (netuid,)).fetchone()
        return row[0] if row else None

    def status(self, netuid: Optional[int]) -> Dict[str, Any]:
        context = self._guarded()
        if "error" in context:
            return context
        try:
            connection = self._connect(context["db"])
            try:
                if netuid is not None:
                    info = fidx.index_freshness(connection, netuid=netuid)
                    info["status_note"] = (
                        "stale=true means the clone advanced past its indexed "
                        "SHA — do NOT present its indexed contents as current.")
                    return info
                overall = flt.fleet_status(connection)
                overall["index"] = fidx.index_freshness(connection)
                overall["note"] = (
                    "index.stale_slots counts slots whose clone advanced past "
                    "their indexed SHA — those are not searchable as current.")
                return overall
            finally:
                connection.close()
        except sqlite3.Error as exc:
            return structured_error("fleet-search-unavailable", str(exc),
                                    retry_safe=True)


class AuditLog:
    """Append-only, size-capped, redacted call log."""

    def __init__(self, path: str):
        self.path = path

    def record(self, tool: str, params: Dict[str, Any], outcome: str) -> None:
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


def handle_tool_call(store: FleetStore, audit: AuditLog, name: str,
                     arguments: Dict[str, Any]) -> Dict[str, Any]:
    if name == "fleet_search":
        query = arguments.get("query")
        if not isinstance(query, str) or not query.strip():
            payload: Dict[str, Any] = structured_error(
                "invalid", "query must be a non-empty string",
                retry_safe=False)
        else:
            netuid = arguments.get("netuid")
            max_results = arguments.get("max_results", DEFAULT_MAX_RESULTS)
            if not isinstance(max_results, int) \
                    or not 1 <= max_results <= MAX_MAX_RESULTS:
                max_results = DEFAULT_MAX_RESULTS
            payload = store.search(query.strip(), netuid, max_results)
    elif name == "fleet_file":
        netuid = arguments.get("netuid")
        path = arguments.get("path")
        start_line = arguments.get("start_line")
        end_line = arguments.get("end_line")
        if not isinstance(path, str) or not path.strip():
            payload = structured_error(
                "invalid", "path must be a non-empty string", retry_safe=False)
        elif any(value is not None and (not isinstance(value, int) or value < 1)
                 for value in (start_line, end_line)):
            payload = structured_error(
                "invalid", "start_line/end_line must be positive integers",
                retry_safe=False)
        else:
            payload = store.file(netuid, path, start_line, end_line)
    elif name == "fleet_status":
        payload = store.status(arguments.get("netuid"))
    elif name == "mining_board":
        limit = arguments.get("limit", DEFAULT_BOARD_LIMIT)
        if not isinstance(limit, int) or not 1 <= limit <= MAX_BOARD_LIMIT:
            limit = DEFAULT_BOARD_LIMIT
        payload = store.mining_board(limit,
                                     bool(arguments.get("include_cut")))
    elif name in ("mining_subnet", "mining_history"):
        netuid = arguments.get("netuid")
        if not isinstance(netuid, int) or netuid < 0:
            payload = structured_error(
                "invalid", "netuid must be a non-negative integer",
                retry_safe=False)
        elif name == "mining_subnet":
            payload = store.mining_subnet(netuid)
        else:
            rows = arguments.get("limit", DEFAULT_HISTORY_ROWS)
            if not isinstance(rows, int) or not 2 <= rows <= MAX_HISTORY_ROWS:
                rows = DEFAULT_HISTORY_ROWS
            field = arguments.get("field")
            payload = store.mining_history(
                netuid, field if isinstance(field, str) else None, rows)
    else:
        payload = structured_error(
            "invalid", "unknown tool: %r (available: %s)"
            % (name, ", ".join(tool["name"] for tool in TOOLS)),
            retry_safe=False)
    audit.record(name, arguments,
                 payload.get("status", "error")
                 if "error" not in payload else payload["error"]["category"])
    return payload


def handle_message(store: FleetStore, audit: AuditLog,
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
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
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
                          "tools/call needs a name and an arguments object")
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
        config = flt.load_config(config_path)
        base = os.path.dirname(config["db"])
    except flt.FleetError:
        base = os.path.join(_REPO_ROOT, "var", "fleet")
    return os.path.join(base, AUDIT_FILE_NAME)


def serve(config_path: str = flt.CONFIG_FILE, stdin: Any = None,
          stdout: Any = None) -> None:
    stdin = stdin if stdin is not None else sys.stdin
    stdout = stdout if stdout is not None else sys.stdout
    store = FleetStore(config_path)
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
                        _error(None, PARSE_ERROR, "expected a JSON-RPC object"))
        if response is not None:
            stdout.write(json.dumps(response) + "\n")
            stdout.flush()


if __name__ == "__main__":
    config_file = sys.argv[sys.argv.index("--config") + 1] \
        if "--config" in sys.argv else flt.CONFIG_FILE
    serve(config_file)
