#!/usr/bin/env python3
"""Atlas Phase 3 — subtensor repository tracking (ATLAS-REPO-001…009).

Maintains a verified, non-shallow clone of the mainnet subtensor
repository with a safe, journaled update process, per-range change
records, and an incremental SQLite/FTS5 file index that the read-only
`atlas-repo` MCP server (atlas_repo_server.py) serves to Hermes.

Flow (all operator-invoked; scheduled execution stays gated on the
PRD §21 Q20 interval decision — nothing here installs a timer):
    validate-identity  report GitHub metadata for the claimed repository
                       (canonical name / moved, archived, default branch)
                       — report only, no state created (ATLAS-REPO-001)
    setup              full clone + non-shallow verification + pinned
                       branch checkout + push-URL disable (ATLAS-REPO-002/003)
    update             journaled pipeline: remote-identity check → clean
                       tree check → fetch → fast-forward or deterministic
                       reset (never merge) → change record → incremental
                       index (ATLAS-REPO-004/005/006)
    index              full (re)build of the file index at the local SHA
    status             every ATLAS-REPO-007 freshness field

Guard: `setup` and `update` refuse to run until the repository identity
is operator-confirmed and recorded (config.json `confirmed_decision`
references the docs/decisions.md entry). Nothing is assumed before it
is recorded (PRD §5.5).

Envelope: unprivileged; writes only the clone, store, and 0600 reports
under gitignored var/repotrack/; never invokes push/commit/rewrite in
the tracked repository (the push URL is disabled at setup as defense in
depth); no build or test of subtensor is ever run (ATLAS-REPO-009).
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
import secrets as secretsmod
from typing import Any, Dict, List, Optional, Sequence, Tuple

_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_MODULE_DIR)

REPOTRACK_VERSION = "0.1.0"
INDEXER_SCHEMA_VERSION = "1"

CONFIG_FILE = os.path.join(_MODULE_DIR, "config.json")
DEFAULT_OUTPUT_DIR = os.path.join("var", "repotrack")
GITHUB_API = "https://api.github.com/repos/%s/%s"
PUSH_URL_DISABLED = "DISABLED"
SUMMARY_LABEL = "[machine summary — not verified effect]"

GIT_TIMEOUT = 600
API_TIMEOUT = 30
MAX_COMMITS_RECORDED = 500
MAX_FILES_RECORDED = 2000
SNIFF_BYTES = 8192

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS update_runs (
    run_id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,
    error TEXT,
    prev_sha TEXT,
    new_sha TEXT,
    fast_forward INTEGER
);
CREATE TABLE IF NOT EXISTS change_ranges (
    id INTEGER PRIMARY KEY,
    run_id TEXT NOT NULL,
    prev_sha TEXT NOT NULL,
    new_sha TEXT NOT NULL,
    retrieved_at TEXT NOT NULL,
    non_fast_forward INTEGER NOT NULL,
    commits_json TEXT NOT NULL,
    files_json TEXT NOT NULL,
    tags_json TEXT NOT NULL,
    index_status TEXT NOT NULL,
    index_detail TEXT,
    summary TEXT NOT NULL,
    prev_spec INTEGER,
    new_spec INTEGER
);
CREATE TABLE IF NOT EXISTS files (
    id INTEGER PRIMARY KEY,
    path TEXT NOT NULL UNIQUE,
    indexed_sha TEXT NOT NULL,
    byte_size INTEGER NOT NULL,
    indexed_at TEXT NOT NULL
);
CREATE VIRTUAL TABLE IF NOT EXISTS files_fts USING fts5(path, content);
CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY,
    timestamp TEXT NOT NULL,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    detail TEXT NOT NULL
);
"""

META_INDEXED_SHA = "indexed_sha"
META_INDEXER_SCHEMA = "indexer_schema_version"
META_LAST_FETCH_ATTEMPT = "last_fetch_attempt"
META_LAST_FETCH_SUCCESS = "last_fetch_success"
META_LAST_DETECTED_UPDATE = "last_detected_update"
META_LAST_REMOTE_SHA = "last_remote_sha"


class FatalRepoError(Exception):
    """Input-contract or pipeline failure; last good state is preserved."""


# ---------------------------------------------------------------------------
# Shared-helper access (lazy so the read-only server can import this module
# without pulling the hermes/inventory verifier chain)
# ---------------------------------------------------------------------------

_AHV: Any = None


def _ahv() -> Any:
    global _AHV
    if _AHV is None:
        sys.path.insert(0, os.path.join(_REPO_ROOT, "hermes"))
        import atlas_hermes_verify  # noqa: E402
        _AHV = atlas_hermes_verify
    return _AHV


def _redact(text: str) -> str:
    return _ahv().inv.redact(text)


def _write_private(path: str, content: str) -> None:
    _ahv()._write_private(path, content)


def _account() -> str:
    return _ahv()._account()


def _utc_now() -> str:
    return datetime.datetime.now(tz=datetime.timezone.utc).isoformat()


def _run_id() -> str:
    return (time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
            + "-" + secretsmod.token_hex(4))


# ---------------------------------------------------------------------------
# Config (pinned identity + policy)
# ---------------------------------------------------------------------------

_IDENTITY_FIELDS = ("owner", "name", "clone_url", "branch")


def load_config(path: str = CONFIG_FILE) -> Dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            config = json.load(handle)
    except (OSError, ValueError) as exc:
        raise FatalRepoError("cannot load config %s: %s" % (path, exc))
    for key in ("identity", "update_interval_hours", "stale_multiplier",
                "clone_dir", "db", "index"):
        if key not in config:
            raise FatalRepoError("config %s is missing %r" % (path, key))
    index = config["index"]
    if (not isinstance(index.get("extensions"), list)
            or not isinstance(index.get("max_file_bytes"), int)):
        raise FatalRepoError("config index section needs extensions[] and "
                             "max_file_bytes")
    return config


def require_confirmed_identity(config: Dict[str, Any]) -> Dict[str, str]:
    """ATLAS-REPO-001 gate: block unless the identity is operator-confirmed
    and recorded (config.confirmed_decision names the decision-log entry)."""
    identity = config.get("identity") or {}
    missing = [key for key in _IDENTITY_FIELDS if not identity.get(key)]
    if missing:
        raise FatalRepoError(
            "repository identity is incomplete (missing: %s) — run "
            "validate-identity and record the operator confirmation first"
            % ", ".join(missing))
    if not config.get("confirmed_decision"):
        raise FatalRepoError(
            "repository identity is NOT operator-confirmed "
            "(config confirmed_decision is empty) — ATLAS-REPO-001 blocks "
            "setup/update until the confirmation is recorded in "
            "docs/decisions.md and referenced in config.json")
    return {key: identity[key] for key in _IDENTITY_FIELDS}


def _resolve(repo_root: str, path: str) -> str:
    return path if os.path.isabs(path) else os.path.join(repo_root, path)


# ---------------------------------------------------------------------------
# Git plumbing (fixed-argument invocations only; no shell)
# ---------------------------------------------------------------------------


def _git(clone_dir: str, *args: str,
         timeout: int = GIT_TIMEOUT) -> Tuple[int, str, str]:
    try:
        proc = subprocess.run(
            ["git", "-C", clone_dir] + list(args),
            capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace")
    except FileNotFoundError:
        raise FatalRepoError("git executable not found")
    except subprocess.TimeoutExpired:
        return 124, "", "timeout after %ds: git %s" % (timeout,
                                                       " ".join(args))
    return proc.returncode, proc.stdout, proc.stderr


def _git_out(clone_dir: str, *args: str, timeout: int = GIT_TIMEOUT) -> str:
    code, out, err = _git(clone_dir, *args, timeout=timeout)
    if code != 0:
        raise FatalRepoError("git %s failed (%d): %s"
                             % (" ".join(args), code, err.strip()[:300]))
    return out.strip()


def working_tree_dirty(clone_dir: str) -> List[str]:
    out = _git_out(clone_dir, "status", "--porcelain")
    return [line for line in out.splitlines() if line.strip()]


def local_sha(clone_dir: str) -> str:
    return _git_out(clone_dir, "rev-parse", "HEAD")


def clone_size_bytes(clone_dir: str) -> Optional[int]:
    code, out, _ = _git(clone_dir, "count-objects", "-v")
    if code != 0:
        return None
    total_kib = 0
    for line in out.splitlines():
        if line.startswith(("size:", "size-pack:")):
            total_kib += int(line.split(":", 1)[1].strip())
    return total_kib * 1024


# ---------------------------------------------------------------------------
# validate-identity (report only — ATLAS-REPO-001 evidence, not the decision)
# ---------------------------------------------------------------------------


def fetch_repo_metadata(owner: str, name: str,
                        timeout: int = API_TIMEOUT) -> Dict[str, Any]:
    request = urllib.request.Request(
        GITHUB_API % (owner, name),
        headers={"User-Agent": "atlas-repotrack/" + REPOTRACK_VERSION,
                 "Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise FatalRepoError("GitHub API returned HTTP %d for %s/%s — "
                             "identity cannot be validated"
                             % (exc.code, owner, name))
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise FatalRepoError("GitHub API unreachable (%s) — identity "
                             "cannot be validated" % exc)
    return body


def validate_identity(owner: str, name: str, output_dir: str,
                      timeout: int = API_TIMEOUT) -> Dict[str, Any]:
    body = fetch_repo_metadata(owner, name, timeout=timeout)
    requested = "%s/%s" % (owner, name)
    canonical = body.get("full_name") or ""
    report = {
        "run_id": _run_id(),
        "generated_at": _utc_now(),
        "requested": requested,
        "canonical_full_name": canonical,
        "moved_or_renamed": canonical.lower() != requested.lower(),
        "archived": bool(body.get("archived")),
        "disabled": bool(body.get("disabled")),
        "fork": bool(body.get("fork")),
        "default_branch": body.get("default_branch"),
        "clone_url": body.get("clone_url"),
        "html_url": body.get("html_url"),
        "pushed_at": body.get("pushed_at"),
        "note": ("Evidence only — ATLAS-REPO-001 requires the operator to "
                 "confirm owner/name, canonical clone URL, default branch, "
                 "and which branch or release represents mainnet, recorded "
                 "in docs/decisions.md before setup may run."),
    }
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir,
                        "identity-%s.json" % report["run_id"])
    _write_private(path, json.dumps(report, indent=2, sort_keys=True))
    report["report_path"] = path
    return report


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


def open_store(db_path: str) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.executescript(SCHEMA_SQL)
    # Additive migration: pre-spec-tiering stores lack the runtime
    # spec_version columns; existing rows stay NULL (= unknown, never
    # guessed).
    columns = {row[1] for row in connection.execute(
        "PRAGMA table_info(change_ranges)")}
    for column in ("prev_spec", "new_spec"):
        if column not in columns:
            connection.execute(
                "ALTER TABLE change_ranges ADD COLUMN %s INTEGER" % column)
    connection.commit()
    return connection


def _audit(connection: sqlite3.Connection, actor: str, action: str,
           detail: str) -> None:
    connection.execute(
        "INSERT INTO audit (timestamp, actor, action, detail) "
        "VALUES (?, ?, ?, ?)", (_utc_now(), actor, action, _redact(detail)))


def meta_get(connection: sqlite3.Connection, key: str) -> Optional[str]:
    row = connection.execute("SELECT value FROM meta WHERE key = ?",
                             (key,)).fetchone()
    return row[0] if row else None


def meta_set(connection: sqlite3.Connection, key: str, value: str) -> None:
    connection.execute(
        "INSERT INTO meta (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value))


# ---------------------------------------------------------------------------
# setup (full clone, non-shallow verification, push disable)
# ---------------------------------------------------------------------------


def _verify_clone(clone_dir: str, identity: Dict[str, str]) -> List[str]:
    """Return verification findings (empty = clone matches the pinned
    identity, is non-shallow, and has the push URL disabled)."""
    findings: List[str] = []
    if _git_out(clone_dir, "rev-parse", "--is-shallow-repository") != "false":
        findings.append("clone is SHALLOW — ATLAS-REPO-002 requires "
                        "complete reachable history")
    fetch_url = _git_out(clone_dir, "remote", "get-url", "origin")
    if fetch_url != identity["clone_url"]:
        findings.append("remote URL %r does not match pinned %r"
                        % (fetch_url, identity["clone_url"]))
    push_url = _git_out(clone_dir, "remote", "get-url", "--push", "origin")
    if push_url != PUSH_URL_DISABLED:
        findings.append("push URL is %r, expected disabled" % push_url)
    code, _, err = _git(clone_dir, "rev-parse", "--verify", "--quiet",
                        "refs/remotes/origin/" + identity["branch"])
    if code != 0:
        findings.append("pinned branch %r not present on origin (%s)"
                        % (identity["branch"], err.strip()[:120]))
    branch = _git_out(clone_dir, "rev-parse", "--abbrev-ref", "HEAD")
    if branch != identity["branch"]:
        findings.append("checked-out branch %r is not the pinned %r"
                        % (branch, identity["branch"]))
    return findings


def setup(config: Dict[str, Any], repo_root: str = _REPO_ROOT,
          actor: Optional[str] = None) -> int:
    identity = require_confirmed_identity(config)
    clone_dir = _resolve(repo_root, config["clone_dir"])
    db_path = _resolve(repo_root, config["db"])
    output_dir = os.path.dirname(db_path)
    actor = actor or _account()

    if os.path.isdir(os.path.join(clone_dir, ".git")):
        print("clone already exists at %s — verifying only" % clone_dir)
        _git_out(clone_dir, "remote", "set-url", "--push", "origin",
                 PUSH_URL_DISABLED)
    elif os.path.isdir(clone_dir) and os.listdir(clone_dir):
        raise FatalRepoError("%s exists and is not a git clone — refusing "
                             "to touch it" % clone_dir)
    else:
        os.makedirs(os.path.dirname(clone_dir), exist_ok=True)
        print("cloning %s (full history) ..." % identity["clone_url"])
        code, _, err = _git(os.path.dirname(clone_dir), "clone",
                            identity["clone_url"], clone_dir)
        if code != 0:
            raise FatalRepoError("clone failed: %s" % err.strip()[:300])
        _git_out(clone_dir, "checkout", identity["branch"])
        _git_out(clone_dir, "remote", "set-url", "--push", "origin",
                 PUSH_URL_DISABLED)

    findings = _verify_clone(clone_dir, identity)
    report = {
        "run_id": _run_id(),
        "generated_at": _utc_now(),
        "clone_dir": clone_dir,
        "identity": identity,
        "non_shallow": _git_out(clone_dir, "rev-parse",
                                "--is-shallow-repository") == "false",
        "local_sha": local_sha(clone_dir),
        "clone_size_bytes": clone_size_bytes(clone_dir),
        "findings": findings,
        "verdict": "ok" if not findings else "failed",
    }
    os.makedirs(output_dir, exist_ok=True)
    _write_private(os.path.join(output_dir,
                                "setup-%s.json" % report["run_id"]),
                   json.dumps(report, indent=2, sort_keys=True))
    connection = open_store(db_path)
    try:
        _audit(connection, actor, "setup",
               "verdict=%s sha=%s findings=%d"
               % (report["verdict"], report["local_sha"][:12],
                  len(findings)))
        connection.commit()
    finally:
        connection.close()
    print("setup %s: %s @ %s" % (report["verdict"], identity["clone_url"],
                                 report["local_sha"][:12]))
    for finding in findings:
        print("  FINDING: %s" % finding)
    return 0 if not findings else 1


# ---------------------------------------------------------------------------
# Indexing (ATLAS-REPO-006)
# ---------------------------------------------------------------------------


def _indexable(abs_path: str, rel_path: str,
               index_cfg: Dict[str, Any]) -> Optional[str]:
    """Return a skip reason, or None when the file should be indexed."""
    ext = os.path.splitext(rel_path)[1].lower()
    if ext not in index_cfg["extensions"]:
        return "extension"
    try:
        size = os.path.getsize(abs_path)
    except OSError:
        return "unreadable"
    if size > index_cfg["max_file_bytes"]:
        return "too-large"
    try:
        with open(abs_path, "rb") as handle:
            if b"\x00" in handle.read(SNIFF_BYTES):
                return "binary"
    except OSError:
        return "unreadable"
    return None


def _index_one(connection: sqlite3.Connection, clone_dir: str,
               rel_path: str, sha: str) -> None:
    abs_path = os.path.join(clone_dir, rel_path)
    with open(abs_path, "r", encoding="utf-8", errors="replace") as handle:
        content = handle.read()
    _remove_one(connection, rel_path)
    cursor = connection.execute(
        "INSERT INTO files (path, indexed_sha, byte_size, indexed_at) "
        "VALUES (?, ?, ?, ?)",
        (rel_path, sha, os.path.getsize(abs_path), _utc_now()))
    connection.execute(
        "INSERT INTO files_fts (rowid, path, content) VALUES (?, ?, ?)",
        (cursor.lastrowid, rel_path, content))


def _remove_one(connection: sqlite3.Connection, rel_path: str) -> bool:
    row = connection.execute("SELECT id FROM files WHERE path = ?",
                             (rel_path,)).fetchone()
    if row is None:
        return False
    connection.execute("DELETE FROM files_fts WHERE rowid = ?", (row[0],))
    connection.execute("DELETE FROM files WHERE id = ?", (row[0],))
    return True


def _walk_tree(clone_dir: str) -> List[str]:
    paths: List[str] = []
    for root, dirs, names in os.walk(clone_dir):
        dirs[:] = [d for d in dirs if d != ".git"]
        for name in names:
            paths.append(os.path.relpath(os.path.join(root, name),
                                         clone_dir).replace(os.sep, "/"))
    return sorted(paths)


def run_index(connection: sqlite3.Connection, clone_dir: str,
              index_cfg: Dict[str, Any],
              changed_paths: Optional[Sequence[str]] = None
              ) -> Dict[str, Any]:
    """Index at the current local SHA. Full walk when `changed_paths` is
    None, the index is empty, or the indexer schema version changed
    (recorded rebuild); otherwise only the changed paths are touched."""
    sha = local_sha(clone_dir)
    stored_schema = meta_get(connection, META_INDEXER_SCHEMA)
    have_index = meta_get(connection, META_INDEXED_SHA) is not None
    if stored_schema is not None and stored_schema != INDEXER_SCHEMA_VERSION:
        mode = "rebuild"
    elif changed_paths is None or not have_index:
        mode = "full"
    else:
        mode = "incremental"

    if mode in ("full", "rebuild"):
        connection.execute("DELETE FROM files_fts")
        connection.execute("DELETE FROM files")
        candidates: Sequence[str] = _walk_tree(clone_dir)
    else:
        candidates = sorted(set(changed_paths or ()))

    indexed = removed = skipped = 0
    for rel_path in candidates:
        abs_path = os.path.join(clone_dir, rel_path)
        if not os.path.isfile(abs_path):
            removed += 1 if _remove_one(connection, rel_path) else 0
            continue
        reason = _indexable(abs_path, rel_path, index_cfg)
        if reason is not None:
            if mode == "incremental":
                _remove_one(connection, rel_path)
            skipped += 1
            continue
        _index_one(connection, clone_dir, rel_path, sha)
        indexed += 1

    if mode == "incremental":
        # unchanged files' content is identical at the new SHA — stamp
        # every row so citations reference the current tracked commit
        connection.execute("UPDATE files SET indexed_sha = ?", (sha,))
    meta_set(connection, META_INDEXED_SHA, sha)
    meta_set(connection, META_INDEXER_SCHEMA, INDEXER_SCHEMA_VERSION)
    return {"mode": mode, "sha": sha, "indexed": indexed,
            "removed": removed, "skipped": skipped}


def index_command(config: Dict[str, Any], repo_root: str = _REPO_ROOT,
                  actor: Optional[str] = None) -> int:
    require_confirmed_identity(config)
    clone_dir = _resolve(repo_root, config["clone_dir"])
    db_path = _resolve(repo_root, config["db"])
    actor = actor or _account()
    connection = open_store(db_path)
    try:
        outcome = run_index(connection, clone_dir, config["index"])
        _audit(connection, actor, "index", json.dumps(outcome))
        connection.commit()
    finally:
        connection.close()
    print("index %s @ %s: %d indexed, %d removed, %d skipped"
          % (outcome["mode"], outcome["sha"][:12], outcome["indexed"],
             outcome["removed"], outcome["skipped"]))
    return 0


# ---------------------------------------------------------------------------
# update (ATLAS-REPO-004/005) — strictly ordered, journaled
# ---------------------------------------------------------------------------


def _collect_range(clone_dir: str, prev_sha: str,
                   new_sha: str) -> Dict[str, Any]:
    commit_lines = _git_out(
        clone_dir, "log", "--format=%H%x09%s",
        "%s..%s" % (prev_sha, new_sha)).splitlines()
    commits = [{"sha": line.split("\t", 1)[0],
                "subject": line.split("\t", 1)[1] if "\t" in line else ""}
               for line in commit_lines[:MAX_COMMITS_RECORDED]]
    numstat_lines = _git_out(
        clone_dir, "diff", "--numstat", "--no-renames",
        prev_sha, new_sha).splitlines()
    files: List[Dict[str, Any]] = []
    for line in numstat_lines[:MAX_FILES_RECORDED]:
        parts = line.split("\t", 2)
        if len(parts) != 3:
            continue
        additions = int(parts[0]) if parts[0].isdigit() else None
        deletions = int(parts[1]) if parts[1].isdigit() else None
        files.append({"path": parts[2], "additions": additions,
                      "deletions": deletions})
    prev_tags = set(_git_out(clone_dir, "tag", "--merged",
                             prev_sha).splitlines())
    new_tags = set(_git_out(clone_dir, "tag", "--merged",
                            new_sha).splitlines())
    return {
        "commits": commits,
        "commits_truncated": len(commit_lines) > MAX_COMMITS_RECORDED,
        "files": files,
        "files_truncated": len(numstat_lines) > MAX_FILES_RECORDED,
        "tags": sorted(new_tags - prev_tags),
    }


DEFAULT_RUNTIME_MANIFEST = "runtime/src/lib.rs"
_SPEC_VERSION_RE = re.compile(r"spec_version\s*:\s*(\d+)")


def _spec_version_at(clone_dir: str, sha: str,
                     manifest_path: str) -> Optional[int]:
    """Runtime `spec_version` at *sha*, read from the tracked clone's
    runtime manifest via `git show`. Returns None (recorded as unknown)
    when the manifest or the field is absent — never guessed. The
    manifest path is config-driven because the monorepo moves trees."""
    code, out, _err = _git(clone_dir, "show", "%s:%s" % (sha, manifest_path))
    if code != 0:
        return None
    match = _SPEC_VERSION_RE.search(out)
    return int(match.group(1)) if match else None


def _machine_summary(range_data: Dict[str, Any], prev_sha: str,
                     new_sha: str, non_fast_forward: bool) -> str:
    top_dirs: Dict[str, int] = {}
    for item in range_data["files"]:
        top = item["path"].split("/", 1)[0]
        top_dirs[top] = top_dirs.get(top, 0) + 1
    top = ", ".join("%s (%d)" % pair for pair in sorted(
        top_dirs.items(), key=lambda pair: -pair[1])[:5])
    subjects = "; ".join(item["subject"] for item in
                         range_data["commits"][:5])
    parts = [
        SUMMARY_LABEL,
        "%d commit(s), %d file(s) changed, %s → %s."
        % (len(range_data["commits"]), len(range_data["files"]),
           prev_sha[:12], new_sha[:12]),
    ]
    if non_fast_forward:
        parts.append("NON-FAST-FORWARD: upstream history was rewritten; "
                     "the commit list may be incomplete.")
    if range_data["tags"]:
        parts.append("Tags encountered: %s."
                     % ", ".join(range_data["tags"][:10]))
    if top:
        parts.append("Top changed areas: %s." % top)
    if subjects:
        parts.append("Recent subjects: %s" % subjects)
    return _redact(" ".join(parts))


def update(config: Dict[str, Any], repo_root: str = _REPO_ROOT,
           actor: Optional[str] = None) -> int:
    identity = require_confirmed_identity(config)
    clone_dir = _resolve(repo_root, config["clone_dir"])
    db_path = _resolve(repo_root, config["db"])
    actor = actor or _account()
    if not os.path.isdir(os.path.join(clone_dir, ".git")):
        raise FatalRepoError("no clone at %s — run setup first" % clone_dir)

    run_id = _run_id()
    connection = open_store(db_path)
    status = "error"
    error: Optional[str] = None
    prev_sha = new_sha = None
    fast_forward: Optional[bool] = None
    try:
        connection.execute(
            "INSERT INTO update_runs (run_id, started_at, status) "
            "VALUES (?, ?, 'running')", (run_id, _utc_now()))
        connection.commit()

        # 1. remote identity must still match the pinned identity
        fetch_url = _git_out(clone_dir, "remote", "get-url", "origin")
        push_url = _git_out(clone_dir, "remote", "get-url", "--push",
                            "origin")
        branch = _git_out(clone_dir, "rev-parse", "--abbrev-ref", "HEAD")
        if fetch_url != identity["clone_url"]:
            status, error = "identity-mismatch", (
                "remote URL %r != pinned %r" % (fetch_url,
                                                identity["clone_url"]))
            return 1
        if push_url != PUSH_URL_DISABLED:
            status, error = "identity-mismatch", (
                "push URL %r is not disabled" % push_url)
            return 1
        if branch != identity["branch"]:
            status, error = "wrong-branch", (
                "checked-out branch %r != pinned %r"
                % (branch, identity["branch"]))
            return 1

        # 2. unexpected local modifications abort before any fetch
        dirty = working_tree_dirty(clone_dir)
        if dirty:
            status = "local-modifications"
            error = ("working tree has %d unexpected change(s), e.g. %s"
                     % (len(dirty), dirty[0].strip()))
            return 1

        prev_sha = local_sha(clone_dir)

        # 3. fetch (failure leaves local refs and tree untouched)
        meta_set(connection, META_LAST_FETCH_ATTEMPT, _utc_now())
        connection.commit()
        code, _, err = _git(clone_dir, "fetch", "origin",
                            identity["branch"], "--tags")
        if code != 0:
            status = "fetch-failed"
            error = err.strip()[:300] or "fetch failed (%d)" % code
            return 1
        meta_set(connection, META_LAST_FETCH_SUCCESS, _utc_now())
        new_sha = _git_out(clone_dir, "rev-parse",
                           "refs/remotes/origin/" + identity["branch"])
        meta_set(connection, META_LAST_REMOTE_SHA, new_sha)
        connection.commit()

        # 4. no change — record and stop
        if new_sha == prev_sha:
            status = "no-change"
            return 0

        # 5. advance: fast-forward when possible, deterministic reset
        #    otherwise; never a merge
        meta_set(connection, META_LAST_DETECTED_UPDATE, _utc_now())
        ancestor_code, _, _ = _git(clone_dir, "merge-base",
                                   "--is-ancestor", prev_sha, new_sha)
        fast_forward = ancestor_code == 0
        if fast_forward:
            _git_out(clone_dir, "merge", "--ff-only",
                     "refs/remotes/origin/" + identity["branch"])
        else:
            _git_out(clone_dir, "reset", "--hard",
                     "refs/remotes/origin/" + identity["branch"])

        # 6. change record, then incremental indexing
        range_data = _collect_range(clone_dir, prev_sha, new_sha)
        summary = _machine_summary(range_data, prev_sha, new_sha,
                                   not fast_forward)
        manifest = config.get("runtime_manifest", DEFAULT_RUNTIME_MANIFEST)
        prev_spec = _spec_version_at(clone_dir, prev_sha, manifest)
        new_spec = _spec_version_at(clone_dir, new_sha, manifest)
        cursor = connection.execute(
            "INSERT INTO change_ranges (run_id, prev_sha, new_sha, "
            "retrieved_at, non_fast_forward, commits_json, files_json, "
            "tags_json, index_status, index_detail, summary, "
            "prev_spec, new_spec) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', NULL, ?, ?, ?)",
            (run_id, prev_sha, new_sha, _utc_now(),
             0 if fast_forward else 1,
             json.dumps({"commits": range_data["commits"],
                         "truncated": range_data["commits_truncated"]}),
             json.dumps({"files": range_data["files"],
                         "truncated": range_data["files_truncated"]}),
             json.dumps(range_data["tags"]), summary,
             prev_spec, new_spec))
        change_id = cursor.lastrowid
        connection.commit()
        try:
            changed_paths = [item["path"] for item in range_data["files"]]
            if range_data["files_truncated"] or not fast_forward:
                # incomplete path list (or rewritten history): a partial
                # incremental pass could miss files — do a full pass
                outcome = run_index(connection, clone_dir, config["index"])
            else:
                outcome = run_index(connection, clone_dir, config["index"],
                                    changed_paths=changed_paths)
            index_status, index_detail = "ok", json.dumps(outcome)
        except (FatalRepoError, OSError, sqlite3.Error) as exc:
            connection.rollback()  # never commit a partial index pass
            index_status, index_detail = "failed", _redact(str(exc))[:300]
        connection.execute(
            "UPDATE change_ranges SET index_status = ?, index_detail = ? "
            "WHERE id = ?", (index_status, index_detail, change_id))
        status = "ok" if index_status == "ok" else "index-failed"
        return 0 if status == "ok" else 1
    finally:
        connection.execute(
            "UPDATE update_runs SET finished_at = ?, status = ?, "
            "error = ?, prev_sha = ?, new_sha = ?, fast_forward = ? "
            "WHERE run_id = ?",
            (_utc_now(), status, _redact(error) if error else None,
             prev_sha, new_sha,
             None if fast_forward is None else int(fast_forward), run_id))
        _audit(connection, actor, "update",
               "run %s status=%s prev=%s new=%s"
               % (run_id, status,
                  (prev_sha or "?")[:12], (new_sha or "?")[:12]))
        connection.commit()
        connection.close()
        print("update run %s: %s%s" % (run_id, status,
                                       " — " + error if error else ""))


# ---------------------------------------------------------------------------
# Freshness (ATLAS-REPO-007) — shared by the CLI and the MCP server
# ---------------------------------------------------------------------------


def freshness(db_path: str, clone_dir: str, config: Dict[str, Any],
              now: Optional[datetime.datetime] = None) -> Dict[str, Any]:
    now = now or datetime.datetime.now(tz=datetime.timezone.utc)
    if not os.path.exists(db_path):
        raise FatalRepoError("no repotrack store at %s" % db_path)
    if not os.path.isdir(os.path.join(clone_dir, ".git")):
        raise FatalRepoError("no clone at %s" % clone_dir)
    connection = sqlite3.connect(
        "file:%s?mode=ro" % db_path.replace("\\", "/"), uri=True)
    try:
        meta = dict(connection.execute(
            "SELECT key, value FROM meta").fetchall())
        last_run = connection.execute(
            "SELECT run_id, status, finished_at FROM update_runs "
            "ORDER BY started_at DESC LIMIT 1").fetchone()
    finally:
        connection.close()
    sha = local_sha(clone_dir)
    dirty = working_tree_dirty(clone_dir)
    indexed_sha = meta.get(META_INDEXED_SHA)
    last_success = meta.get(META_LAST_FETCH_SUCCESS)
    max_age_hours = (float(config["update_interval_hours"])
                     * float(config["stale_multiplier"]))
    if last_success is None:
        stale = True
    else:
        age = now - datetime.datetime.fromisoformat(last_success)
        stale = age.total_seconds() > max_age_hours * 3600
    return {
        "local_sha": sha,
        "remote_sha_last_fetch": meta.get(META_LAST_REMOTE_SHA),
        "last_fetch_attempt": meta.get(META_LAST_FETCH_ATTEMPT),
        "last_fetch_success": last_success,
        "last_detected_update": meta.get(META_LAST_DETECTED_UPDATE),
        "working_tree_clean": not dirty,
        "index_matches_local_sha": indexed_sha == sha,
        "indexed_sha": indexed_sha,
        "stale": stale,
        "stale_policy_hours": max_age_hours,
        "last_run": ({"run_id": last_run[0], "status": last_run[1],
                      "finished_at": last_run[2]} if last_run else None),
        "clone_size_bytes": clone_size_bytes(clone_dir),
        "generated_at": now.isoformat(),
    }


def status_command(config: Dict[str, Any],
                   repo_root: str = _REPO_ROOT) -> int:
    clone_dir = _resolve(repo_root, config["clone_dir"])
    db_path = _resolve(repo_root, config["db"])
    info = freshness(db_path, clone_dir, config)
    for key in ("local_sha", "remote_sha_last_fetch", "last_fetch_attempt",
                "last_fetch_success", "last_detected_update",
                "working_tree_clean", "index_matches_local_sha", "stale",
                "stale_policy_hours", "clone_size_bytes"):
        print("%s: %s" % (key, info[key]))
    if info["last_run"]:
        print("last_run: %s (%s)" % (info["last_run"]["run_id"],
                                     info["last_run"]["status"]))
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="atlas_repo",
        description="Atlas subtensor repository tracking: identity-gated "
                    "full clone, safe journaled updates, change records, "
                    "incremental index, freshness status.")
    parser.add_argument("--config", default=CONFIG_FILE)
    parser.add_argument("--repo-root", default=_REPO_ROOT,
                        help=argparse.SUPPRESS)
    subparsers = parser.add_subparsers(dest="subcommand", required=True)
    validate = subparsers.add_parser("validate-identity")
    validate.add_argument("--owner", default=None)
    validate.add_argument("--name", default=None)
    for name in ("setup", "update", "index"):
        sub = subparsers.add_parser(name)
        sub.add_argument("--actor", default=None)
    subparsers.add_parser("status")
    args = parser.parse_args(argv)

    try:
        config = load_config(args.config)
        if args.subcommand == "validate-identity":
            identity = config.get("identity") or {}
            owner = args.owner or identity.get("owner")
            name = args.name or identity.get("name")
            if not owner or not name:
                raise FatalRepoError("no owner/name given and none in "
                                     "config")
            output_dir = os.path.dirname(
                _resolve(args.repo_root, config["db"]))
            report = validate_identity(owner, name, output_dir)
            print(json.dumps({key: value for key, value in report.items()
                              if key != "note"}, indent=2, sort_keys=True))
            print(report["note"])
            return 0
        if args.subcommand == "setup":
            return setup(config, args.repo_root, args.actor)
        if args.subcommand == "update":
            return update(config, args.repo_root, args.actor)
        if args.subcommand == "index":
            return index_command(config, args.repo_root, args.actor)
        if args.subcommand == "status":
            return status_command(config, args.repo_root)
    except FatalRepoError as exc:
        print("FATAL: %s" % _redact(str(exc)), file=sys.stderr)
        return 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
