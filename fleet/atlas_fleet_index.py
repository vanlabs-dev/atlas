#!/usr/bin/env python3
"""Shared full-text index over the subnet-repo fleet (change: fleet-search).

Generalizes repotrack's proven `files` / `files_fts` indexer across the
~104-clone fleet into ONE index scoped by `(netuid, epoch)`, stored in the
existing fleet store (`var/fleet/fleet.db`). Reuses repotrack's pure helpers
(`_indexable` / `_walk_tree` / `local_sha`) via a lazy import — it does NOT fork
`run_index`, and it never builds, tests, or executes subnet code (it only reads
the already-checked-out working tree).

Public surface (consumed by the reconcile hooks, the `fleet index` CLI, and the
read-only `atlas-fleet` MCP server):

- ensure_schema(conn)                              — create index tables
- index_slot(conn, netuid, epoch, clone_dir, cfg,  — full/incremental per slot
             changed_paths=None, local_sha=None)
- purge_slot(conn, netuid, epoch=None)             — remove a netuid's rows
- index_freshness(conn, netuid=None)               — indexed-vs-local coverage
- search(conn, query, netuid=None, max_results=…)  — ranked FTS with provenance
"""

from __future__ import annotations

import datetime
import os
import re
import sys
from typing import Any, Dict, List, Optional, Sequence

_TOKEN = re.compile(r"[A-Za-z0-9_]+")
MAX_QUERY_TOKENS = 12

_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_MODULE_DIR)

INDEXER_SCHEMA_VERSION = "1"

# Polyglot default when a config carries no `index` block (subnet repos span
# many languages); the shipped fleet/config.json overrides this.
DEFAULT_INDEX_CFG: Dict[str, Any] = {
    "extensions": [".rs", ".toml", ".md", ".py", ".js", ".ts", ".tsx", ".jsx",
                   ".go", ".sol", ".move", ".vy", ".java", ".rb", ".c", ".h",
                   ".cpp", ".hpp", ".sh", ".yml", ".yaml", ".json", ".txt",
                   ".cfg", ".ini", ".proto"],
    "max_file_bytes": 524288,
}

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS fleet_files (
    id INTEGER PRIMARY KEY,
    netuid INTEGER NOT NULL,
    epoch INTEGER NOT NULL,
    path TEXT NOT NULL,
    indexed_sha TEXT NOT NULL,
    byte_size INTEGER NOT NULL,
    indexed_at TEXT NOT NULL,
    UNIQUE (netuid, path)
);
CREATE VIRTUAL TABLE IF NOT EXISTS fleet_files_fts USING fts5(path, content);
CREATE TABLE IF NOT EXISTS index_state (
    netuid INTEGER PRIMARY KEY,
    epoch INTEGER NOT NULL,
    indexed_sha TEXT NOT NULL,
    indexer_schema TEXT NOT NULL,
    files INTEGER NOT NULL,
    indexed_at TEXT NOT NULL
);
"""

_RT: Any = None


def _repotrack() -> Any:
    """Lazy import of the repotrack module for its pure indexer helpers."""
    global _RT
    if _RT is None:
        sys.path.insert(0, os.path.join(_REPO_ROOT, "repotrack"))
        import atlas_repo  # noqa: E402
        _RT = atlas_repo
    return _RT


def _utc_now() -> str:
    return datetime.datetime.now(tz=datetime.timezone.utc).isoformat()


def ensure_schema(connection: Any) -> None:
    """Create the index tables if absent. Owns only its own tables — the
    reconcile store's `SCHEMA_SQL` is never touched."""
    connection.executescript(SCHEMA_SQL)


# ---------------------------------------------------------------------------
# Per-slot indexing — every DELETE/INSERT scoped by netuid (never a
# whole-table wipe), so one slot's index is independent of the other ~103.
# ---------------------------------------------------------------------------


def _state(connection: Any, netuid: int) -> Optional[tuple]:
    return connection.execute(
        "SELECT epoch, indexed_sha, indexer_schema, files FROM index_state "
        "WHERE netuid=?", (netuid,)).fetchone()


def _remove_one(connection: Any, netuid: int, rel_path: str) -> bool:
    row = connection.execute(
        "SELECT id FROM fleet_files WHERE netuid=? AND path=?",
        (netuid, rel_path)).fetchone()
    if row is None:
        return False
    connection.execute("DELETE FROM fleet_files_fts WHERE rowid=?", (row[0],))
    connection.execute("DELETE FROM fleet_files WHERE id=?", (row[0],))
    return True


def _index_one(connection: Any, netuid: int, epoch: int, clone_dir: str,
               rel_path: str, sha: str) -> None:
    abs_path = os.path.join(clone_dir, rel_path)
    with open(abs_path, "r", encoding="utf-8", errors="replace") as handle:
        content = handle.read()
    _remove_one(connection, netuid, rel_path)
    cursor = connection.execute(
        "INSERT INTO fleet_files (netuid, epoch, path, indexed_sha, "
        "byte_size, indexed_at) VALUES (?, ?, ?, ?, ?, ?)",
        (netuid, epoch, rel_path, sha, os.path.getsize(abs_path), _utc_now()))
    connection.execute(
        "INSERT INTO fleet_files_fts (rowid, path, content) VALUES (?, ?, ?)",
        (cursor.lastrowid, rel_path, content))


def purge_slot(connection: Any, netuid: int,
               epoch: Optional[int] = None) -> int:
    """Remove a netuid's index rows (all epochs, or one epoch) and — when no
    epoch is scoped — its `index_state`. Returns the row count removed."""
    if epoch is None:
        ids = [row[0] for row in connection.execute(
            "SELECT id FROM fleet_files WHERE netuid=?", (netuid,))]
    else:
        ids = [row[0] for row in connection.execute(
            "SELECT id FROM fleet_files WHERE netuid=? AND epoch=?",
            (netuid, epoch))]
    for row_id in ids:
        connection.execute("DELETE FROM fleet_files_fts WHERE rowid=?",
                           (row_id,))
    if epoch is None:
        connection.execute("DELETE FROM fleet_files WHERE netuid=?", (netuid,))
        connection.execute("DELETE FROM index_state WHERE netuid=?", (netuid,))
    else:
        connection.execute("DELETE FROM fleet_files WHERE netuid=? AND epoch=?",
                           (netuid, epoch))
    return len(ids)


def index_slot(connection: Any, netuid: int, epoch: int, clone_dir: str,
               index_cfg: Optional[Dict[str, Any]] = None,
               changed_paths: Optional[Sequence[str]] = None,
               local_sha: Optional[str] = None) -> Dict[str, Any]:
    """Index one slot's checked-out working tree at its local SHA.

    Full walk when there is no current-schema baseline at this epoch, or when
    `changed_paths` is None; incremental over `changed_paths` only when a valid
    baseline exists (mirrors repotrack `run_index`). No-op when already indexed
    at (sha, epoch, schema). Full mode first purges this netuid's rows, so a new
    epoch never leaves the prior project's files behind."""
    rt = _repotrack()
    index_cfg = index_cfg or DEFAULT_INDEX_CFG
    sha = local_sha or rt.local_sha(clone_dir)
    state = _state(connection, netuid)
    if (state is not None and state[1] == sha and state[0] == epoch
            and state[2] == INDEXER_SCHEMA_VERSION):
        return {"mode": "noop", "netuid": netuid, "sha": sha,
                "indexed": 0, "removed": 0, "skipped": 0}
    have_baseline = (state is not None and state[0] == epoch
                     and state[2] == INDEXER_SCHEMA_VERSION)
    mode = "incremental" if (changed_paths is not None and have_baseline) \
        else "full"

    if mode == "full":
        purge_slot(connection, netuid)
        candidates: Sequence[str] = rt._walk_tree(clone_dir)
    else:
        candidates = sorted(set(changed_paths or ()))

    indexed = removed = skipped = 0
    for rel_path in candidates:
        abs_path = os.path.join(clone_dir, rel_path)
        if not os.path.isfile(abs_path):
            removed += 1 if _remove_one(connection, netuid, rel_path) else 0
            continue
        if rt._indexable(abs_path, rel_path, index_cfg) is not None:
            if mode == "incremental":
                _remove_one(connection, netuid, rel_path)
            skipped += 1
            continue
        _index_one(connection, netuid, epoch, clone_dir, rel_path, sha)
        indexed += 1

    if mode == "incremental":
        # Unchanged files' content is identical at the new SHA — restamp so
        # every row cites the current tracked commit (indexed_at is preserved).
        connection.execute(
            "UPDATE fleet_files SET indexed_sha=? WHERE netuid=?", (sha, netuid))
    files_count = connection.execute(
        "SELECT count(*) FROM fleet_files WHERE netuid=?", (netuid,)).fetchone()[0]
    connection.execute(
        "INSERT INTO index_state (netuid, epoch, indexed_sha, indexer_schema, "
        "files, indexed_at) VALUES (?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(netuid) DO UPDATE SET epoch=excluded.epoch, "
        "indexed_sha=excluded.indexed_sha, indexer_schema=excluded.indexer_schema, "
        "files=excluded.files, indexed_at=excluded.indexed_at",
        (netuid, epoch, sha, INDEXER_SCHEMA_VERSION, files_count, _utc_now()))
    return {"mode": mode, "netuid": netuid, "sha": sha,
            "indexed": indexed, "removed": removed, "skipped": skipped}


# ---------------------------------------------------------------------------
# Freshness reporting (fleet_status / backfill) and read-only search.
# ---------------------------------------------------------------------------


def index_freshness(connection: Any,
                    netuid: Optional[int] = None) -> Dict[str, Any]:
    """Index coverage relative to the clones' local SHAs. With a netuid: that
    slot's per-slot detail; without: fleet-wide counts. A slot is `stale` when
    it is indexed but its clone's `slots.local_sha` has advanced past the
    recorded indexed SHA."""
    if netuid is not None:
        row = connection.execute(
            "SELECT s.status, s.local_sha, i.epoch, i.indexed_sha, i.files "
            "FROM slots s LEFT JOIN index_state i ON i.netuid = s.netuid "
            "WHERE s.netuid = ?", (netuid,)).fetchone()
        if row is None:
            row = connection.execute(
                "SELECT NULL, NULL, epoch, indexed_sha, files FROM "
                "index_state WHERE netuid = ?", (netuid,)).fetchone()
        if row is None:
            return {"netuid": netuid, "indexed": False, "stale": False,
                    "status": None, "local_sha": None, "indexed_sha": None,
                    "epoch": None, "files": 0}
        status, local_sha, epoch, indexed_sha, files = row
        indexed = indexed_sha is not None
        stale = bool(indexed and local_sha is not None
                     and indexed_sha != local_sha)
        return {"netuid": netuid, "indexed": indexed, "stale": stale,
                "status": status, "local_sha": local_sha,
                "indexed_sha": indexed_sha, "epoch": epoch,
                "files": files or 0}

    rows = connection.execute(
        "SELECT i.indexed_sha, i.files, s.local_sha FROM index_state i "
        "LEFT JOIN slots s ON s.netuid = i.netuid").fetchall()
    indexed_slots = len(rows)
    stale_slots = sum(1 for indexed_sha, _files, local_sha in rows
                      if local_sha is not None and indexed_sha != local_sha)
    total_files = sum((files or 0) for _sha, files, _local in rows)
    return {"indexed_slots": indexed_slots, "stale_slots": stale_slots,
            "total_indexed_files": total_files}


def tokenize(query: str) -> List[str]:
    """Reduce a free-text query to allowlisted search tokens, so full-text
    operators/punctuation in the query can never inject or error the MATCH."""
    return _TOKEN.findall(query or "")[:MAX_QUERY_TOKENS]


def search(connection: Any, query: str, netuid: Optional[int] = None,
           max_results: int = 10) -> List[Dict[str, Any]]:
    """Ranked full-text search over the fleet index (all subnets, or one
    netuid), returning each hit's netuid, path, indexed SHA, and snippet.
    Returns an empty list for a query with no searchable terms or no match."""
    tokens = tokenize(query)
    if not tokens:
        return []
    match = " OR ".join('"%s"' % token for token in tokens)
    sql = ("SELECT ff.netuid, ff.path, ff.indexed_sha, "
           "snippet(fleet_files_fts, 1, '>>', '<<', ' … ', 24) "
           "FROM fleet_files_fts JOIN fleet_files ff "
           "ON ff.id = fleet_files_fts.rowid WHERE fleet_files_fts MATCH ?")
    params: List[Any] = [match]
    if netuid is not None:
        sql += " AND ff.netuid = ?"
        params.append(netuid)
    sql += " ORDER BY bm25(fleet_files_fts) LIMIT ?"
    params.append(max_results)
    return [{"netuid": n, "path": p, "indexed_sha": s, "snippet": snip}
            for n, p, s, snip in connection.execute(sql, params).fetchall()]
