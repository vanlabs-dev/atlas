#!/usr/bin/env python3
"""Atlas fleet organisation repositories (change: fleet-multi-repo-activity).

Some subnets develop in several repositories of one GitHub organisation,
while chain identity names only one. This module finds the other
repositories and keeps their commit history, so the activity metric can
count them.

- Listing: GitHub REST `GET /orgs/{owner}/repos` (unauthenticated), at most
  daily per owner, under a per-pass call budget. The owner type comes from
  `GET /users/{owner}` once and is cached. A failed call keeps the last good
  listing; a listing older than `listing_max_age_days` is not used.
- Eligibility: the owner is an organisation, no other current subnet names
  that owner on chain, and the operator has not set it to single-repository.
  A repository counts when it is not a fork, not archived, pushed in the last
  `recent_push_days`, not excluded, and among the `max_repos` most recently
  pushed.
- History: a bare `--filter=tree:0` clone holds commits only. No working
  tree, no trees, no file contents, no tags, no hooks, push URL disabled.
  Free disk is checked before each clone and fetch, and the stored size is
  checked after.

No file from these repositories is opened, indexed or scanned. The metrics
module reads their commit log and decides, through `activity.multi_repo`,
whether the combined figures reach the board.

Public surface:

- activity_cfg(config)                  - merged `activity` block
- ensure_schema(conn)                   - `org_repos`, `org_repo_history`
- refresh_listings(conn, config, ...)   - budgeted listing refresh
- plan(conn, config, slots, now)        - per-netuid counted repositories
- sync_histories(conn, config, ...)     - clone or fetch the counted repos
- run(conn, config, ...)                - refresh, plan, sync (one stage)
- history_log(clone_root, repo, git)    - (sha, when, email) commits
"""

from __future__ import annotations

import datetime
import json
import math
import os
import re
import sqlite3
import sys
import urllib.error
import urllib.request
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))

MODE_OFF = "off"
MODE_SHADOW = "shadow"
MODE_ON = "on"
MODES = (MODE_OFF, MODE_SHADOW, MODE_ON)

# Why a subnet keeps single-repository activity (recorded per pass).
WHY_SHARED = "shared-owner"
WHY_USER = "user-owner"
WHY_OPERATOR = "single-repo-owner"
WHY_NO_LISTING = "no-listing"
WHY_STALE = "listing-stale"
WHY_PLACEHOLDER = "placeholder-owner"
WHY_NO_OWNER = "no-owner"
WHY_OFF = "off"

# History states (org_repo_history.status).
H_OK = "ok"
H_DISK = "disk-limited"
H_OVERSIZED = "oversized"
H_FAILED = "fetch-failed"
H_PENDING = "pending"

USER_AGENT = "atlas-fleet"
API_BASE = "https://api.github.com"
MAX_BODY_BYTES = 4 * 1024 * 1024
_NAME_RE = re.compile(r"^[A-Za-z0-9._-]{1,100}$")

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS org_repos (
    owner TEXT PRIMARY KEY,
    owner_type TEXT,
    fetched_at TEXT,
    ok INTEGER NOT NULL DEFAULT 0,
    repos_json TEXT,
    attempted_at TEXT,
    last_error TEXT
);
CREATE TABLE IF NOT EXISTS org_repo_history (
    repo TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    fetched_at TEXT,
    attempted_at TEXT,
    size_bytes INTEGER,
    error TEXT
);
CREATE TABLE IF NOT EXISTS org_repos_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

DEFAULT_ACTIVITY_CFG: Dict[str, Any] = {
    # `off` in code so a store or test without the block never calls
    # GitHub; fleet/config.json sets `shadow`.
    "multi_repo": MODE_OFF,
    "exclude_repos": [],
    "single_repo_owners": [],
    "max_repos": 20,
    "max_repo_bytes": 268435456,
    "recent_push_days": 90,
    "listing_refresh_hours": 24,
    "listing_max_age_days": 7,
    "passes_per_day": 4,
    "max_calls_per_pass": 50,
    "max_new_histories_per_pass": 40,
    "rate_limit_backoff_seconds": 3600,
    "http_timeout": 20,
    "oversized_retry_days": 7,
    "placeholder_owners": ["deprecated", "orgs", "username", "user",
                           "example", "your-org", "owner"],
}


def activity_cfg(config: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(DEFAULT_ACTIVITY_CFG)
    for key, value in (config.get("activity") or {}).items():
        if key == "_comment":
            continue
        merged[key] = value
    if merged.get("multi_repo") not in MODES:
        merged["multi_repo"] = MODE_OFF
    return merged


def mode(config: Dict[str, Any]) -> str:
    return activity_cfg(config)["multi_repo"]


def _utc_now() -> str:
    return datetime.datetime.now(tz=datetime.timezone.utc).isoformat()


def _parse_iso(text: str) -> datetime.datetime:
    parsed = datetime.datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.timezone.utc)
    return parsed


def ensure_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(SCHEMA_SQL)


def _state_get(connection: sqlite3.Connection, key: str) -> Optional[str]:
    row = connection.execute(
        "SELECT value FROM org_repos_state WHERE key = ?", (key,)).fetchone()
    return row[0] if row else None


def _state_set(connection: sqlite3.Connection, key: str, value: str) -> None:
    connection.execute(
        "INSERT INTO org_repos_state (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))


_FLEET: Any = None


def _fleet() -> Any:
    global _FLEET
    if _FLEET is None:
        sys.path.insert(0, _MODULE_DIR)
        import atlas_fleet  # noqa: E402
        _FLEET = atlas_fleet
    return _FLEET


# ---------------------------------------------------------------------------
# Owner parse
# ---------------------------------------------------------------------------


def owner_repo(github_repo: Optional[str]) -> Optional[Tuple[str, str]]:
    """(owner, name), lower case, from a slot's canonical repository URL."""
    if not github_repo or "github.com/" not in github_repo:
        return None
    parts = github_repo.split("github.com/", 1)[1].strip("/").split("/")
    if len(parts) < 2:
        return None
    owner, name = parts[0].lower(), parts[1].lower()
    if name.endswith(".git"):
        name = name[:-4]
    if not _NAME_RE.match(owner) or not _NAME_RE.match(name):
        return None
    if owner in (".", "..") or name in (".", ".."):
        return None
    return owner, name


def shared_owners(slots: Sequence[Dict[str, Any]]) -> Dict[str, List[int]]:
    """Owners named on chain by more than one current slot (any status)."""
    members: Dict[str, List[int]] = {}
    for slot in slots:
        parsed = owner_repo(slot.get("github_repo"))
        if parsed:
            members.setdefault(parsed[0], []).append(slot["netuid"])
    return {owner: sorted(nids) for owner, nids in members.items()
            if len(nids) > 1}


# ---------------------------------------------------------------------------
# Listing - HTTP (injectable opener; tests never reach the network)
# ---------------------------------------------------------------------------

Opener = Callable[[str, int], Tuple[int, Dict[str, str], bytes]]


def default_opener(url: str, timeout: int
                   ) -> Tuple[int, Dict[str, str], bytes]:
    request = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read(MAX_BODY_BYTES + 1)
            return (response.status,
                    {k.lower(): v for k, v in response.headers.items()}, body)
    except urllib.error.HTTPError as exc:
        headers = {k.lower(): v for k, v in (exc.headers or {}).items()}
        return exc.code, headers, b""


class RateLimited(Exception):
    def __init__(self, until: datetime.datetime) -> None:
        super().__init__("rate limited until %s" % until.isoformat())
        self.until = until


class ListingError(Exception):
    pass


def _rate_limit_until(status: int, headers: Dict[str, str],
                      now: datetime.datetime, backoff: int
                      ) -> Optional[datetime.datetime]:
    limited = status == 429 or (
        status == 403 and headers.get("x-ratelimit-remaining") == "0")
    if not limited:
        return None
    retry = headers.get("retry-after")
    if retry and retry.isdigit():
        return now + datetime.timedelta(seconds=int(retry))
    reset = headers.get("x-ratelimit-reset")
    if reset and reset.isdigit():
        return datetime.datetime.fromtimestamp(int(reset),
                                               tz=datetime.timezone.utc)
    return now + datetime.timedelta(seconds=backoff)


def _get_json(opener: Opener, url: str, cfg: Dict[str, Any],
              now: datetime.datetime) -> Any:
    try:
        status, headers, body = opener(url, int(cfg["http_timeout"]))
    except (OSError, ValueError) as exc:
        raise ListingError("network: %s" % type(exc).__name__)
    until = _rate_limit_until(status, headers, now,
                              int(cfg["rate_limit_backoff_seconds"]))
    if until is not None:
        raise RateLimited(until)
    if status != 200:
        raise ListingError("http %d" % status)
    if len(body) > MAX_BODY_BYTES:
        raise ListingError("body too large")
    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise ListingError("bad json")


def _clean_repos(payload: Any) -> List[Dict[str, Any]]:
    """Validated subset of the listing. Untrusted input: names must match
    the segment pattern; anything malformed is dropped."""
    if not isinstance(payload, list):
        raise ListingError("listing is not a list")
    repos = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        pushed = item.get("pushed_at")
        if not isinstance(name, str) or not _NAME_RE.match(name):
            continue
        if name in (".", ".."):
            continue
        if pushed is not None and not isinstance(pushed, str):
            pushed = None
        repos.append({"name": name.lower(),
                      "fork": bool(item.get("fork")),
                      "archived": bool(item.get("archived")),
                      "pushed_at": pushed})
    return repos


def _owner_rows(connection: sqlite3.Connection) -> Dict[str, Dict[str, Any]]:
    out = {}
    for (owner, otype, fetched, ok, repos_json, attempted,
         error) in connection.execute(
            "SELECT owner, owner_type, fetched_at, ok, repos_json, "
            "attempted_at, last_error FROM org_repos"):
        out[owner] = {"owner_type": otype, "fetched_at": fetched,
                      "ok": bool(ok), "repos_json": repos_json,
                      "attempted_at": attempted, "last_error": error}
    return out


def candidate_owners(slots: Sequence[Dict[str, Any]],
                     cfg: Dict[str, Any]) -> List[str]:
    """Owners worth a listing: named by exactly one slot, not a placeholder,
    not set to single-repository by the operator."""
    shared = shared_owners(slots)
    single = {o.lower() for o in cfg.get("single_repo_owners") or []}
    placeholders = {o.lower() for o in cfg.get("placeholder_owners") or []}
    owners = set()
    for slot in slots:
        if slot.get("status") != "active":
            continue
        parsed = owner_repo(slot.get("github_repo"))
        if not parsed:
            continue
        owner = parsed[0]
        if owner in shared or owner in single or owner in placeholders:
            continue
        owners.add(owner)
    return sorted(owners)


def refresh_listings(connection: sqlite3.Connection, config: Dict[str, Any],
                     slots: Sequence[Dict[str, Any]],
                     now: Optional[str] = None,
                     opener: Optional[Opener] = None) -> Dict[str, Any]:
    """Refresh due owner listings, oldest attempt first, within the pass
    budget. A failure keeps the last good listing and records the error.
    A rate-limit answer stops the pass's calls and holds later passes until
    the reset time."""
    cfg = activity_cfg(config)
    opener = opener or default_opener
    now = now or _utc_now()
    now_dt = _parse_iso(now)
    owners = candidate_owners(slots, cfg)
    summary = {"owners": len(owners), "calls": 0, "refreshed": 0,
               "failed": 0, "rate_limited": False, "budget": 0}
    held = _state_get(connection, "rate_limited_until")
    if held and _parse_iso(held) > now_dt:
        summary["rate_limited"] = True
        return summary
    budget = min(int(cfg["max_calls_per_pass"]),
                 max(1, math.ceil(len(owners) * 1.0
                                  / max(1, int(cfg["passes_per_day"])))))
    # First listings cost two calls (type, then repos): allow the cold
    # start to use the full cap so it does not take days.
    rows = _owner_rows(connection)
    if any(owner not in rows for owner in owners):
        budget = int(cfg["max_calls_per_pass"])
    summary["budget"] = budget
    refresh = datetime.timedelta(hours=float(cfg["listing_refresh_hours"]))

    def due(owner: str) -> bool:
        row = rows.get(owner)
        if not row or not row["attempted_at"]:
            return True
        return now_dt - _parse_iso(row["attempted_at"]) >= refresh

    queue = sorted((o for o in owners if due(o)),
                   key=lambda o: ((rows.get(o) or {}).get("attempted_at")
                                  or ""))
    for owner in queue:
        row = rows.get(owner) or {}
        known = row.get("owner_type")
        if known == "User":
            # Owner types do not change in practice: a personal account is
            # rechecked with one call per refresh window.
            known = None
        need = 1 if known else 2
        if summary["calls"] + need > budget:
            break
        otype = known
        try:
            if not otype:
                summary["calls"] += 1
                info = _get_json(opener, "%s/users/%s" % (API_BASE, owner),
                                 cfg, now_dt)
                otype = info.get("type") if isinstance(info, dict) else None
                if otype not in ("Organization", "User"):
                    raise ListingError("unknown owner type")
            repos: List[Dict[str, Any]] = []
            if otype == "Organization":
                summary["calls"] += 1
                payload = _get_json(
                    opener, "%s/orgs/%s/repos?per_page=100&sort=pushed"
                    % (API_BASE, owner), cfg, now_dt)
                repos = _clean_repos(payload)
        except RateLimited as exc:
            _state_set(connection, "rate_limited_until",
                       exc.until.isoformat())
            _record_failure(connection, owner, otype, now, "rate-limited")
            summary["rate_limited"] = True
            summary["failed"] += 1
            break
        except ListingError as exc:
            _record_failure(connection, owner, otype, now, str(exc)[:120])
            summary["failed"] += 1
            continue
        # A personal account is stored with an empty listing: it is never
        # read organisation-wide.
        connection.execute(
            "INSERT INTO org_repos (owner, owner_type, fetched_at, ok, "
            "repos_json, attempted_at, last_error) VALUES (?, ?, ?, 1, ?, ?, "
            "NULL) ON CONFLICT(owner) DO UPDATE SET owner_type = "
            "excluded.owner_type, fetched_at = excluded.fetched_at, ok = 1, "
            "repos_json = excluded.repos_json, attempted_at = "
            "excluded.attempted_at, last_error = NULL",
            (owner, otype, now, json.dumps(repos, sort_keys=True), now))
        connection.commit()
        summary["refreshed"] += 1
    return summary


def _record_failure(connection: sqlite3.Connection, owner: str,
                    owner_type: Optional[str], now: str, error: str) -> None:
    """Keep the last good listing; record the attempt and the error."""
    connection.execute(
        "INSERT INTO org_repos (owner, owner_type, ok, attempted_at, "
        "last_error) VALUES (?, ?, 0, ?, ?) ON CONFLICT(owner) DO UPDATE SET "
        "owner_type = COALESCE(excluded.owner_type, org_repos.owner_type), "
        "attempted_at = excluded.attempted_at, last_error = "
        "excluded.last_error", (owner, owner_type, now, error))
    connection.commit()


# ---------------------------------------------------------------------------
# Eligibility
# ---------------------------------------------------------------------------


def plan(connection: sqlite3.Connection, config: Dict[str, Any],
         slots: Sequence[Dict[str, Any]], now: Optional[str] = None
         ) -> Dict[int, Dict[str, Any]]:
    """Per active netuid: `repos` (extra `owner/name` keys to count, the
    on-chain repository excluded) and `why` (null when organisation-wide
    reading applies, else the reason the subnet keeps one repository)."""
    cfg = activity_cfg(config)
    now_dt = _parse_iso(now or _utc_now())
    shared = shared_owners(slots)
    single = {o.lower() for o in cfg.get("single_repo_owners") or []}
    placeholders = {o.lower() for o in cfg.get("placeholder_owners") or []}
    excluded = {r.lower().strip("/") for r in cfg.get("exclude_repos") or []}
    rows = _owner_rows(connection)
    max_age = datetime.timedelta(days=float(cfg["listing_max_age_days"]))
    recent = datetime.timedelta(days=float(cfg["recent_push_days"]))
    out: Dict[int, Dict[str, Any]] = {}
    for slot in slots:
        if slot.get("status") != "active":
            continue
        nid = slot["netuid"]
        parsed = owner_repo(slot.get("github_repo"))
        entry: Dict[str, Any] = {"owner": parsed[0] if parsed else None,
                                 "onchain": ("%s/%s" % parsed) if parsed
                                 else None,
                                 "repos": [], "why": None, "detail": None}
        out[nid] = entry
        if cfg["multi_repo"] == MODE_OFF:
            entry["why"] = WHY_OFF
            continue
        if not parsed:
            entry["why"] = WHY_NO_OWNER
            continue
        owner, name = parsed
        if owner in placeholders:
            entry["why"] = WHY_PLACEHOLDER
            continue
        if owner in shared:
            entry["why"] = WHY_SHARED
            entry["detail"] = "SN" + ",".join(str(n) for n in shared[owner])
            continue
        if owner in single:
            entry["why"] = WHY_OPERATOR
            continue
        row = rows.get(owner)
        if not row or not row["fetched_at"]:
            entry["why"] = WHY_NO_LISTING
            entry["detail"] = (row or {}).get("last_error")
            continue
        if row["owner_type"] == "User":
            entry["why"] = WHY_USER
            continue
        age = now_dt - _parse_iso(row["fetched_at"])
        if age > max_age:
            entry["why"] = WHY_STALE
            entry["detail"] = "listing %dd old" % age.days
            continue
        try:
            listed = json.loads(row["repos_json"] or "[]")
        except ValueError:
            entry["why"] = WHY_NO_LISTING
            continue
        picks = []
        for repo in listed:
            key = "%s/%s" % (owner, repo["name"])
            if repo["name"] == name or key in excluded:
                continue
            if repo["fork"] or repo["archived"] or not repo["pushed_at"]:
                continue
            try:
                pushed = _parse_iso(repo["pushed_at"])
            except ValueError:
                continue
            if now_dt - pushed > recent:
                continue
            picks.append((pushed, key))
        picks.sort(key=lambda p: (-p[0].timestamp(), p[1]))
        # The on-chain repository takes one of the `max_repos` places.
        keep = max(0, int(cfg["max_repos"]) - 1)
        entry["repos"] = [key for _, key in picks[:keep]]
    return out


# ---------------------------------------------------------------------------
# History-only bare repositories
# ---------------------------------------------------------------------------


def history_dir(clone_root: str, repo: str) -> str:
    owner, name = repo.split("/", 1)
    return os.path.join(clone_root, "activity", owner, name + ".git")


def _dir_bytes(path: str) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.lstat(os.path.join(root, f)).st_size
            except OSError:
                continue
    return total


def _history_rows(connection: sqlite3.Connection) -> Dict[str, Dict[str, Any]]:
    return {repo: {"status": status, "fetched_at": fetched,
                   "attempted_at": attempted, "size_bytes": size,
                   "error": error}
            for (repo, status, fetched, attempted, size, error)
            in connection.execute(
                "SELECT repo, status, fetched_at, attempted_at, size_bytes, "
                "error FROM org_repo_history")}


def _record_history(connection: sqlite3.Connection, repo: str, status: str,
                    now: str, size: Optional[int] = None,
                    error: Optional[str] = None, fetched: bool = False
                    ) -> None:
    connection.execute(
        "INSERT INTO org_repo_history (repo, status, fetched_at, "
        "attempted_at, size_bytes, error) VALUES (?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(repo) DO UPDATE SET status = excluded.status, "
        "fetched_at = COALESCE(excluded.fetched_at, "
        "org_repo_history.fetched_at), attempted_at = excluded.attempted_at, "
        "size_bytes = COALESCE(excluded.size_bytes, "
        "org_repo_history.size_bytes), error = excluded.error",
        (repo, status, now if fetched else None, now, size, error))
    connection.commit()


def fetch_history(target: str, url: str,
                  git: Callable[..., Tuple[int, str, str]],
                  max_bytes: Optional[int], disk_ok: Callable[[], bool]
                  ) -> Dict[str, Any]:
    """Clone (first time) or fetch a commit-only bare repository.

    `--filter=tree:0` asks the server for commits without trees or blobs.
    `--template=` installs no hook samples; `--no-tags` and
    `--single-branch` keep only the default branch. The fetch refspec is
    set explicitly, because a bare clone records none and a plain `fetch`
    would not move the branch."""
    fleet = _fleet()
    if not disk_ok():
        return {"status": H_DISK, "error": "free disk below the ceiling"}
    fresh = not os.path.isdir(target)
    if fresh:
        os.makedirs(os.path.dirname(target), exist_ok=True)
        code, _out, err = git(None, [
            "clone", "--bare", "--filter=tree:0", "--no-tags",
            "--single-branch", "--template=", url, target])
        if code != 0:
            fleet._rmtree(target)
            return {"status": H_FAILED,
                    "error": fleet.redact(err.strip()[:200])}
        code, head, err = git(target, ["symbolic-ref", "HEAD"])
        branch_ref = head.strip()
        if code != 0 or not branch_ref.startswith("refs/heads/"):
            fleet._rmtree(target)
            return {"status": H_FAILED, "error": "no default branch"}
        for args in (["config", "remote.origin.fetch",
                      "+%s:%s" % (branch_ref, branch_ref)],
                     ["config", "remote.origin.tagOpt", "--no-tags"],
                     ["remote", "set-url", "--push", "origin",
                      fleet.PUSH_URL_DISABLED]):
            code, _out, err = git(target, args)
            if code != 0:
                fleet._rmtree(target)
                return {"status": H_FAILED,
                        "error": fleet.redact(err.strip()[:200])}
    else:
        code, _out, err = git(target, ["fetch", "--no-tags",
                                       "--filter=tree:0", "origin"])
        if code != 0:
            return {"status": H_FAILED,
                    "error": fleet.redact(err.strip()[:200])}
    size = _dir_bytes(target)
    if max_bytes is not None and size > max_bytes:
        fleet._rmtree(target)
        return {"status": H_OVERSIZED, "size_bytes": size,
                "error": "history %d bytes exceeds cap %d" % (size,
                                                              max_bytes)}
    return {"status": H_OK, "size_bytes": size, "fresh": fresh}


def sync_histories(connection: sqlite3.Connection, config: Dict[str, Any],
                   repos: Sequence[str], now: Optional[str] = None,
                   git: Optional[Callable[..., Tuple[int, str, str]]] = None,
                   disk_free: Optional[Callable[[], Optional[int]]] = None,
                   url_for: Optional[Callable[[str], str]] = None
                   ) -> Dict[str, Any]:
    cfg = activity_cfg(config)
    fleet = _fleet()
    now = now or _utc_now()
    now_dt = _parse_iso(now)
    git = git or fleet._run_git
    clone_root = config.get("clone_root") or fleet.DEFAULT_CLONE_ROOT
    min_free = config.get("min_free_bytes")
    probe = disk_free or (lambda: fleet._default_disk_free(clone_root))
    url_for = url_for or (lambda repo: "https://github.com/%s.git" % repo)

    def disk_ok() -> bool:
        if min_free is None:
            return True
        free = probe()
        return free is None or free >= min_free

    history = _history_rows(connection)
    retry = datetime.timedelta(days=float(cfg["oversized_retry_days"]))
    summary: Dict[str, int] = {"ok": 0, H_DISK: 0, H_OVERSIZED: 0,
                               H_FAILED: 0, "skipped": 0, "new": 0}
    new_left = int(cfg["max_new_histories_per_pass"])
    for repo in sorted(set(repos)):
        prev = history.get(repo) or {}
        if prev.get("status") == H_OVERSIZED and prev.get("attempted_at") \
                and now_dt - _parse_iso(prev["attempted_at"]) < retry:
            summary["skipped"] += 1
            continue
        target = history_dir(clone_root, repo)
        if not os.path.isdir(target):
            if new_left <= 0:
                summary["skipped"] += 1
                if not prev:
                    _record_history(connection, repo, H_PENDING, now)
                continue
            new_left -= 1
            summary["new"] += 1
        result = fetch_history(target, url_for(repo), git,
                               cfg.get("max_repo_bytes"), disk_ok)
        status = result["status"]
        _record_history(connection, repo, status, now,
                        size=result.get("size_bytes"),
                        error=result.get("error"), fetched=status == H_OK)
        summary["ok" if status == H_OK else status] += 1
    return summary


def counted_repos(connection: sqlite3.Connection, config: Dict[str, Any],
                  repos: Sequence[str]) -> Tuple[List[str], Dict[str, str]]:
    """Repos whose history exists on disk and is not oversized; and a
    reason for each one dropped."""
    fleet = _fleet()
    clone_root = config.get("clone_root") or fleet.DEFAULT_CLONE_ROOT
    history = _history_rows(connection)
    keep, dropped = [], {}
    for repo in repos:
        status = (history.get(repo) or {}).get("status")
        if status == H_OVERSIZED:
            dropped[repo] = H_OVERSIZED
        elif os.path.isdir(history_dir(clone_root, repo)):
            keep.append(repo)
        else:
            dropped[repo] = status or H_PENDING
    return keep, dropped


def history_log(clone_root: str, repo: str,
                git: Callable[..., Tuple[int, str, str]]
                ) -> List[Tuple[str, datetime.datetime, str]]:
    """(sha, committer time, author email) for a history repository.

    `rev-list`, not `log`: in a `tree:0` repository `git log` fetches the
    missing trees from the remote on demand, while `rev-list` reads only
    the commits that are stored."""
    target = history_dir(clone_root, repo)
    code, out, err = git(target, ["rev-list", "--no-merges",
                                  "--no-commit-header",
                                  "--format=%H%x09%cI%x09%ae", "HEAD"])
    if code != 0:
        raise RuntimeError("git rev-list failed: %s" % err.strip()[:200])
    return parse_log(out)


def parse_log(out: str) -> List[Tuple[str, datetime.datetime, str]]:
    rows = []
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        sha, when, email = parts
        try:
            rows.append((sha.strip(), _parse_iso(when.strip()),
                         email.strip()))
        except ValueError:
            continue
    return rows


def run(connection: sqlite3.Connection, config: Dict[str, Any],
        now: Optional[str] = None, opener: Optional[Opener] = None,
        git: Optional[Callable[..., Tuple[int, str, str]]] = None,
        disk_free: Optional[Callable[[], Optional[int]]] = None,
        url_for: Optional[Callable[[str], str]] = None
        ) -> Dict[str, Any]:
    """One stage per pass: refresh listings, plan, sync histories."""
    ensure_schema(connection)
    if mode(config) == MODE_OFF:
        return {"mode": MODE_OFF}
    now = now or _utc_now()
    slots = _fleet().all_slots(connection)
    listing = refresh_listings(connection, config, slots, now=now,
                               opener=opener)
    planned = plan(connection, config, slots, now=now)
    repos = sorted({r for p in planned.values() for r in p["repos"]})
    histories = sync_histories(connection, config, repos, now=now, git=git,
                               disk_free=disk_free, url_for=url_for)
    return {"mode": mode(config), "listing": listing,
            "multi": sum(1 for p in planned.values() if not p["why"]),
            "repos": len(repos), "histories": histories}

