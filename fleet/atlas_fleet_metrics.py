#!/usr/bin/env python3
"""Atlas fleet-rotation-metrics — a rotation cockpit over the subnet-repo
fleet (change: fleet-rotation-metrics).

Turns data already on disk into standing, epoch-scoped rotation metrics,
each traceable to evidence and each degrading honestly rather than
guessing:

- Emission-redirect map: per (netuid, epoch) routing entries
  (burn/partner/treasury/owner/royalty — fraction where a literal is
  parseable, destination hotkey where present) scanned from the slot's
  reward/weight/scoring code paths with file:line evidence; a subnet whose
  economics load from a remote URL at runtime is flagged `opaque` instead
  of having numbers invented. Recomputed only when a slot's head sha moves.
- Repo-activity: epoch-scoped default-branch commit/author counts over
  trailing windows (all-time totals kept as context only, excluded from
  ranking so upstream fork history cannot inflate a subnet), plus a branch
  pulse — `git ls-remote` tip churn between passes — so a live subnet whose
  work happens off the default branch is not mistaken for abandoned.
- Momentum and percentile ranks: alpha-price momentum reused from the
  signals module's accumulating `signal_prices` vectors (no new API call,
  no backfill; missing history or a re-registered netuid renders n/a), and
  activity/momentum percentile ranks with averaged ties. The
  accumulate/fade quadrant was dropped (change: signal-statistics-ties).

Invariants inherited from the fleet: read-only over clones, never builds
or executes subnet code, additive tables in the shared fleet store (the
reconcile and signals schemas are untouched), per-subnet fail-closed (one
bad slot is recorded and skipped, never a pass failure), and every scanned
input is treated as untrusted (length/route caps).

Public surface (consumed by the reconcile inline hook and the CLI):

- ensure_schema(conn)                       — create the metric tables
- run_pass(conn, config, …)                 — branch tips + activity + emissions
- record_branch_tips(conn, config, …)       — per-slot ls-remote tip snapshot
- run_activity(conn, config, …)             — windowed epoch-scoped activity
- run_emissions(conn, config, …)            — sha-gated emission-map scan
- report(conn, config, …)                   — combined ranked JSON view
- metrics_status(conn)                       — coverage + failure summary

The LAN dashboard render/serve (proposal §dashboard) is intentionally not
part of this module yet — `report()` is the machine-readable surface a
renderer would consume.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import sqlite3
import sys
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_MODULE_DIR)

METRICS_VERSION = "0.1.0"

# Emission-scan outcomes (per slot, recorded in metric_emission_scan).
OUT_OK = "ok"
OUT_UNCHANGED = "unchanged"
OUT_TRUNCATED = "truncated"
OUT_FAILED = "failed"
OUT_NO_SURFACE = "no-surface"

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS metric_emission_routes (
    id INTEGER PRIMARY KEY,
    netuid INTEGER NOT NULL,
    epoch INTEGER NOT NULL,
    sha TEXT NOT NULL,
    kind TEXT NOT NULL,
    symbol TEXT,
    fraction REAL,
    dest_hotkey TEXT,
    file TEXT NOT NULL,
    line INTEGER NOT NULL,
    scanned_at TEXT NOT NULL,
    UNIQUE (netuid, epoch, kind, symbol, file)
);
CREATE TABLE IF NOT EXISTS metric_emission_scan (
    netuid INTEGER PRIMARY KEY,
    epoch INTEGER NOT NULL,
    sha TEXT,
    opaque INTEGER NOT NULL DEFAULT 0,
    truncated INTEGER NOT NULL DEFAULT 0,
    routes INTEGER NOT NULL DEFAULT 0,
    outcome TEXT NOT NULL,
    scanned_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS metric_activity (
    netuid INTEGER NOT NULL,
    epoch INTEGER NOT NULL,
    pass_ts TEXT NOT NULL,
    c7 INTEGER, c30 INTEGER, c90 INTEGER,
    a30 INTEGER,
    last_commit_at TEXT,
    days_since INTEGER,
    total_commits INTEGER,
    total_authors INTEGER,
    PRIMARY KEY (netuid, epoch, pass_ts)
);
CREATE TABLE IF NOT EXISTS metric_activity_repos (
    netuid INTEGER NOT NULL,
    epoch INTEGER NOT NULL,
    pass_ts TEXT NOT NULL,
    repo TEXT NOT NULL,
    c30 INTEGER,
    last_commit_at TEXT,
    PRIMARY KEY (netuid, epoch, pass_ts, repo)
);
CREATE TABLE IF NOT EXISTS metric_branch_tips (
    netuid INTEGER NOT NULL,
    epoch INTEGER NOT NULL,
    pass_ts TEXT NOT NULL,
    tips_json TEXT NOT NULL,
    tips_count INTEGER NOT NULL,
    changed_tips INTEGER,
    PRIMARY KEY (netuid, epoch, pass_ts)
);
CREATE TABLE IF NOT EXISTS metric_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

# ---------------------------------------------------------------------------
# Config — code defaults merged under fleet/config.json's `metrics` block.
# ---------------------------------------------------------------------------

DEFAULT_METRICS_CFG: Dict[str, Any] = {
    "enabled": True,
    # Emission scan surface: a file is scanned when its lowercased path
    # contains any of these tokens (reward/weight/scoring/emission code).
    # Vendored/test/docs/example paths are excluded everywhere.
    "econ_path_tokens": ["reward", "incentive", "scoring", "score",
                         "emission", "weight", "set_weights", "payout",
                         "mechanism", "burn"],
    "scan_extensions": [".py"],
    "exclude_path_parts": ["vendor", "node_modules", "test", "tests",
                           "docs", "doc", "examples", "example", ".github"],
    # Route families: a symbol assigned on a line is a candidate route when
    # its normalized name (lowercased, non-alnum stripped) contains a
    # keyword. Keywords are kept tight — over-broad ones ("reserve", "grant")
    # matched incidental variables (federal_reserve, improvement_grant) on
    # the real fleet and were dropped.
    "route_families": {
        "burn": ["burn"],
        "partner": ["partner"],
        "royalty": ["royalty", "commission", "kickback"],
        "treasury": ["treasury", "devfund", "devwallet", "teamwallet"],
        "owner": ["ownertake", "ownercut", "ownershare", "ownerfee",
                  "ownerpct", "ownerpercent"],
    },
    # A candidate becomes a recorded route only when it also looks like a
    # PROPORTION (its name carries one of these tokens) OR it carries a
    # parseable fraction OR a destination hotkey. This drops the flood of
    # incidental family-word variables (is_burn, burn_uid, burned_epochs)
    # that are code mentioning a concept, not an emission split.
    "proportion_tokens": ["fraction", "share", "pct", "percent", "ratio",
                          "take", "cut", "split", "alloc"],
    # Runtime-remote-config vocabulary; co-occurring with economic vocab in
    # the same file flags the subnet opaque (values live off-chain).
    "opacity_tokens": ["remote_config", "remoteconfig", "fetch_config",
                       "config_url", "dynamic_config", "remote_weights"],
    "route_cap_per_subnet": 40,
    "symbol_max_length": 60,
    "max_scan_files_per_slot": 400,
    "max_file_bytes": 262144,
    # Activity windows (days) and the ls-remote ref cap for branch pulse.
    "activity_windows": [7, 30, 90],
    "ls_remote_ref_cap": 200,
    "ls_remote_timeout": 45,
    # Momentum windows (days) computed from signal_prices; no new API call.
    "momentum_windows": [7, 30],
    # Author addresses that are automation, not development (change:
    # signal-statistics-ties). Case-insensitive regexes on the author email;
    # matching commits are left out of windowed counts, a30 and
    # days-since-last-commit. All-time totals stay unfiltered context.
    "bot_author_patterns": [r"\[bot\]@", r"^(github-)?actions?@github\.com$",
                            r"^(dependabot|renovate)"],
    # GitHub orgs to drop from the team-concentration view (placeholders).
    "placeholder_orgs": ["deprecated", "orgs", "username", "user",
                         "example", "your-org", "owner"],
}


def metrics_cfg(config: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(DEFAULT_METRICS_CFG)
    for key, value in (config.get("metrics") or {}).items():
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


# Combined (organisation-wide) activity columns, added to an existing
# store in place (change: fleet-multi-repo-activity). `single_why` records
# why a subnet kept one repository; null means its organisation was read.
_ACTIVITY_ALL_COLUMNS = (
    ("c7_all", "INTEGER"), ("c30_all", "INTEGER"), ("c90_all", "INTEGER"),
    ("a30_all", "INTEGER"), ("last_commit_at_all", "TEXT"),
    ("days_since_all", "INTEGER"), ("repos_counted", "INTEGER"),
    ("single_why", "TEXT"),
)


def ensure_schema(connection: sqlite3.Connection) -> None:
    """Create the metric tables if absent. Owns only its own tables — the
    reconcile and signals schemas are never touched."""
    connection.executescript(SCHEMA_SQL)
    have = {row[1] for row in connection.execute(
        "PRAGMA table_info(metric_activity)")}
    for name, kind in _ACTIVITY_ALL_COLUMNS:
        if name not in have:
            connection.execute("ALTER TABLE metric_activity ADD COLUMN "
                               "%s %s" % (name, kind))
    connection.commit()


def state_get(connection: sqlite3.Connection, key: str) -> Optional[str]:
    row = connection.execute(
        "SELECT value FROM metric_state WHERE key = ?", (key,)).fetchone()
    return row[0] if row else None


def state_set(connection: sqlite3.Connection, key: str, value: str) -> None:
    connection.execute(
        "INSERT INTO metric_state (key, value) VALUES (?, ?) "
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


_ORGREPOS: Any = None


def _orgrepos() -> Any:
    """Lazy import of the organisation-repository module."""
    global _ORGREPOS
    if _ORGREPOS is None:
        sys.path.insert(0, _MODULE_DIR)
        import atlas_fleet_orgrepos  # noqa: E402
        _ORGREPOS = atlas_fleet_orgrepos
    return _ORGREPOS


# ---------------------------------------------------------------------------
# Scan surface — pure path predicates (unit-testable, no git)
# ---------------------------------------------------------------------------


def _path_excluded(path: str, cfg: Dict[str, Any]) -> bool:
    parts = {part.lower() for part in path.split("/")}
    return bool(parts & {p.lower() for p in cfg["exclude_path_parts"]})


def is_econ_scan_file(path: str, cfg: Dict[str, Any]) -> bool:
    """A file on the emission scan surface: right extension, an econ token
    in its path, and not under an excluded directory."""
    if _path_excluded(path, cfg):
        return False
    name = path.rsplit("/", 1)[-1]
    if not any(name.endswith(ext) for ext in cfg["scan_extensions"]):
        return False
    lowered = path.lower()
    return any(token in lowered for token in cfg["econ_path_tokens"])


# ---------------------------------------------------------------------------
# Emission-redirect extraction — line-based, evidence-linked, never executes
# ---------------------------------------------------------------------------

# An assignment line: `SYMBOL = …`, `SYMBOL: type = …`, or `"KEY": …`.
_ASSIGN_RE = re.compile(
    r"""^\s*(?:['"]?)([A-Za-z_][A-Za-z0-9_]{1,59})(?:['"]?)\s*(?::[^=]+)?[=:]""")
_SS58_RE = re.compile(r"5[1-9A-HJ-NP-Za-km-z]{47}")
# A LONE fraction literal in [0, 1] as the whole right-hand side (allowing a
# trailing comment and a trailing comma). An arithmetic expression such as
# `1.0 - PARTNER_FRACTION` is deliberately NOT matched — its stray literal is
# not the route's value, so the fraction stays unparsed (rendered "?").
_LONE_FRACTION_RE = re.compile(
    r"^\s*(0?\.\d+|1\.0+|0\.0+|0|1)\s*,?\s*(?:#.*)?$")


def _normalize_symbol(symbol: str) -> str:
    return re.sub(r"[^a-z0-9]", "", symbol.lower())


def classify_symbol(symbol: str, cfg: Dict[str, Any]) -> Optional[str]:
    """The route family a symbol belongs to, or None. First family whose
    keyword is a substring of the normalized symbol wins (families ordered
    by specificity in config)."""
    norm = _normalize_symbol(symbol)
    for kind, keywords in cfg["route_families"].items():
        if any(keyword in norm for keyword in keywords):
            return kind
    return None


def _parse_fraction(rhs: str) -> Optional[float]:
    """A fraction in [0, 1] when the assignment's right-hand side is a lone
    literal, else None. An expression (`1.0 - PARTNER_FRACTION`), a call, or
    a bare integer other than 0/1 is ambiguous and left unparsed so the map
    never fabricates a value."""
    match = _LONE_FRACTION_RE.match(rhs)
    if not match:
        return None
    try:
        value = float(match.group(1))
    except ValueError:
        return None
    return value if 0.0 <= value <= 1.0 else None


def extract_routes_from_lines(path: str, lines: Sequence[str],
                              cfg: Dict[str, Any]
                              ) -> List[Dict[str, Any]]:
    """Emission routes from one file's lines. One route per matching
    assignment; a docstring/comment mention of a symbol is not an
    assignment and never matches, so mentions collapse into the assignment.
    De-duplicated to one row per (kind, symbol) within the file."""
    routes: List[Dict[str, Any]] = []
    seen: set = set()
    for index, line in enumerate(lines, start=1):
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue
        assign = _ASSIGN_RE.match(line)
        if not assign:
            continue
        symbol = assign.group(1)
        if len(symbol) > cfg["symbol_max_length"]:
            continue
        kind = classify_symbol(symbol, cfg)
        if kind is None:
            continue
        key = (kind, symbol)
        if key in seen:
            continue
        rhs = line[assign.end():]
        fraction = _parse_fraction(rhs)
        hotkey_match = _SS58_RE.search(line)
        dest_hotkey = hotkey_match.group(0) if hotkey_match else None
        # A candidate qualifies only if it looks like a proportion, or it
        # carries a fraction literal or a destination hotkey — otherwise it
        # is an incidental family-word variable, not an emission split.
        norm = _normalize_symbol(symbol)
        proportion = any(tok in norm for tok in cfg.get("proportion_tokens", ()))
        if not (proportion or fraction is not None or dest_hotkey):
            continue
        seen.add(key)
        routes.append({
            "kind": kind, "symbol": symbol, "file": path, "line": index,
            "fraction": fraction, "dest_hotkey": dest_hotkey,
        })
    return routes


def file_is_opaque(text: str, cfg: Dict[str, Any]) -> bool:
    """True when a file couples remote-config vocabulary with economic
    vocabulary — its economics load at runtime and cannot be read here."""
    lowered = text.lower()
    if not any(token in lowered for token in cfg["opacity_tokens"]):
        return False
    return any(token in lowered for token in cfg["econ_path_tokens"])


def _tracked_econ_files(clone_dir: str, cfg: Dict[str, Any],
                        git: Callable[..., Tuple[int, str, str]]
                        ) -> List[str]:
    code, out, err = git(clone_dir, ["ls-tree", "-r", "--name-only", "HEAD"])
    if code != 0:
        raise RuntimeError("ls-tree failed: %s" % err.strip()[:200])
    return [line.strip() for line in out.splitlines()
            if line.strip() and is_econ_scan_file(line.strip(), cfg)]


def scan_clone_emissions(clone_dir: str, cfg: Dict[str, Any],
                         git: Optional[Callable[..., Tuple[int, str, str]]] = None
                         ) -> Dict[str, Any]:
    """Scan one clone's econ-surface files for routes + opacity. Reads only
    already-local files, never executes. Returns
    {routes, opaque, truncated, files_scanned}."""
    git = git or _fleet()._run_git
    paths = _tracked_econ_files(clone_dir, cfg, git)
    truncated = False
    if len(paths) > cfg["max_scan_files_per_slot"]:
        paths = paths[:cfg["max_scan_files_per_slot"]]
        truncated = True
    routes: List[Dict[str, Any]] = []
    opaque = False
    for path in paths:
        abs_path = _fleet()._repotrack().contained_file(clone_dir, path)
        if abs_path is None:
            continue  # a link or an out-of-clone path is never read
        try:
            size = os.path.getsize(abs_path)
            if size > cfg["max_file_bytes"]:
                continue
            with open(abs_path, "r", encoding="utf-8",
                      errors="replace") as handle:
                text = handle.read()
        except OSError:
            continue  # blobless miss / deleted locally: skip the file
        if file_is_opaque(text, cfg):
            opaque = True
        routes.extend(extract_routes_from_lines(path, text.splitlines(), cfg))
    if len(routes) > cfg["route_cap_per_subnet"]:
        routes = routes[:cfg["route_cap_per_subnet"]]
        truncated = True
    return {"routes": routes, "opaque": opaque, "truncated": truncated,
            "files_scanned": len(paths)}


def _store_emission_scan(connection: sqlite3.Connection, netuid: int,
                         epoch: int, sha: Optional[str], outcome: str,
                         opaque: bool, truncated: bool, routes: int,
                         now: str) -> None:
    connection.execute(
        "INSERT INTO metric_emission_scan (netuid, epoch, sha, opaque, "
        "truncated, routes, outcome, scanned_at) VALUES (?, ?, ?, ?, ?, ?, "
        "?, ?) ON CONFLICT(netuid) DO UPDATE SET epoch=excluded.epoch, "
        "sha=excluded.sha, opaque=excluded.opaque, truncated=excluded."
        "truncated, routes=excluded.routes, outcome=excluded.outcome, "
        "scanned_at=excluded.scanned_at",
        (netuid, epoch, sha, 1 if opaque else 0, 1 if truncated else 0,
         routes, outcome, now))


def run_emissions(connection: sqlite3.Connection, config: Dict[str, Any],
                  netuid: Optional[int] = None, now: Optional[str] = None,
                  git: Optional[Callable[..., Tuple[int, str, str]]] = None
                  ) -> Dict[str, Any]:
    """Scan the emission map for every active slot whose head sha moved
    since its last scan (cold start scans all). Per-slot fail-closed —
    a slot's scan failure is recorded and skipped, never a pass failure."""
    cfg = metrics_cfg(config)
    now = now or _utc_now()
    fleet = _fleet()
    clone_root = config.get("clone_root") or fleet.DEFAULT_CLONE_ROOT
    slots = ([fleet.get_slot(connection, netuid)] if netuid is not None
             else fleet.all_slots(connection))
    summary = {"scanned": 0, "unchanged": 0, "failed": 0, "no-surface": 0,
               "opaque": 0, "routes": 0}
    for slot in slots:
        if not slot or slot.get("status") != "active":
            continue
        nid = slot["netuid"]
        epoch = slot.get("epoch") or 1
        sha = slot.get("local_sha")
        prior = connection.execute(
            "SELECT sha FROM metric_emission_scan WHERE netuid = ?",
            (nid,)).fetchone()
        if prior and prior[0] == sha and sha is not None:
            summary["unchanged"] += 1
            continue
        clone_dir = os.path.join(clone_root, str(nid))
        try:
            outcome = scan_clone_emissions(clone_dir, cfg, git=git)
        except Exception as exc:  # noqa: BLE001 — per-slot fail-closed
            connection.rollback()
            _store_emission_scan(connection, nid, epoch, sha, OUT_FAILED,
                                 False, False, 0, now)
            connection.commit()
            summary["failed"] += 1
            continue
        # Replace this slot's routes with the fresh scan (the latest scan
        # is the map; an old route removed upstream must disappear).
        connection.execute(
            "DELETE FROM metric_emission_routes WHERE netuid = ?", (nid,))
        for route in outcome["routes"]:
            connection.execute(
                "INSERT OR IGNORE INTO metric_emission_routes (netuid, epoch, "
                "sha, kind, symbol, fraction, dest_hotkey, file, line, "
                "scanned_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (nid, epoch, sha, route["kind"], route["symbol"],
                 route["fraction"], route["dest_hotkey"], route["file"],
                 route["line"], now))
        n_routes = len(outcome["routes"])
        result = (OUT_NO_SURFACE if (n_routes == 0 and not outcome["opaque"])
                  else OUT_TRUNCATED if outcome["truncated"] else OUT_OK)
        _store_emission_scan(connection, nid, epoch, sha, result,
                             outcome["opaque"], outcome["truncated"],
                             n_routes, now)
        connection.commit()
        summary["scanned"] += 1
        summary["routes"] += n_routes
        if outcome["opaque"]:
            summary["opaque"] += 1
        if result == OUT_NO_SURFACE:
            summary["no-surface"] += 1
    return summary


# ---------------------------------------------------------------------------
# Repo-activity — epoch-scoped windows + all-time context, one git call/slot
# ---------------------------------------------------------------------------


def _commit_log(clone_dir: str,
                git: Callable[..., Tuple[int, str, str]]
                ) -> List[Tuple[datetime.datetime, str]]:
    """(committer_datetime, author_email) for every commit on HEAD, one
    git call. Raises RuntimeError on git failure."""
    code, out, err = git(clone_dir, ["log", "--no-merges",
                                     "--format=%cI%x09%ae"])
    if code != 0:
        raise RuntimeError("git log failed: %s" % err.strip()[:200])
    rows: List[Tuple[datetime.datetime, str]] = []
    for line in out.splitlines():
        if "\t" not in line:
            continue
        when, email = line.split("\t", 1)
        try:
            rows.append((_parse_iso(when.strip()), email.strip()))
        except ValueError:
            continue
    return rows


def _commit_log_ids(clone_dir: str,
                    git: Callable[..., Tuple[int, str, str]]
                    ) -> List[Tuple[str, datetime.datetime, str]]:
    """(sha, committer time, author email) for every non-merge commit on
    HEAD. The commit id lets commits from several repositories be counted
    once (change: fleet-multi-repo-activity)."""
    code, out, err = git(clone_dir, ["log", "--no-merges",
                                     "--format=%H%x09%cI%x09%ae"])
    if code != 0:
        raise RuntimeError("git log failed: %s" % err.strip()[:200])
    return _orgrepos().parse_log(out)


def union_commits(logs: Sequence[Sequence[Tuple[str, datetime.datetime,
                                                str]]]
                  ) -> List[Tuple[datetime.datetime, str]]:
    """Merge commit logs, each commit id counted once. The first log wins
    for a repeated id, so the on-chain repository goes first."""
    seen: Dict[str, Tuple[datetime.datetime, str]] = {}
    for log in logs:
        for sha, when, email in log:
            if sha not in seen:
                seen[sha] = (when, email)
    return list(seen.values())


def compile_bot_patterns(patterns: Sequence[str]) -> List[Any]:
    """Compiled bot-author patterns; an invalid pattern is skipped."""
    compiled = []
    for pattern in patterns or ():
        try:
            compiled.append(re.compile(pattern, re.IGNORECASE))
        except re.error:
            continue
    return compiled


def is_bot_author(email: str, patterns: Sequence[Any]) -> bool:
    return any(p.search(email or "") for p in patterns)


def compute_activity(commits: Sequence[Tuple[datetime.datetime, str]],
                     windows: Sequence[int], now: datetime.datetime,
                     bot_patterns: Sequence[Any] = ()
                     ) -> Dict[str, Any]:
    """Windowed commit counts + 30d author count + all-time context from a
    commit log. All-time totals are context only, never ranking inputs.
    Commits by a bot or CI author address (`bot_patterns`) are not
    development activity: they are left out of the windows, the author
    count and the last-commit date (change: signal-statistics-ties)."""
    counts = {w: 0 for w in windows}
    authors_30: set = set()
    human = [(when, email) for when, email in commits
             if not is_bot_author(email, bot_patterns)]
    for when, email in human:
        age_days = (now - when).total_seconds() / 86400.0
        for w in windows:
            if age_days <= w:
                counts[w] += 1
        if age_days <= 30:
            authors_30.add(email)
    last = max((when for when, _ in human), default=None)
    days_since = (int((now - last).total_seconds() // 86400)
                  if last is not None else None)
    return {
        "windows": counts,
        "a30": len(authors_30),
        "last_commit_at": last.isoformat() if last is not None else None,
        "days_since": days_since,
        "total_commits": len(commits),
        "total_authors": len({email for _, email in commits}),
    }


def run_activity(connection: sqlite3.Connection, config: Dict[str, Any],
                 pass_ts: Optional[str] = None, netuid: Optional[int] = None,
                 git: Optional[Callable[..., Tuple[int, str, str]]] = None
                 ) -> Dict[str, Any]:
    """Record windowed epoch-scoped activity for every active slot. Per-slot
    fail-closed. Unless `activity.multi_repo` is `off`, the combined
    figures over the organisation's counted repositories are recorded
    beside the single-repository ones (change: fleet-multi-repo-activity).
    """
    cfg = metrics_cfg(config)
    pass_ts = pass_ts or _utc_now()
    now = _parse_iso(pass_ts)
    windows = cfg["activity_windows"]
    bots = compile_bot_patterns(cfg.get("bot_author_patterns") or [])
    fleet = _fleet()
    org = _orgrepos()
    clone_root = config.get("clone_root") or fleet.DEFAULT_CLONE_ROOT
    git = git or fleet._run_git
    all_slots = fleet.all_slots(connection)
    slots = ([fleet.get_slot(connection, netuid)] if netuid is not None
             else all_slots)
    combine = org.mode(config) != org.MODE_OFF
    if combine:
        org.ensure_schema(connection)
        plans = org.plan(connection, config, all_slots, now=pass_ts)
    summary = {"recorded": 0, "failed": 0, "combined": 0}
    for slot in slots:
        if not slot or slot.get("status") != "active":
            continue
        nid = slot["netuid"]
        epoch = slot.get("epoch") or 1
        clone_dir = os.path.join(clone_root, str(nid))
        try:
            commits = _commit_log(clone_dir, git)
            act = compute_activity(commits, windows, now, bots)
        except Exception:  # noqa: BLE001 — per-slot fail-closed
            connection.rollback()
            summary["failed"] += 1
            continue
        connection.execute(
            "INSERT OR REPLACE INTO metric_activity (netuid, epoch, pass_ts, "
            "c7, c30, c90, a30, last_commit_at, days_since, total_commits, "
            "total_authors) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (nid, epoch, pass_ts, act["windows"].get(7), act["windows"].get(30),
             act["windows"].get(90), act["a30"], act["last_commit_at"],
             act["days_since"], act["total_commits"], act["total_authors"]))
        if combine:
            try:
                _record_combined(connection, config, plans.get(nid) or {},
                                 nid, epoch, pass_ts, clone_dir, git,
                                 windows, now, bots)
                summary["combined"] += 1
            except Exception:  # noqa: BLE001 (single figures still land)
                connection.execute(
                    "UPDATE metric_activity SET single_why = ? WHERE "
                    "netuid = ? AND epoch = ? AND pass_ts = ?",
                    ("combine-failed", nid, epoch, pass_ts))
        connection.commit()
        summary["recorded"] += 1
    if combine:
        cutoff = (now - datetime.timedelta(days=30)).isoformat()
        connection.execute("DELETE FROM metric_activity_repos WHERE "
                           "pass_ts < ?", (cutoff,))
        connection.commit()
    return summary


def _record_combined(connection: sqlite3.Connection, config: Dict[str, Any],
                     plan: Dict[str, Any], nid: int, epoch: int,
                     pass_ts: str, clone_dir: str,
                     git: Callable[..., Tuple[int, str, str]],
                     windows: Sequence[int], now: datetime.datetime,
                     bots: Sequence[Any]) -> None:
    """Combined figures for one slot: the on-chain log plus every counted
    history repository, by commit id. A history whose log cannot be read
    is left out and named in `single_why` only when none is counted."""
    org = _orgrepos()
    fleet = _fleet()
    clone_root = config.get("clone_root") or fleet.DEFAULT_CLONE_ROOT
    onchain = plan.get("onchain") or "SN%d" % nid
    logs = [(onchain, _commit_log_ids(clone_dir, git))]
    why = plan.get("why")
    if not why:
        counted, dropped = org.counted_repos(connection, config,
                                             plan.get("repos") or [])
        for repo in counted:
            try:
                logs.append((repo, org.history_log(clone_root, repo, git)))
            except RuntimeError:
                continue
        if len(logs) == 1 and (plan.get("repos") or []):
            why = "no-history"
        elif len(logs) == 1:
            why = "no-sibling"
    act = compute_activity(union_commits([log for _, log in logs]),
                           windows, now, bots)
    connection.execute(
        "UPDATE metric_activity SET c7_all = ?, c30_all = ?, c90_all = ?, "
        "a30_all = ?, last_commit_at_all = ?, days_since_all = ?, "
        "repos_counted = ?, single_why = ? WHERE netuid = ? AND epoch = ? "
        "AND pass_ts = ?",
        (act["windows"].get(7), act["windows"].get(30),
         act["windows"].get(90), act["a30"], act["last_commit_at"],
         act["days_since"], len(logs), why, nid, epoch, pass_ts))
    for repo, log in logs:
        one = compute_activity([(w, e) for _, w, e in log], windows, now,
                               bots)
        connection.execute(
            "INSERT OR REPLACE INTO metric_activity_repos (netuid, epoch, "
            "pass_ts, repo, c30, last_commit_at) VALUES (?, ?, ?, ?, ?, ?)",
            (nid, epoch, pass_ts, repo, one["windows"].get(30),
             one["last_commit_at"]))


def activity_commit_log(connection: sqlite3.Connection,
                        config: Dict[str, Any], netuid: int,
                        pass_ts: str,
                        git: Optional[Callable[..., Tuple[int, str, str]]]
                        = None) -> List[Tuple[datetime.datetime, str]]:
    """(when, email) commits behind the figures the board shows for one
    subnet's pass: the on-chain log, plus the repositories that pass
    counted when `activity.multi_repo` is `on`. The site export bins
    these, so its bins match the shown c7/c30."""
    fleet = _fleet()
    org = _orgrepos()
    git = git or fleet._run_git
    clone_root = config.get("clone_root") or fleet.DEFAULT_CLONE_ROOT
    clone_dir = os.path.join(clone_root, str(netuid))
    if org.mode(config) != org.MODE_ON or not _has_combined(
            connection, netuid, pass_ts):
        return _commit_log(clone_dir, git)
    logs = [_commit_log_ids(clone_dir, git)]
    rows = connection.execute(
        "SELECT repo FROM metric_activity_repos WHERE netuid = ? AND "
        "pass_ts = ? ORDER BY repo", (netuid, pass_ts)).fetchall()
    slot_repo = org.owner_repo((fleet.get_slot(connection, netuid) or {})
                               .get("github_repo"))
    onchain = ("%s/%s" % slot_repo) if slot_repo else None
    for (repo,) in rows:
        if "/" not in repo or repo == onchain:
            continue
        try:
            logs.append(org.history_log(clone_root, repo, git))
        except RuntimeError:
            continue
    return union_commits(logs)


def _has_combined(connection: sqlite3.Connection, netuid: int,
                  pass_ts: str) -> bool:
    have = {r[1] for r in connection.execute(
        "PRAGMA table_info(metric_activity)")}
    if "c30_all" not in have:
        return False
    row = connection.execute(
        "SELECT c30_all FROM metric_activity WHERE netuid = ? AND "
        "pass_ts = ?", (netuid, pass_ts)).fetchone()
    return bool(row) and row[0] is not None


# ---------------------------------------------------------------------------
# Branch pulse — ls-remote tip snapshot (recorded within the reconcile pass)
# ---------------------------------------------------------------------------

_LS_REMOTE_RE = re.compile(r"^([0-9a-f]{40})\s+refs/heads/(.+)$")


def _parse_ls_remote(out: str, cap: int) -> Dict[str, str]:
    """`ref -> sha` map from `git ls-remote --heads` output, capped."""
    tips: Dict[str, str] = {}
    for line in out.splitlines():
        match = _LS_REMOTE_RE.match(line.strip())
        if match:
            tips[match.group(2)] = match.group(1)
            if len(tips) >= cap:
                break
    return tips


def diff_tips(prev: Dict[str, str], current: Dict[str, str]) -> int:
    """Count of refs added, removed, or moved between two tip snapshots."""
    changed = 0
    for ref, sha in current.items():
        if prev.get(ref) != sha:
            changed += 1
    for ref in prev:
        if ref not in current:
            changed += 1
    return changed


def record_branch_tips(connection: sqlite3.Connection, config: Dict[str, Any],
                       pass_ts: Optional[str] = None,
                       token: Optional[str] = None,
                       git: Optional[Callable[..., Tuple[int, str, str]]] = None
                       ) -> Dict[str, Any]:
    """For each active slot, record a bounded `git ls-remote --heads` tip
    snapshot and its `changed_tips` vs the slot's previous snapshot. No
    fetch, no checkout, no dating. Per-slot fail-closed and non-blocking:
    an ls-remote failure records nothing for that slot."""
    cfg = metrics_cfg(config)
    pass_ts = pass_ts or _utc_now()
    fleet = _fleet()
    clone_root = config.get("clone_root") or fleet.DEFAULT_CLONE_ROOT
    git = git or fleet._run_git
    cap = cfg["ls_remote_ref_cap"]
    timeout = cfg["ls_remote_timeout"]
    summary = {"recorded": 0, "failed": 0, "churned": 0}
    for slot in fleet.all_slots(connection):
        if slot.get("status") != "active":
            continue
        nid = slot["netuid"]
        epoch = slot.get("epoch") or 1
        clone_dir = os.path.join(clone_root, str(nid))
        try:
            code, out, _err = git(clone_dir, ["ls-remote", "--heads", "origin"],
                                  token=token, timeout=timeout)
        except TypeError:
            # Injected test git without token/timeout kwargs.
            code, out, _err = git(clone_dir, ["ls-remote", "--heads", "origin"])
        if code != 0:
            summary["failed"] += 1
            continue
        tips = _parse_ls_remote(out, cap)
        prior = connection.execute(
            "SELECT tips_json FROM metric_branch_tips WHERE netuid = ? AND "
            "epoch = ? ORDER BY pass_ts DESC LIMIT 1", (nid, epoch)).fetchone()
        changed = (diff_tips(json.loads(prior[0]), tips)
                   if prior is not None else None)
        connection.execute(
            "INSERT OR REPLACE INTO metric_branch_tips (netuid, epoch, "
            "pass_ts, tips_json, tips_count, changed_tips) VALUES "
            "(?, ?, ?, ?, ?, ?)",
            (nid, epoch, pass_ts, json.dumps(tips, sort_keys=True), len(tips),
             changed))
        connection.commit()
        summary["recorded"] += 1
        if changed:
            summary["churned"] += 1
    return summary


# ---------------------------------------------------------------------------
# Momentum (from signal_prices) + percentile ranks, read-time, no writes
# ---------------------------------------------------------------------------


def _price_series(connection: sqlite3.Connection
                  ) -> Dict[int, List[Tuple[str, float]]]:
    """netuid -> [(ts, price)] ascending, from the signals price panel.
    Empty when the signals module has not accrued any prices yet."""
    series: Dict[int, List[Tuple[str, float]]] = {}
    try:
        rows = connection.execute(
            "SELECT netuid, ts, price_tao FROM signal_prices "
            "WHERE price_tao IS NOT NULL ORDER BY ts ASC").fetchall()
    except sqlite3.Error:
        return series
    for netuid, ts, price in rows:
        series.setdefault(netuid, []).append((ts, price))
    return series


def _occupant_judge(connection: sqlite3.Connection
                    ) -> Optional[Callable[[int, str, str], Optional[str]]]:
    """The signals ledger's same-subnet test over stored vectors (change:
    signal-statistics-ties), or None while no stored vector carries a
    registration block yet (nothing to judge by)."""
    try:
        has_reg = connection.execute(
            "SELECT 1 FROM signal_prices WHERE reg_block IS NOT NULL LIMIT 1"
        ).fetchone()
    except sqlite3.Error:
        return None
    if not has_reg:
        return None
    sys.path.insert(0, _MODULE_DIR)
    import atlas_fleet_signals as sig  # noqa: E402
    panel = sig.PricePanel(
        connection, registered_now=sig._latest_registration(connection),
        anchors=sig._livedata_block_anchors)
    return panel.same_subnet


def _window_return(points: Sequence[Tuple[str, float]], window_days: int,
                   now: datetime.datetime,
                   judge: Optional[Callable[[str, str], Optional[str]]] = None
                   ) -> Optional[float]:
    """Percent change from the oldest in-window point to the latest, or
    None when fewer than two points fall inside the window, or when `judge`
    says the two points belong to different subnets (a reused netuid)."""
    cutoff = now - datetime.timedelta(days=window_days)
    inside = [(ts, price) for ts, price in points
              if _parse_iso(ts) >= cutoff]
    if len(inside) < 2:
        return None
    if judge is not None and judge(inside[0][0], inside[-1][0]) is not None:
        return None
    entry = inside[0][1]
    latest = inside[-1][1]
    if not entry:
        return None
    return (latest / entry - 1.0) * 100.0


def _median(values: Sequence[float]) -> Optional[float]:
    ordered = sorted(values)
    if not ordered:
        return None
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def _percentile_ranks(values: Dict[int, float]) -> Dict[int, float]:
    """Fractional percentile rank (0..1) of each netuid's value among the
    non-null set. Ties share the average of the ranks they occupy, so a
    subnet's rank never depends on its netuid or on input order (change:
    signal-statistics-ties; before it, ties followed netuid order)."""
    if not values:
        return {}
    ordered = sorted(values.values())
    n = len(ordered)
    first: Dict[float, int] = {}
    last: Dict[float, int] = {}
    for index, value in enumerate(ordered):
        first.setdefault(value, index)
        last[value] = index
    return {netuid: ((first[value] + last[value]) / 2.0 + 0.5) / n
            for netuid, value in values.items()}


def compute_momentum(connection: sqlite3.Connection, cfg: Dict[str, Any],
                     now: Optional[datetime.datetime] = None
                     ) -> Dict[str, Any]:
    """Per-subnet and fleet-median momentum over each configured window,
    reusing stored price vectors. Missing history yields None (n/a), and so
    does a window whose ends belong to different subnets in one netuid; the
    fleet median leaves those out."""
    now = now or datetime.datetime.now(tz=datetime.timezone.utc)
    series = _price_series(connection)
    same_subnet = _occupant_judge(connection)
    per_subnet: Dict[int, Dict[int, Optional[float]]] = {}
    baseline: Dict[int, Optional[float]] = {}
    for window in cfg["momentum_windows"]:
        returns: Dict[int, float] = {}
        for netuid, points in series.items():
            judge = (None if same_subnet is None else
                     (lambda a, b, n=netuid: same_subnet(n, a, b)))
            value = _window_return(points, window, now, judge)
            per_subnet.setdefault(netuid, {})[window] = value
            if value is not None:
                returns[netuid] = value
        baseline[window] = _median(list(returns.values()))
    return {"per_subnet": per_subnet, "baseline": baseline,
            "windows": list(cfg["momentum_windows"])}


# ---------------------------------------------------------------------------
# Combined report — the machine-readable rotation view (feeds a dashboard)
# ---------------------------------------------------------------------------


def _github_org(github_repo: Optional[str]) -> Optional[str]:
    if not github_repo or "github.com/" not in github_repo:
        return None
    tail = github_repo.split("github.com/", 1)[1].strip("/")
    parts = tail.split("/")
    return parts[0].lower() if parts and parts[0] else None


def _latest_activity(connection: sqlite3.Connection,
                     config: Optional[Dict[str, Any]] = None
                     ) -> Dict[int, Dict[str, Any]]:
    """Latest pass per subnet, with the figure set the board uses."""
    use_all = (config is not None
               and _orgrepos().mode(config) == _orgrepos().MODE_ON)
    # A read-only reader can meet a store the pass has not migrated yet.
    have = {row[1] for row in connection.execute(
        "PRAGMA table_info(metric_activity)")}
    combined = ("c7_all, c30_all, c90_all, a30_all, days_since_all"
                if "days_since_all" in have
                else "NULL, NULL, NULL, NULL, NULL")
    rows = connection.execute(
        "SELECT netuid, epoch, c7, c30, c90, a30, days_since, total_commits, "
        "total_authors, %s FROM metric_activity WHERE (netuid, pass_ts) IN "
        "(SELECT netuid, MAX(pass_ts) FROM metric_activity GROUP BY netuid)"
        % combined).fetchall()
    out: Dict[int, Dict[str, Any]] = {}
    for row in rows:
        out[row[0]] = select_figures(row, use_all)
    return out


def select_figures(row: Sequence[Any], use_all: bool) -> Dict[str, Any]:
    """The one switch between single-repository and combined figures
    (change: fleet-multi-repo-activity). `row` is (netuid, epoch, c7, c30,
    c90, a30, days_since, total_commits, total_authors, c7_all, c30_all,
    c90_all, a30_all, days_since_all). Combined figures are used only when
    switched on and present for that pass; otherwise the single ones."""
    (_nid, epoch, c7, c30, c90, a30, days_since, tc, ta,
     c7a, c30a, c90a, a30a, daysa) = row
    if use_all and c30a is not None:
        c7, c30, c90, a30, days_since = c7a, c30a, c90a, a30a, daysa
    return {"epoch": epoch, "c7": c7, "c30": c30, "c90": c90,
            "a30": a30, "days_since": days_since,
            "total_commits": tc, "total_authors": ta}


def _latest_branch_pulse(connection: sqlite3.Connection) -> Dict[int, Any]:
    rows = connection.execute(
        "SELECT netuid, changed_tips, tips_count FROM metric_branch_tips "
        "WHERE (netuid, pass_ts) IN (SELECT netuid, MAX(pass_ts) FROM "
        "metric_branch_tips GROUP BY netuid)").fetchall()
    return {nid: {"changed_tips": changed, "tips_count": count}
            for nid, changed, count in rows}


def _emission_map(connection: sqlite3.Connection) -> Dict[int, Dict[str, Any]]:
    scans = {row[0]: {"opaque": bool(row[1]), "truncated": bool(row[2]),
                      "outcome": row[3]}
             for row in connection.execute(
                 "SELECT netuid, opaque, truncated, outcome "
                 "FROM metric_emission_scan")}
    out: Dict[int, Dict[str, Any]] = {}
    for nid, meta in scans.items():
        routes = [{"kind": k, "symbol": s, "fraction": f, "dest_hotkey": d,
                   "file": fl, "line": ln}
                  for (k, s, f, d, fl, ln) in connection.execute(
                      "SELECT kind, symbol, fraction, dest_hotkey, file, line "
                      "FROM metric_emission_routes WHERE netuid = ? "
                      "ORDER BY kind, symbol", (nid,))]
        redirect_upper = sum(r["fraction"] for r in routes
                             if r["fraction"] is not None
                             and r["kind"] != "burn")
        out[nid] = {"opaque": meta["opaque"], "truncated": meta["truncated"],
                    "outcome": meta["outcome"], "routes": routes,
                    "redirect_fraction_upper_bound": round(redirect_upper, 4)}
    return out


def _classify_activity(act: Optional[Dict[str, Any]],
                       pulse: Optional[Dict[str, Any]]) -> str:
    """Fold windowed default-branch activity and branch pulse into a label.
    The branch-pulse rule is what keeps a live off-default subnet off the
    fade list (proposal: the chutes/computehorde correction)."""
    c30 = (act or {}).get("c30") or 0
    days_since = (act or {}).get("days_since")
    changed = (pulse or {}).get("changed_tips")
    if c30 > 0:
        return "active"
    if changed:
        return "active-non-default"
    if days_since is not None and days_since > 90:
        return "fade-eligible"
    return "idle"


def report(connection: sqlite3.Connection, config: Dict[str, Any],
           now: Optional[datetime.datetime] = None) -> Dict[str, Any]:
    """Combined ranked rotation view: per-subnet activity, branch pulse,
    momentum, emission summary, org; plus percentile ranks, the
    team-concentration groups, and the invisible-fleet tier. Read-only —
    ranks evidence, recommends nothing."""
    cfg = metrics_cfg(config)
    now = now or datetime.datetime.now(tz=datetime.timezone.utc)
    fleet = _fleet()
    slots = fleet.all_slots(connection)
    activity = _latest_activity(connection, config)
    pulse = _latest_branch_pulse(connection)
    emissions = _emission_map(connection)
    momentum = compute_momentum(connection, cfg, now=now)
    mom_7 = {nid: w.get(7) for nid, w in momentum["per_subnet"].items()
             if w.get(7) is not None}
    act_score = {nid: (a.get("c30") or 0)
                 + (pulse.get(nid, {}).get("changed_tips") or 0)
                 for nid, a in activity.items()}
    mom_ranks = _percentile_ranks(mom_7)
    act_ranks = _percentile_ranks(act_score)

    rows: List[Dict[str, Any]] = []
    invisible: List[Dict[str, Any]] = []
    org_members: Dict[str, List[int]] = {}
    for slot in slots:
        nid = slot["netuid"]
        status = slot.get("status")
        org = _github_org(slot.get("github_repo"))
        if status == "active" and org and org not in cfg["placeholder_orgs"]:
            org_members.setdefault(org, []).append(nid)
        if status != "active":
            invisible.append({
                "netuid": nid, "status": status,
                "github_repo": slot.get("github_repo"),
                "reason": "placeholder-url" if (
                    slot.get("github_repo") and status == "unreachable")
                    else status})
            continue
        act = activity.get(nid)
        pul = pulse.get(nid)
        emap = emissions.get(nid, {})
        rows.append({
            "netuid": nid, "epoch": slot.get("epoch"), "org": org,
            "activity_class": _classify_activity(act, pul),
            "c7": (act or {}).get("c7"), "c30": (act or {}).get("c30"),
            "c90": (act or {}).get("c90"), "a30": (act or {}).get("a30"),
            "days_since": (act or {}).get("days_since"),
            "changed_tips": (pul or {}).get("changed_tips"),
            "tips_count": (pul or {}).get("tips_count"),
            "total_commits_context": (act or {}).get("total_commits"),
            "total_authors_context": (act or {}).get("total_authors"),
            "momentum_7d": momentum["per_subnet"].get(nid, {}).get(7),
            "momentum_30d": momentum["per_subnet"].get(nid, {}).get(30),
            "activity_pct": round(act_ranks[nid], 4) if nid in act_ranks
                            else None,
            "momentum_pct": round(mom_ranks[nid], 4) if nid in mom_ranks
                            else None,
            "emission_opaque": emap.get("opaque", False),
            "emission_routes": len(emap.get("routes", [])),
            "redirect_fraction_upper_bound": emap.get(
                "redirect_fraction_upper_bound", 0.0),
        })
    rows.sort(key=lambda r: (r["activity_pct"] is None, -(r["activity_pct"]
                             or 0.0)))
    concentration = sorted(
        [{"org": org, "netuids": sorted(members), "count": len(members)}
         for org, members in org_members.items() if len(members) > 1],
        key=lambda g: (-g["count"], g["org"]))
    return {
        "generated_at": now.isoformat(),
        "subnets": rows,
        "emission_detail": emissions,
        "team_concentration": concentration,
        "invisible_fleet": sorted(invisible, key=lambda s: s["netuid"]),
        "momentum_baseline": {str(w): momentum["baseline"].get(w)
                              for w in momentum["windows"]},
        "price_history_present": bool(mom_7),
        "note": "read-only rotation evidence — no recommendation derived; "
                "momentum n/a until price history accrues",
    }


# ---------------------------------------------------------------------------
# The inline pass (reconcile hook) — branch tips, activity, emissions
# ---------------------------------------------------------------------------


def run_pass(connection: sqlite3.Connection, config: Dict[str, Any],
             now: Optional[str] = None, token: Optional[str] = None,
             git: Optional[Callable[..., Tuple[int, str, str]]] = None
             ) -> Dict[str, Any]:
    """The metrics step, invoked inline after signals in the hourly fleet
    pass. Records branch tips (one cheap ls-remote per active slot), then
    windowed activity, then the sha-gated emission scan. Honors the
    `metrics.enabled` kill-switch."""
    cfg = metrics_cfg(config)
    now = now or _utc_now()
    ensure_schema(connection)
    if not cfg.get("enabled", True):
        return {"disabled": True}
    if state_get(connection, "installed_at") is None:
        state_set(connection, "installed_at", now)
        connection.commit()
    summary: Dict[str, Any] = {
        "branch_tips": record_branch_tips(connection, config, pass_ts=now,
                                          token=token, git=git)}
    # Organisation listings and history fetches (change:
    # fleet-multi-repo-activity). Fail-isolated: a GitHub or git failure
    # leaves single-repository activity untouched.
    try:
        summary["org_repos"] = _orgrepos().run(connection, config, now=now,
                                               git=git)
    except Exception as exc:  # noqa: BLE001 (never blocks activity)
        connection.rollback()
        summary["org_repos"] = {"error": str(exc)[:160]}
    summary.update({
        "activity": run_activity(connection, config, pass_ts=now, git=git),
        "emissions": run_emissions(connection, config, now=now, git=git),
    })
    # Render the ranked dashboard from the just-computed metrics. Read-only,
    # config-gated, and fail-isolated — a render error never fails the pass.
    dash_cfg = config.get("dashboard") or {}
    if dash_cfg.get("enabled", True):
        try:
            summary["dashboard"] = _dashboard().render(connection, config,
                                                       now=now)
        except Exception as exc:  # noqa: BLE001 — render never fails the pass
            summary["dashboard"] = {"error": str(exc)[:160]}
    return summary


_DASH: Any = None


def _dashboard() -> Any:
    """Lazy import of the dashboard renderer (avoids an import cycle: the
    dashboard imports this module)."""
    global _DASH
    if _DASH is None:
        sys.path.insert(0, _MODULE_DIR)
        import atlas_fleet_dashboard  # noqa: E402
        _DASH = atlas_fleet_dashboard
    return _DASH


# ---------------------------------------------------------------------------
# Status + CLI
# ---------------------------------------------------------------------------


def activity_sources(connection: sqlite3.Connection,
                     config: Dict[str, Any]) -> Dict[str, Any]:
    """Shadow report (change: fleet-multi-repo-activity): per subnet, both
    figure sets from its latest pass, the repositories counted with their
    own 30-day counts, why a subnet kept one repository, and repositories
    left out (oversized, disk-limited, failed, pending). Read-only."""
    org = _orgrepos()
    org.ensure_schema(connection)
    history = org._history_rows(connection)
    listings = org._owner_rows(connection)
    planned = org.plan(connection, config, _fleet().all_slots(connection))
    rows = connection.execute(
        "SELECT netuid, pass_ts, c7, c30, a30, days_since, c7_all, c30_all, "
        "a30_all, days_since_all, repos_counted, single_why FROM "
        "metric_activity WHERE (netuid, pass_ts) IN (SELECT netuid, "
        "MAX(pass_ts) FROM metric_activity GROUP BY netuid) ORDER BY netuid"
    ).fetchall()
    subnets = []
    for (nid, pass_ts, c7, c30, a30, days, c7a, c30a, a30a, daysa, counted,
         why) in rows:
        repos = [{"repo": repo, "c30": rc30, "last_commit_at": last}
                 for repo, rc30, last in connection.execute(
                     "SELECT repo, c30, last_commit_at FROM "
                     "metric_activity_repos WHERE netuid = ? AND pass_ts = ? "
                     "ORDER BY c30 DESC, repo", (nid, pass_ts))]
        plan = planned.get(nid) or {}
        left_out = [{"repo": r, "status": (history.get(r) or {}).get(
                        "status") or org.H_PENDING,
                     "error": (history.get(r) or {}).get("error")}
                    for r in plan.get("repos") or []
                    if r not in {x["repo"] for x in repos}]
        owner = plan.get("owner")
        listing = listings.get(owner) if owner else None
        subnets.append({
            "netuid": nid, "pass_ts": pass_ts,
            "single": {"c7": c7, "c30": c30, "a30": a30, "days_since": days},
            "combined": None if c30a is None else {
                "c7": c7a, "c30": c30a, "a30": a30a, "days_since": daysa},
            "c30_gain": None if c30a is None else (c30a - (c30 or 0)),
            "repos_counted": counted, "single_why": why,
            "plan_why": plan.get("why"), "plan_detail": plan.get("detail"),
            "listing": None if not listing else {
                "owner_type": listing["owner_type"],
                "fetched_at": listing["fetched_at"],
                "last_error": listing["last_error"]},
            "repos": repos, "left_out": left_out,
        })
    subnets.sort(key=lambda r: (-(r["c30_gain"] or 0), r["netuid"]))
    return {"mode": org.mode(config),
            "changed": sum(1 for r in subnets if r["c30_gain"]),
            "subnets": subnets}


def metrics_status(connection: sqlite3.Connection) -> Dict[str, Any]:
    ensure_schema(connection)
    scan_outcomes = {row[0]: row[1] for row in connection.execute(
        "SELECT outcome, COUNT(*) FROM metric_emission_scan GROUP BY outcome")}
    opaque = connection.execute(
        "SELECT COUNT(*) FROM metric_emission_scan WHERE opaque = 1"
    ).fetchone()[0]
    routes = connection.execute(
        "SELECT COUNT(*) FROM metric_emission_routes").fetchone()[0]
    activity_slots = connection.execute(
        "SELECT COUNT(DISTINCT netuid) FROM metric_activity").fetchone()[0]
    pulse_slots = connection.execute(
        "SELECT COUNT(DISTINCT netuid) FROM metric_branch_tips").fetchone()[0]
    last_activity = connection.execute(
        "SELECT MAX(pass_ts) FROM metric_activity").fetchone()[0]
    return {
        "installed_at": state_get(connection, "installed_at"),
        "emission_scan": scan_outcomes,
        "emission_opaque": opaque,
        "emission_routes": routes,
        "activity_slots": activity_slots,
        "branch_pulse_slots": pulse_slots,
        "last_activity_pass": last_activity,
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="atlas_fleet_metrics",
        description="Atlas fleet-rotation-metrics: emission map, epoch-scoped "
                    "activity + branch pulse, momentum, and the rotation "
                    "report over the subnet-repo fleet.")
    parser.add_argument("--config", default=None)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    em = sub.add_parser("emissions", help="sha-gated emission-map scan")
    em.add_argument("--netuid", type=int, default=None)
    ac = sub.add_parser("activity", help="record windowed activity")
    ac.add_argument("--netuid", type=int, default=None)
    sub.add_parser("branch-tips", help="record ls-remote tip snapshots")
    sub.add_parser("pass", help="branch tips + activity + emissions "
                                "(also runs inline on reconcile)")
    sub.add_parser("report", help="combined ranked rotation view (read-only)")
    sub.add_parser("activity-sources",
                   help="single vs organisation-wide activity per subnet, "
                        "with the repositories counted (read-only)")
    args = parser.parse_args(argv)

    fleet = _fleet()
    try:
        config = fleet.load_config(args.config or fleet.CONFIG_FILE)
        connection = fleet.open_store(config["db"])
        try:
            ensure_schema(connection)
            if args.command == "status":
                result: Dict[str, Any] = metrics_status(connection)
            elif args.command == "emissions":
                result = run_emissions(connection, config, netuid=args.netuid)
            elif args.command == "activity":
                result = run_activity(connection, config, netuid=args.netuid)
            elif args.command == "branch-tips":
                token = fleet.load_env_token()
                result = record_branch_tips(connection, config, token=token)
            elif args.command == "pass":
                token = fleet.load_env_token()
                result = run_pass(connection, config, token=token)
            elif args.command == "report":
                result = report(connection, config)
            elif args.command == "activity-sources":
                result = activity_sources(connection, config)
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
