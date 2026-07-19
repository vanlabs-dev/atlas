#!/usr/bin/env python3
"""Atlas fleet-signals — narrative radar + econ-code alerts over the
subnet-repo fleet (change: fleet-signals).

Turns the fleet's recorded change ranges into a term ledger (dependency
names from structured manifests + model-id strings), gates new adoptions
through novelty/cluster/watchlist/econ-code detection, and queues tiered
events for the Telegram notifier. Every instant event snapshots the
affected subnet's alpha price in TAO (keyless TaoSwap subnets operation,
via the live-data layer) and accrues horizon outcomes against a
fleet-median baseline so the operator can measure whether alerts carried
signal.

Invariants inherited from the fleet: read-only over clones (targeted
`git diff` only — blobless clones fetch exactly the blobs a diff needs),
never builds or executes subnet code, per-range fail-closed (one bad
range is recorded and skipped, never a pass failure), additive tables in
the shared fleet store (the reconcile schema is untouched), and terms
are adversarial input — length-capped, count-capped, and rendered as
data only.

Public surface (consumed by the reconcile inline hook and the CLI):

- ensure_schema(conn)                      — create the signals tables
- run_pass(conn, config, …)                — seed epochs + extract + prices
- backfill(conn, config, …)                — silent historical manifest seed
- seed_modelids(conn, config, …)           — silent model-id prevalence seed
- calibrate(conn, config, grid…)           — replay ledger, report clusters
- effectiveness(conn, …)                   — per-class × horizon report
- signals_status(conn)                     — watermark/ledger/queue summary
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import sqlite3
import statistics
import sys
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_MODULE_DIR)

SIGNALS_VERSION = "0.1.0"

# Event classes / tiers (the notifier renders these; keep names stable).
CLASS_CLUSTER = "narrative-cluster"
CLASS_WATCHLIST = "watchlist"
CLASS_ECON = "econ-code"
CLASS_DIGEST = "signal-digest"
TIER_INSTANT = "instant"
TIER_DIGEST = "digest"

# Term kinds.
KIND_DEP = "dependency"
KIND_MODEL = "model-id"

# Entry/outcome states — labeled, never fabricated.
ST_PENDING = "pending"
ST_RECORDED = "recorded"
ST_LATE = "late"
ST_UNAVAILABLE = "unavailable"

# A fill later than this after its natural moment is labeled `late`.
LATE_GRACE_HOURS = 6

# Hard bound on diff lines processed per range (defense in depth beyond
# the file/commit caps — a single pathological blob cannot stall a pass).
MAX_ADDED_LINES_PER_RANGE = 50000
_DIFF_PATH_BATCH = 40

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS signal_terms (
    term TEXT NOT NULL,
    kind TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    first_netuid INTEGER,
    PRIMARY KEY (term, kind)
);
CREATE TABLE IF NOT EXISTS signal_adoptions (
    id INTEGER PRIMARY KEY,
    term TEXT NOT NULL,
    kind TEXT NOT NULL,
    netuid INTEGER NOT NULL,
    epoch INTEGER NOT NULL,
    adopted_at TEXT NOT NULL,
    commit_sha TEXT,
    source_file TEXT,
    seeded INTEGER NOT NULL DEFAULT 0,
    UNIQUE (term, kind, netuid, epoch)
);
CREATE INDEX IF NOT EXISTS signal_adoptions_term
    ON signal_adoptions (term, kind, adopted_at);
CREATE TABLE IF NOT EXISTS signal_events (
    id INTEGER PRIMARY KEY,
    class TEXT NOT NULL,
    tier TEXT NOT NULL,
    netuid INTEGER,
    term TEXT,
    dedup_key TEXT NOT NULL UNIQUE,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS signal_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS signal_range_log (
    range_id INTEGER PRIMARY KEY,
    netuid INTEGER NOT NULL,
    epoch INTEGER NOT NULL,
    outcome TEXT NOT NULL,
    detail TEXT,
    processed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS signal_epoch_seeds (
    netuid INTEGER NOT NULL,
    epoch INTEGER NOT NULL,
    seeded_at TEXT NOT NULL,
    outcome TEXT NOT NULL,
    PRIMARY KEY (netuid, epoch)
);
CREATE TABLE IF NOT EXISTS signal_prices (
    ts TEXT NOT NULL,
    netuid INTEGER NOT NULL,
    price_tao REAL,
    PRIMARY KEY (ts, netuid)
);
CREATE TABLE IF NOT EXISTS signal_entries (
    event_id INTEGER NOT NULL,
    netuid INTEGER NOT NULL,
    price_tao REAL,
    as_of TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    PRIMARY KEY (event_id, netuid)
);
CREATE TABLE IF NOT EXISTS signal_outcomes (
    id INTEGER PRIMARY KEY,
    event_id INTEGER NOT NULL,
    netuid INTEGER NOT NULL,
    horizon_days INTEGER NOT NULL,
    due_at TEXT NOT NULL,
    exit_price_tao REAL,
    return_pct REAL,
    baseline_return_pct REAL,
    status TEXT NOT NULL DEFAULT 'pending',
    filled_at TEXT,
    UNIQUE (event_id, netuid, horizon_days)
);
"""

# ---------------------------------------------------------------------------
# Config — code defaults merged under fleet/config.json's `signals` block.
# ---------------------------------------------------------------------------

DEFAULT_SIGNALS_CFG: Dict[str, Any] = {
    "enabled": True,
    # Scan surface v1: structured manifests only; lockfiles are excluded
    # (transitive noise), vendored/test paths are excluded everywhere.
    "manifest_names": ["pyproject.toml", "package.json", "Cargo.toml",
                       "setup.py", "setup.cfg"],
    "manifest_name_regexes": [r"^requirements[^/]*\.txt$"],
    "lockfile_names": ["package-lock.json", "yarn.lock", "pnpm-lock.yaml",
                       "poetry.lock", "Cargo.lock", "uv.lock"],
    "exclude_path_parts": ["vendor", "node_modules", "test", "tests",
                           "docs", "examples", ".github"],
    # Model-id strings over added lines of these text files.
    "model_ids": True,
    "model_id_extensions": [".py", ".json", ".yaml", ".yml", ".toml"],
    "model_id_extra_files": [".env.example"],
    "model_id_patterns": [
        r"\bgpt-[0-9o][a-z0-9.\-]*",
        r"\bclaude-[a-z0-9][a-z0-9.\-]*",
        r"\bllama-?[0-9][a-z0-9.\-]*",
        r"\bdeepseek(?:-[a-z0-9.]+)+",
        r"\bqwen[0-9][a-z0-9.\-]*",
        r"\bmistral-[a-z0-9][a-z0-9.\-]*",
        r"\bmixtral[a-z0-9.\-]+",
        r"\bgemini-[0-9][a-z0-9.\-]*",
        r"\bgrok-[0-9][a-z0-9.\-]*",
        r"\bphi-[0-9][a-z0-9.\-]*",
        r"\b[A-Za-z0-9_.\-]{2,39}/[A-Za-z0-9_.\-]+-"
        r"(?:[0-9]+[bB]\b|[Ii]nstruct|[Cc]hat|[Bb]ase\b)[A-Za-z0-9_.\-]*",
    ],
    # Adversarial-input bounds.
    "term_max_length": 120,
    "max_terms_per_range": 200,
    # Giant-range caps: over these, manifests-only (model-id pass skipped).
    "range_caps": {"max_files": 200, "max_commits": 100},
    # Detection thresholds (strawmen — reset from `calibrate` evidence).
    "novelty_max_adopters": 10,
    "cluster": {"k": 3, "window_days": 14},
    # Watchlist: plain substrings-of-term or `re:` patterns, matched
    # against normalized extracted terms only. Operator edits in config.
    "watchlist": ["re:^vllm", "re:^sglang", "re:^verl$", "re:^trl$",
                  "re:^lmdeploy", "re:^tensorrt", "chutes", "targon"],
    # Econ-code path vocabulary (substring match on lowercased paths).
    "econ_paths": ["reward", "incentive", "scoring", "emission",
                   "set_weights", "mechanism"],
    "econ_cooldown_hours": 24,
    # Effectiveness measurement.
    "outcome_horizons_days": [1, 7, 30],
    "price_retention_days": 120,
    "backfill_max_commits": 500,
}


def signals_cfg(config: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(DEFAULT_SIGNALS_CFG)
    for key, value in (config.get("signals") or {}).items():
        if key == "_comment":
            continue
        merged[key] = value
    return merged


def _utc_now() -> str:
    return datetime.datetime.now(tz=datetime.timezone.utc).isoformat()


def _parse_iso(text: str) -> datetime.datetime:
    parsed = datetime.datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.timezone.utc)
    return parsed


def ensure_schema(connection: sqlite3.Connection) -> None:
    """Create the signals tables if absent. Owns only its own tables —
    the reconcile store's schema is never touched (fleet-search pattern)."""
    connection.executescript(SCHEMA_SQL)


def state_get(connection: sqlite3.Connection, key: str) -> Optional[str]:
    row = connection.execute(
        "SELECT value FROM signal_state WHERE key = ?", (key,)).fetchone()
    return row[0] if row else None


def state_set(connection: sqlite3.Connection, key: str, value: str) -> None:
    connection.execute(
        "INSERT INTO signal_state (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))


_FLEET: Any = None


def _fleet() -> Any:
    """Lazy import of atlas_fleet for its git runner / store helpers."""
    global _FLEET
    if _FLEET is None:
        sys.path.insert(0, _MODULE_DIR)
        import atlas_fleet  # noqa: E402
        _FLEET = atlas_fleet
    return _FLEET


# ---------------------------------------------------------------------------
# Scan surface — pure path predicates (unit-testable, no git)
# ---------------------------------------------------------------------------


def _path_excluded(path: str, cfg: Dict[str, Any]) -> bool:
    parts = {part.lower() for part in path.split("/")[:-1]}
    return bool(parts & {p.lower() for p in cfg["exclude_path_parts"]})


def is_manifest(path: str, cfg: Dict[str, Any]) -> bool:
    if _path_excluded(path, cfg):
        return False
    name = path.rsplit("/", 1)[-1]
    if name in cfg["lockfile_names"]:
        return False
    if name in cfg["manifest_names"]:
        return True
    return any(re.match(pattern, name)
               for pattern in cfg["manifest_name_regexes"])


def is_model_id_file(path: str, cfg: Dict[str, Any]) -> bool:
    if _path_excluded(path, cfg):
        return False
    name = path.rsplit("/", 1)[-1]
    if name in cfg["lockfile_names"]:
        return False
    if name in cfg["model_id_extra_files"]:
        return True
    return any(name.endswith(ext) for ext in cfg["model_id_extensions"])


def is_econ_path(path: str, cfg: Dict[str, Any]) -> bool:
    if _path_excluded(path, cfg):
        return False
    lowered = path.lower()
    return any(token in lowered for token in cfg["econ_paths"])


# ---------------------------------------------------------------------------
# Term extraction — line-based, parse-what-parses heuristics
# ---------------------------------------------------------------------------

_DEP_NAME_RE = re.compile(r"^[A-Za-z0-9@][A-Za-z0-9._/-]*")
_REQ_LINE_RE = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*(\[[^\]]*\])?"
                          r"\s*(?:[<>=!~;#].*)?$")
# Quoted requirement strings need a VERSION OPERATOR terminator — a bare
# quoted word ("myproj", "README.md") is any string, not evidence of a
# dependency (precision over recall; poetry/cargo styles are covered by
# the key = version rule). The spec must sit at the START of the quoted
# string: a PEP 508 environment marker after ';' ("numpy>=1.0;
# python_version >= '3.8'") is a condition, not a dependency.
_QUOTED_STRING_RE = re.compile(r"['\"]([^'\"]+)['\"]")
_QUOTED_REQ_SPEC_RE = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)"
                                 r"(?:\[[^\]]*\])?\s*[<>=!~;]")
_TOML_KEY_VER_RE = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*=\s*"
                              r"(?:\"[~^<>=]{0,2}\d|\{)")
_PKGJSON_DEP_RE = re.compile(r"\"(@?[A-Za-z0-9][A-Za-z0-9._/-]*)\"\s*:\s*"
                             r"\"[~^<>=]{0,2}\d")
_VERSION_SHAPED_RE = re.compile(r"^\d+(\.\d+)*$")

# TOML keys that look like `name = "1.0"` but are metadata, not deps.
_TOML_NOISE_KEYS = frozenset((
    "version", "python", "python-requires", "requires-python", "edition",
    "rust-version", "name", "description", "readme", "license", "channel"))

# PEP 508 environment-marker names — conditions, never dependencies.
# Rejected at normalization so no parser path (quoted specs, poetry
# `markers = "python_version >= '3.8'"` values, TOML keys) can ledger one.
_MARKER_NAMES = frozenset((
    "python_version", "python_full_version", "sys_platform", "sys.platform",
    "platform_machine", "platform_system", "platform_release",
    "platform_version", "platform_python_implementation",
    "implementation_name", "implementation_version", "os_name", "os.name",
    "extra"))


def normalize_dep(raw: str, max_length: int) -> Optional[str]:
    """Canonical dependency term or None. Lowercased, extras/version
    specifiers stripped, URL/path-shaped and trivial strings rejected."""
    text = (raw or "").strip().strip("'\"").lower()
    if not text or "://" in text or text.startswith((".", "/", "-")):
        return None
    match = _DEP_NAME_RE.match(text)
    if not match:
        return None
    term = match.group(0).rstrip(".")
    if (len(term) < 2 or len(term) > max_length
            or _VERSION_SHAPED_RE.match(term) or term in _MARKER_NAMES):
        return None
    return term


def _dep_terms_requirements(lines: Sequence[str]) -> List[str]:
    terms = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", "-", "git+", "http")):
            continue
        match = _REQ_LINE_RE.match(stripped)
        if match:
            terms.append(match.group(1))
    return terms


def _quoted_req_terms(line: str) -> List[str]:
    """Requirement names from quoted strings, spec anchored at the start
    of each string so environment markers can never match."""
    terms = []
    for quoted in _QUOTED_STRING_RE.finditer(line):
        spec = _QUOTED_REQ_SPEC_RE.match(quoted.group(1))
        if spec:
            terms.append(spec.group(1))
    return terms


def _dep_terms_pyproject(lines: Sequence[str]) -> List[str]:
    terms = []
    for line in lines:
        terms.extend(_quoted_req_terms(line))
        toml = _TOML_KEY_VER_RE.match(line)
        if toml and toml.group(1).lower() not in _TOML_NOISE_KEYS:
            terms.append(toml.group(1))
    return terms


def _dep_terms_package_json(lines: Sequence[str]) -> List[str]:
    return [match.group(1) for line in lines
            for match in _PKGJSON_DEP_RE.finditer(line)]


def _dep_terms_cargo(lines: Sequence[str]) -> List[str]:
    terms = []
    for line in lines:
        toml = _TOML_KEY_VER_RE.match(line)
        if toml and toml.group(1).lower() not in _TOML_NOISE_KEYS:
            terms.append(toml.group(1))
    return terms


def _dep_terms_setup(lines: Sequence[str]) -> List[str]:
    return [term for line in lines for term in _quoted_req_terms(line)]


def dep_terms_for(path: str, lines: Sequence[str],
                  cfg: Dict[str, Any]) -> List[str]:
    """Dependency terms from a manifest file's added lines, normalized.
    A line no parser understands is skipped — parse-what-parses."""
    name = path.rsplit("/", 1)[-1]
    if name == "pyproject.toml":
        raw = _dep_terms_pyproject(lines)
    elif name == "package.json":
        raw = _dep_terms_package_json(lines)
    elif name == "Cargo.toml":
        raw = _dep_terms_cargo(lines)
    elif name in ("setup.py", "setup.cfg"):
        raw = _dep_terms_setup(lines)
    else:  # requirements*.txt
        raw = _dep_terms_requirements(lines)
    seen: List[str] = []
    for item in raw:
        term = normalize_dep(item, cfg["term_max_length"])
        if term and term not in seen:
            seen.append(term)
    return seen


def _model_regexes(cfg: Dict[str, Any]) -> List[Any]:
    compiled = []
    for pattern in cfg["model_id_patterns"]:
        try:
            compiled.append(re.compile(pattern, re.IGNORECASE))
        except re.error:
            continue  # a broken configured pattern is skipped, never fatal
    return compiled


def model_terms_for(lines: Sequence[str], regexes: Sequence[Any],
                    max_length: int) -> List[str]:
    """Model-id terms from added lines, lowercased and de-duplicated."""
    seen: List[str] = []
    for line in lines:
        for regex in regexes:
            for match in regex.finditer(line):
                term = match.group(0).strip().lower().rstrip(".-")
                if 2 < len(term) <= max_length and term not in seen:
                    seen.append(term)
    return seen


# ---------------------------------------------------------------------------
# Watchlist — validated at load; a bad regex is skipped and surfaced
# ---------------------------------------------------------------------------


def compile_watchlist(cfg: Dict[str, Any]) -> Tuple[List[Any], List[str]]:
    """(matchers, invalid_entries). A matcher is (kind, needle_or_regex)."""
    matchers: List[Any] = []
    invalid: List[str] = []
    for entry in cfg["watchlist"]:
        if not isinstance(entry, str) or not entry.strip():
            invalid.append(repr(entry))
            continue
        if entry.startswith("re:"):
            try:
                matchers.append(("re", re.compile(entry[3:], re.IGNORECASE)))
            except re.error:
                invalid.append(entry)
        else:
            matchers.append(("plain", entry.lower()))
    return matchers, invalid


def watchlist_hit(term: str, matchers: Sequence[Any]) -> bool:
    for kind, needle in matchers:
        if kind == "plain" and needle in term:
            return True
        if kind == "re" and needle.search(term):
            return True
    return False


# ---------------------------------------------------------------------------
# Ledger + event queue
# ---------------------------------------------------------------------------


def record_adoption(connection: sqlite3.Connection, term: str, kind: str,
                    netuid: int, epoch: int, adopted_at: str,
                    commit_sha: Optional[str], source_file: Optional[str],
                    seeded: bool = False,
                    replace_seeded: bool = False) -> bool:
    """Record a first adoption of (term, kind) by (netuid, epoch).
    Returns True when a NEW adoption row was created. `replace_seeded`
    lets the historical backfill upgrade a silent seed row with its real
    date (never the other way around)."""
    existing = connection.execute(
        "SELECT id, seeded FROM signal_adoptions WHERE term = ? AND kind = ? "
        "AND netuid = ? AND epoch = ?", (term, kind, netuid, epoch)).fetchone()
    if existing is not None:
        if replace_seeded and existing[1]:
            connection.execute(
                "UPDATE signal_adoptions SET adopted_at = ?, commit_sha = ?, "
                "source_file = ?, seeded = 0 WHERE id = ?",
                (adopted_at, commit_sha, source_file, existing[0]))
        return False
    connection.execute(
        "INSERT INTO signal_adoptions (term, kind, netuid, epoch, adopted_at, "
        "commit_sha, source_file, seeded) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (term, kind, netuid, epoch, adopted_at, commit_sha, source_file,
         1 if seeded else 0))
    connection.execute(
        "INSERT OR IGNORE INTO signal_terms (term, kind, first_seen_at, "
        "first_netuid) VALUES (?, ?, ?, ?)", (term, kind, adopted_at, netuid))
    return True


def queue_event(connection: sqlite3.Connection, event_class: str, tier: str,
                netuid: Optional[int], term: Optional[str], dedup_key: str,
                payload: Dict[str, Any], created_at: str) -> Optional[int]:
    """Append an event once per dedup key. Returns the row id, or None
    when the key already exists (an episode never re-fires)."""
    cursor = connection.execute(
        "INSERT OR IGNORE INTO signal_events (class, tier, netuid, term, "
        "dedup_key, payload_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (event_class, tier, netuid, term, dedup_key,
         json.dumps(payload, sort_keys=True), created_at))
    return cursor.lastrowid if cursor.rowcount else None


def queue_digest_line(connection: sqlite3.Connection, dedup_key: str,
                      line: str, created_at: str,
                      netuid: Optional[int] = None,
                      term: Optional[str] = None) -> Optional[int]:
    return queue_event(connection, CLASS_DIGEST, TIER_DIGEST, netuid, term,
                       dedup_key, {"line": line}, created_at)


def _adopter_count(connection: sqlite3.Connection, term: str,
                   kind: str) -> int:
    return connection.execute(
        "SELECT COUNT(DISTINCT netuid) FROM signal_adoptions "
        "WHERE term = ? AND kind = ?", (term, kind)).fetchone()[0]


def _active_slot_count(connection: sqlite3.Connection) -> int:
    try:
        return connection.execute(
            "SELECT COUNT(*) FROM slots WHERE status = 'active'").fetchone()[0]
    except sqlite3.Error:
        return 0  # standalone store without the reconcile schema (tests)


def _window_adoptions(connection: sqlite3.Connection, term: str, kind: str,
                      now: str, window_days: int) -> List[Tuple[int, str, str]]:
    """Distinct netuids whose (non-seeded) first adoption of the term falls
    inside the trailing window, oldest first: [(netuid, adopted_at, sha)]."""
    cutoff = (_parse_iso(now)
              - datetime.timedelta(days=window_days)).isoformat()
    rows = connection.execute(
        "SELECT netuid, MIN(adopted_at), commit_sha FROM signal_adoptions "
        "WHERE term = ? AND kind = ? AND seeded = 0 GROUP BY netuid",
        (term, kind)).fetchall()
    inside = [(netuid, at, sha) for netuid, at, sha in rows if at >= cutoff]
    return sorted(inside, key=lambda row: row[1])


def _first_mover(connection: sqlite3.Connection, term: str,
                 kind: str) -> Optional[Tuple[int, str, str]]:
    row = connection.execute(
        "SELECT netuid, adopted_at, commit_sha FROM signal_adoptions "
        "WHERE term = ? AND kind = ? AND seeded = 0 "
        "ORDER BY adopted_at ASC LIMIT 1", (term, kind)).fetchone()
    return tuple(row) if row else None


def evaluate_adoption(connection: sqlite3.Connection, cfg: Dict[str, Any],
                      matchers: Sequence[Any], term: str, kind: str,
                      netuid: int, epoch: int, adopted_at: str,
                      commit_sha: Optional[str], source_file: Optional[str],
                      now: str) -> Dict[str, int]:
    """Detection for one NEW adoption: watchlist, then novelty-gated
    clustering. Returns per-class emit counts (for the pass summary)."""
    emitted = {"watchlist": 0, "cluster": 0, "digest": 0}

    if watchlist_hit(term, matchers):
        row_id = queue_event(
            connection, CLASS_WATCHLIST, TIER_INSTANT, netuid, term,
            "watchlist:%s:%s:%d:%d" % (kind, term, netuid, epoch),
            {"term": term, "kind": kind, "netuid": netuid, "epoch": epoch,
             "commit_sha": commit_sha, "source_file": source_file},
            now)
        if row_id:
            emitted["watchlist"] += 1

    adopters = _adopter_count(connection, term, kind)
    if adopters > cfg["novelty_max_adopters"]:
        return emitted  # common term: recorded, never clustered

    cluster_key = "cluster:%s:%s" % (kind, term)
    cluster_exists = connection.execute(
        "SELECT id FROM signal_events WHERE dedup_key = ?",
        (cluster_key,)).fetchone()
    if cluster_exists:
        if queue_digest_line(
                connection,
                "cluster-follow:%s:%s:%d:%d" % (kind, term, netuid, epoch),
                "SN%d joined existing cluster · %s" % (netuid, term),
                now, netuid=netuid, term=term):
            emitted["digest"] += 1
        return emitted

    window = _window_adoptions(connection, term, kind, now,
                               cfg["cluster"]["window_days"])
    if len(window) >= cfg["cluster"]["k"]:
        first = _first_mover(connection, term, kind)
        payload = {
            "term": term, "kind": kind,
            "members": [{"netuid": n, "adopted_at": at, "commit_sha": sha}
                        for n, at, sha in window],
            "first_mover": ({"netuid": first[0], "adopted_at": first[1],
                             "commit_sha": first[2]} if first else None),
            "window_days": cfg["cluster"]["window_days"],
            "prevalence": {"adopters": adopters,
                           "active_slots": _active_slot_count(connection)},
        }
        if queue_event(connection, CLASS_CLUSTER, TIER_INSTANT, None, term,
                       cluster_key, payload, now):
            emitted["cluster"] += 1
    return emitted


# ---------------------------------------------------------------------------
# Diff plumbing — targeted added-line extraction from a blobless clone
# ---------------------------------------------------------------------------

_DIFF_TARGET_RE = re.compile(r"^\+\+\+ b/(.*)$")


def _parse_added_lines(diff_text: str,
                       max_lines: int) -> Tuple[Dict[str, List[str]], bool]:
    """Map path -> added lines from unified diff output. Returns
    (mapping, truncated) — truncated when the processing cap was hit."""
    added: Dict[str, List[str]] = {}
    current: Optional[str] = None
    processed = 0
    for line in diff_text.splitlines():
        target = _DIFF_TARGET_RE.match(line)
        if target:
            current = target.group(1)
            continue
        if line.startswith("+++"):
            current = None  # /dev/null or unparsable target
            continue
        if current is not None and line.startswith("+"):
            processed += 1
            if processed > max_lines:
                return added, True
            added.setdefault(current, []).append(line[1:])
    return added, False


def _diff_added_lines(clone_dir: str, prev_sha: str, new_sha: str,
                      paths: Sequence[str],
                      git: Optional[Callable[..., Tuple[int, str, str]]] = None
                      ) -> Dict[str, List[str]]:
    """Added lines for the given paths, batched to bound argv size.
    Raises RuntimeError on a git failure (caller records extract-failed)."""
    git = git or _fleet()._run_git
    merged: Dict[str, List[str]] = {}
    budget = MAX_ADDED_LINES_PER_RANGE
    for start in range(0, len(paths), _DIFF_PATH_BATCH):
        batch = list(paths[start:start + _DIFF_PATH_BATCH])
        code, out, err = git(clone_dir, ["diff", "--no-renames", "--unified=0",
                                         prev_sha, new_sha, "--"] + batch)
        if code != 0:
            raise RuntimeError("git diff failed: %s" % err.strip()[:200])
        mapping, truncated = _parse_added_lines(out, budget)
        for path, lines in mapping.items():
            merged.setdefault(path, []).extend(lines)
            budget -= len(lines)
        if truncated or budget <= 0:
            break
    return merged


def _diff_name_only(clone_dir: str, prev_sha: str, new_sha: str,
                    git: Optional[Callable[..., Tuple[int, str, str]]] = None
                    ) -> List[str]:
    git = git or _fleet()._run_git
    code, out, err = git(clone_dir, ["diff", "--no-renames", "--name-only",
                                     prev_sha, new_sha])
    if code != 0:
        raise RuntimeError("git diff --name-only failed: %s"
                           % err.strip()[:200])
    return [line.strip() for line in out.splitlines() if line.strip()]


# ---------------------------------------------------------------------------
# Range processing — the per-range fail-closed extraction core
# ---------------------------------------------------------------------------


def _range_paths(range_row: Dict[str, Any], clone_dir: str,
                 cfg: Dict[str, Any],
                 git: Optional[Callable[..., Tuple[int, str, str]]] = None
                 ) -> Tuple[List[str], List[str]]:
    """(paths, notes). The recorded file list is trusted only when it is
    complete and fast-forward; a truncated or non-fast-forward record
    never takes the free path — the changed-path list is rebuilt with a
    capped name-only diff (no blob fetch), degrading visibly."""
    notes: List[str] = []
    files = range_row["files"]
    if not range_row["files_truncated"] and not range_row["non_fast_forward"]:
        return [item["path"] for item in files], notes
    rebuilt = _diff_name_only(clone_dir, range_row["prev_sha"],
                              range_row["new_sha"], git=git)
    notes.append("record incomplete · path list rebuilt (%d paths)"
                 % len(rebuilt))
    return rebuilt, notes


def process_range(connection: sqlite3.Connection, cfg: Dict[str, Any],
                  matchers: Sequence[Any], regexes: Sequence[Any],
                  range_row: Dict[str, Any], clone_dir: str, now: str,
                  git: Optional[Callable[..., Tuple[int, str, str]]] = None
                  ) -> Dict[str, Any]:
    """Extract + detect over one change range. Never raises for per-range
    problems — the outcome is recorded in signal_range_log by the caller."""
    netuid, epoch = range_row["netuid"], range_row["epoch"]
    summary: Dict[str, Any] = {"outcome": "ok", "notes": [],
                               "adoptions": 0, "events": {}}

    paths, notes = _range_paths(range_row, clone_dir, cfg, git=git)
    summary["notes"].extend(notes)

    commits_over = (range_row["commit_count"] > cfg["range_caps"]["max_commits"]
                    or range_row["commits_truncated"])
    files_over = len(paths) > cfg["range_caps"]["max_files"]
    capped = commits_over or files_over
    if capped:
        summary["outcome"] = "truncated-degraded"
        summary["notes"].append("range over caps · manifests only")
        queue_digest_line(
            connection, "range-capped:%d" % range_row["id"],
            "SN%d range %s capped (%d paths, %d commits) · manifests only"
            % (netuid, range_row["new_sha"][:12], len(paths),
               range_row["commit_count"]), now, netuid=netuid)

    manifest_paths = [p for p in paths if is_manifest(p, cfg)]
    model_paths = ([] if (capped or not cfg["model_ids"])
                   else [p for p in paths
                         if is_model_id_file(p, cfg)
                         and p not in manifest_paths])

    terms: List[Tuple[str, str, str]] = []  # (term, kind, source_file)
    if manifest_paths or model_paths:
        added = _diff_added_lines(clone_dir, range_row["prev_sha"],
                                  range_row["new_sha"],
                                  manifest_paths + model_paths, git=git)
        for path in manifest_paths:
            for term in dep_terms_for(path, added.get(path, ()), cfg):
                terms.append((term, KIND_DEP, path))
        if model_paths and cfg["model_ids"]:
            for path in model_paths:
                for term in model_terms_for(added.get(path, ()), regexes,
                                            cfg["term_max_length"]):
                    terms.append((term, KIND_MODEL, path))

    if len(terms) > cfg["max_terms_per_range"]:
        dropped = len(terms) - cfg["max_terms_per_range"]
        terms = terms[:cfg["max_terms_per_range"]]
        summary["notes"].append("term overflow · %d dropped" % dropped)
        queue_digest_line(
            connection, "term-overflow:%d" % range_row["id"],
            "SN%d range %s dropped %d over-cap term(s)"
            % (netuid, range_row["new_sha"][:12], dropped), now,
            netuid=netuid)

    for term, kind, source in terms:
        if record_adoption(connection, term, kind, netuid, epoch, now,
                           range_row["new_sha"], source):
            summary["adoptions"] += 1
            emitted = evaluate_adoption(
                connection, cfg, matchers, term, kind, netuid, epoch, now,
                range_row["new_sha"], source, now)
            for key, count in emitted.items():
                summary["events"][key] = summary["events"].get(key, 0) + count

    # Econ-code detection: recorded/rebuilt path metadata only, no blobs.
    econ_files = [p for p in paths if is_econ_path(p, cfg)]
    if econ_files:
        cooldown_cutoff = (_parse_iso(now) - datetime.timedelta(
            hours=cfg["econ_cooldown_hours"])).isoformat()
        recent = connection.execute(
            "SELECT id FROM signal_events WHERE class = ? AND tier = ? AND "
            "netuid = ? AND created_at >= ?",
            (CLASS_ECON, TIER_INSTANT, netuid, cooldown_cutoff)).fetchone()
        if recent:
            if queue_digest_line(
                    connection, "econ-cooldown:%d" % range_row["id"],
                    "SN%d further incentive-code change %s · in cooldown"
                    % (netuid, range_row["new_sha"][:12]), now,
                    netuid=netuid):
                summary["events"]["digest"] = (
                    summary["events"].get("digest", 0) + 1)
        else:
            payload = {"netuid": netuid, "range_id": range_row["id"],
                       "prev_sha": range_row["prev_sha"],
                       "new_sha": range_row["new_sha"],
                       "files": econ_files[:12],
                       "commit_count": range_row["commit_count"],
                       "commits_truncated": range_row["commits_truncated"]}
            if queue_event(connection, CLASS_ECON, TIER_INSTANT, netuid, None,
                           "econ:%d" % range_row["id"], payload, now):
                summary["events"]["econ"] = (
                    summary["events"].get("econ", 0) + 1)
    return summary


def _decode_range(row: Tuple[Any, ...]) -> Dict[str, Any]:
    (range_id, netuid, epoch, prev_sha, new_sha, non_ff, commits_json,
     files_json) = row
    commits = json.loads(commits_json)
    files = json.loads(files_json)
    return {"id": range_id, "netuid": netuid, "epoch": epoch,
            "prev_sha": prev_sha, "new_sha": new_sha,
            "non_fast_forward": bool(non_ff),
            "commit_count": len(commits.get("commits", [])),
            "commits_truncated": bool(commits.get("truncated")),
            "files": files.get("files", []),
            "files_truncated": bool(files.get("truncated"))}


def run_extract(connection: sqlite3.Connection, config: Dict[str, Any],
                now: Optional[str] = None,
                git: Optional[Callable[..., Tuple[int, str, str]]] = None
                ) -> Dict[str, Any]:
    """Process every change range past the extraction watermark. Each
    range commits on its own; a failed range is logged `extract-failed`
    and skipped — never blocking later ranges or the reconcile."""
    cfg = signals_cfg(config)
    now = now or _utc_now()
    clone_root = config.get("clone_root") or _fleet().DEFAULT_CLONE_ROOT
    matchers, invalid = compile_watchlist(cfg)
    regexes = _model_regexes(cfg)
    if invalid:
        state_set(connection, "watchlist_invalid", json.dumps(invalid))

    watermark = int(state_get(connection, "range_watermark") or 0)
    rows = connection.execute(
        "SELECT id, netuid, epoch, prev_sha, new_sha, non_fast_forward, "
        "commits_json, files_json FROM change_ranges WHERE id > ? "
        "ORDER BY id ASC", (watermark,)).fetchall()

    summary = {"ranges": 0, "ok": 0, "no-surface": 0, "degraded": 0,
               "failed": 0, "adoptions": 0, "events": {}}
    for row in rows:
        range_row = _decode_range(row)
        clone_dir = os.path.join(clone_root, str(range_row["netuid"]))
        summary["ranges"] += 1
        try:
            outcome = process_range(connection, cfg, matchers, regexes,
                                    range_row, clone_dir, now, git=git)
        except Exception as exc:  # noqa: BLE001 — per-range fail-closed
            connection.rollback()
            connection.execute(
                "INSERT OR REPLACE INTO signal_range_log (range_id, netuid, "
                "epoch, outcome, detail, processed_at) VALUES (?, ?, ?, ?, "
                "?, ?)",
                (range_row["id"], range_row["netuid"], range_row["epoch"],
                 "extract-failed", str(exc)[:300], now))
            summary["failed"] += 1
        else:
            if (outcome["adoptions"] == 0 and not outcome["events"]
                    and not outcome["notes"]):
                log_outcome = "no-surface"
                summary["no-surface"] += 1
            elif outcome["outcome"] == "truncated-degraded":
                log_outcome = "truncated-degraded"
                summary["degraded"] += 1
            else:
                log_outcome = "ok"
                summary["ok"] += 1
            connection.execute(
                "INSERT OR REPLACE INTO signal_range_log (range_id, netuid, "
                "epoch, outcome, detail, processed_at) VALUES (?, ?, ?, ?, "
                "?, ?)",
                (range_row["id"], range_row["netuid"], range_row["epoch"],
                 log_outcome, " · ".join(outcome["notes"]) or None, now))
            summary["adoptions"] += outcome["adoptions"]
            for key, count in outcome["events"].items():
                summary["events"][key] = summary["events"].get(key, 0) + count
        state_set(connection, "range_watermark", str(range_row["id"]))
        connection.commit()
    return summary


# ---------------------------------------------------------------------------
# Epoch-open seeding — change ranges exist only for updates, so a new
# clone (or re-point) seeds adoptions from its current manifest state.
# ---------------------------------------------------------------------------


def _epoch_opened_at(connection: sqlite3.Connection, netuid: int,
                     epoch: int) -> Optional[str]:
    row = connection.execute(
        "SELECT opened_at FROM epochs WHERE netuid = ? AND epoch = ?",
        (netuid, epoch)).fetchone()
    return row[0] if row else None


def seed_epoch(connection: sqlite3.Connection, cfg: Dict[str, Any],
               matchers: Sequence[Any], netuid: int, epoch: int,
               clone_dir: str, opened_at: str, silent: bool, now: str,
               git: Optional[Callable[..., Tuple[int, str, str]]] = None
               ) -> Dict[str, Any]:
    """Seed adoptions from the clone's current manifests, dated at epoch
    open. `silent` (epochs predating the signals install) records with
    seeded=1 and runs no detection — exactly like the backfill posture."""
    git = git or _fleet()._run_git
    code, out, err = git(clone_dir, ["ls-tree", "-r", "--name-only", "HEAD"])
    if code != 0:
        raise RuntimeError("ls-tree failed: %s" % err.strip()[:200])
    manifest_paths = [line.strip() for line in out.splitlines()
                      if line.strip() and is_manifest(line.strip(), cfg)]
    adopted = 0
    events: Dict[str, int] = {}
    for path in manifest_paths:
        abs_path = os.path.join(clone_dir, path.replace("/", os.sep))
        try:
            with open(abs_path, "r", encoding="utf-8",
                      errors="replace") as handle:
                lines = handle.read().splitlines()
        except OSError:
            continue  # blobless miss / deleted locally: skip the file
        for term in dep_terms_for(path, lines, cfg):
            if record_adoption(connection, term, KIND_DEP, netuid, epoch,
                               opened_at, None, path, seeded=silent):
                adopted += 1
                if not silent:
                    emitted = evaluate_adoption(
                        connection, cfg, matchers, term, KIND_DEP, netuid,
                        epoch, opened_at, None, path, now)
                    for key, count in emitted.items():
                        events[key] = events.get(key, 0) + count
    return {"manifests": len(manifest_paths), "adoptions": adopted,
            "events": events}


def seed_epochs(connection: sqlite3.Connection, config: Dict[str, Any],
                now: Optional[str] = None,
                git: Optional[Callable[..., Tuple[int, str, str]]] = None
                ) -> Dict[str, Any]:
    """Seed every active (netuid, epoch) not yet seeded. Epochs opened
    before the signals install are seeded silently (their open date is
    not an adoption signal); later ones run full detection."""
    cfg = signals_cfg(config)
    now = now or _utc_now()
    clone_root = config.get("clone_root") or _fleet().DEFAULT_CLONE_ROOT
    matchers, _invalid = compile_watchlist(cfg)
    installed_at = state_get(connection, "installed_at") or now

    try:
        slots = connection.execute(
            "SELECT netuid, epoch FROM slots WHERE status = 'active' AND "
            "epoch IS NOT NULL").fetchall()
    except sqlite3.Error:
        return {"seeded": 0, "failed": 0}
    summary = {"seeded": 0, "failed": 0, "events": {}}
    for netuid, epoch in slots:
        seen = connection.execute(
            "SELECT 1 FROM signal_epoch_seeds WHERE netuid = ? AND epoch = ?",
            (netuid, epoch)).fetchone()
        if seen:
            continue
        clone_dir = os.path.join(clone_root, str(netuid))
        opened_at = _epoch_opened_at(connection, netuid, epoch) or now
        silent = opened_at < installed_at
        try:
            outcome = seed_epoch(connection, cfg, matchers, netuid, epoch,
                                 clone_dir, opened_at, silent, now, git=git)
        except Exception as exc:  # noqa: BLE001 — per-slot fail-closed
            connection.rollback()
            connection.execute(
                "INSERT OR REPLACE INTO signal_epoch_seeds (netuid, epoch, "
                "seeded_at, outcome) VALUES (?, ?, ?, ?)",
                (netuid, epoch, now, "failed: %s" % str(exc)[:200]))
            summary["failed"] += 1
        else:
            connection.execute(
                "INSERT OR REPLACE INTO signal_epoch_seeds (netuid, epoch, "
                "seeded_at, outcome) VALUES (?, ?, ?, ?)",
                (netuid, epoch, now,
                 "silent" if silent else "seeded:%d" % outcome["adoptions"]))
            summary["seeded"] += 1
            for key, count in outcome.get("events", {}).items():
                summary["events"][key] = summary["events"].get(key, 0) + count
        connection.commit()
    return summary


# ---------------------------------------------------------------------------
# Price snapshots + outcomes (effectiveness ledger)
# ---------------------------------------------------------------------------


def default_price_fetcher() -> Optional[Dict[int, Optional[float]]]:
    """Fleet-wide alpha prices in TAO from the keyless TaoSwap subnets
    operation, THROUGH the live-data layer (contract validation, health
    recording, fail-closed) — never a raw HTTP call. None on any failure
    (fail-soft: measurement never blocks alerting)."""
    sys.path.insert(0, os.path.join(_REPO_ROOT, "livedata"))
    try:
        import atlas_live as al  # noqa: E402
        live_config = al.load_config()
        env = al.load_env()
        conn = al.open_store(al.resolve(live_config["db"]))
        try:
            ledger = al.QuotaLedger(conn, live_config)
            result = al.run_operation(conn, live_config, ledger,
                                      "subnets_taoswap", interactive=False,
                                      env=env)
        finally:
            conn.close()
        if result.get("status") != "ok":
            return None
        subnets = (result.get("values") or {}).get("subnets") or []
        return {row["netuid"]: row.get("alpha_price_tao")
                for row in subnets if row.get("netuid") is not None}
    except Exception:  # noqa: BLE001 — fail-soft by contract
        return None


def _instant_members(connection: sqlite3.Connection,
                     event_id: int) -> List[int]:
    row = connection.execute(
        "SELECT class, netuid, payload_json FROM signal_events WHERE id = ?",
        (event_id,)).fetchone()
    if row is None:
        return []
    event_class, netuid, payload_json = row
    if event_class == CLASS_CLUSTER:
        payload = json.loads(payload_json)
        return [member["netuid"] for member in payload.get("members", [])]
    return [netuid] if netuid is not None else []


def _ensure_measurement_rows(connection: sqlite3.Connection,
                             cfg: Dict[str, Any]) -> None:
    """Entries (pending) and outcome horizon rows for every instant event
    that lacks them. Idempotent."""
    rows = connection.execute(
        "SELECT id, created_at FROM signal_events WHERE tier = ?",
        (TIER_INSTANT,)).fetchall()
    for event_id, created_at in rows:
        for netuid in _instant_members(connection, event_id):
            connection.execute(
                "INSERT OR IGNORE INTO signal_entries (event_id, netuid, "
                "status) VALUES (?, ?, ?)", (event_id, netuid, ST_PENDING))
            created = _parse_iso(created_at)
            for horizon in cfg["outcome_horizons_days"]:
                due = (created
                       + datetime.timedelta(days=int(horizon))).isoformat()
                connection.execute(
                    "INSERT OR IGNORE INTO signal_outcomes (event_id, netuid, "
                    "horizon_days, due_at, status) VALUES (?, ?, ?, ?, ?)",
                    (event_id, netuid, int(horizon), due, ST_PENDING))


def _measurement_needed(connection: sqlite3.Connection, now: str) -> bool:
    pending_entry = connection.execute(
        "SELECT 1 FROM signal_entries WHERE status = ? LIMIT 1",
        (ST_PENDING,)).fetchone()
    if pending_entry:
        return True
    due = connection.execute(
        "SELECT 1 FROM signal_outcomes WHERE status = ? AND due_at <= ? "
        "LIMIT 1", (ST_PENDING, now)).fetchone()
    return due is not None


def _price_vector(connection: sqlite3.Connection,
                  ts: str) -> Dict[int, Optional[float]]:
    return {netuid: price for netuid, price in connection.execute(
        "SELECT netuid, price_tao FROM signal_prices WHERE ts = ?", (ts,))}


def _fleet_median_return(entry_vector: Dict[int, Optional[float]],
                         exit_vector: Dict[int, Optional[float]]
                         ) -> Optional[float]:
    returns = []
    for netuid, entry in entry_vector.items():
        exit_price = exit_vector.get(netuid)
        if entry and exit_price:
            returns.append((exit_price / entry - 1.0) * 100.0)
    return statistics.median(returns) if returns else None


def run_measurement(connection: sqlite3.Connection, config: Dict[str, Any],
                    now: Optional[str] = None,
                    price_fetcher: Optional[Callable[
                        [], Optional[Dict[int, Optional[float]]]]] = None
                    ) -> Dict[str, Any]:
    """One measurement step: ensure entry/outcome rows exist, fetch the
    fleet price vector AT MOST ONCE (and only when something needs it),
    fill pending entries and due outcomes, prune old vectors. A failed
    fetch leaves everything pending — retried next pass, never blocking."""
    cfg = signals_cfg(config)
    now = now or _utc_now()
    _ensure_measurement_rows(connection, cfg)
    summary = {"fetched": False, "entries_filled": 0, "outcomes_filled": 0,
               "unavailable": 0}
    if not _measurement_needed(connection, now):
        connection.commit()
        return summary

    fetcher = price_fetcher or default_price_fetcher
    vector = fetcher()
    if vector is None:
        connection.commit()
        summary["fetch_failed"] = True
        return summary
    summary["fetched"] = True
    connection.executemany(
        "INSERT OR IGNORE INTO signal_prices (ts, netuid, price_tao) "
        "VALUES (?, ?, ?)",
        [(now, netuid, price) for netuid, price in vector.items()])

    late_cutoff = (_parse_iso(now) - datetime.timedelta(
        hours=LATE_GRACE_HOURS)).isoformat()

    # Entries: price at (or nearest after) event creation.
    entry_rows = connection.execute(
        "SELECT e.event_id, e.netuid, ev.created_at FROM signal_entries e "
        "JOIN signal_events ev ON ev.id = e.event_id WHERE e.status = ?",
        (ST_PENDING,)).fetchall()
    for event_id, netuid, created_at in entry_rows:
        if netuid not in vector:
            status = ST_UNAVAILABLE  # deregistered before entry could fill
            price = None
        else:
            price = vector[netuid]
            status = ST_LATE if created_at < late_cutoff else ST_RECORDED
        connection.execute(
            "UPDATE signal_entries SET price_tao = ?, as_of = ?, status = ? "
            "WHERE event_id = ? AND netuid = ?",
            (price, now, status, event_id, netuid))
        if status == ST_UNAVAILABLE:
            summary["unavailable"] += 1
        else:
            summary["entries_filled"] += 1

    # Outcomes: due rows whose entry has a usable price.
    due_rows = connection.execute(
        "SELECT o.id, o.event_id, o.netuid, o.due_at, en.price_tao, en.as_of, "
        "en.status FROM signal_outcomes o JOIN signal_entries en "
        "ON en.event_id = o.event_id AND en.netuid = o.netuid "
        "WHERE o.status = ? AND o.due_at <= ?",
        (ST_PENDING, now)).fetchall()
    for (outcome_id, _event_id, netuid, due_at, entry_price, entry_ts,
         entry_status) in due_rows:
        if entry_status == ST_UNAVAILABLE or not entry_price:
            connection.execute(
                "UPDATE signal_outcomes SET status = ?, filled_at = ? "
                "WHERE id = ?", (ST_UNAVAILABLE, now, outcome_id))
            summary["unavailable"] += 1
            continue
        exit_price = vector.get(netuid)
        if not exit_price:
            connection.execute(
                "UPDATE signal_outcomes SET status = ?, filled_at = ? "
                "WHERE id = ?", (ST_UNAVAILABLE, now, outcome_id))
            summary["unavailable"] += 1
            continue
        return_pct = (exit_price / entry_price - 1.0) * 100.0
        baseline = _fleet_median_return(
            _price_vector(connection, entry_ts), vector)
        status = ST_LATE if due_at < late_cutoff else ST_RECORDED
        connection.execute(
            "UPDATE signal_outcomes SET exit_price_tao = ?, return_pct = ?, "
            "baseline_return_pct = ?, status = ?, filled_at = ? WHERE id = ?",
            (exit_price, return_pct, baseline, status, now, outcome_id))
        summary["outcomes_filled"] += 1

    # Retention: never below the longest horizon plus a week of slack.
    horizon_floor = max([int(h) for h in cfg["outcome_horizons_days"]]
                        or [30]) + 7
    keep_days = max(int(cfg["price_retention_days"]), horizon_floor)
    cutoff = (_parse_iso(now)
              - datetime.timedelta(days=keep_days)).isoformat()
    connection.execute("DELETE FROM signal_prices WHERE ts < ?", (cutoff,))
    connection.commit()
    return summary


# ---------------------------------------------------------------------------
# The inline pass (reconcile hook) — seed epochs, extract, measure
# ---------------------------------------------------------------------------


def run_pass(connection: sqlite3.Connection, config: Dict[str, Any],
             now: Optional[str] = None,
             git: Optional[Callable[..., Tuple[int, str, str]]] = None,
             price_fetcher: Optional[Callable[
                 [], Optional[Dict[int, Optional[float]]]]] = None
             ) -> Dict[str, Any]:
    """The hourly signals pass, invoked inline after reconcile records
    its ranges. First run installs quietly: the extraction watermark
    seeds to the current newest range (history is the backfill's job,
    never an alert flood) and `installed_at` gates epoch-seed silence."""
    cfg = signals_cfg(config)
    now = now or _utc_now()
    ensure_schema(connection)
    if not cfg.get("enabled", True):
        return {"disabled": True}

    if state_get(connection, "installed_at") is None:
        state_set(connection, "installed_at", now)
    if state_get(connection, "range_watermark") is None:
        row = connection.execute("SELECT MAX(id) FROM change_ranges"
                                 ).fetchone()
        state_set(connection, "range_watermark",
                  str(row[0] if row and row[0] is not None else 0))
    connection.commit()

    summary = {"seed": seed_epochs(connection, config, now=now, git=git),
               "extract": run_extract(connection, config, now=now, git=git),
               "measure": run_measurement(connection, config, now=now,
                                          price_fetcher=price_fetcher)}
    return summary


# ---------------------------------------------------------------------------
# Backfill (silent historical manifest seed) + model-id prevalence seed
# ---------------------------------------------------------------------------

_LOG_COMMIT_RE = re.compile(r"^__COMMIT__\t([0-9a-f]{40})\t(\S+)$")


def _backfill_clone(connection: sqlite3.Connection, cfg: Dict[str, Any],
                    netuid: int, epoch: int, clone_dir: str,
                    git: Optional[Callable[..., Tuple[int, str, str]]] = None
                    ) -> Dict[str, Any]:
    """Walk one clone's manifest history oldest-first, recording each
    term's earliest adoption with its real commit date. No --follow (it
    accepts a single pathspec only; manifest renames are accepted as
    lost). Emits nothing."""
    git = git or _fleet()._run_git
    code, out, err = git(clone_dir, ["ls-tree", "-r", "--name-only", "HEAD"])
    if code != 0:
        raise RuntimeError("ls-tree failed: %s" % err.strip()[:200])
    manifest_paths = [line.strip() for line in out.splitlines()
                      if line.strip() and is_manifest(line.strip(), cfg)]
    if not manifest_paths:
        return {"commits": 0, "adoptions": 0}

    code, out, err = git(clone_dir, [
        "log", "-p", "--no-renames", "--reverse", "--unified=0",
        "--format=__COMMIT__%x09%H%x09%aI", "--"] + manifest_paths)
    if code != 0:
        raise RuntimeError("git log -p failed: %s" % err.strip()[:200])

    commits = 0
    adoptions = 0
    sha: Optional[str] = None
    date: Optional[str] = None
    current: Optional[str] = None
    for line in out.splitlines():
        header = _LOG_COMMIT_RE.match(line)
        if header:
            commits += 1
            if commits > cfg["backfill_max_commits"]:
                break
            sha, date = header.group(1), header.group(2)
            current = None
            continue
        target = _DIFF_TARGET_RE.match(line)
        if target:
            path = target.group(1)
            current = path if is_manifest(path, cfg) else None
            continue
        if line.startswith("+++"):
            current = None
            continue
        if current is None or not line.startswith("+") or sha is None:
            continue
        for term in dep_terms_for(current, [line[1:]], cfg):
            if record_adoption(connection, term, KIND_DEP, netuid, epoch,
                               date or _utc_now(), sha, current,
                               replace_seeded=True):
                adoptions += 1
    return {"commits": min(commits, cfg["backfill_max_commits"]),
            "adoptions": adoptions,
            "partial": commits > cfg["backfill_max_commits"]}


def backfill(connection: sqlite3.Connection, config: Dict[str, Any],
             netuid: Optional[int] = None,
             git: Optional[Callable[..., Tuple[int, str, str]]] = None
             ) -> Dict[str, Any]:
    """Seed the term ledger from existing clone history (manifests only;
    real commit author dates — calibration data, so no event is ever
    derived from them), then pin the extraction watermark to the newest
    range. Per-slot fail-closed."""
    cfg = signals_cfg(config)
    ensure_schema(connection)
    now = _utc_now()
    if state_get(connection, "installed_at") is None:
        state_set(connection, "installed_at", now)
    fleet = _fleet()
    clone_root = config.get("clone_root") or fleet.DEFAULT_CLONE_ROOT
    slots = ([fleet.get_slot(connection, netuid)] if netuid is not None
             else fleet.all_slots(connection))
    summary = {"slots": 0, "adoptions": 0, "failed": 0, "partial": 0}
    for slot in slots:
        if not slot or slot.get("status") != "active":
            continue
        nid = slot["netuid"]
        clone_dir = os.path.join(clone_root, str(nid))
        summary["slots"] += 1
        try:
            outcome = _backfill_clone(connection, cfg, nid,
                                      slot.get("epoch") or 1, clone_dir,
                                      git=git)
            summary["adoptions"] += outcome["adoptions"]
            summary["partial"] += 1 if outcome.get("partial") else 0
            connection.commit()
        except Exception:  # noqa: BLE001 — per-slot fail-closed
            connection.rollback()
            summary["failed"] += 1
    row = connection.execute("SELECT MAX(id) FROM change_ranges").fetchone()
    state_set(connection, "range_watermark",
              str(row[0] if row and row[0] is not None else 0))
    connection.commit()
    return summary


def seed_modelids(connection: sqlite3.Connection,
                  config: Dict[str, Any]) -> Dict[str, Any]:
    """One-shot model-id prevalence seed from the fleet-search index's
    current file contents (read-only; the only place the FTS tables are
    touched by signals). Rows are flagged `seeded`: they raise the
    novelty ceiling but never enter a cluster window, closing the
    cold-start hole where every established model id looks novel."""
    cfg = signals_cfg(config)
    ensure_schema(connection)
    now = _utc_now()
    regexes = _model_regexes(cfg)
    present = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND "
        "name = 'fleet_files'").fetchone()
    if present is None:
        return {"error": "fleet_files index absent — run `fleet index` first",
                "adoptions": 0}
    rows = connection.execute(
        "SELECT ff.netuid, ff.epoch, ff.path, fts.content FROM fleet_files ff "
        "JOIN fleet_files_fts fts ON fts.rowid = ff.id").fetchall()
    adoptions = 0
    scanned = 0
    for netuid, epoch, path, content in rows:
        if not is_model_id_file(path, cfg):
            continue
        scanned += 1
        for term in model_terms_for(content.splitlines(), regexes,
                                    cfg["term_max_length"]):
            if record_adoption(connection, term, KIND_MODEL, netuid, epoch,
                               now, None, path, seeded=True):
                adoptions += 1
    connection.commit()
    return {"files_scanned": scanned, "adoptions": adoptions}


# ---------------------------------------------------------------------------
# Calibration + effectiveness reporting (both read-only)
# ---------------------------------------------------------------------------


def calibrate(connection: sqlite3.Connection, config: Dict[str, Any],
              k_values: Sequence[int] = (2, 3, 4),
              window_values: Sequence[int] = (7, 14, 30),
              novelty_values: Sequence[int] = (5, 10, 20)) -> Dict[str, Any]:
    """Replay the (non-seeded) adoption ledger under a threshold grid and
    report the clusters each candidate would have fired, with dates —
    evidence for the operator's config choice. Changes no state."""
    cfg = signals_cfg(config)
    rows = connection.execute(
        "SELECT term, kind, netuid, MIN(adopted_at) FROM signal_adoptions "
        "WHERE seeded = 0 GROUP BY term, kind, netuid "
        "ORDER BY MIN(adopted_at) ASC").fetchall()
    total_by_term: Dict[Tuple[str, str], List[Tuple[str, int]]] = {}
    for term, kind, netuid, adopted_at in rows:
        total_by_term.setdefault((term, kind), []).append((adopted_at, netuid))

    report: Dict[str, Any] = {"adoptions": len(rows),
                              "terms": len(total_by_term), "grid": []}
    for k in k_values:
        for window in window_values:
            for novelty in novelty_values:
                clusters = []
                for (term, kind), adoption_list in total_by_term.items():
                    if len(adoption_list) > novelty:
                        continue  # never qualified under this ceiling
                    window_delta = datetime.timedelta(days=window)
                    for index in range(k - 1, len(adoption_list)):
                        first = _parse_iso(adoption_list[index - k + 1][0])
                        this = _parse_iso(adoption_list[index][0])
                        if this - first <= window_delta:
                            clusters.append({
                                "term": term, "kind": kind,
                                "fired_at": adoption_list[index][0],
                                "members": [n for _at, n in
                                            adoption_list[:index + 1]]})
                            break  # one episode per term
                report["grid"].append({
                    "k": k, "window_days": window, "novelty_max": novelty,
                    "clusters": len(clusters),
                    "examples": clusters[:8]})
    report["current_config"] = {"k": cfg["cluster"]["k"],
                                "window_days": cfg["cluster"]["window_days"],
                                "novelty_max": cfg["novelty_max_adopters"]}
    return report


def effectiveness(connection: sqlite3.Connection) -> Dict[str, Any]:
    """Per alert class × horizon: alerted-subnet median return vs the
    fleet-median baseline, with counts and pending/unavailable tallies.
    Read-only measurement — ranks nothing, recommends nothing."""
    rows = connection.execute(
        "SELECT ev.class, o.horizon_days, o.status, o.return_pct, "
        "o.baseline_return_pct FROM signal_outcomes o "
        "JOIN signal_events ev ON ev.id = o.event_id").fetchall()
    buckets: Dict[Tuple[str, int], Dict[str, Any]] = {}
    for event_class, horizon, status, return_pct, baseline in rows:
        bucket = buckets.setdefault((event_class, horizon), {
            "returns": [], "baselines": [], "pending": 0, "unavailable": 0,
            "filled": 0})
        if status in (ST_RECORDED, ST_LATE):
            bucket["filled"] += 1
            if return_pct is not None:
                bucket["returns"].append(return_pct)
            if baseline is not None:
                bucket["baselines"].append(baseline)
        elif status == ST_UNAVAILABLE:
            bucket["unavailable"] += 1
        else:
            bucket["pending"] += 1
    report = []
    for (event_class, horizon), bucket in sorted(buckets.items()):
        report.append({
            "class": event_class, "horizon_days": horizon,
            "filled": bucket["filled"], "pending": bucket["pending"],
            "unavailable": bucket["unavailable"],
            "median_return_pct": (round(statistics.median(bucket["returns"]),
                                        3) if bucket["returns"] else None),
            "median_baseline_pct": (round(statistics.median(
                bucket["baselines"]), 3) if bucket["baselines"] else None),
        })
    return {"report": report,
            "note": "measurement only — medians vs fleet baseline over "
                    "identical windows; no recommendation derived"}


# ---------------------------------------------------------------------------
# Status + CLI
# ---------------------------------------------------------------------------


def signals_status(connection: sqlite3.Connection) -> Dict[str, Any]:
    ensure_schema(connection)
    counts = {row[0]: row[1] for row in connection.execute(
        "SELECT outcome, COUNT(*) FROM signal_range_log GROUP BY outcome")}
    events = {row[0]: row[1] for row in connection.execute(
        "SELECT class, COUNT(*) FROM signal_events GROUP BY class")}
    adoptions = connection.execute(
        "SELECT COUNT(*), COUNT(DISTINCT term) FROM signal_adoptions"
    ).fetchone()
    outcome_states = {row[0]: row[1] for row in connection.execute(
        "SELECT status, COUNT(*) FROM signal_outcomes GROUP BY status")}
    invalid = state_get(connection, "watchlist_invalid")
    return {
        "range_watermark": state_get(connection, "range_watermark"),
        "installed_at": state_get(connection, "installed_at"),
        "ranges": counts,
        "adoptions": {"rows": adoptions[0], "terms": adoptions[1]},
        "events": events,
        "outcomes": outcome_states,
        "watchlist_invalid": json.loads(invalid) if invalid else [],
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="atlas_fleet_signals",
        description="Atlas fleet-signals: narrative radar + econ-code alerts "
                    "over the subnet-repo fleet.")
    parser.add_argument("--config", default=None)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    sub.add_parser("extract", help="process ranges past the watermark "
                                   "(also runs inline on reconcile)")
    bf = sub.add_parser("backfill", help="silent historical manifest seed")
    bf.add_argument("--netuid", type=int, default=None)
    sub.add_parser("seed-modelids", help="silent model-id prevalence seed "
                                         "from the fleet-search index")
    cal = sub.add_parser("calibrate", help="replay ledger over a threshold "
                                           "grid (read-only)")
    cal.add_argument("--k", type=int, nargs="*", default=[2, 3, 4])
    cal.add_argument("--window", type=int, nargs="*", default=[7, 14, 30])
    cal.add_argument("--novelty", type=int, nargs="*", default=[5, 10, 20])
    sub.add_parser("effectiveness", help="per-class × horizon report "
                                         "(read-only)")
    args = parser.parse_args(argv)

    fleet = _fleet()
    try:
        config = fleet.load_config(args.config or fleet.CONFIG_FILE)
        connection = fleet.open_store(config["db"])
        try:
            ensure_schema(connection)
            if args.command == "status":
                result: Dict[str, Any] = signals_status(connection)
            elif args.command == "extract":
                result = run_pass(connection, config)
            elif args.command == "backfill":
                result = backfill(connection, config, netuid=args.netuid)
            elif args.command == "seed-modelids":
                result = seed_modelids(connection, config)
            elif args.command == "calibrate":
                result = calibrate(connection, config, k_values=args.k,
                                   window_values=args.window,
                                   novelty_values=args.novelty)
            elif args.command == "effectiveness":
                result = effectiveness(connection)
            else:
                return 2
            print(json.dumps(result, indent=2, sort_keys=True))
        finally:
            connection.close()
        return 0
    except fleet.FleetError as exc:
        print("fatal: %s" % exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
