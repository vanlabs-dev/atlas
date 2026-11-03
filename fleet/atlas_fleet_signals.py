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

sys.path.insert(0, _MODULE_DIR)
import atlas_econ_judge as ejudge  # noqa: E402

SIGNALS_VERSION = "0.1.0"

# Event classes / tiers (the notifier renders these; keep names stable).
CLASS_CLUSTER = "narrative-cluster"
CLASS_WATCHLIST = "watchlist"
CLASS_ECON = "econ-code"
CLASS_DIGEST = "signal-digest"
TIER_INSTANT = "instant"
TIER_DIGEST = "digest"
# Ledger source stores (change: rotation-signal-gate). An entry is keyed by
# (source store, source row id, netuid), so a livedata row id can never be
# confused with a fleet event id.
SOURCE_FLEET = "fleet"
SOURCE_LIVEDATA = "livedata"
# Netuid-scoped classes livedata produces, read into the ledger by the hourly
# fleet pass. Each maps to (table, netuid column, timestamp column).
LIVEDATA_MEASURED = {
    "gate-crossing": ("gate_events", "netuid", "observed_at"),
}

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
CREATE TABLE IF NOT EXISTS signal_vectors (
    ts TEXT PRIMARY KEY,
    block_number INTEGER
);
CREATE TABLE IF NOT EXISTS signal_entries (
    source_store TEXT NOT NULL DEFAULT 'fleet',
    event_id INTEGER NOT NULL,
    netuid INTEGER NOT NULL,
    source_class TEXT,
    created_at TEXT,
    price_tao REAL,
    as_of TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    PRIMARY KEY (source_store, event_id, netuid)
);
CREATE TABLE IF NOT EXISTS signal_outcomes (
    id INTEGER PRIMARY KEY,
    source_store TEXT NOT NULL DEFAULT 'fleet',
    event_id INTEGER NOT NULL,
    netuid INTEGER NOT NULL,
    source_class TEXT,
    horizon_days INTEGER NOT NULL,
    due_at TEXT NOT NULL,
    exit_price_tao REAL,
    return_pct REAL,
    baseline_return_pct REAL,
    status TEXT NOT NULL DEFAULT 'pending',
    filled_at TEXT,
    UNIQUE (source_store, event_id, netuid, horizon_days)
);
CREATE TABLE IF NOT EXISTS signal_econ_verdicts (
    content_hash TEXT PRIMARY KEY,
    netuid INTEGER NOT NULL,
    range_id INTEGER,
    prev_sha TEXT,
    new_sha TEXT,
    matched_files TEXT NOT NULL,
    significance TEXT NOT NULL,
    direction TEXT NOT NULL,
    what_changed TEXT,
    why_it_matters TEXT,
    evidence TEXT,
    outcome TEXT NOT NULL,
    partial_view INTEGER NOT NULL DEFAULT 0,
    model_id TEXT,
    created_at TEXT NOT NULL
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
    # Promotion floor (change: rotation-signal-gate). A class needs at least
    # this many FILLED 7-day outcomes before an operator may promote it to a
    # paging tier. A floor on sample size, not a significance test: the report
    # prints medians and counts and a human decides. Strawman — reset from
    # `calibrate`/`effectiveness` evidence on-device.
    "min_filled_for_promotion": 30,
    "promotion_horizon_days": 7,
    "backfill_max_commits": 500,
}


def signals_cfg(config: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(DEFAULT_SIGNALS_CFG)
    for key, value in (config.get("signals") or {}).items():
        if key == "_comment":
            continue
        merged[key] = value
    return merged


# Econ-alert intelligence gate (change: econ-alert-intelligence-gate).
# Defaults OFF: with `enabled` false (or no `claude_path`), econ detection
# keeps today's path-match-and-page behaviour, so enabling/disabling is the
# whole rollback. The judge runs `claude -p` with no tools and checks each
# call's own tool surface (change: rewrite-judge-lockdown). Auth is the
# `claude` CLI login; no key, provider, or model id here.
DEFAULT_JUDGE_CFG: Dict[str, Any] = {
    "enabled": False,
    "claude_path": "",
    "timeout_seconds": 120,
    "max_calls_per_run": 20,
    "max_calls_per_day": 200,
    "max_diff_bytes": 20000,
    "high_stakes_paths": ["mechanism", "set_weights", "emission"],
}


def judge_cfg(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Merge the operator's `signals.judge` block under the code defaults, so
    a partial config keeps the rest of the defaults."""
    merged = dict(DEFAULT_JUDGE_CFG)
    for key, value in (cfg.get("judge") or {}).items():
        if key == "_comment":
            continue
        merged[key] = value
    return merged


def _gate_active(jcfg: Dict[str, Any]) -> bool:
    """The gate runs only when explicitly enabled AND given a CLI path; any
    misconfiguration falls back to the legacy econ path (fail-safe)."""
    return bool(jcfg.get("enabled") and jcfg.get("claude_path"))


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
    _migrate_ledger_source(connection)
    _migrate_registration_columns(connection)


# Columns added by change signal-statistics-ties. Additive only: every
# reader of the older columns keeps working, and old rows keep their values.
_ADDED_COLUMNS = (
    ("signal_prices", "reg_block", "INTEGER"),
    ("signal_entries", "anchor_at", "TEXT"),
    ("signal_entries", "entry_ts", "TEXT"),
    ("signal_entries", "reg_block", "INTEGER"),
    ("signal_entries", "reason", "TEXT"),
    ("signal_outcomes", "v2_status", "TEXT"),
    ("signal_outcomes", "v2_reason", "TEXT"),
    ("signal_outcomes", "v2_entry_ts", "TEXT"),
    ("signal_outcomes", "v2_exit_ts", "TEXT"),
    ("signal_outcomes", "v2_return_pct", "REAL"),
    ("signal_outcomes", "v2_baseline_pct", "REAL"),
    ("signal_outcomes", "v2_excess_pct", "REAL"),
    ("signal_outcomes", "v2_rules", "INTEGER"),
)


def _migrate_registration_columns(connection: sqlite3.Connection) -> None:
    """Add the occupant and rescore columns (change:
    signal-statistics-ties). Idempotent."""
    changed = False
    for table, column, kind in _ADDED_COLUMNS:
        if not _has_column(connection, table, column):
            connection.execute("ALTER TABLE %s ADD COLUMN %s %s"
                               % (table, column, kind))
            changed = True
    if changed:
        connection.commit()


def _has_column(connection: sqlite3.Connection, table: str,
                column: str) -> bool:
    return any(row[1] == column for row in
               connection.execute("PRAGMA table_info(%s)" % table))


def _migrate_ledger_source(connection: sqlite3.Connection) -> None:
    """Rebuild the ledger tables onto the source triple (change:
    rotation-signal-gate). Pre-change rows were keyed by a `signal_events`
    id alone, which cannot distinguish a fleet event from a livedata event
    that happens to share a row id. Existing rows backfill as store `fleet`,
    carrying their class and creation time out of `signal_events` so entry
    filling no longer needs that join. Idempotent: a store already on the
    new shape is left alone."""
    if _has_column(connection, "signal_entries", "source_store"):
        return
    connection.executescript("""
        ALTER TABLE signal_entries RENAME TO signal_entries_pre_source;
        ALTER TABLE signal_outcomes RENAME TO signal_outcomes_pre_source;
    """)
    connection.executescript(SCHEMA_SQL)
    connection.execute(
        "INSERT INTO signal_entries (source_store, event_id, netuid, "
        "source_class, created_at, price_tao, as_of, status) "
        "SELECT 'fleet', e.event_id, e.netuid, ev.class, ev.created_at, "
        "e.price_tao, e.as_of, e.status FROM signal_entries_pre_source e "
        "LEFT JOIN signal_events ev ON ev.id = e.event_id")
    connection.execute(
        "INSERT INTO signal_outcomes (id, source_store, event_id, netuid, "
        "source_class, horizon_days, due_at, exit_price_tao, return_pct, "
        "baseline_return_pct, status, filled_at) "
        "SELECT o.id, 'fleet', o.event_id, o.netuid, ev.class, "
        "o.horizon_days, o.due_at, o.exit_price_tao, o.return_pct, "
        "o.baseline_return_pct, o.status, o.filled_at "
        "FROM signal_outcomes_pre_source o "
        "LEFT JOIN signal_events ev ON ev.id = o.event_id")
    connection.executescript("""
        DROP TABLE signal_entries_pre_source;
        DROP TABLE signal_outcomes_pre_source;
    """)
    connection.commit()


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


# ---------------------------------------------------------------------------
# Econ-alert intelligence gate — read the diff, judge significance, then
# route (alert / digest / drop). Reuses the local clone (read-only git) and
# the Hermes X OAuth subscription via the injected judge. See the
# econ-alert-intelligence-gate change.
# ---------------------------------------------------------------------------

def _fetch_econ_diff(clone_dir: str, prev_sha: str, new_sha: str,
                     econ_files: Sequence[str], max_bytes: int,
                     git: Optional[Callable[..., Tuple[int, str, str]]] = None
                     ) -> Tuple[str, bool, bool]:
    """(diff_text, partial_view, ok). Read-only unified diff of the matched
    econ files from the local clone, byte-bounded. `ok` is False when the
    clone/diff is unavailable — the caller then ships `unjudged`."""
    git = git or _fleet()._run_git
    try:
        code, out, err = git(clone_dir, [
            "diff", "--no-renames", "--unified=3", prev_sha, new_sha, "--"
        ] + list(econ_files[:_DIFF_PATH_BATCH]))
    except Exception:  # noqa: BLE001 — missing clone → unjudged, never raise
        return "", False, False
    if code != 0:
        return "", False, False
    encoded = out.encode("utf-8", "replace")
    if len(encoded) > max_bytes:
        return encoded[:max_bytes].decode("utf-8", "ignore"), True, True
    return out, False, True


def _is_high_stakes(econ_files: Sequence[str], jcfg: Dict[str, Any]) -> bool:
    tokens = [t.lower() for t in jcfg.get("high_stakes_paths") or ()]
    return any(tok in p.lower() for p in econ_files for tok in tokens)


def _route_outcome(significance: str, high_stakes: bool
                   ) -> Tuple[str, bool]:
    """(route, break_cooldown) from a verdict significance.
    route ∈ instant | digest | drop. `high` breaks the per-netuid cooldown;
    a high-stakes path floors `none` up to a digest so it is never dropped."""
    if significance == "high":
        return "instant", True
    if significance in ("med", ejudge.UNJUDGED):
        return "instant", False
    if significance == "low":
        return "digest", False
    # none
    return ("digest" if high_stakes else "drop"), False


def _judge_day_key(now: str) -> str:
    return "judge_calls:%s" % now[:10]


def _budget_allows(connection: sqlite3.Connection, jcfg: Dict[str, Any],
                   budget: Optional[Dict[str, int]], now: str) -> bool:
    if budget is not None and budget.get("run", 0) >= jcfg["max_calls_per_run"]:
        return False
    today = int(state_get(connection, _judge_day_key(now)) or 0)
    return today < jcfg["max_calls_per_day"]


def _budget_consume(connection: sqlite3.Connection,
                    budget: Optional[Dict[str, int]], now: str) -> None:
    if budget is not None:
        budget["run"] = budget.get("run", 0) + 1
    key = _judge_day_key(now)
    state_set(connection, key, str(int(state_get(connection, key) or 0) + 1))


def _emit_econ_legacy(connection: sqlite3.Connection, cfg: Dict[str, Any],
                      range_row: Dict[str, Any], netuid: int,
                      econ_files: List[str], now: str,
                      summary: Dict[str, Any]) -> None:
    """Pre-gate behaviour: page every matching range, dampen repeats within
    the per-netuid cooldown to a digest line. Used when the gate is off."""
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
                % (netuid, range_row["new_sha"][:12]), now, netuid=netuid):
            summary["events"]["digest"] = summary["events"].get("digest", 0) + 1
    else:
        payload = {"netuid": netuid, "range_id": range_row["id"],
                   "prev_sha": range_row["prev_sha"],
                   "new_sha": range_row["new_sha"],
                   "files": econ_files[:12],
                   "commit_count": range_row["commit_count"],
                   "commits_truncated": range_row["commits_truncated"]}
        if queue_event(connection, CLASS_ECON, TIER_INSTANT, netuid, None,
                       "econ:%d" % range_row["id"], payload, now):
            summary["events"]["econ"] = summary["events"].get("econ", 0) + 1


def _emit_econ_gated(connection: sqlite3.Connection, cfg: Dict[str, Any],
                     jcfg: Dict[str, Any], range_row: Dict[str, Any],
                     netuid: int, econ_files: List[str], clone_dir: str,
                     now: str,
                     judge: Optional[Callable[..., Dict[str, Any]]],
                     budget: Optional[Dict[str, int]],
                     summary: Dict[str, Any],
                     git: Optional[Callable[..., Tuple[int, str, str]]]
                     ) -> None:
    """Gate one econ candidate: reuse cached verdict or judge the diff, then
    route. Never raises for judge/diff problems — worst case is `unjudged`."""
    prev_sha, new_sha = range_row["prev_sha"], range_row["new_sha"]
    content_hash = ejudge.econ_content_hash(prev_sha, new_sha, econ_files)
    cached = ejudge.verdict_lookup(connection, content_hash)
    if cached:
        verdict = {"status": ("ok" if cached["significance"]
                              in ejudge.VALID_SIGNIFICANCE else ejudge.UNJUDGED),
                   "significance": cached["significance"],
                   "direction": cached["direction"],
                   "what_changed": cached["what_changed"],
                   "why_it_matters": cached["why_it_matters"],
                   "evidence": cached["evidence"]}
        partial_view = cached["partial_view"]
    else:
        diff_text, partial_view, diff_ok = _fetch_econ_diff(
            clone_dir, prev_sha, new_sha, econ_files,
            jcfg["max_diff_bytes"], git=git)
        if not diff_ok:
            verdict = ejudge._unjudged("diff unavailable")
        elif not _budget_allows(connection, jcfg, budget, now):
            verdict = ejudge._unjudged("judge budget exhausted")
        else:
            active_judge = judge or ejudge.make_default_judge(jcfg)
            verdict = active_judge(diff_text, econ_files,
                                   {"netuid": netuid,
                                    "partial_view": partial_view})
            _budget_consume(connection, budget, now)

    significance = verdict.get("significance") or ejudge.UNJUDGED
    high_stakes = _is_high_stakes(econ_files, jcfg)
    route, break_cooldown = _route_outcome(significance, high_stakes)

    if not cached:
        ejudge.verdict_record(connection, content_hash, netuid,
                              range_row["id"], prev_sha, new_sha, econ_files,
                              verdict, route, partial_view, now)

    if route == "drop":
        summary["events"]["econ-drop"] = (
            summary["events"].get("econ-drop", 0) + 1)
        return

    if route == "digest":
        line = _econ_digest_line(netuid, new_sha, significance, verdict,
                                 high_stakes)
        if queue_digest_line(connection, "econ-digest:%d" % range_row["id"],
                             line, now, netuid=netuid):
            summary["events"]["econ-digest"] = (
                summary["events"].get("econ-digest", 0) + 1)
        return

    # route == "instant": respect cooldown unless the verdict breaks through.
    if not break_cooldown:
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
                    % (netuid, new_sha[:12]), now, netuid=netuid):
                summary["events"]["digest"] = (
                    summary["events"].get("digest", 0) + 1)
            return

    unjudged = significance == ejudge.UNJUDGED
    payload = {"netuid": netuid, "range_id": range_row["id"],
               "prev_sha": prev_sha, "new_sha": new_sha,
               "files": econ_files[:12],
               "commit_count": range_row["commit_count"],
               "commits_truncated": range_row["commits_truncated"],
               "significance": None if unjudged else significance,
               "direction": verdict.get("direction"),
               "what_changed": verdict.get("what_changed"),
               "why_it_matters": verdict.get("why_it_matters"),
               "evidence": None if unjudged else verdict.get("evidence"),
               "partial_view": bool(partial_view),
               "unjudged": unjudged}
    if queue_event(connection, CLASS_ECON, TIER_INSTANT, netuid, None,
                   "econ:%d" % range_row["id"], payload, now):
        key = "econ-unjudged" if unjudged else "econ"
        summary["events"][key] = summary["events"].get(key, 0) + 1


def _econ_digest_line(netuid: int, new_sha: str, significance: str,
                      verdict: Dict[str, Any], high_stakes: bool) -> str:
    what = str(verdict.get("what_changed") or "").strip()
    if high_stakes and significance == "none":
        tail = "high-stakes path · low-signal verdict"
    elif what:
        tail = "minor · %s" % what[:100]
    else:
        tail = "minor incentive-code change"
    return "SN%d incentive-code change %s · %s" % (netuid, new_sha[:12], tail)


def process_range(connection: sqlite3.Connection, cfg: Dict[str, Any],
                  matchers: Sequence[Any], regexes: Sequence[Any],
                  range_row: Dict[str, Any], clone_dir: str, now: str,
                  git: Optional[Callable[..., Tuple[int, str, str]]] = None,
                  judge: Optional[Callable[..., Dict[str, Any]]] = None,
                  budget: Optional[Dict[str, int]] = None
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

    # Econ-code detection: recorded/rebuilt path metadata selects candidates;
    # the gate (when enabled) reads the diff and judges before emitting.
    econ_files = [p for p in paths if is_econ_path(p, cfg)]
    if econ_files:
        jcfg = judge_cfg(cfg)
        if _gate_active(jcfg):
            _emit_econ_gated(connection, cfg, jcfg, range_row, netuid,
                             econ_files, clone_dir, now, judge, budget,
                             summary, git)
        else:
            _emit_econ_legacy(connection, cfg, range_row, netuid, econ_files,
                              now, summary)
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
                git: Optional[Callable[..., Tuple[int, str, str]]] = None,
                judge: Optional[Callable[..., Dict[str, Any]]] = None
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

    # Build the real Hermes judge once per pass when the gate is on and no
    # judge was injected (tests pass a stub). `budget` bounds model calls
    # across the whole pass.
    jcfg = judge_cfg(cfg)
    if judge is None and _gate_active(jcfg):
        judge = ejudge.make_default_judge(jcfg)
    budget: Dict[str, int] = {"run": 0}

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
                                    range_row, clone_dir, now, git=git,
                                    judge=judge, budget=budget)
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
        abs_path = _fleet()._repotrack().contained_file(clone_dir, path)
        if abs_path is None:
            continue  # a link or an out-of-clone path is never read
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


def default_price_fetcher() -> Optional[Dict[str, Any]]:
    """Fleet-wide alpha prices in TAO from the keyless TaoSwap subnets
    operation, THROUGH the live-data layer (contract validation, health
    recording, fail-closed), never a raw HTTP call, plus every netuid's
    `NetworkRegisteredAt` block read from chain in the same pass (change:
    signal-statistics-ties). Returns a snapshot
    {prices, registered, block_number}. None when either read fails
    (fail-soft: measurement never blocks alerting), because a vector without
    its occupant key cannot tell two subnets in one netuid apart."""
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
            if result.get("status") != "ok":
                return None
            registration = al.read_registration_blocks(live_config,
                                                       connection=conn)
        finally:
            conn.close()
        if not registration.get("ok"):
            return None
        subnets = (result.get("values") or {}).get("subnets") or []
        prices = {row["netuid"]: row.get("alpha_price_tao")
                  for row in subnets if row.get("netuid") is not None}
        default = int(registration.get("default_block") or 0)
        registered = {netuid: registration["values"].get(netuid, default)
                      for netuid in prices}
        return {"prices": prices, "registered": registered,
                "block_number": registration.get("block_number")}
    except Exception:  # noqa: BLE001 - fail-soft by contract
        return None


def _normalize_snapshot(fetched: Any) -> Optional[Dict[str, Any]]:
    """A fetcher result as {prices, registered, block_number}. A snapshot
    must carry a registration block for every priced netuid; one that does
    not is refused, never stored without its occupant key."""
    if not isinstance(fetched, dict) or "prices" not in fetched:
        return None
    prices = {int(n): p for n, p in (fetched.get("prices") or {}).items()}
    registered = {int(n): b for n, b in
                  (fetched.get("registered") or {}).items()}
    if any(netuid not in registered for netuid in prices):
        return None
    return {"prices": prices, "registered": registered,
            "block_number": fetched.get("block_number")}


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


def enter_measured_event(connection: sqlite3.Connection, cfg: Dict[str, Any],
                         source_store: str, event_id: int, netuid: int,
                         event_class: str, created_at: str,
                         anchor_at: Optional[str] = None) -> None:
    """Enter one netuid-scoped event into the effectiveness ledger by its
    source triple (change: rotation-signal-gate). Idempotent on re-entry:
    a second call for the same (store, row id, netuid) changes nothing, so
    a store re-read cannot duplicate or reset a filled row.

    `anchor_at` is the moment measurement starts from: the time the event
    could page. It defaults to `created_at`; a gate crossing passes its
    eligibility time (change: signal-statistics-ties). Horizons fall due
    from the anchor, so a crossing entered two days late never fills a
    1-day outcome from its own entry price.

    Measurement is deliberately NOT conditioned on the delivery tier: a
    demoted class keeps filling, which is the only way a demotion can ever
    be reversed on evidence (design D5)."""
    anchor_at = anchor_at or created_at
    connection.execute(
        "INSERT OR IGNORE INTO signal_entries (source_store, event_id, "
        "netuid, source_class, created_at, anchor_at, status) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (source_store, event_id, netuid, event_class, created_at, anchor_at,
         ST_PENDING))
    anchor = _parse_iso(anchor_at)
    for horizon in cfg["outcome_horizons_days"]:
        due = (anchor + datetime.timedelta(days=int(horizon))).isoformat()
        connection.execute(
            "INSERT OR IGNORE INTO signal_outcomes (source_store, event_id, "
            "netuid, source_class, horizon_days, due_at, status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (source_store, event_id, netuid, event_class, int(horizon), due,
             ST_PENDING))


def _ensure_measurement_rows(connection: sqlite3.Connection,
                             cfg: Dict[str, Any]) -> None:
    """Entries (pending) and outcome horizon rows for every fleet-store
    event that lacks them. Idempotent. The `tier` filter here selects
    events rather than digest lines; it is not the delivery tier, which
    lives in the notifier's class registry and never gates measurement."""
    rows = connection.execute(
        "SELECT id, class, created_at FROM signal_events WHERE tier = ?",
        (TIER_INSTANT,)).fetchall()
    for event_id, event_class, created_at in rows:
        for netuid in _instant_members(connection, event_id):
            enter_measured_event(connection, cfg, SOURCE_FLEET, event_id,
                                 netuid, event_class, created_at)


def _livedata_db_path() -> Optional[str]:
    """Resolved path to the livedata store, via livedata's own config,
    never a hardcoded path. None if livedata is not importable."""
    sys.path.insert(0, os.path.join(_REPO_ROOT, "livedata"))
    try:
        import atlas_live as al  # noqa: E402
        return al.resolve(al.load_config()["db"])
    except Exception:  # noqa: BLE001 - fail-soft by contract
        return None


def _open_livedata_ro(db_path: Optional[str]
                      ) -> Optional[sqlite3.Connection]:
    path = db_path if db_path is not None else _livedata_db_path()
    if not path or not os.path.exists(path):
        return None
    try:
        return sqlite3.connect("file:%s?mode=ro" % path, uri=True)
    except sqlite3.Error:
        return None


def _gate_anchor_expr(source: sqlite3.Connection) -> str:
    """SQL for a gate crossing's anchor: the time it became eligible to
    page, or its observation time on a store written before eligibility
    was recorded (change: signal-statistics-ties)."""
    columns = {r[1] for r in source.execute("PRAGMA table_info(gate_events)")}
    if "eligibility_at" in columns:
        return "COALESCE(eligibility_at, observed_at)"
    return "observed_at"


def ingest_livedata_events(connection: sqlite3.Connection,
                           cfg: Dict[str, Any],
                           db_path: Optional[str] = None) -> Dict[str, int]:
    """Enter livedata's netuid-scoped events into the ledger (change:
    rotation-signal-gate). The livedata store is opened STRICTLY read-only:
    measurement never writes to the store that owns the event.

    Gate crossings are entered only once livedata has marked them eligible
    for delivery, so the ledger measures what would actually page and not
    the reversals that never will. They are anchored at their eligibility
    time, the moment the alert could reach the operator. Fail-soft: a
    missing store, a missing table, or an unreadable row leaves the ledger
    untouched and never blocks the pass.

    SEEDS SILENTLY, like every other watermark here. The first sight of a
    class records the store's current high-water row id and enters nothing.
    Backfilling history would be worse than useless: an event from weeks ago
    gets today's price as its entry, and every horizon it already passed
    fills immediately with that same price as the exit, so the ledger fills
    with fabricated near-zero returns for exactly the class the promotion
    decision rests on."""
    entered: Dict[str, int] = {}
    source = _open_livedata_ro(db_path)
    if source is None:
        return entered
    try:
        tables = {row[0] for row in source.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'")}
        for event_class, (table, nid_col, ts_col) in LIVEDATA_MEASURED.items():
            if table not in tables:
                continue
            state_key = "ingest:%s" % event_class
            mark = state_get(connection, state_key)
            try:
                if mark is None:
                    high = source.execute(
                        "SELECT COALESCE(MAX(id), 0) FROM %s" % table
                    ).fetchone()[0]
                    state_set(connection, state_key, str(int(high)))
                    continue  # seeded: history is never entered
                last_id = int(mark)
                where = " WHERE id > ?"
                params: List[Any] = [last_id]
                anchor_expr = ts_col
                if table == "gate_events":
                    if any(r[1] == "eligibility" for r in source.execute(
                            "PRAGMA table_info(gate_events)")):
                        where += " AND eligibility = 'eligible'"
                    anchor_expr = _gate_anchor_expr(source)
                rows = source.execute(
                    "SELECT id, %s, %s, %s FROM %s%s ORDER BY id"
                    % (nid_col, ts_col, anchor_expr, table, where),
                    params).fetchall()
            except (sqlite3.Error, ValueError):
                continue
            count = 0
            for row_id, netuid, observed_at, anchor_at in rows:
                if netuid is None or not observed_at:
                    continue
                before = connection.total_changes
                enter_measured_event(connection, cfg, SOURCE_LIVEDATA,
                                     int(row_id), int(netuid), event_class,
                                     observed_at, anchor_at or observed_at)
                if connection.total_changes > before:
                    count += 1  # a re-scanned row is not a new entry
            # The watermark follows the store's high-water mark, not the
            # last row entered: a crossing still `pending` must not hold the
            # mark back, or every later crossing waits behind it.
            try:
                high = source.execute(
                    "SELECT COALESCE(MAX(id), 0) FROM %s" % table
                ).fetchone()[0]
            except sqlite3.Error:
                high = last_id
            eligible_high = high
            if table == "gate_events":
                # A pending crossing may still become eligible, so the mark
                # stops before the oldest one that has not settled.
                try:
                    unsettled = source.execute(
                        "SELECT MIN(id) FROM gate_events WHERE id > ? AND "
                        "COALESCE(eligibility, 'eligible') = 'pending'",
                        (last_id,)).fetchone()[0]
                except sqlite3.Error:
                    unsettled = None
                if unsettled is not None:
                    eligible_high = int(unsettled) - 1
            if eligible_high > last_id:
                state_set(connection, state_key, str(int(eligible_high)))
            if count:
                entered[event_class] = count
    finally:
        source.close()
    return entered


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


# ---------------------------------------------------------------------------
# The price panel and the one outcome rule (change: signal-statistics-ties)
#
# Every return is read off stored vectors. An entry or exit takes the first
# vector at or after its time, within the late grace; with none there, the
# horizon is unavailable rather than stretched or shortened. Two vectors
# hold one subnet's prices only when they carry the same registration block
# for the netuid: a reused netuid is a different subnet.
# ---------------------------------------------------------------------------

RULES_VERSION = 2
GRACE = datetime.timedelta(hours=LATE_GRACE_HOURS)
# Margin around a registration time read off block anchors.
REG_MARGIN = datetime.timedelta(hours=1)
# Seconds per block, used only to extrapolate past the recorded anchors.
# Measured at 12.015 s over 1,496 panel_snapshot anchors (2026-08-31 to
# 2026-11-03). An assumption outside that range, not a chain fact.
BLOCK_SECONDS_ASSUMED = 12.015

R_NO_VECTOR = "no-vector"
R_NO_PRICE = "no-price"
R_REREGISTERED = "re-registered"
R_UNVERIFIED = "unverified"
ST_UNVERIFIED = "unverified"

# Bootstrap of the median excess return, clustered on event moments.
BOOTSTRAP_DRAWS = 2000
BOOTSTRAP_SEED = 20261103
BOOTSTRAP_MIN_MOMENTS = 10


def _livedata_block_anchors(db_path: Optional[str] = None
                            ) -> List[Tuple[int, datetime.datetime]]:
    """(block, time) pairs from livedata's panel snapshots, read-only.
    Empty on any failure."""
    source = _open_livedata_ro(db_path)
    if source is None:
        return []
    try:
        rows = source.execute(
            "SELECT block_number, MIN(observed_at) FROM panel_snapshot "
            "WHERE block_number IS NOT NULL GROUP BY block_number").fetchall()
    except sqlite3.Error:
        rows = []
    finally:
        source.close()
    out = []
    for block, observed in rows:
        try:
            out.append((int(block), _parse_iso(observed)))
        except (TypeError, ValueError):
            continue
    return out


class PricePanel:
    """Stored price vectors with their occupant keys, loaded once."""

    def __init__(self, connection: sqlite3.Connection,
                 registered_now: Optional[Dict[int, int]] = None,
                 anchors: Any = None) -> None:
        self.rows: Dict[str, Dict[int, Tuple[Optional[float],
                                             Optional[int]]]] = {}
        for ts, netuid, price, reg in connection.execute(
                "SELECT ts, netuid, price_tao, reg_block FROM signal_prices"):
            self.rows.setdefault(ts, {})[int(netuid)] = (price, reg)
        self.times = sorted(self.rows, key=_parse_iso)
        self.parsed = [_parse_iso(ts) for ts in self.times]
        # Block anchors load on first use: a panel whose vectors all carry
        # registration blocks never needs livedata's store.
        self._anchor_source = anchors
        self._own_anchors = [(int(block), _parse_iso(ts)) for ts, block in
                             connection.execute(
                                 "SELECT ts, block_number FROM signal_vectors "
                                 "WHERE block_number IS NOT NULL")]
        self._anchors: Optional[List[Tuple[int, datetime.datetime]]] = None
        self.registered_now = dict(registered_now or {})
        self._baseline_cache: Dict[Tuple[str, str], Optional[float]] = {}

    def vector_at_or_after(self, when: datetime.datetime
                           ) -> Optional[str]:
        import bisect
        index = bisect.bisect_left(self.parsed, when)
        if index < len(self.parsed) and self.parsed[index] <= when + GRACE:
            return self.times[index]
        return None

    def latest_time(self) -> Optional[datetime.datetime]:
        return self.parsed[-1] if self.parsed else None

    def price(self, ts: str, netuid: int) -> Optional[float]:
        return (self.rows.get(ts, {}).get(netuid) or (None, None))[0]

    def reg(self, ts: str, netuid: int) -> Optional[int]:
        return (self.rows.get(ts, {}).get(netuid) or (None, None))[1]

    @property
    def anchors(self) -> List[Tuple[int, datetime.datetime]]:
        if self._anchors is None:
            source = self._anchor_source
            extra = list(source() if callable(source) else (source or []))
            self._anchors = sorted(set(extra + self._own_anchors))
        return self._anchors

    def block_time(self, block: int) -> Optional[datetime.datetime]:
        """Time of a block, interpolated between recorded anchors and
        extrapolated at BLOCK_SECONDS_ASSUMED beyond them."""
        if not self.anchors:
            return None
        import bisect
        blocks = [b for b, _t in self.anchors]
        index = bisect.bisect_left(blocks, block)
        if index < len(blocks) and blocks[index] == block:
            return self.anchors[index][1]
        if 0 < index < len(blocks):
            (b0, t0), (b1, t1) = self.anchors[index - 1], self.anchors[index]
            fraction = (block - b0) / float(b1 - b0)
            return t0 + (t1 - t0) * fraction
        ref_block, ref_time = (self.anchors[0] if index == 0
                               else self.anchors[-1])
        return ref_time + datetime.timedelta(
            seconds=(block - ref_block) * BLOCK_SECONDS_ASSUMED)

    def same_subnet(self, netuid: int, entry_ts: str, exit_ts: str
                    ) -> Optional[str]:
        """None when both vectors hold one subnet's price for the netuid,
        else the reason they may not."""
        reg0, reg1 = self.reg(entry_ts, netuid), self.reg(exit_ts, netuid)
        if reg0 is not None and reg1 is not None:
            return None if reg0 == reg1 else R_REREGISTERED
        # An older vector carries no occupant key: judge it from a later
        # registration block, at the exit or, failing that, today's.
        reference = reg1 if reg1 is not None else self.registered_now.get(
            netuid)
        if reference is None:
            return R_UNVERIFIED
        if reference == 0:
            return None  # registered at genesis: never re-registered
        registered_at = self.block_time(reference)
        if registered_at is None:
            return R_UNVERIFIED
        start, end = _parse_iso(entry_ts), _parse_iso(exit_ts)
        if registered_at <= start - REG_MARGIN:
            return None
        if registered_at <= end + REG_MARGIN:
            return R_REREGISTERED
        return R_UNVERIFIED

    def baseline(self, entry_ts: str, exit_ts: str) -> Optional[float]:
        """Fleet-median return over the window, counting only netuids that
        hold one subnet across it."""
        key = (entry_ts, exit_ts)
        if key not in self._baseline_cache:
            returns = []
            exit_row = self.rows.get(exit_ts, {})
            for netuid, (entry, _reg) in self.rows.get(entry_ts, {}).items():
                exit_price = (exit_row.get(netuid) or (None, None))[0]
                if not entry or not exit_price:
                    continue
                if self.same_subnet(netuid, entry_ts, exit_ts) is not None:
                    continue
                returns.append((exit_price / entry - 1.0) * 100.0)
            self._baseline_cache[key] = (statistics.median(returns)
                                         if returns else None)
        return self._baseline_cache[key]


def evaluate_entry(panel: PricePanel, netuid: int, anchor_at: str,
                   now: datetime.datetime) -> Optional[Dict[str, Any]]:
    """The entry for one netuid, or None while it can still fill."""
    anchor = _parse_iso(anchor_at)
    entry_ts = panel.vector_at_or_after(anchor)
    if entry_ts is None:
        if now <= anchor + GRACE:
            return None
        return {"status": ST_UNAVAILABLE, "reason": R_NO_VECTOR}
    price = panel.price(entry_ts, netuid)
    if not price:
        return {"status": ST_UNAVAILABLE, "reason": R_NO_PRICE,
                "entry_ts": entry_ts}
    return {"status": ST_RECORDED, "reason": None, "entry_ts": entry_ts,
            "price": price, "reg_block": panel.reg(entry_ts, netuid)}


def evaluate_outcome(panel: PricePanel, netuid: int, anchor_at: str,
                     horizon_days: int, now: datetime.datetime
                     ) -> Optional[Dict[str, Any]]:
    """One outcome under the current rules, or None while it can still
    fill. Used by the live fill and by `rescore`, so both read the same
    way."""
    entry = evaluate_entry(panel, netuid, anchor_at, now)
    if entry is None:
        return None
    if entry["status"] != ST_RECORDED:
        return {"status": entry["status"], "reason": entry["reason"],
                "entry_ts": entry.get("entry_ts")}
    due = _parse_iso(anchor_at) + datetime.timedelta(days=int(horizon_days))
    if now < due:
        return None
    exit_ts = panel.vector_at_or_after(due)
    if exit_ts is None:
        if now <= due + GRACE:
            return None
        return {"status": ST_UNAVAILABLE, "reason": R_NO_VECTOR,
                "entry_ts": entry["entry_ts"]}
    exit_price = panel.price(exit_ts, netuid)
    base = {"entry_ts": entry["entry_ts"], "exit_ts": exit_ts}
    if not exit_price:
        return dict(base, status=ST_UNAVAILABLE, reason=R_NO_PRICE)
    reason = panel.same_subnet(netuid, entry["entry_ts"], exit_ts)
    if reason is not None:
        return dict(base, reason=reason,
                    status=(ST_UNVERIFIED if reason == R_UNVERIFIED
                            else ST_UNAVAILABLE))
    return_pct = (exit_price / entry["price"] - 1.0) * 100.0
    baseline = panel.baseline(entry["entry_ts"], exit_ts)
    return dict(base, status=ST_RECORDED, reason=None,
                exit_price=exit_price, return_pct=return_pct,
                baseline_pct=baseline,
                excess_pct=(None if baseline is None
                            else return_pct - baseline))


def _write_v2(connection: sqlite3.Connection, outcome_id: int,
              result: Dict[str, Any]) -> None:
    connection.execute(
        "UPDATE signal_outcomes SET v2_status = ?, v2_reason = ?, "
        "v2_entry_ts = ?, v2_exit_ts = ?, v2_return_pct = ?, "
        "v2_baseline_pct = ?, v2_excess_pct = ?, v2_rules = ? WHERE id = ?",
        (result["status"], result.get("reason"), result.get("entry_ts"),
         result.get("exit_ts"), result.get("return_pct"),
         result.get("baseline_pct"), result.get("excess_pct"),
         RULES_VERSION, outcome_id))


def _store_snapshot(connection: sqlite3.Connection, now: str,
                    snapshot: Dict[str, Any]) -> None:
    registered = snapshot["registered"]
    connection.executemany(
        "INSERT OR IGNORE INTO signal_prices (ts, netuid, price_tao, "
        "reg_block) VALUES (?, ?, ?, ?)",
        [(now, netuid, price, registered.get(netuid))
         for netuid, price in snapshot["prices"].items()])
    connection.execute(
        "INSERT OR IGNORE INTO signal_vectors (ts, block_number) "
        "VALUES (?, ?)", (now, snapshot.get("block_number")))


def _latest_registration(connection: sqlite3.Connection
                         ) -> Dict[int, int]:
    """The newest stored vector's registration blocks."""
    row = connection.execute(
        "SELECT MAX(ts) FROM signal_prices WHERE reg_block IS NOT NULL"
    ).fetchone()
    if not row or row[0] is None:
        return {}
    return {int(n): int(b) for n, b in connection.execute(
        "SELECT netuid, reg_block FROM signal_prices WHERE ts = ? AND "
        "reg_block IS NOT NULL", (row[0],))}


def run_measurement(connection: sqlite3.Connection, config: Dict[str, Any],
                    now: Optional[str] = None,
                    price_fetcher: Optional[Callable[[], Any]] = None,
                    anchors: Any = None) -> Dict[str, Any]:
    """One measurement step: ensure entry/outcome rows exist, fetch the
    fleet price snapshot AT MOST ONCE (and only when something needs it),
    then settle every pending entry and due outcome from the stored vectors
    under the one outcome rule, and prune old vectors. A failed fetch stores
    nothing; rows still inside their grace wait for a later pass, and rows
    past it are marked unavailable. Measurement never blocks alerting."""
    cfg = signals_cfg(config)
    now = now or _utc_now()
    _ensure_measurement_rows(connection, cfg)
    ingested = ingest_livedata_events(connection, cfg)
    # Gate crossings entered before eligibility anchors existed move onto
    # them before anything is scored (idempotent; livedata read-only).
    reanchored = _reanchor_gate_crossings(connection, cfg)
    summary = {"fetched": False, "entries_filled": 0, "outcomes_filled": 0,
               "unavailable": 0}
    if reanchored:
        summary["reanchored"] = reanchored
    if ingested:
        summary["ingested"] = ingested
    if not _measurement_needed(connection, now):
        connection.commit()
        return summary

    fetcher = price_fetcher or default_price_fetcher
    snapshot = _normalize_snapshot(fetcher())
    if snapshot is None:
        summary["fetch_failed"] = True
    else:
        summary["fetched"] = True
        _store_snapshot(connection, now, snapshot)

    now_dt = _parse_iso(now)
    panel = PricePanel(connection,
                       registered_now=_latest_registration(connection),
                       anchors=(anchors if anchors is not None
                                else _livedata_block_anchors))

    # Entries: the first vector at or after the anchor, within the grace.
    entry_rows = connection.execute(
        "SELECT source_store, event_id, netuid, "
        "COALESCE(anchor_at, created_at) FROM signal_entries "
        "WHERE status = ?", (ST_PENDING,)).fetchall()
    for source_store, event_id, netuid, anchor_at in entry_rows:
        if not anchor_at:
            continue
        entry = evaluate_entry(panel, netuid, anchor_at, now_dt)
        if entry is None:
            continue
        connection.execute(
            "UPDATE signal_entries SET price_tao = ?, as_of = ?, status = ?, "
            "entry_ts = ?, reg_block = ?, reason = ? WHERE source_store = ? "
            "AND event_id = ? AND netuid = ?",
            (entry.get("price"), entry.get("entry_ts"), entry["status"],
             entry.get("entry_ts"), entry.get("reg_block"),
             entry.get("reason"), source_store, event_id, netuid))
        if entry["status"] == ST_RECORDED:
            summary["entries_filled"] += 1
        else:
            summary["unavailable"] += 1

    # Outcomes: due rows, settled by the same rule rescore applies.
    due_rows = connection.execute(
        "SELECT o.id, o.netuid, o.horizon_days, "
        "COALESCE(en.anchor_at, en.created_at) FROM signal_outcomes o "
        "JOIN signal_entries en ON en.source_store = o.source_store "
        "AND en.event_id = o.event_id AND en.netuid = o.netuid "
        "WHERE o.status = ? AND o.due_at <= ?",
        (ST_PENDING, now)).fetchall()
    for outcome_id, netuid, horizon, anchor_at in due_rows:
        if not anchor_at:
            continue
        result = evaluate_outcome(panel, netuid, anchor_at, horizon, now_dt)
        if result is None:
            continue
        connection.execute(
            "UPDATE signal_outcomes SET exit_price_tao = ?, return_pct = ?, "
            "baseline_return_pct = ?, status = ?, filled_at = ? WHERE id = ?",
            (result.get("exit_price"), result.get("return_pct"),
             result.get("baseline_pct"),
             (ST_UNAVAILABLE if result["status"] == ST_UNVERIFIED
              else result["status"]), now, outcome_id))
        _write_v2(connection, outcome_id, result)
        if result["status"] == ST_RECORDED:
            summary["outcomes_filled"] += 1
        else:
            summary["unavailable"] += 1

    # Rows settled under the old rules get their current-rules score once a
    # vector with registration blocks exists to judge them by. Only the
    # v2 columns are written; `rescore` does the same on demand.
    if panel.registered_now:
        summary["scored"] = _score_unscored(connection, panel, now_dt)

    # Retention: never below the longest horizon plus a week of slack.
    horizon_floor = max([int(h) for h in cfg["outcome_horizons_days"]]
                        or [30]) + 7
    keep_days = max(int(cfg["price_retention_days"]), horizon_floor)
    cutoff = (now_dt - datetime.timedelta(days=keep_days)).isoformat()
    connection.execute("DELETE FROM signal_prices WHERE ts < ?", (cutoff,))
    connection.execute("DELETE FROM signal_vectors WHERE ts < ?", (cutoff,))
    connection.commit()
    return summary


def _score_unscored(connection: sqlite3.Connection, panel: PricePanel,
                    now: datetime.datetime, everything: bool = False) -> int:
    """Write current-rules scores (v2 columns only) for settled outcomes.
    `everything` rescores rows that already have a score too."""
    where = "o.status != ?" + ("" if everything else " AND o.v2_rules IS NULL")
    rows = connection.execute(
        "SELECT o.id, o.netuid, o.horizon_days, "
        "COALESCE(en.anchor_at, en.created_at) FROM signal_outcomes o "
        "JOIN signal_entries en ON en.source_store = o.source_store "
        "AND en.event_id = o.event_id AND en.netuid = o.netuid WHERE "
        + where, (ST_PENDING,)).fetchall()
    scored = 0
    for outcome_id, netuid, horizon, anchor_at in rows:
        if not anchor_at:
            continue
        result = evaluate_outcome(panel, netuid, anchor_at, horizon, now)
        if result is None:
            continue  # its re-anchored window has not closed yet
        _write_v2(connection, outcome_id, result)
        scored += 1
    return scored


def _reanchor_gate_crossings(connection: sqlite3.Connection,
                             cfg: Dict[str, Any],
                             db_path: Optional[str] = None) -> int:
    """Move gate-crossing entries entered before this change onto their
    eligibility anchor, and the due times of their still-pending horizons
    with them. Settled rows keep their stored values; their current-rules
    score reads the anchor. The livedata store is read-only."""
    source = _open_livedata_ro(db_path)
    if source is None:
        return 0
    try:
        anchors = dict(source.execute(
            "SELECT id, %s FROM gate_events" % _gate_anchor_expr(source)))
    except sqlite3.Error:
        anchors = {}
    finally:
        source.close()
    moved = 0
    rows = connection.execute(
        "SELECT event_id, netuid, anchor_at FROM signal_entries WHERE "
        "source_store = ? AND source_class = 'gate-crossing'",
        (SOURCE_LIVEDATA,)).fetchall()
    for event_id, netuid, anchor_at in rows:
        target = anchors.get(event_id)
        if not target or anchor_at == target:
            continue
        connection.execute(
            "UPDATE signal_entries SET anchor_at = ? WHERE source_store = ? "
            "AND event_id = ? AND netuid = ?",
            (target, SOURCE_LIVEDATA, event_id, netuid))
        for horizon in cfg["outcome_horizons_days"]:
            due = (_parse_iso(target)
                   + datetime.timedelta(days=int(horizon))).isoformat()
            connection.execute(
                "UPDATE signal_outcomes SET due_at = ? WHERE source_store = ? "
                "AND event_id = ? AND netuid = ? AND horizon_days = ? "
                "AND status = ?", (due, SOURCE_LIVEDATA, event_id, netuid,
                                   int(horizon), ST_PENDING))
        moved += 1
    return moved


def _registration_now(config: Dict[str, Any]) -> Dict[int, int]:
    """Today's registration block per netuid, read from chain."""
    sys.path.insert(0, os.path.join(_REPO_ROOT, "livedata"))
    import atlas_live as al  # noqa: E402
    read = al.read_registration_blocks(al.load_config())
    if not read.get("ok"):
        raise RuntimeError("registration read failed: %s"
                           % read.get("error"))
    return read["values"]


def rescore(connection: sqlite3.Connection, config: Dict[str, Any],
            now: Optional[str] = None,
            registered_now: Optional[Dict[int, int]] = None,
            livedata_path: Optional[str] = None,
            anchors: Any = None) -> Dict[str, Any]:
    """Recompute every settled outcome under the current rules into the v2
    columns (change: signal-statistics-ties). The original return,
    baseline and status columns are never written. Idempotent: the same
    vectors and registration map give the same scores. Needs today's
    registration map from chain to judge vectors stored before occupant
    keys existed; fails rather than guessing when that read fails."""
    cfg = signals_cfg(config)
    now_dt = _parse_iso(now or _utc_now())
    registered_now = (registered_now if registered_now is not None
                      else _registration_now(config))
    moved = _reanchor_gate_crossings(connection, cfg, livedata_path)
    panel = PricePanel(
        connection, registered_now=registered_now,
        anchors=(anchors if anchors is not None
                 else (lambda: _livedata_block_anchors(livedata_path))))
    scored = _score_unscored(connection, panel, now_dt, everything=True)
    connection.commit()
    states = {row[0] or "unscored": row[1] for row in connection.execute(
        "SELECT v2_status, COUNT(*) FROM signal_outcomes WHERE status != ? "
        "GROUP BY v2_status", (ST_PENDING,))}
    return {"reanchored_gate_entries": moved, "scored": scored,
            "v2_states": states, "rules_version": RULES_VERSION}


# ---------------------------------------------------------------------------
# The inline pass (reconcile hook) — seed epochs, extract, measure
# ---------------------------------------------------------------------------


def run_pass(connection: sqlite3.Connection, config: Dict[str, Any],
             now: Optional[str] = None,
             git: Optional[Callable[..., Tuple[int, str, str]]] = None,
             price_fetcher: Optional[Callable[
                 [], Optional[Dict[int, Optional[float]]]]] = None,
             judge: Optional[Callable[..., Dict[str, Any]]] = None
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
               "extract": run_extract(connection, config, now=now, git=git,
                                      judge=judge),
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


def delivery_tiers() -> Dict[str, str]:
    """The notifier's class tier registry, read strictly read-only for
    REPORTING (change: rotation-signal-gate). Measurement never depends on
    it: a class absent here is reported as `unregistered` and is still
    measured. Fail-soft — an unreadable notifier config yields no tiers
    rather than an error."""
    path = os.path.join(_REPO_ROOT, "telegram", "config.json")
    try:
        with open(path, "r", encoding="utf-8") as handle:
            classes = (json.load(handle).get("classes") or {})
    except Exception:  # noqa: BLE001 — fail-soft by contract
        return {}
    return {name: spec.get("tier") for name, spec in classes.items()
            if isinstance(spec, dict) and spec.get("tier")}


def _percentile(ordered: Sequence[float], q: float) -> float:
    """Nearest-rank percentile of an ascending list."""
    index = min(len(ordered) - 1, max(0, int(round(q * (len(ordered) - 1)))))
    return ordered[index]


def clustered_median_interval(clusters: Dict[str, List[float]],
                              draws: int = BOOTSTRAP_DRAWS,
                              seed: int = BOOTSTRAP_SEED
                              ) -> Optional[Tuple[float, float]]:
    """95% interval for the median of the pooled values, resampling whole
    clusters (event moments) with replacement. Outcomes entered against one
    price vector share one market window, so they are not independent
    draws. Deterministic for a given seed. None below the minimum cluster
    count."""
    keys = sorted(clusters)
    if len(keys) < BOOTSTRAP_MIN_MOMENTS:
        return None
    import random
    rng = random.Random(seed)
    medians = []
    for _ in range(draws):
        pooled: List[float] = []
        for _k in keys:
            pooled.extend(clusters[keys[rng.randrange(len(keys))]])
        medians.append(statistics.median(pooled))
    medians.sort()
    return _percentile(medians, 0.025), _percentile(medians, 0.975)


def effectiveness(connection: sqlite3.Connection,
                  config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Per alert class x horizon (change: signal-statistics-ties): the
    median paired excess return over the fleet baseline, its interval from a
    bootstrap over event moments, the class and baseline medians, and the
    counts behind them. Read-only measurement: ranks nothing, recommends
    nothing.

    Reads only outcomes settled under the current rules (`v2_*`). A settled
    row without them is counted as unscored until `rescore` runs. The floor
    counts distinct event moments, not rows: every outcome entered against
    one price vector shares one market window. A horizon whose pending
    outcomes outnumber its filled ones is marked unreadable."""
    cfg = signals_cfg(config or {})
    tiers = delivery_tiers()
    min_events = int(cfg["min_filled_for_promotion"])
    promo_horizon = int(cfg["promotion_horizon_days"])
    rows = connection.execute(
        "SELECT COALESCE(o.source_class, ev.class, 'unknown'), "
        "o.horizon_days, o.status, o.v2_rules, o.v2_status, o.v2_reason, "
        "o.v2_entry_ts, o.v2_return_pct, o.v2_baseline_pct, o.v2_excess_pct "
        "FROM signal_outcomes o "
        "LEFT JOIN signal_events ev "
        "ON ev.id = o.event_id AND o.source_store = 'fleet'").fetchall()
    buckets: Dict[Tuple[str, int], Dict[str, Any]] = {}
    for (event_class, horizon, status, rules, v2_status, reason, moment,
         ret, base, excess) in rows:
        bucket = buckets.setdefault((event_class, horizon), {
            "returns": [], "baselines": [], "clusters": {}, "pending": 0,
            "unavailable": 0, "reasons": {}, "unverified": 0,
            "unscored": 0, "filled": 0})
        if status == ST_PENDING:
            bucket["pending"] += 1
        elif rules != RULES_VERSION:
            bucket["unscored"] += 1
        elif v2_status == ST_RECORDED:
            bucket["filled"] += 1
            if ret is not None:
                bucket["returns"].append(ret)
            if base is not None:
                bucket["baselines"].append(base)
            if excess is not None:
                bucket["clusters"].setdefault(moment or "", []).append(
                    excess)
        elif v2_status == ST_UNVERIFIED:
            bucket["unverified"] += 1
        else:
            bucket["unavailable"] += 1
            key = reason or "unknown"
            bucket["reasons"][key] = bucket["reasons"].get(key, 0) + 1

    def r3(value: Optional[float]) -> Optional[float]:
        return None if value is None else round(value, 3)

    report = []
    for (event_class, horizon), bucket in sorted(buckets.items()):
        readable = bucket["filled"] >= bucket["pending"]
        excess = [v for vals in bucket["clusters"].values() for v in vals]
        interval = clustered_median_interval(bucket["clusters"])
        entry = {
            "class": event_class, "horizon_days": horizon,
            "tier": tiers.get(event_class, "unregistered"),
            "filled": bucket["filled"],
            "events": len(bucket["clusters"]),
            "pending": bucket["pending"],
            "unavailable": bucket["unavailable"],
            "unavailable_reasons": bucket["reasons"],
            "unverified": bucket["unverified"],
            "unscored": bucket["unscored"],
            "readable": readable,
            "median_return_pct": r3(statistics.median(bucket["returns"])
                                    if bucket["returns"] else None),
            "median_baseline_pct": r3(statistics.median(bucket["baselines"])
                                      if bucket["baselines"] else None),
            "median_excess_pct": r3(statistics.median(excess)
                                    if excess else None),
            "excess_ci95": ([r3(interval[0]), r3(interval[1])]
                            if interval else None),
        }
        if horizon == promo_horizon:
            meets = entry["events"] >= min_events and readable
            entry["meets_promotion_sample"] = meets
            entry["min_events_for_promotion"] = min_events
            entry["beats_baseline"] = bool(
                meets and interval is not None and interval[0] > 0)
        report.append(entry)
    return {"report": report,
            "min_events_for_promotion": min_events,
            "promotion_horizon_days": promo_horizon,
            "bootstrap": {"draws": BOOTSTRAP_DRAWS, "seed": BOOTSTRAP_SEED,
                          "min_events": BOOTSTRAP_MIN_MOMENTS,
                          "cluster": "entry price vector"},
            "note": "measurement only: median paired excess return over the "
                    "fleet baseline across identical windows, with a 95% "
                    "interval from a bootstrap over event moments; no "
                    "recommendation derived. beats_baseline needs the "
                    "promotion floor in distinct events and an interval "
                    "lower bound above zero. A horizon with readable false "
                    "has more pending than filled outcomes and cannot "
                    "justify a tier change."}


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
        "econ_gate": _econ_gate_status(connection),
        "watchlist_invalid": json.loads(invalid) if invalid else [],
    }


def _econ_gate_status(connection: sqlite3.Connection) -> Dict[str, Any]:
    """Verdict counters for the intelligence gate: how many candidates were
    alerted / digested / dropped / left unjudged, plus today's model-call
    tally. Reads the audit table so dropped changes stay visible."""
    verdicts = {row[0]: row[1] for row in connection.execute(
        "SELECT outcome, COUNT(*) FROM signal_econ_verdicts GROUP BY outcome")}
    calls_today = state_get(connection, _judge_day_key(_utc_now()))
    return {"verdicts": verdicts,
            "calls_today": int(calls_today) if calls_today else 0}


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
    sub.add_parser("effectiveness", help="per-class x horizon report: "
                                         "median excess over the fleet "
                                         "baseline with a 95%% interval "
                                         "(read-only)")
    sub.add_parser("rescore", help="recompute settled outcomes under the "
                                   "current rules into the v2 columns "
                                   "(writes the fleet store; back it up "
                                   "first)")
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
                result = effectiveness(connection, config)
            elif args.command == "rescore":
                try:
                    result = rescore(connection, config)
                except RuntimeError as exc:
                    print("fatal: %s" % exc, file=sys.stderr)
                    return 2
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
