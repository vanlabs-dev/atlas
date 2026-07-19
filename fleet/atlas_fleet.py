#!/usr/bin/env python3
"""Atlas subnet-repo-fleet — chain-driven reconciliation of a local fleet
of subnet code repositories.

The chain (via the live-data subnet-identity operation) is the desired
state: for each netuid, the on-chain `github_repo`. The local registry +
clones under gitignored `var/fleet/` are the actual state. A reconcile
pass diffs desired against actual and clones what is new, updates what
exists, re-points what churned, and discards what deregistered — reusing
the repotrack update primitives underneath, never building or executing
subnet code.

This module currently carries the registry layer (URL normalization,
identity fingerprinting, the SQLite store) and the pure reconciler
plan builder. Clone/update orchestration, scheduling, and the CLI build
on top of these.

Envelope: unprivileged; writes only the clones, store, and reports under
gitignored `var/fleet/`; never invokes push/commit in a tracked repo and
never builds, tests, or runs subnet code.
"""

from __future__ import annotations

import argparse
import base64
import collections
import datetime
import hashlib
import json
import os
import re
import shutil
import sqlite3
import stat
import subprocess
import sys
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_MODULE_DIR)

FLEET_VERSION = "0.1.0"
GIT_TIMEOUT = 600
PUSH_URL_DISABLED = "DISABLED"


class FleetError(Exception):
    """Input-contract or environment failure in the fleet pipeline."""

# The on-chain `github_repo` field is free text set by the subnet owner.
# For the MVP the fleet accepts only github.com repositories: it matches
# the field's name and semantics and bounds the untrusted-clone surface.
ALLOWED_HOST = "github.com"

_BARE_REPO_RE = re.compile(r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$")
_SEGMENT_RE = re.compile(r"^[A-Za-z0-9._-]+$")


# ---------------------------------------------------------------------------
# Identity: URL normalization + fingerprint
# ---------------------------------------------------------------------------


def normalize_repo_url(raw: Optional[str]) -> Tuple[Optional[str], str]:
    """Canonicalize the free-text on-chain `github_repo` into a stable
    clone URL, or reject it.

    Returns `(canonical_url, "ok")` on success, else `(None, reason)` where
    reason is one of `empty`, `unsupported-host`, `unparsable`. The
    canonical form is `https://github.com/<owner>/<repo>` with host and
    path lower-cased (GitHub treats them case-insensitively, so lowering
    keeps the fingerprint stable), any `.git` suffix and trailing path
    (a `/tree/...` subdirectory link) stripped to the repository root.
    """
    if raw is None:
        return None, "empty"
    text = raw.strip()
    if not text:
        return None, "empty"
    if any(char.isspace() for char in text):
        return None, "unparsable"

    if "://" in text:
        parsed = urlparse(text)
        if parsed.scheme.lower() not in ("http", "https"):
            return None, "unparsable"
        host = (parsed.hostname or "").lower()
        if host.startswith("www."):
            host = host[4:]
        if host != ALLOWED_HOST:
            return None, "unsupported-host"
        segments = [seg for seg in parsed.path.split("/") if seg]
    elif text.startswith("git@") or text.startswith("ssh:"):
        return None, "unparsable"
    elif _BARE_REPO_RE.match(text):
        segments = text.split("/")
    else:
        return None, "unparsable"

    if len(segments) < 2:
        return None, "unparsable"
    owner, repo = segments[0], segments[1]
    if repo.endswith(".git"):
        repo = repo[:-4]
    if not repo or not _SEGMENT_RE.match(owner) or not _SEGMENT_RE.match(repo):
        return None, "unparsable"
    return "https://%s/%s/%s" % (ALLOWED_HOST, owner.lower(),
                                 repo.lower()), "ok"


def fingerprint(owner_ss58: Optional[str], canonical_url: Optional[str]) -> str:
    """Identity fingerprint for a slot: `hash(owner ‖ normalized repo)`.

    Deliberately takes only the owner and the repository URL — the subnet
    display name is never an input, so a rename alone cannot change the
    fingerprint (and therefore cannot trigger a re-point)."""
    basis = "%s\n%s" % ((owner_ss58 or "").strip(), canonical_url or "")
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Registry store
# ---------------------------------------------------------------------------

SLOT_COLUMNS = (
    "netuid", "github_repo", "owner_ss58", "fingerprint", "epoch",
    "default_branch", "status", "local_sha", "clone_size_bytes",
    "first_seen_block", "last_reconciled", "last_fetch_success",
    "clone_attempts", "next_attempt_at",
)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS slots (
    netuid INTEGER PRIMARY KEY,
    github_repo TEXT,
    owner_ss58 TEXT,
    fingerprint TEXT,
    epoch INTEGER,
    default_branch TEXT,
    status TEXT,
    local_sha TEXT,
    clone_size_bytes INTEGER,
    first_seen_block INTEGER,
    last_reconciled TEXT,
    last_fetch_success TEXT,
    clone_attempts INTEGER,
    next_attempt_at TEXT
);
CREATE TABLE IF NOT EXISTS epochs (
    id INTEGER PRIMARY KEY,
    netuid INTEGER NOT NULL,
    epoch INTEGER NOT NULL,
    fingerprint TEXT,
    github_repo TEXT,
    owner_ss58 TEXT,
    opened_at TEXT NOT NULL,
    opened_block INTEGER,
    closed_at TEXT,
    UNIQUE (netuid, epoch)
);
CREATE TABLE IF NOT EXISTS change_ranges (
    id INTEGER PRIMARY KEY,
    netuid INTEGER NOT NULL,
    epoch INTEGER NOT NULL,
    prev_sha TEXT NOT NULL,
    new_sha TEXT NOT NULL,
    retrieved_at TEXT NOT NULL,
    non_fast_forward INTEGER NOT NULL,
    commits_json TEXT NOT NULL,
    files_json TEXT NOT NULL,
    tags_json TEXT NOT NULL,
    summary TEXT
);
CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY,
    timestamp TEXT NOT NULL,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    netuid INTEGER,
    detail TEXT NOT NULL
);
"""


def open_store(db_path: str) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    connection = sqlite3.connect(db_path, timeout=10)
    # WAL + busy timeout (change: fleet-signals): the Telegram notifier
    # reads this store read-only from a DIFFERENT scheduled unit while a
    # reconcile may be writing — readers must never error or block the
    # writer. Write access stays exclusively with fleet-side processes.
    try:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=10000")
    except sqlite3.Error:
        pass  # a filesystem that rejects WAL still gets a working store
    connection.executescript(SCHEMA_SQL)
    # Additive migration: pre-backoff stores lack the retry-backoff columns;
    # existing rows stay NULL (= never failed, retry immediately).
    columns = {row[1] for row in connection.execute(
        "PRAGMA table_info(slots)")}
    for column, coltype in (("clone_attempts", "INTEGER"),
                            ("next_attempt_at", "TEXT")):
        if column not in columns:
            connection.execute(
                "ALTER TABLE slots ADD COLUMN %s %s" % (column, coltype))
    connection.commit()
    return connection


def upsert_slot(connection: sqlite3.Connection, row: Dict[str, Any]) -> None:
    """Insert or update a slot by netuid. Only the columns present in
    `row` are written; absent columns are left untouched on update."""
    if "netuid" not in row:
        raise ValueError("slot row requires a netuid")
    cols = [col for col in SLOT_COLUMNS if col in row]
    placeholders = ", ".join("?" for _ in cols)
    updates = ", ".join("%s = excluded.%s" % (col, col)
                        for col in cols if col != "netuid")
    sql = "INSERT INTO slots (%s) VALUES (%s)" % (", ".join(cols),
                                                  placeholders)
    sql += (" ON CONFLICT(netuid) DO UPDATE SET %s" % updates if updates
            else " ON CONFLICT(netuid) DO NOTHING")
    connection.execute(sql, tuple(row[col] for col in cols))


def _row_to_dict(row: Tuple[Any, ...]) -> Dict[str, Any]:
    return {SLOT_COLUMNS[index]: row[index]
            for index in range(len(SLOT_COLUMNS))}


def get_slot(connection: sqlite3.Connection,
             netuid: int) -> Optional[Dict[str, Any]]:
    row = connection.execute(
        "SELECT %s FROM slots WHERE netuid = ?" % ", ".join(SLOT_COLUMNS),
        (netuid,)).fetchone()
    return _row_to_dict(row) if row else None


def all_slots(connection: sqlite3.Connection) -> List[Dict[str, Any]]:
    rows = connection.execute(
        "SELECT %s FROM slots ORDER BY netuid" % ", ".join(SLOT_COLUMNS)
    ).fetchall()
    return [_row_to_dict(row) for row in rows]


# ---------------------------------------------------------------------------
# Reconciler — pure diff of desired (chain) vs actual (registry)
# ---------------------------------------------------------------------------

CLONE = "clone"       # a new slot, or a resume/retry of an in-flight one
UPDATE = "update"     # advance an active clone (git fetch)
REPOINT = "repoint"   # identity churned: discard old, clone new, new epoch
DISCARD = "discard"   # deregistered: absent from a trusted desired map
NO_REPO = "no-repo"   # tracked slot with no usable github_repo (not cloned)
SKIP = "skip"         # recorded terminal state (e.g. quarantined), no action
DEFERRED = "deferred"  # a clone/repoint held back by the per-pass bound


# Escalating retry backoff for repos that will not clone (placeholder URLs,
# private repos the public-read-only token cannot see, deleted/moved repos).
# A fix (new repo URL) changes the fingerprint and re-points immediately,
# bypassing this — so only persistently-dead repos are throttled.
DEFAULT_BACKOFF_HOURS = [6, 24, 72, 168]


def _next_attempt_at(now_iso: str, attempts: int,
                     schedule: Optional[List[int]] = None) -> str:
    schedule = schedule or DEFAULT_BACKOFF_HOURS
    hours = schedule[min(max(attempts, 1), len(schedule)) - 1]
    now = datetime.datetime.fromisoformat(now_iso)
    return (now + datetime.timedelta(hours=hours)).isoformat()


def _action(action: str, netuid: int, url: Optional[str] = None,
            fingerprint: Optional[str] = None,
            owner_ss58: Optional[str] = None,
            subnet_name: Optional[str] = None, reason: str = "") -> Dict[str, Any]:
    return {"action": action, "netuid": netuid, "url": url,
            "fingerprint": fingerprint, "owner_ss58": owner_ss58,
            "subnet_name": subnet_name, "reason": reason}


def _backed_off(slot: Dict[str, Any], now: Optional[str]) -> bool:
    """True when a persistently-unreachable slot is still inside its retry
    backoff window (so it is left untouched this pass, not re-attempted)."""
    next_at = slot.get("next_attempt_at")
    return bool(now and next_at and now < next_at)


def build_plan(desired: List[Dict[str, Any]], registry: List[Dict[str, Any]],
               fetch_ok: bool = True,
               now: Optional[str] = None) -> List[Dict[str, Any]]:
    """Diff the desired identity map against the registry into a per-slot
    plan. Exactly one action per slot from
    {clone, update, repoint, discard, no-repo, skip}.

    `fetch_ok` is the mass-discard guard: when False the desired map is
    untrusted for this pass, so no destructive or map-derived action is
    produced — only registry-derived work runs (advance active slots,
    resume in-flight clones). A degraded fetch therefore changes nothing
    destructive and never reads a partial map as deregistrations."""
    by_netuid = {slot["netuid"]: slot for slot in registry}

    if not fetch_ok:
        plan: List[Dict[str, Any]] = []
        for slot in registry:
            status = slot.get("status")
            if status == "active":
                plan.append(_action(
                    UPDATE, slot["netuid"], url=slot.get("github_repo"),
                    fingerprint=slot.get("fingerprint"),
                    reason="degraded-fetch-registry-update"))
            elif status in ("pending", "cloning"):
                plan.append(_action(
                    CLONE, slot["netuid"], url=slot.get("github_repo"),
                    fingerprint=slot.get("fingerprint"), reason="resume"))
        return plan

    plan = []
    seen = set()
    for entry in desired:
        netuid = entry["netuid"]
        seen.add(netuid)
        canonical, reason = normalize_repo_url(entry.get("github_repo"))
        if canonical is None:
            plan.append(_action(
                NO_REPO, netuid,
                reason=("no-github-repo" if reason == "empty" else reason)))
            continue
        fp = fingerprint(entry.get("owner_ss58"), canonical)
        common = dict(url=canonical, fingerprint=fp,
                      owner_ss58=entry.get("owner_ss58"),
                      subnet_name=entry.get("subnet_name"))
        existing = by_netuid.get(netuid)
        if (existing is None or not existing.get("fingerprint")
                or existing.get("status") in (None, NO_REPO)):
            plan.append(_action(CLONE, netuid, reason="new", **common))
        elif existing["fingerprint"] == fp:
            status = existing.get("status")
            if status == "unreachable" and _backed_off(existing, now):
                continue  # persistently dead repo — throttled until due
            if status in ("pending", "cloning", "unreachable", "disk-limited"):
                plan.append(_action(CLONE, netuid, reason="resume", **common))
            elif status == "quarantined":
                plan.append(_action(SKIP, netuid, reason="quarantined",
                                    **common))
            else:  # active (or any other recorded, cloned state) → advance
                plan.append(_action(UPDATE, netuid, reason="advance",
                                    **common))
        else:
            plan.append(_action(REPOINT, netuid, reason="identity-churn",
                                **common))

    for slot in registry:
        if slot["netuid"] not in seen:
            plan.append(_action(DISCARD, slot["netuid"],
                                reason="deregistered"))
    return plan


def apply_bound(plan: List[Dict[str, Any]],
                max_new: Optional[int]) -> List[Dict[str, Any]]:
    """Cap the number of clone/repoint (new-work) actions per pass. Excess
    ones become `deferred` (the executor leaves them pending, so the next
    pass resumes them); update/discard/no-repo are never bounded."""
    if max_new is None:
        return list(plan)
    result: List[Dict[str, Any]] = []
    started = 0
    for action in plan:
        if action["action"] in (CLONE, REPOINT):
            if started >= max_new:
                result.append({**action, "action": DEFERRED,
                               "reason": "bounded:%s" % action["action"]})
                continue
            started += 1
        result.append(action)
    return result


# ---------------------------------------------------------------------------
# Secret handling (GITHUB_TOKEN) — redaction; token passed by env, never argv
# ---------------------------------------------------------------------------

_SECRET_VALUES: List[str] = []


def register_secret(value: Optional[str]) -> None:
    if value and len(value) >= 8 and value not in _SECRET_VALUES:
        _SECRET_VALUES.append(value)


def redact(text: str) -> str:
    """Strip every registered secret from a string before it is printed,
    stored, or audited. The GITHUB_TOKEN and its derived auth header are
    registered whenever a token is used."""
    for value in _SECRET_VALUES:
        if value and value in text:
            text = text.replace(value, "[REDACTED]")
    return text


# ---------------------------------------------------------------------------
# repotrack reuse — the update primitives are already clone-path injectable,
# so the fleet drives them without touching the subtensor singleton.
# ---------------------------------------------------------------------------

_RT: Any = None


def _repotrack() -> Any:
    global _RT
    if _RT is None:
        sys.path.insert(0, os.path.join(_REPO_ROOT, "repotrack"))
        import atlas_repo  # noqa: E402
        _RT = atlas_repo
    return _RT


_FI: Any = None


def _fleet_index() -> Any:
    """Lazy import of the shared FTS indexer (change: fleet-search). Kept as a
    module reference so its functions stay monkeypatchable in tests."""
    global _FI
    if _FI is None:
        import atlas_fleet_index  # noqa: E402  (same dir, stdlib-pure import)
        _FI = atlas_fleet_index
    return _FI


_FS: Any = None


def _fleet_signals() -> Any:
    """Lazy import of the signals module (change: fleet-signals). Module
    reference so its functions stay monkeypatchable in tests."""
    global _FS
    if _FS is None:
        sys.path.insert(0, _MODULE_DIR)
        import atlas_fleet_signals  # noqa: E402
        _FS = atlas_fleet_signals
    return _FS


_FM: Any = None


def _fleet_metrics() -> Any:
    """Lazy import of the metrics module (change: fleet-rotation-metrics).
    Module reference so its functions stay monkeypatchable in tests."""
    global _FM
    if _FM is None:
        sys.path.insert(0, _MODULE_DIR)
        import atlas_fleet_metrics  # noqa: E402
        _FM = atlas_fleet_metrics
    return _FM


def _update_index_directive(result: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Map an `update_clone` result to the index work it implies, or None.

    Incremental (changed paths) ONLY on a clean fast-forward with a complete,
    non-truncated change range; a truncated range, a non-fast-forward reset, or
    a `record-failed` advance (clone moved but no range) fall back to a full
    walk (`changed_paths=None`). `no-change` and every failure index nothing —
    mirrors repotrack's update-path guard (atlas_repo.py incremental-vs-full)."""
    status = result.get("status")
    if status == "ok":
        rng = result.get("range") or {}
        if result.get("fast_forward") and not rng.get("files_truncated"):
            paths = [item["path"] for item in rng.get("files", [])]
            return {"changed_paths": paths, "local_sha": result.get("new_sha")}
        return {"changed_paths": None, "local_sha": result.get("new_sha")}
    if status == "record-failed":
        return {"changed_paths": None,
                "local_sha": result.get("local_sha") or result.get("new_sha")}
    return None


# ---------------------------------------------------------------------------
# Git runner — fixed-argument, no shell. An optional token is injected via
# GIT_CONFIG_* environment (http.extraHeader), so it reaches the network
# request but never lands in argv (ps-safe) or the clone's on-disk config.
# ---------------------------------------------------------------------------


def _auth_env(token: Optional[str]) -> Optional[Dict[str, str]]:
    if not token:
        return None
    header = "Authorization: Basic " + base64.b64encode(
        ("x-access-token:%s" % token).encode("utf-8")).decode("ascii")
    register_secret(token)
    register_secret(header)
    return {"GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "http.extraHeader",
            "GIT_CONFIG_VALUE_0": header}


def _run_git(cwd: Optional[str], args: List[str], token: Optional[str] = None,
             timeout: int = GIT_TIMEOUT) -> Tuple[int, str, str]:
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"  # never block waiting for credentials
    auth = _auth_env(token)
    if auth:
        env.update(auth)
    command = ["git"] + (["-C", cwd] if cwd else []) + list(args)
    try:
        proc = subprocess.run(command, capture_output=True, text=True,
                              timeout=timeout, encoding="utf-8",
                              errors="replace", env=env)
    except FileNotFoundError:
        raise FleetError("git executable not found")
    except subprocess.TimeoutExpired:
        return 124, "", "timeout after %ds" % timeout
    return proc.returncode, proc.stdout, proc.stderr


# ---------------------------------------------------------------------------
# Clone / update executor
# ---------------------------------------------------------------------------


def _is_git_clone(clone_dir: str) -> bool:
    return os.path.isdir(os.path.join(clone_dir, ".git"))


def _on_rm_error(func: Any, path: str, _exc: Any) -> None:
    """git marks pack files read-only; clear the bit and retry so a
    quarantine/discard fully removes the clone (notably on Windows)."""
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except OSError:
        pass


def _rmtree(path: str) -> None:
    if os.path.exists(path):
        shutil.rmtree(path, onerror=_on_rm_error)


def _default_branch(clone_dir: str) -> str:
    code, out, _ = _run_git(clone_dir, ["symbolic-ref", "--short", "HEAD"])
    if code == 0 and out.strip():
        return out.strip()
    _c, out, _ = _run_git(clone_dir, ["rev-parse", "--abbrev-ref", "HEAD"])
    return out.strip() or "main"


def _tracked_file_count(clone_dir: str) -> int:
    code, out, _ = _run_git(clone_dir, ["ls-tree", "-r", "--name-only", "HEAD"])
    if code != 0:
        return 0
    return len([line for line in out.splitlines() if line.strip()])


def _clone_state(clone_dir: str, status: str, branch: Optional[str] = None,
                 size: Optional[int] = None) -> Dict[str, Any]:
    return {
        "status": status,
        "default_branch": branch or _default_branch(clone_dir),
        "local_sha": _repotrack().local_sha(clone_dir),
        "clone_size_bytes": (size if size is not None
                             else _repotrack().clone_size_bytes(clone_dir)),
    }


def setup_clone(clone_dir: str, url: str, token: Optional[str] = None,
                caps: Optional[Dict[str, int]] = None) -> Dict[str, Any]:
    """Blobless, minimal-footprint clone of an untrusted subnet repo.

    `git clone --filter=blob:none --no-checkout --no-recurse-submodules`
    fetches the commit graph and trees but no historical blobs; the
    file-count cap is enforced on the tree BEFORE checkout so an oversized
    repo never materialises its blobs; the size cap is enforced after
    checkout. On any cap breach the clone is removed and the slot is
    quarantined. The push URL is disabled (we never push). The remote
    default branch is checked out and recorded — no third-party API call.
    Subnet code is never built, tested, or executed."""
    caps = caps or {}
    if _is_git_clone(clone_dir):
        return _clone_state(clone_dir, "active")  # idempotent / resume-noop
    if os.path.isdir(clone_dir) and os.listdir(clone_dir):
        _rmtree(clone_dir)  # stale partial dir from an interrupted pass
    os.makedirs(os.path.dirname(os.path.abspath(clone_dir)), exist_ok=True)

    code, _out, err = _run_git(None, [
        "clone", "--filter=blob:none", "--no-checkout",
        "--no-recurse-submodules", url, clone_dir], token=token)
    if code != 0:
        _rmtree(clone_dir)
        return {"status": "unreachable", "error": redact(err.strip()[:300])}

    max_files = caps.get("max_files")
    if max_files is not None and _tracked_file_count(clone_dir) > max_files:
        _rmtree(clone_dir)
        return {"status": "quarantined",
                "error": "tracked file count exceeds cap %d" % max_files}

    branch = _default_branch(clone_dir)
    code, _out, err = _run_git(clone_dir, ["checkout", branch], token=token)
    if code != 0:
        _rmtree(clone_dir)
        return {"status": "unreachable", "error": redact(err.strip()[:300])}

    size = _repotrack().clone_size_bytes(clone_dir)
    max_bytes = caps.get("max_bytes")
    if max_bytes is not None and size is not None and size > max_bytes:
        _rmtree(clone_dir)
        return {"status": "quarantined",
                "error": "clone size %d exceeds cap %d" % (size, max_bytes)}

    _run_git(clone_dir, ["remote", "set-url", "--push", "origin",
                         PUSH_URL_DISABLED])
    return _clone_state(clone_dir, "active", branch=branch, size=size)


def update_clone(clone_dir: str, branch: str, prev_sha: str,
                 token: Optional[str] = None) -> Dict[str, Any]:
    """Advance a fleet clone: clean-tree check -> fetch -> fast-forward or
    deterministic reset (never a merge) -> recorded change range (reusing
    repotrack's `collect_range` for the exact recorded shape). Any failure
    preserves the clone's last good state. The change range is returned for
    the reconcile driver to persist scoped to the slot's (netuid, epoch)."""
    if not _is_git_clone(clone_dir):
        return {"status": "missing"}
    dirty = _repotrack().working_tree_dirty(clone_dir)
    if dirty:
        return {"status": "local-modifications", "detail": dirty[0].strip()}

    code, _out, err = _run_git(clone_dir, ["fetch", "origin", branch, "--tags"],
                               token=token)
    if code != 0:
        return {"status": "fetch-failed", "error": redact(err.strip()[:300])}
    ref = "refs/remotes/origin/%s" % branch
    code, out, _err = _run_git(clone_dir, ["rev-parse", ref])
    if code != 0:
        return {"status": "fetch-failed",
                "error": "cannot resolve %s after fetch" % ref}
    new_sha = out.strip()
    if new_sha == prev_sha:
        return {"status": "no-change", "prev_sha": prev_sha,
                "new_sha": new_sha}

    ancestor_code, _o, _e = _run_git(
        clone_dir, ["merge-base", "--is-ancestor", prev_sha, new_sha])
    fast_forward = ancestor_code == 0
    advance = (["merge", "--ff-only", ref] if fast_forward
               else ["reset", "--hard", ref])
    code, _out, err = _run_git(clone_dir, advance)
    if code != 0:
        return {"status": "advance-failed", "error": redact(err.strip()[:300])}

    try:
        range_data = _repotrack().collect_range(clone_dir, prev_sha, new_sha)
    except _repotrack().FatalRepoError as exc:
        # The advance succeeded but the range could not be collected (e.g. a
        # blobless backfill failed, or prev is no longer reachable). The clone
        # is at the new head; report the record failure without losing that
        # fact, mirroring repotrack's advance-then-record ordering.
        return {"status": "record-failed", "prev_sha": prev_sha,
                "new_sha": new_sha, "fast_forward": fast_forward,
                "local_sha": _repotrack().local_sha(clone_dir),
                "error": redact(str(exc)[:300])}
    return {"status": "ok", "prev_sha": prev_sha, "new_sha": new_sha,
            "fast_forward": fast_forward, "range": range_data,
            "local_sha": _repotrack().local_sha(clone_dir),
            "clone_size_bytes": _repotrack().clone_size_bytes(clone_dir)}


# ---------------------------------------------------------------------------
# Reconcile driver — plan -> bound -> execute, persisting slot transitions,
# identity epochs, per-slot change ranges, and an audit trail.
# ---------------------------------------------------------------------------

DEFAULT_CLONE_ROOT = os.path.join(_REPO_ROOT, "var", "fleet")


def _utc_now() -> str:
    return datetime.datetime.now(tz=datetime.timezone.utc).isoformat()


def _identity_ok(result: Optional[Dict[str, Any]]) -> bool:
    """The mass-discard guard predicate: destructive/map-derived actions run
    only when the identity fetch succeeded, validated (status ok), is within
    its freshness envelope, and was paginated to completion."""
    if not result or result.get("status") != "ok":
        return False
    if result.get("freshness_status") == "aged-upstream":
        return False
    return (result.get("values") or {}).get("complete") is True


def _desired_from(result: Dict[str, Any]) -> List[Dict[str, Any]]:
    return ((result.get("values") or {}).get("subnets")) or []


def _norepo_status(reason: str) -> str:
    return "no-repo" if reason == "no-github-repo" else "invalid-url"


def audit(connection: sqlite3.Connection, actor: str, action: str,
          netuid: Optional[int], detail: str) -> None:
    connection.execute(
        "INSERT INTO audit (timestamp, actor, action, netuid, detail) "
        "VALUES (?, ?, ?, ?, ?)",
        (_utc_now(), actor, action, netuid, redact(detail)[:400]))


def _next_epoch(connection: sqlite3.Connection, netuid: int) -> int:
    row = connection.execute(
        "SELECT MAX(epoch) FROM epochs WHERE netuid = ?", (netuid,)).fetchone()
    return (row[0] or 0) + 1


def _open_epoch(connection: sqlite3.Connection, netuid: int, epoch: int,
                action: Dict[str, Any], block: Optional[int],
                now: str) -> None:
    connection.execute(
        "INSERT OR IGNORE INTO epochs (netuid, epoch, fingerprint, "
        "github_repo, owner_ss58, opened_at, opened_block) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (netuid, epoch, action.get("fingerprint"), action.get("url"),
         action.get("owner_ss58"), now, block))


def _close_epoch(connection: sqlite3.Connection, netuid: int, epoch: int,
                 now: str) -> None:
    connection.execute(
        "UPDATE epochs SET closed_at = ? WHERE netuid = ? AND epoch = ? "
        "AND closed_at IS NULL", (now, netuid, epoch))


def _record_range(connection: sqlite3.Connection, netuid: int, epoch: int,
                  result: Dict[str, Any], now: str) -> None:
    rng = result["range"]
    summary = "%d commit(s), %d file(s), %s -> %s" % (
        len(rng["commits"]), len(rng["files"]),
        result["prev_sha"][:12], result["new_sha"][:12])
    connection.execute(
        "INSERT INTO change_ranges (netuid, epoch, prev_sha, new_sha, "
        "retrieved_at, non_fast_forward, commits_json, files_json, "
        "tags_json, summary) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (netuid, epoch, result["prev_sha"], result["new_sha"], now,
         0 if result["fast_forward"] else 1,
         json.dumps({"commits": rng["commits"],
                     "truncated": rng["commits_truncated"]}),
         json.dumps({"files": rng["files"],
                     "truncated": rng["files_truncated"]}),
         json.dumps(rng["tags"]), summary))


def _persist_clone(connection: sqlite3.Connection, netuid: int, epoch: int,
                   action: Dict[str, Any], state: Dict[str, Any],
                   block: Optional[int], now: str) -> None:
    row = {"netuid": netuid, "github_repo": action.get("url"),
           "owner_ss58": action.get("owner_ss58"),
           "fingerprint": action.get("fingerprint"), "epoch": epoch,
           "status": state["status"], "last_reconciled": now}
    if state["status"] == "active":
        row.update({"default_branch": state["default_branch"],
                    "local_sha": state["local_sha"],
                    "clone_size_bytes": state["clone_size_bytes"],
                    "first_seen_block": block, "last_fetch_success": now})
    upsert_slot(connection, row)


def _persist_update(connection: sqlite3.Connection, netuid: int, epoch: int,
                    result: Dict[str, Any], now: str) -> None:
    status = result["status"]
    if status == "no-change":
        upsert_slot(connection, {"netuid": netuid, "last_reconciled": now,
                                 "last_fetch_success": now})
    elif status in ("ok", "record-failed"):
        upsert_slot(connection, {
            "netuid": netuid, "local_sha": result["new_sha"], "status":
            "active", "clone_size_bytes": result.get("clone_size_bytes"),
            "last_reconciled": now, "last_fetch_success": now})
        if status == "ok":
            _record_range(connection, netuid, epoch, result, now)
    else:
        # fetch-failed / advance-failed / local-modifications / missing:
        # preserve last good state, record only that we tried.
        upsert_slot(connection, {"netuid": netuid, "last_reconciled": now})


def _handle_deferred(connection: sqlite3.Connection, action: Dict[str, Any],
                     now: str) -> None:
    existing = get_slot(connection, action["netuid"])
    if existing and existing.get("status") == "active":
        return  # a deferred re-point: leave the old active clone until it runs
    upsert_slot(connection, {
        "netuid": action["netuid"], "github_repo": action.get("url"),
        "owner_ss58": action.get("owner_ss58"),
        "fingerprint": action.get("fingerprint"), "status": "pending",
        "last_reconciled": now})


_Pass = collections.namedtuple(
    "_Pass", "clone_root caps token block now actor setup update disk_check "
             "backoff index_cfg")


def _record_attempt(connection: sqlite3.Connection, netuid: int,
                    base_attempts: Optional[int], state: Dict[str, Any],
                    now: str, backoff: Optional[List[int]]) -> None:
    """Maintain the retry-backoff bookkeeping after a clone attempt: a
    success clears it; an unreachable result escalates the delay."""
    if state["status"] == "active":
        connection.execute("UPDATE slots SET clone_attempts = 0, "
                           "next_attempt_at = NULL WHERE netuid = ?", (netuid,))
    elif state["status"] == "unreachable":
        attempts = (base_attempts or 0) + 1
        connection.execute(
            "UPDATE slots SET clone_attempts = ?, next_attempt_at = ? "
            "WHERE netuid = ?",
            (attempts, _next_attempt_at(now, attempts, backoff), netuid))


def _default_disk_free(path: str) -> Optional[int]:
    try:
        return shutil.disk_usage(path).free
    except OSError:
        return None


def _close_epoch_all(connection: sqlite3.Connection, netuid: int,
                     now: str) -> None:
    connection.execute(
        "UPDATE epochs SET closed_at = ? WHERE netuid = ? AND closed_at "
        "IS NULL", (now, netuid))


def _bump(summary: Dict[str, int], key: str) -> None:
    summary[key] = summary.get(key, 0) + 1


def _apply_action(connection: sqlite3.Connection, action: Dict[str, Any],
                  ctx: "_Pass", summary: Dict[str, int]) -> None:
    kind = action["action"]
    netuid = action["netuid"]
    clone_dir = os.path.join(ctx.clone_root, str(netuid))

    def _walk(epoch: int, changed_paths: Optional[List[str]],
              local_sha: Optional[str]) -> Dict[str, Any]:
        return {"netuid": netuid, "epoch": epoch, "clone_dir": clone_dir,
                "changed_paths": changed_paths, "local_sha": local_sha}

    if kind == NO_REPO:
        upsert_slot(connection, {"netuid": netuid, "github_repo": None,
                                 "status": _norepo_status(action["reason"]),
                                 "last_reconciled": ctx.now})
        audit(connection, ctx.actor, "no-repo", netuid, action["reason"])
        summary["no-repo"] += 1
        return None
    elif kind == DISCARD:
        _rmtree(clone_dir)
        _close_epoch_all(connection, netuid, ctx.now)
        connection.execute("DELETE FROM slots WHERE netuid = ?", (netuid,))
        # purge in the SAME transaction as the slot delete — no window where a
        # search returns a hit for a discarded slot.
        _fleet_index().purge_slot(connection, netuid)
        audit(connection, ctx.actor, "discard", netuid,
              action.get("reason", ""))
        summary["discard"] += 1
        return None
    elif kind == SKIP:
        audit(connection, ctx.actor, "skip", netuid, action.get("reason", ""))
        summary["skip"] += 1
        return None
    elif kind == DEFERRED:
        _handle_deferred(connection, action, ctx.now)
        summary["deferred"] += 1
        return None
    elif kind == CLONE:
        if not ctx.disk_check():
            upsert_slot(connection, {
                "netuid": netuid, "github_repo": action.get("url"),
                "owner_ss58": action.get("owner_ss58"),
                "fingerprint": action.get("fingerprint"),
                "status": "disk-limited", "last_reconciled": ctx.now})
            audit(connection, ctx.actor, "disk-limited", netuid,
                  action.get("reason", ""))
            summary["disk-limited"] += 1
            return None
        existing = get_slot(connection, netuid)
        if existing and existing.get("epoch"):
            epoch = existing["epoch"]
        else:
            epoch = _next_epoch(connection, netuid)
            _open_epoch(connection, netuid, epoch, action, ctx.block, ctx.now)
        state = ctx.setup(clone_dir, action["url"], token=ctx.token,
                          caps=ctx.caps)
        _persist_clone(connection, netuid, epoch, action, state, ctx.block,
                       ctx.now)
        _record_attempt(connection, netuid,
                        existing.get("clone_attempts") if existing else 0,
                        state, ctx.now, ctx.backoff)
        audit(connection, ctx.actor, "clone", netuid,
              "%s -> %s" % (action["reason"], state["status"]))
        # a non-active clone (unreachable / quarantined) is a recorded
        # per-slot outcome, not a process error — bucket it by its status
        _bump(summary, "clone" if state["status"] == "active"
              else state["status"])
        return (_walk(epoch, None, state.get("local_sha"))
                if state["status"] == "active" else None)
    elif kind == REPOINT:
        if not ctx.disk_check():
            audit(connection, ctx.actor, "disk-limited", netuid,
                  "repoint deferred")
            summary["disk-limited"] += 1
            return None
        old = get_slot(connection, netuid)
        if old and old.get("epoch"):
            _close_epoch(connection, netuid, old["epoch"], ctx.now)
        _rmtree(clone_dir)
        # the old project's index rows are stale the moment we re-point —
        # purge them in this transaction before the new tree is indexed.
        _fleet_index().purge_slot(connection, netuid)
        epoch = _next_epoch(connection, netuid)
        _open_epoch(connection, netuid, epoch, action, ctx.block, ctx.now)
        state = ctx.setup(clone_dir, action["url"], token=ctx.token,
                          caps=ctx.caps)
        _persist_clone(connection, netuid, epoch, action, state, ctx.block,
                       ctx.now)
        _record_attempt(connection, netuid, 0, state, ctx.now, ctx.backoff)
        audit(connection, ctx.actor, "repoint", netuid,
              "epoch %s -> %d, %s" % (old.get("epoch") if old else "-",
                                      epoch, state["status"]))
        _bump(summary, "repoint" if state["status"] == "active"
              else state["status"])
        return (_walk(epoch, None, state.get("local_sha"))
                if state["status"] == "active" else None)
    elif kind == UPDATE:
        slot = get_slot(connection, netuid)
        if not slot or not slot.get("default_branch") or not slot.get(
                "local_sha"):
            return None  # not a cloned slot yet; a later pass will clone it
        result = ctx.update(clone_dir, slot["default_branch"],
                            slot["local_sha"], token=ctx.token)
        _persist_update(connection, netuid, slot["epoch"], result, ctx.now)
        audit(connection, ctx.actor, "update", netuid, result["status"])
        _bump(summary, "update" if result["status"] in (
            "ok", "no-change", "record-failed") else result["status"])
        spec = _update_index_directive(result)
        return (_walk(slot["epoch"], spec["changed_paths"], spec["local_sha"])
                if spec else None)
    return None


def reconcile(connection: sqlite3.Connection,
              identity_result: Dict[str, Any], config: Dict[str, Any],
              setup: Any = None, update: Any = None,
              token: Optional[str] = None, actor: str = "fleet",
              now: Optional[str] = None, disk_free: Any = None
              ) -> Dict[str, Any]:
    """One reconcile pass: build the desired-vs-actual plan (guarded by the
    identity-fetch health), bound the new-work, and execute — persisting
    every slot transition, identity epoch, change range, and audit line.

    `setup`/`update`/`disk_free` default to the real git executor and a real
    free-disk probe; they are injectable so the orchestration can be tested
    against fixture remotes and simulated disk pressure."""
    clone_root = config.get("clone_root") or DEFAULT_CLONE_ROOT
    min_free = config.get("min_free_bytes")
    probe = disk_free or (lambda: _default_disk_free(clone_root))

    def disk_check() -> bool:
        if min_free is None:
            return True
        free = probe()
        return free is None or free >= min_free

    now = now or _utc_now()
    ctx = _Pass(clone_root=clone_root, caps=config.get("caps"), token=token,
                block=None, now=now, actor=actor,
                setup=setup or setup_clone, update=update or update_clone,
                disk_check=disk_check,
                backoff=config.get("unreachable_backoff_hours"),
                index_cfg=config.get("index"))

    # The shared FTS index (change: fleet-search) lives in this same store;
    # ensure its tables exist before any purge/index runs this pass.
    _fleet_index().ensure_schema(connection)

    fetch_ok = _identity_ok(identity_result)
    desired = _desired_from(identity_result) if fetch_ok else []
    if fetch_ok:
        ctx = ctx._replace(block=identity_result.get("block_reference"))
    registry = all_slots(connection)
    plan = apply_bound(
        build_plan(desired, registry, fetch_ok=fetch_ok, now=now),
        config.get("max_new_clones_per_pass"))

    # Per-slot failure outcomes (unreachable / quarantined / fetch-failed …)
    # are bucketed dynamically by their status, never as process "errors" —
    # a scheduled pass that ran is healthy even if some repos are dead.
    summary = {"fetch_ok": fetch_ok, "planned": len(plan), "clone": 0,
               "update": 0, "repoint": 0, "discard": 0, "no-repo": 0,
               "deferred": 0, "skip": 0, "disk-limited": 0}
    for action in plan:
        directive = _apply_action(connection, action, ctx, summary)
        connection.commit()  # slot transition is durable before indexing
        if directive:
            _run_index_directive(connection, directive, ctx, summary)

    # Signals pass (change: fleet-signals) — inline after every range is
    # recorded, so the notifier's next scan can deliver this hour's
    # events. Fail-isolated: a signals failure is audited and never
    # counts as a reconcile process error.
    try:
        summary["signals"] = _fleet_signals().run_pass(connection, config,
                                                       now=now)
    except Exception as exc:  # noqa: BLE001 — extraction never fails the pass
        connection.rollback()
        audit(connection, actor, "signals-failed", None,
              redact(str(exc))[:300])
        connection.commit()
        summary["signals"] = {"error": redact(str(exc))[:120]}

    # Metrics pass (change: fleet-rotation-metrics) — inline after signals so
    # this hour's branch-tip snapshot, windowed activity, and sha-gated
    # emission scan are current for the report/dashboard. Records branch tips
    # for the pass (one cheap ls-remote per active slot; the modified
    # subnet-repo-fleet spec). Fail-isolated: a metrics failure is audited and
    # never counts as a reconcile process error.
    try:
        summary["metrics"] = _fleet_metrics().run_pass(connection, config,
                                                       now=now, token=token)
    except Exception as exc:  # noqa: BLE001 — metrics never fail the pass
        connection.rollback()
        audit(connection, actor, "metrics-failed", None,
              redact(str(exc))[:300])
        connection.commit()
        summary["metrics"] = {"error": redact(str(exc))[:120]}
    return summary


def _run_index_directive(connection: sqlite3.Connection,
                         directive: Dict[str, Any], ctx: "_Pass",
                         summary: Dict[str, int]) -> None:
    """Apply one slot's index walk in its own transaction. On any failure only
    the index is rolled back — the already-committed clone/update is preserved
    (per-slot fail-closed, mirroring repotrack's separate index transaction)."""
    netuid = directive["netuid"]
    try:
        _fleet_index().index_slot(
            connection, netuid, directive["epoch"], directive["clone_dir"],
            ctx.index_cfg, changed_paths=directive.get("changed_paths"),
            local_sha=directive.get("local_sha"))
        connection.commit()
        _bump(summary, "indexed")
    except Exception as exc:  # noqa: BLE001 — index failure must not fail the pass
        connection.rollback()
        audit(connection, ctx.actor, "index-failed", netuid,
              redact(str(exc))[:300])
        connection.commit()
        _bump(summary, "index-failed")


# ---------------------------------------------------------------------------
# Status, config, identity loading, and the CLI
# ---------------------------------------------------------------------------

CONFIG_FILE = os.path.join(_MODULE_DIR, "config.json")
ENV_FILE = os.path.join(_REPO_ROOT, ".env")


def fleet_status(connection: sqlite3.Connection) -> Dict[str, Any]:
    """Operator-facing registry summary: counts by status, total clone
    bytes, the last reconcile time, and the stalest active slot."""
    slots = all_slots(connection)
    by_status: Dict[str, int] = {}
    total_bytes = 0
    last_reconcile: Optional[str] = None
    stalest: Optional[Dict[str, Any]] = None
    for slot in slots:
        status = slot.get("status") or "unknown"
        by_status[status] = by_status.get(status, 0) + 1
        total_bytes += slot.get("clone_size_bytes") or 0
        reconciled = slot.get("last_reconciled")
        if reconciled and (last_reconcile is None
                           or reconciled > last_reconcile):
            last_reconcile = reconciled
        fetched = slot.get("last_fetch_success")
        if status == "active" and fetched and (
                stalest is None or fetched < stalest["last_fetch_success"]):
            stalest = {"netuid": slot["netuid"], "last_fetch_success": fetched}
    return {"total_slots": len(slots), "by_status": by_status,
            "total_clone_bytes": total_bytes, "last_reconcile": last_reconcile,
            "stalest": stalest}


def backfill_index(connection: sqlite3.Connection, config: Dict[str, Any],
                   netuid: Optional[int] = None, rebuild: bool = False,
                   actor: str = "fleet") -> Dict[str, Any]:
    """Standalone (re)index of already-cloned slots (change: fleet-search).

    Walks the active clones — or one netuid — and indexes those whose index is
    missing, stale (indexed SHA != local SHA), or on an old indexer schema;
    `rebuild` purges first and re-walks unconditionally. This backfills clones
    that predate the index (the deployed fleet) and repairs drift, without
    requiring a clone to change first. Per-slot fail-closed: one slot's index
    error is recorded and skipped, never aborting the run."""
    fidx = _fleet_index()
    fidx.ensure_schema(connection)
    clone_root = config.get("clone_root") or DEFAULT_CLONE_ROOT
    index_cfg = config.get("index")
    slots = ([get_slot(connection, netuid)] if netuid is not None
             else all_slots(connection))
    summary = {"considered": 0, "indexed": 0, "skipped": 0, "failed": 0}
    for slot in slots:
        if (not slot or slot.get("status") != "active"
                or not slot.get("local_sha")):
            continue
        nid = slot["netuid"]
        clone_dir = os.path.join(clone_root, str(nid))
        if not _is_git_clone(clone_dir):
            summary["skipped"] += 1
            continue
        summary["considered"] += 1
        try:
            if rebuild:
                fidx.purge_slot(connection, nid)
            outcome = fidx.index_slot(connection, nid, slot.get("epoch"),
                                      clone_dir, index_cfg,
                                      local_sha=slot.get("local_sha"))
            connection.commit()
            if outcome["mode"] != "noop":
                summary["indexed"] += 1
            audit(connection, actor, "index", nid, outcome["mode"])
            connection.commit()
        except Exception as exc:  # noqa: BLE001 — per-slot fail-closed
            connection.rollback()
            audit(connection, actor, "index-failed", nid,
                  redact(str(exc))[:300])
            connection.commit()
            summary["failed"] += 1
    return summary


def _resolve(path: str) -> str:
    return path if os.path.isabs(path) else os.path.join(_REPO_ROOT, path)


def load_config(path: str = CONFIG_FILE) -> Dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            config = json.load(handle)
    except (OSError, ValueError) as exc:
        raise FleetError("cannot load config %s: %s" % (path, exc))
    for key in ("db", "clone_root"):
        if key not in config:
            raise FleetError("config %s is missing %r" % (path, key))
    config["db"] = _resolve(config["db"])
    config["clone_root"] = _resolve(config["clone_root"])
    return config


def load_identity_file(path: str) -> Dict[str, Any]:
    """Read a manual/seed identity map from disk. Accepts a bare list of
    subnet entries (wrapped as a complete, fresh result) or a full
    live-result envelope."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError) as exc:
        raise FleetError("cannot load identity file %s: %s" % (path, exc))
    if isinstance(payload, list):
        return {"status": "ok", "freshness_status": "fresh",
                "block_reference": None,
                "values": {"subnets": payload, "count": len(payload),
                           "complete": True}}
    if isinstance(payload, dict) and "values" in payload:
        return payload
    if isinstance(payload, dict) and "subnets" in payload:
        return {"status": "ok", "freshness_status": "fresh",
                "block_reference": payload.get("block_reference"),
                "values": {"subnets": payload["subnets"],
                           "count": len(payload["subnets"]), "complete": True}}
    raise FleetError("identity file %s is not a subnet list or result "
                     "envelope" % path)


def load_env_token(env_path: str = ENV_FILE) -> Optional[str]:
    """GITHUB_TOKEN from the environment or the 0600 .env, registered for
    redaction. Absent is fine — the fleet clones anonymously."""
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not token and os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if line.startswith("GITHUB_TOKEN=") and "=" in line:
                    token = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break
    if token:
        register_secret(token)
        return token
    return None


def _fetch_identity(config: Dict[str, Any]) -> Dict[str, Any]:
    """Automatic identity source: page the live-data TaoStats subnet-identity
    operation to completion into the fleet-consumable netuid->identity map.
    A degraded fetch is returned as-is (complete=False) so the mass-discard
    guard treats it as untrusted; a hard live-data failure raises FleetError
    so the CLI fails closed."""
    sys.path.insert(0, os.path.join(_REPO_ROOT, "livedata"))
    try:
        import atlas_live as al  # noqa: E402
        live_config = al.load_config()
        env = al.load_env()
        connection = al.open_store(al.resolve(live_config["db"]))
        try:
            ledger = al.QuotaLedger(connection, live_config)
            return al.run_subnet_identity(connection, live_config, ledger, env)
        finally:
            connection.close()
    except FleetError:
        raise
    except Exception as exc:  # livedata FatalLiveError, import/config errors
        raise FleetError("subnet-identity fetch failed: %s" % redact(str(exc)))


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="atlas_fleet",
        description="Atlas subnet-repo-fleet: chain-driven reconciliation of "
                    "a local fleet of subnet code repositories.")
    parser.add_argument("--config", default=CONFIG_FILE)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("status")
    reconcile_parser = subparsers.add_parser("reconcile")
    reconcile_parser.add_argument("--identity-file", default=None)
    reconcile_parser.add_argument("--max-new", type=int, default=None)
    index_parser = subparsers.add_parser("index")
    index_parser.add_argument("--netuid", type=int, default=None)
    index_parser.add_argument("--rebuild", action="store_true")
    args = parser.parse_args(argv)

    try:
        config = load_config(args.config)
        if args.command == "status":
            connection = open_store(config["db"])
            try:
                summary = fleet_status(connection)
                summary["index"] = _fleet_index().index_freshness(connection)
                print(json.dumps(summary, indent=2, sort_keys=True))
            finally:
                connection.close()
            return 0
        if args.command == "reconcile":
            if args.max_new is not None:
                config["max_new_clones_per_pass"] = args.max_new
            identity = (load_identity_file(args.identity_file)
                        if args.identity_file else _fetch_identity(config))
            token = load_env_token()
            connection = open_store(config["db"])
            try:
                summary = reconcile(connection, identity, config, token=token)
                print(json.dumps(summary, indent=2, sort_keys=True))
            finally:
                connection.close()
            # The pass is healthy if it ran against a validated identity map,
            # regardless of individual dead/oversized repos (recorded per
            # slot). A degraded identity fetch exits 1 to surface it.
            return 0 if summary["fetch_ok"] else 1
        if args.command == "index":
            connection = open_store(config["db"])
            try:
                summary = backfill_index(connection, config,
                                         netuid=args.netuid,
                                         rebuild=args.rebuild)
                print(json.dumps(summary, indent=2, sort_keys=True))
            finally:
                connection.close()
            return 0
    except FleetError as exc:
        print("fatal: %s" % redact(str(exc)), file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    sys.exit(main())
