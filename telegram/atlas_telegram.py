#!/usr/bin/env python3
"""Atlas Phase 5 — outbound Telegram operational notifier.

The inbound conversation channel is the native NousResearch Hermes
Telegram gateway (operator-configured; Atlas writes none of it). This
module is the *outbound* half only: it turns events already produced by
earlier phases into de-duplicated, secret-scrubbed Telegram alerts and
records every delivery.

Fail-closed, stdlib-only, read-only toward the device except its own 0600
`var/telegram/` store (ATLAS-TG-004/005; PRD §12.11):

- credentials resolved from operator env files (the wizard-written
  `~/.hermes/.env` is reused — no secret is duplicated into the repo);
- four source adapters read existing stores read-only and surface only
  events past a persisted per-source watermark:
    chain-runtime-upgrade <- var/livedata/livedata.db   (spec_upgrades)
    repository-update     <- var/repotrack/repotrack.db (change_ranges)
    schema-drift          <- var/livedata/livedata.db   (integration_health)
    knowledge-ingestion   <- var/knowledge/knowledge.db (intake_runs)
- repository ranges are tiered: churn (an explicit allowlist of
  non-protocol directories) is digested — persisted durably before the
  watermark passes it, never paged, never dropped — while significant
  ranges page with a breakdown and an explicit repo-vs-live-chain line;
- a **refuse-don't-truncate** scrubber gates every send, built on the
  pinned inventory redaction oracle plus the registered bot token;
- messages render as Telegram HTML (escaped after redaction, sized
  before rendering); an HTTP 400 falls back once to plain text;
- a delivery ledger carries the six ATLAS-TG-005 fields; de-duplication
  is by stable `event_id` within a coalescing window;
- Telegram failure is caught at the per-event boundary, recorded, and
  never propagated — core Atlas functions are unaffected.

Adding service-failure later is a new adapter only (the scan loop and
ledger are class-agnostic).
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import secrets as secretsmod
from typing import Any, Callable, Dict, List, Optional, Tuple

_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_MODULE_DIR)

TELEGRAM_VERSION = "0.1.0"
CONFIG_FILE = os.path.join(_MODULE_DIR, "config.json")
USER_AGENT = "atlas-telegram/" + TELEGRAM_VERSION

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY,
    event_id TEXT NOT NULL UNIQUE,
    event_class TEXT NOT NULL,
    created_at TEXT NOT NULL,
    attempted_at TEXT,
    status TEXT NOT NULL,
    retry_count INTEGER NOT NULL DEFAULT 0,
    final_failure TEXT
);
CREATE INDEX IF NOT EXISTS events_class_created ON events (event_class, created_at);
CREATE TABLE IF NOT EXISTS watermarks (
    source TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS pending_churn (
    range_id INTEGER PRIMARY KEY,
    prev_sha TEXT NOT NULL,
    new_sha TEXT NOT NULL,
    dominant_area TEXT NOT NULL,
    detected_at TEXT NOT NULL
);
"""

# Repository-range significance policy defaults (config-overridable).
# Churn is DENY-BY-DEFAULT: an explicit allowlist; any directory not
# provably in it (including a top-level dir never seen before) escalates
# to significant — the monorepo reorganizes, fail toward paging.
DEFAULT_PROTOCOL_DIRS = ("pallets", "runtime", "precompiles", "common")
DEFAULT_CHURN_DIRS = (".github", "docs", "website", "vendor", "sdk")
DEFAULT_DIGEST_BACKSTOP_HOURS = 24
DEFAULT_GOVERNANCE_THRESHOLD = 425
SIGNIFICANT = "significant"
CHURN = "churn"

# Terminal ledger states (a repeat of one of these suppresses a re-send).
STATUS_DELIVERED = "delivered"
STATUS_FAILED = "failed"
STATUS_SUPPRESSED = "suppressed"
STATUS_SCRUB_REFUSED = "scrub-refused"
_TERMINAL = (STATUS_DELIVERED, STATUS_FAILED, STATUS_SUPPRESSED,
             STATUS_SCRUB_REFUSED)


class FatalTelegramError(Exception):
    """Configuration/contract failure; the run aborts fail-closed."""


class ScrubRefusal(Exception):
    """A message would expose a secret or exceed the exposure policy."""


# ---------------------------------------------------------------------------
# Shared inventory redaction oracle (pinned import, same as livedata)
# ---------------------------------------------------------------------------

_INV: Any = None


def _inv() -> Any:
    global _INV
    if _INV is None:
        sys.path.insert(0, os.path.join(_REPO_ROOT, "inventory"))
        import atlas_inventory  # noqa: E402
        _INV = atlas_inventory
    return _INV


_SECRET_VALUES: List[str] = []


def register_secret(value: str) -> None:
    if value and len(value) >= 8 and value not in _SECRET_VALUES:
        _SECRET_VALUES.append(value)


def redact(text: str) -> str:
    for value in _SECRET_VALUES:
        if value and value in text:
            text = text.replace(value, "[REDACTED-SECRET]")
    return _inv().redact(text)


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _utc_now() -> str:
    return datetime.datetime.now(tz=datetime.timezone.utc).isoformat()


def _now_epoch() -> float:
    return time.time()


def run_id() -> str:
    return (time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
            + "-" + secretsmod.token_hex(4))


def resolve(path: str, repo_root: str = _REPO_ROOT) -> str:
    path = os.path.expanduser(path)
    return path if os.path.isabs(path) else os.path.join(repo_root, path)


# ---------------------------------------------------------------------------
# Config + credentials
# ---------------------------------------------------------------------------

def load_config(path: str = CONFIG_FILE) -> Dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            config = json.load(handle)
    except (OSError, ValueError) as exc:
        raise FatalTelegramError("cannot load config %s: %s" % (path, exc))
    for key in ("credential_env_files", "bot_token_env", "alert_chat_id_env",
                "api_base", "db", "retry", "classes"):
        if key not in config:
            raise FatalTelegramError("config missing %r" % key)
    return config


def _read_env_file(path: str) -> Dict[str, str]:
    values: Dict[str, str] = {}
    if not os.path.exists(path):
        return values
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            value = value.strip().strip('"').strip("'")
            if value:
                values[key.strip()] = value
    return values


def load_env(config: Dict[str, Any]) -> Dict[str, str]:
    """Merge the configured env files (first file wins) and the process
    environment. Every discovered value is registered for redaction."""
    merged: Dict[str, str] = {}
    for rel in config["credential_env_files"]:
        for key, value in _read_env_file(resolve(rel)).items():
            merged.setdefault(key, value)
    for key, value in os.environ.items():
        merged.setdefault(key, value)
    return merged


def resolve_credentials(config: Dict[str, Any],
                        env: Optional[Dict[str, str]] = None
                        ) -> Tuple[str, str]:
    """Return (bot_token, alert_chat_id) or fail closed with guidance.

    The bot token is registered as a secret so it can never leak into a
    message body, error, or ledger record."""
    env = env if env is not None else load_env(config)
    token = (env.get(config["bot_token_env"]) or "").strip()
    chat_id = (env.get(config["alert_chat_id_env"]) or "").strip()
    if not token:
        raise FatalTelegramError(
            "no %s found in %s — the bot token is written by "
            "`hermes gateway setup`; point credential_env_files at that file"
            % (config["bot_token_env"], config["credential_env_files"]))
    if not chat_id:
        raise FatalTelegramError(
            "no %s found in %s — set it to the operator's numeric Telegram "
            "id (the alert target); see telegram/docs/operator-setup.md"
            % (config["alert_chat_id_env"], config["credential_env_files"]))
    register_secret(token)
    return token, chat_id


# ---------------------------------------------------------------------------
# Store / ledger (ATLAS-TG-005)
# ---------------------------------------------------------------------------

def open_store(db_path: str) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    connection = sqlite3.connect(db_path, timeout=10)
    connection.executescript(SCHEMA_SQL)
    return connection


def open_source_ro(db_path: str) -> Optional[sqlite3.Connection]:
    """Open a source store read-only. Returns None if it does not exist
    yet (a source that has never run is 'no events', not an error)."""
    if not os.path.exists(db_path):
        return None
    uri = "file:%s?mode=ro" % urllib.request.pathname2url(db_path)
    return sqlite3.connect(uri, uri=True, timeout=10)


def watermark_get(connection: sqlite3.Connection,
                  source: str) -> Optional[str]:
    row = connection.execute(
        "SELECT value FROM watermarks WHERE source = ?", (source,)).fetchone()
    return row[0] if row else None


def watermark_set(connection: sqlite3.Connection, source: str,
                  value: str) -> None:
    connection.execute(
        "INSERT INTO watermarks (source, value, updated_at) VALUES (?, ?, ?) "
        "ON CONFLICT(source) DO UPDATE SET value = excluded.value, "
        "updated_at = excluded.updated_at",
        (source, value, _utc_now()))
    connection.commit()


def ledger_seen_recent(connection: sqlite3.Connection, event_id: str,
                       window_seconds: int) -> bool:
    """True if this event_id already reached a terminal state within the
    coalescing window (identity de-dup that prevents alert floods)."""
    row = connection.execute(
        "SELECT status, created_at FROM events WHERE event_id = ?",
        (event_id,)).fetchone()
    if row is None:
        return False
    status, created_at = row
    if status not in _TERMINAL:
        return False
    try:
        created = datetime.datetime.fromisoformat(created_at)
    except ValueError:
        return True
    age = (datetime.datetime.now(tz=datetime.timezone.utc)
           - created).total_seconds()
    return age <= window_seconds


def ledger_record(connection: sqlite3.Connection, event_id: str,
                  event_class: str, created_at: str, attempted_at: Optional[str],
                  status: str, retry_count: int,
                  final_failure: Optional[str]) -> None:
    connection.execute(
        "INSERT INTO events (event_id, event_class, created_at, attempted_at, "
        "status, retry_count, final_failure) VALUES (?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(event_id) DO UPDATE SET attempted_at = excluded.attempted_at, "
        "status = excluded.status, retry_count = excluded.retry_count, "
        "final_failure = excluded.final_failure",
        (event_id, event_class, created_at, attempted_at, status,
         retry_count, redact(final_failure)[:400] if final_failure else None))
    connection.commit()


# ---------------------------------------------------------------------------
# Scrubber (ATLAS-TG-004) — refuse, never truncate
# ---------------------------------------------------------------------------

def assert_sendable(text: str) -> None:
    """Raise ScrubRefusal if *text* would expose a secret or exceed the
    approved exposure policy. A registered secret (e.g. the bot token) or
    any pinned redaction pattern triggers a refusal — the message is not
    sent at all, not sent-with-a-mask."""
    for value in _SECRET_VALUES:
        if value and value in text:
            raise ScrubRefusal("registered secret value present in message")
    if redact(text) != text:
        raise ScrubRefusal(
            "message matches a secret / over-exposure pattern")


# ---------------------------------------------------------------------------
# Telegram HTML rendering — escape after redact, size before render
# ---------------------------------------------------------------------------
# Only Bot-API-supported tags are ever emitted (b, i, code, blockquote,
# blockquote expandable). Every dynamic value passes html_escape(); a real
# in-range commit subject contains `Vec<PerU16>`, which unescaped would
# 400 the send. Rendered HTML is NEVER truncated after rendering — the
# builder shortens *content* until the rendered body fits, because a
# post-render slice can cut a tag mid-entity and 400 every long message.


def html_escape(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))


def _typography(text: str) -> str:
    """Operator style rule (2026-07-13): alert bodies never contain em or
    en dashes. Composed strings use '·' separators; anything imported
    from stored data is normalized here, the single choke point."""
    return text.replace("—", "-").replace("–", "-")


def render_html(headline: str, lines: List[str], expandable: str,
                trailer: Optional[str], max_chars: int) -> str:
    """Compose the supported-tag HTML body, shrinking the expandable
    content (never the markup) until the result fits max_chars."""
    headline = _typography(headline)
    lines = [_typography(line) for line in lines]
    expandable = _typography(expandable)
    trailer = _typography(trailer) if trailer else trailer
    for _ in range(4):
        parts = ["<b>%s</b>" % html_escape(headline)]
        parts.extend(html_escape(line) for line in lines)
        if expandable:
            parts.append("<blockquote expandable>%s</blockquote>"
                         % html_escape(expandable))
        if trailer:
            parts.append("<i>%s</i>" % html_escape(trailer))
        body = "\n".join(parts)
        if len(body) <= max_chars:
            return body
        overshoot = len(body) - max_chars
        if expandable and len(expandable) > 40:
            expandable = expandable[:max(20, len(expandable)
                                         - overshoot - 20)] + "…"
        elif trailer:
            trailer = None
        else:
            lines = lines[:-1] if lines else []
    return body[:0] + "<b>%s</b>" % html_escape(headline[:max_chars - 7])


def render_plain(headline: str, lines: List[str], expandable: str,
                 trailer: Optional[str], max_chars: int) -> str:
    parts = [headline] + list(lines)
    if expandable:
        parts.append(expandable)
    if trailer:
        parts.append(trailer)
    return _typography("\n".join(parts))[:max_chars]


# ---------------------------------------------------------------------------
# Transport — Telegram Bot API sendMessage with bounded, observable retry
# ---------------------------------------------------------------------------

def _do_post(url: str, data: bytes, timeout: int) -> Tuple[int, str]:
    request = urllib.request.Request(
        url, data=data, method="POST",
        headers={"User-Agent": USER_AGENT,
                 "Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.status, response.read().decode("utf-8", "replace")


def send_message(config: Dict[str, Any], token: str, chat_id: str,
                 text: str,
                 poster: Optional[Callable[[str, bytes, int], Tuple[int, str]]]
                 = None, parse_mode: Optional[str] = None) -> Dict[str, Any]:
    """Attempt delivery with bounded retry. Returns a result dict with
    delivered/attempts/status/detail. Never raises for transport or API
    failures — those are the caller's recorded terminal outcomes. The
    token is in the URL and MUST NOT appear in any returned detail."""
    poster = poster or _do_post
    register_secret(token)  # defensive: token is in the URL, never in output
    retry = config["retry"]
    max_attempts = int(retry["max_attempts"])
    retry_on = set(retry.get("retry_on_status", []))
    never_retry = set(retry.get("never_retry_on_status", []))
    backoff = retry.get("backoff_seconds", [1.0, 3.0])
    timeout = int(config.get("request_timeout_seconds", 20))
    url = "%s/bot%s/sendMessage" % (config["api_base"], token)
    fields = {"chat_id": chat_id, "text": text,
              "disable_web_page_preview": "true"}
    if parse_mode:
        fields["parse_mode"] = parse_mode
    payload = urllib.parse.urlencode(fields).encode("utf-8")

    attempts = 0
    last_detail = "no attempt made"
    last_status: Optional[int] = None
    while attempts < max_attempts:
        attempts += 1
        try:
            status, body = poster(url, payload, timeout)
            last_status = status
            if status == 200:
                return {"delivered": True, "attempts": attempts,
                        "status": status, "detail": "ok"}
            last_detail = redact("HTTP %s: %s" % (status, body))[:300]
            if status in never_retry or status not in retry_on:
                break
        except urllib.error.HTTPError as exc:
            last_status = exc.code
            last_detail = redact("HTTP %s" % exc.code)[:300]
            if exc.code in never_retry or exc.code not in retry_on:
                break
        except (urllib.error.URLError, OSError, ValueError) as exc:
            last_detail = redact("transport error: %s" % exc)[:300]
        if attempts < max_attempts:
            time.sleep(backoff[min(attempts - 1, len(backoff) - 1)])
    return {"delivered": False, "attempts": attempts,
            "status": last_status, "detail": last_detail}


# ---------------------------------------------------------------------------
# Event adapters — read existing stores read-only, past a watermark
# ---------------------------------------------------------------------------
# Each returns (events, new_watermark). An event is a dict:
#   {event_id, event_class, created_at, text} plus optional keys:
#   html (rendered Telegram HTML body) and digest_range_ids (pending
#   churn cleared by the scan once the carrying event is DELIVERED).
# Adapters never mutate their source and never invent data. `ctx`
# carries the notifier's own store + config: {"config", "spec",
# "connection"}; adapters that need neither ignore it.


def _repo_policy(ctx: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    policy = ((ctx or {}).get("config") or {}).get("repository_update", {})
    return {
        "protocol_dirs": set(policy.get("protocol_dirs",
                                        DEFAULT_PROTOCOL_DIRS)),
        "churn_dirs": set(policy.get("churn_dirs", DEFAULT_CHURN_DIRS)),
        "digest_backstop_hours": float(policy.get(
            "digest_backstop_hours", DEFAULT_DIGEST_BACKSTOP_HOURS)),
    }


def classify_range(rng: Dict[str, Any], policy: Dict[str, Any]) -> str:
    """Deny-by-default significance: churn only when the recorded file
    list is complete, trustworthy, and provably a subset of the churn
    allowlist with no spec_version change. Everything else pages."""
    if rng["files_truncated"] or rng["non_fast_forward"]:
        return SIGNIFICANT  # file list known-incomplete: cannot prove churn
    prev_spec, new_spec = rng["prev_spec"], rng["new_spec"]
    if (prev_spec is not None and new_spec is not None
            and prev_spec != new_spec):
        return SIGNIFICANT  # runtime spec bump: the strongest signal
    dirs = {path.split("/", 1)[0] for path in rng["files"]}
    if dirs & policy["protocol_dirs"]:
        return SIGNIFICANT
    if dirs and dirs <= policy["churn_dirs"]:
        return CHURN
    return SIGNIFICANT  # unknown/new top-level dir (or empty) → escalate


def _dominant_area(files: List[str]) -> str:
    counts: Dict[str, int] = {}
    for path in files:
        top = path.split("/", 1)[0]
        counts[top] = counts.get(top, 0) + 1
    if not counts:
        return "unknown"
    return sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))[0][0]


def _resolve_repo_watermark(conn: sqlite3.Connection,
                            watermark: Optional[str]) -> Optional[int]:
    """The repository-update watermark is the last-processed
    `change_ranges.id`. The pre-tiering deployment stored a head SHA —
    translate it once (its range's id, else reseed to the current max so
    a hex string is never int()'d and history is never replayed)."""
    if watermark is None:
        return None
    if watermark.isdigit():
        return int(watermark)
    row = conn.execute("SELECT id FROM change_ranges WHERE new_sha = ?",
                       (watermark,)).fetchone()
    if row is not None:
        return int(row[0])
    row = conn.execute("SELECT MAX(id) FROM change_ranges").fetchone()
    return int(row[0]) if row and row[0] is not None else 0


def read_live_spec(live_db: Optional[str]) -> Optional[Dict[str, Any]]:
    """Last-seen live runtime spec_version from livedata's store,
    read-only. None when unavailable — the caller degrades honestly."""
    if not live_db:
        return None
    conn = open_source_ro(live_db)
    if conn is None:
        return None
    try:
        rows = dict(conn.execute(
            "SELECT key, value FROM meta WHERE key IN "
            "('last_live_spec', 'last_live_spec_block')").fetchall())
    except sqlite3.Error:
        return None
    finally:
        conn.close()
    spec = rows.get("last_live_spec")
    if spec is None:
        return None
    return {"spec_version": int(spec),
            "block": rows.get("last_live_spec_block")}


def _both_clocks_line(new_spec: Optional[int],
                      live: Optional[Dict[str, Any]]) -> str:
    """The repo-vs-live-chain distinction, stated on every repo alert."""
    if live is None:
        return ("live chain spec unavailable · cannot compare · "
                "repository event only")
    if new_spec is None:
        return ("repo spec unknown · live Finney spec %d · not enacted "
                "on chain" % live["spec_version"])
    delta = new_spec - live["spec_version"]
    return ("repo spec %d · live Finney spec %d · Δ%+d · not enacted "
            "on chain" % (new_spec, live["spec_version"], delta))


def _pending_churn_rows(store: sqlite3.Connection
                        ) -> List[Tuple[int, str, str, str]]:
    return store.execute(
        "SELECT range_id, new_sha, dominant_area, detected_at "
        "FROM pending_churn ORDER BY range_id ASC").fetchall()


def _digest_line(pending: List[Tuple[int, str, str, str]]) -> str:
    items = " · ".join("%s (%s)" % (row[2], row[1][:12]) for row in pending)
    return ("digested %d low-signal update(s): %s · no protocol or spec "
            "change" % (len(pending), items))


def _breakdown_lines(rng: Dict[str, Any]) -> str:
    """Structured breakdown from the recorded change range: one fact per
    line (operator feedback 2026-07-13: never a prose blob)."""
    lines: List[str] = []
    counts: Dict[str, int] = {}
    for path in rng["files"]:
        top = path.split("/", 1)[0]
        counts[top] = counts.get(top, 0) + 1
    top = sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))[:5]
    if top:
        lines.append("top areas: " + " · ".join(
            "%s (%d)" % pair for pair in top))
    if rng["tags"]:
        lines.append("tags: " + " · ".join(rng["tags"][:10]))
    for commit in rng["commits"][:5]:
        subject = (commit.get("subject") or "").strip()
        if subject:
            lines.append("• " + subject[:100])
    lines.append("from recorded change data · effects not verified")
    return "\n".join(lines)


def _build_repo_event(rng: Dict[str, Any], live: Optional[Dict[str, Any]],
                      pending: List[Tuple[int, str, str, str]],
                      max_chars: int) -> Dict[str, Any]:
    prev_spec, new_spec = rng["prev_spec"], rng["new_spec"]
    if (prev_spec is not None and new_spec is not None
            and prev_spec != new_spec):
        reason = "runtime spec bump %d→%d" % (prev_spec, new_spec)
    elif rng["files_truncated"] or rng["non_fast_forward"]:
        reason = "review needed (incomplete change record)"
    else:
        reason = "protocol-area change"
    headline = "Atlas · subtensor repo · %s" % reason
    lines = [
        "%s → %s · %d commit(s)%s · %d file(s)%s"
        % (rng["prev_sha"][:12], rng["new_sha"][:12],
           len(rng["commits"]), "+" if rng["commits_truncated"] else "",
           len(rng["files"]), "+" if rng["files_truncated"] else ""),
        _both_clocks_line(new_spec, live),
        "source: repository (source code), not the live chain",
    ]
    breakdown = redact(_breakdown_lines(rng))
    trailer = _digest_line(pending) if pending else None
    plain = render_plain(headline, lines, breakdown, trailer, max_chars)
    html = render_html(headline, lines, breakdown, trailer, max_chars)
    return {"event_id": "repository-update:range:%d" % rng["id"],
            "event_class": "repository-update",
            "created_at": _utc_now(), "text": plain, "html": html,
            "digest_range_ids": [row[0] for row in pending]}


def _build_digest_event(pending: List[Tuple[int, str, str, str]],
                        max_chars: int) -> Dict[str, Any]:
    headline = "Atlas · subtensor repo · low-signal digest"
    lines = ["no protocol or spec_version change in these ranges",
             "source: repository (source code), not the live chain"]
    body = _digest_line(pending)
    plain = render_plain(headline, lines, body, None, max_chars)
    html = render_html(headline, lines, body, None, max_chars)
    return {"event_id": "repository-churn-digest:%d" % pending[-1][0],
            "event_class": "repository-update",
            "created_at": _utc_now(), "text": plain, "html": html,
            "digest_range_ids": [row[0] for row in pending]}


def repository_update_events(source_db: str, watermark: Optional[str],
                             ctx: Optional[Dict[str, Any]] = None
                             ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    conn = open_source_ro(source_db)
    if conn is None:
        return [], watermark
    try:
        wm_id = _resolve_repo_watermark(conn, watermark)
        columns = {row[1] for row in conn.execute(
            "PRAGMA table_info(change_ranges)")}
        spec_cols = (", prev_spec, new_spec"
                     if {"prev_spec", "new_spec"} <= columns
                     else ", NULL, NULL")
        rows = conn.execute(
            "SELECT id, prev_sha, new_sha, retrieved_at, non_fast_forward, "
            "commits_json, files_json, tags_json" + spec_cols +
            " FROM change_ranges WHERE id > ? ORDER BY id ASC LIMIT 50",
            (wm_id or 0,)).fetchall()
    finally:
        conn.close()

    ctx = ctx or {}
    config = ctx.get("config") or {}
    store: Optional[sqlite3.Connection] = ctx.get("connection")
    policy = _repo_policy(ctx)
    max_chars = int(config.get("message_max_chars", 3500))
    live = read_live_spec((ctx.get("spec") or {}).get("live_db"))

    events: List[Dict[str, Any]] = []
    high = wm_id
    for (range_id, prev_sha, new_sha, retrieved_at, non_ff, commits_json,
         files_json, tags_json, prev_spec, new_spec) in rows:
        high = range_id if high is None else max(high, range_id)
        files_data = json.loads(files_json)
        commits_data = json.loads(commits_json)
        rng = {"id": range_id, "prev_sha": prev_sha, "new_sha": new_sha,
               "non_fast_forward": bool(non_ff),
               "files": [item["path"] for item in files_data["files"]],
               "files_truncated": bool(files_data["truncated"]),
               "commits": commits_data.get("commits", []),
               "commits_truncated": bool(commits_data.get("truncated")),
               "tags": json.loads(tags_json),
               "prev_spec": prev_spec, "new_spec": new_spec}
        tier = classify_range(rng, policy)
        if tier == CHURN and store is not None:
            # Durable BEFORE the watermark passes it (never dropped):
            # committed by the same connection's next commit, and
            # idempotent on re-scan if that commit never lands.
            store.execute(
                "INSERT OR IGNORE INTO pending_churn (range_id, prev_sha, "
                "new_sha, dominant_area, detected_at) VALUES (?, ?, ?, ?, ?)",
                (range_id, prev_sha, new_sha,
                 _dominant_area(rng["files"]), _utc_now()))
            continue
        if tier == CHURN:
            tier = SIGNIFICANT  # no durable store → never silently drop
        pending = _pending_churn_rows(store) if store is not None else []
        events.append(_build_repo_event(rng, live, pending, max_chars))

    if not events and store is not None:
        # Backstop: pending churn must not linger forever waiting for a
        # significant alert to ride.
        pending = _pending_churn_rows(store)
        if pending:
            backstop = policy["digest_backstop_hours"] * 3600
            oldest = pending[0][3]
            try:
                age = (datetime.datetime.now(tz=datetime.timezone.utc)
                       - datetime.datetime.fromisoformat(oldest)
                       ).total_seconds()
            except ValueError:
                age = backstop + 1
            if age > backstop:
                events.append(_build_digest_event(pending, max_chars))

    new_wm = str(high) if high is not None else watermark
    return events, new_wm


def chain_runtime_upgrade_events(source_db: str, watermark: Optional[str],
                                 ctx: Optional[Dict[str, Any]] = None
                                 ) -> Tuple[List[Dict[str, Any]],
                                            Optional[str]]:
    """Live runtime upgrades recorded by livedata — the network actually
    changed, as opposed to the source-code repository moving."""
    conn = open_source_ro(source_db)
    if conn is None:
        return [], watermark
    try:
        present = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND "
            "name = 'spec_upgrades'").fetchone()
        if present is None:
            return [], watermark  # livedata not migrated yet: no events
        last_id = int(watermark) if watermark else 0
        rows = conn.execute(
            "SELECT id, observed_at, prev_spec, new_spec, block_reference "
            "FROM spec_upgrades WHERE id > ? ORDER BY id ASC LIMIT 50",
            (last_id,)).fetchall()
    finally:
        conn.close()

    config = (ctx or {}).get("config") or {}
    max_chars = int(config.get("message_max_chars", 3500))
    threshold = int(config.get("governance_threshold",
                               DEFAULT_GOVERNANCE_THRESHOLD))
    events: List[Dict[str, Any]] = []
    high = last_id
    for row_id, observed_at, prev_spec, new_spec, block in rows:
        high = max(high, int(row_id))
        headline = ("Atlas · LIVE CHAIN UPGRADED · Finney runtime "
                    "spec %s → %s" % (prev_spec, new_spec))
        lines = ["the LIVE network changed (enacted), not the source "
                 "repository",
                 "reference block: %s · observed: %s"
                 % (block if block is not None else "unknown",
                    observed_at)]
        if prev_spec < threshold <= new_spec:
            lines.append("governance threshold %d crossed · "
                         "conviction-based subnet ownership enforcement "
                         "is now ENACTED" % threshold)
        plain = render_plain(headline, lines, "", None, max_chars)
        html = render_html(headline, lines, "", None, max_chars)
        events.append({"event_id": "chain-runtime-upgrade:%s" % row_id,
                       "event_class": "chain-runtime-upgrade",
                       "created_at": _utc_now(), "text": plain,
                       "html": html})
    return events, (str(high) if high else watermark)


def schema_drift_events(source_db: str, watermark: Optional[str],
                        ctx: Optional[Dict[str, Any]] = None
                        ) -> Tuple[List[Dict[str, str]], Optional[str]]:
    conn = open_source_ro(source_db)
    if conn is None:
        return [], watermark
    try:
        last_id = int(watermark) if watermark else 0
        rows = conn.execute(
            "SELECT id, timestamp, provider, operation, detail FROM "
            "integration_health WHERE category = 'schema-drift' AND id > ? "
            "ORDER BY id ASC LIMIT 50", (last_id,)).fetchall()
        events: List[Dict[str, str]] = []
        high = last_id
        for row_id, ts, provider, operation, detail in rows:
            high = max(high, int(row_id))
            text = ("Atlas • live-data schema drift\n"
                    "%s / %s\nwhen: %s\n%s"
                    % (provider, operation, ts, (detail or "")[:400]))
            events.append({"event_id": "schema-drift:%s" % row_id,
                           "event_class": "schema-drift",
                           "created_at": _utc_now(), "text": text})
        return events, (str(high) if high else watermark)
    finally:
        conn.close()


def knowledge_ingestion_events(source_db: str, watermark: Optional[str],
                               ctx: Optional[Dict[str, Any]] = None
                               ) -> Tuple[List[Dict[str, str]], Optional[str]]:
    conn = open_source_ro(source_db)
    if conn is None:
        return [], watermark
    try:
        # intake_runs is keyed by run_id, a sortable "%Y%m%dT%H%M%SZ-hex"
        # string; lexicographic ordering is chronological, so the watermark
        # is the highest run_id already notified.
        rows = conn.execute(
            "SELECT run_id, intake_date, coverage_date FROM intake_runs "
            "WHERE run_id > ? ORDER BY run_id ASC LIMIT 50",
            (watermark or "",)).fetchall()
        events: List[Dict[str, str]] = []
        high = watermark
        for rid, intake_date, coverage in rows:
            high = rid
            staged = conn.execute(
                "SELECT COUNT(*) FROM units WHERE run_id = ? AND active = 0",
                (rid,)).fetchone()[0]
            text = ("Atlas • knowledge ingestion complete — review needed\n"
                    "run: %s\ningested: %s\ncoverage: %s\nunits staged: %s"
                    % (rid, intake_date, coverage, staged))
            events.append({"event_id": "knowledge-ingestion:%s" % rid,
                           "event_class": "knowledge-ingestion",
                           "created_at": _utc_now(), "text": text})
        return events, high
    finally:
        conn.close()


_ADAPTERS: Dict[str, Callable[..., Tuple[List[Dict[str, Any]],
                                         Optional[str]]]] = {
    "chain-runtime-upgrade": chain_runtime_upgrade_events,
    "repository-update": repository_update_events,
    "schema-drift": schema_drift_events,
    "knowledge-ingestion": knowledge_ingestion_events,
}


# ---------------------------------------------------------------------------
# Delivery of one event — the isolation boundary lives in the caller
# ---------------------------------------------------------------------------

def deliver_event(connection: sqlite3.Connection, config: Dict[str, Any],
                  token: str, chat_id: str, event: Dict[str, str],
                  poster: Optional[Callable[..., Tuple[int, str]]] = None
                  ) -> str:
    """Scrub → send → record. Returns the terminal status. Any transport
    failure is turned into a recorded 'failed' outcome, not an exception."""
    event_id = event["event_id"]
    event_class = event["event_class"]
    created_at = event["created_at"]
    window = int(config.get("coalesce_window_seconds", 3600))

    if ledger_seen_recent(connection, event_id, window):
        return STATUS_SUPPRESSED

    max_chars = int(config.get("message_max_chars", 3500))
    text = (event["text"] or "")[:max_chars]
    # HTML bodies are sized by the renderer and are NEVER sliced here —
    # a post-render cut can split a tag/entity and 400 the send. An
    # oversized HTML body (renderer contract breach) demotes to plain.
    html = event.get("html") if config.get("parse_mode") == "HTML" else None
    if html and len(html) > max_chars:
        html = None
    try:
        assert_sendable(text)
        if html:
            assert_sendable(html)
    except ScrubRefusal as refusal:
        ledger_record(connection, event_id, event_class, created_at,
                      _utc_now(), STATUS_SCRUB_REFUSED, 0, str(refusal))
        return STATUS_SCRUB_REFUSED

    fallback_note = None
    if html:
        result = send_message(config, token, chat_id, html, poster=poster,
                              parse_mode="HTML")
        if not result["delivered"] and result.get("status") == 400:
            # Rejected formatting must never suppress an alert: resend
            # once as the untagged structured text (never the HTML
            # source) and record the fallback.
            plain_result = send_message(config, token, chat_id, text,
                                        poster=poster)
            plain_result["attempts"] += result["attempts"]
            if plain_result["delivered"]:
                fallback_note = "html-400-fallback: delivered as plain text"
            result = plain_result
    else:
        result = send_message(config, token, chat_id, text, poster=poster)

    if result["delivered"]:
        ledger_record(connection, event_id, event_class, created_at,
                      _utc_now(), STATUS_DELIVERED, result["attempts"],
                      fallback_note)
        return STATUS_DELIVERED
    ledger_record(connection, event_id, event_class, created_at, _utc_now(),
                  STATUS_FAILED, result["attempts"], result["detail"])
    return STATUS_FAILED


def seed_watermarks(config: Dict[str, Any],
                    connection: sqlite3.Connection) -> Dict[str, Any]:
    """Advance every enabled class's watermark to the current source max
    WITHOUT sending anything. Run once at deploy time so the first
    scheduled scan does not replay historical events as an alert flood.
    Only seeds classes that have no watermark yet (idempotent, safe to
    re-run — it never rolls a watermark backward)."""
    seeded: Dict[str, Any] = {}
    for event_class, spec in config["classes"].items():
        if not spec.get("enabled"):
            continue
        adapter = _ADAPTERS.get(event_class)
        if adapter is None:
            continue
        if watermark_get(connection, event_class) is not None:
            seeded[event_class] = "already-seeded"
            continue
        # Seed ctx carries NO store connection: backlog churn must not
        # land in pending_churn (seeding skips history, not digests it).
        ctx = {"config": config, "spec": spec, "connection": None}
        _events, new_wm = adapter(resolve(spec["source_db"]), None, ctx)
        if new_wm:
            watermark_set(connection, event_class, new_wm)
            seeded[event_class] = {"seeded_to": new_wm, "skipped": len(_events)}
        else:
            seeded[event_class] = "no-source-yet"
    return seeded


def notify_scan(config: Dict[str, Any], token: str, chat_id: str,
                connection: sqlite3.Connection,
                poster: Optional[Callable[..., Tuple[int, str]]] = None
                ) -> Dict[str, Any]:
    """Scan every enabled class, deliver new events, advance watermarks.
    Per-event failures are isolated: one bad event or a Telegram outage
    never aborts the scan or touches core Atlas state."""
    summary: Dict[str, Any] = {"run_id": run_id(), "classes": {}}
    for event_class, spec in config["classes"].items():
        if not spec.get("enabled"):
            continue
        adapter = _ADAPTERS.get(event_class)
        if adapter is None:
            summary["classes"][event_class] = {"error": "no adapter"}
            continue
        source_db = resolve(spec["source_db"])
        wm = watermark_get(connection, event_class)
        counts = {"delivered": 0, "suppressed": 0, "failed": 0,
                  "scrub-refused": 0, "error": 0}
        ctx = {"config": config, "spec": spec, "connection": connection}
        try:
            events, new_wm = adapter(source_db, wm, ctx)
        except Exception as exc:  # adapter is isolated from the scan
            summary["classes"][event_class] = {
                "error": redact(str(exc))[:200]}
            continue
        for event in events:
            try:
                status = deliver_event(connection, config, token, chat_id,
                                       event, poster=poster)
                counts[status] = counts.get(status, 0) + 1
                if (status == STATUS_DELIVERED
                        and event.get("digest_range_ids")):
                    # Pending churn clears ONLY once its digest was in a
                    # delivered message (never dropped, auditable).
                    connection.executemany(
                        "DELETE FROM pending_churn WHERE range_id = ?",
                        [(rid,) for rid in event["digest_range_ids"]])
            except Exception as exc:  # never let one event break the loop
                counts["error"] += 1
                ledger_record(connection, event["event_id"],
                              event["event_class"], event["created_at"],
                              _utc_now(), STATUS_FAILED, 0,
                              redact(str(exc)))
        if new_wm and new_wm != wm:
            watermark_set(connection, event_class, new_wm)
        else:
            connection.commit()  # land pending churn even when wm is unchanged
        summary["classes"][event_class] = counts
    return summary


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _cmd_scan(config: Dict[str, Any]) -> int:
    token, chat_id = resolve_credentials(config)  # validate before any state
    connection = open_store(resolve(config["db"]))
    try:
        summary = notify_scan(config, token, chat_id, connection)
    finally:
        connection.close()
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


def _cmd_test(config: Dict[str, Any], event_class: str) -> int:
    if event_class not in _ADAPTERS:
        raise FatalTelegramError("unknown class %r" % event_class)
    token, chat_id = resolve_credentials(config)  # validate before any state
    connection = open_store(resolve(config["db"]))
    try:
        event = {"event_id": "test:%s:%s" % (event_class, run_id()),
                 "event_class": event_class, "created_at": _utc_now(),
                 "text": "Atlas • test alert (%s) — delivery check only"
                         % event_class}
        status = deliver_event(connection, config, token, chat_id, event)
    finally:
        connection.close()
    print(json.dumps({"class": event_class, "status": status},
                     indent=2, sort_keys=True))
    return 0 if status == STATUS_DELIVERED else 1


def _cmd_init(config: Dict[str, Any]) -> int:
    connection = open_store(resolve(config["db"]))
    try:
        seeded = seed_watermarks(config, connection)
    finally:
        connection.close()
    print(json.dumps({"seeded": seeded}, indent=2, sort_keys=True))
    return 0


def _cmd_status(config: Dict[str, Any]) -> int:
    db = resolve(config["db"])
    if not os.path.exists(db):
        print(json.dumps({"store": "absent", "db": db}))
        return 0
    connection = open_store(db)
    try:
        rows = connection.execute(
            "SELECT event_class, status, COUNT(*) FROM events "
            "GROUP BY event_class, status ORDER BY event_class, status"
        ).fetchall()
        wm = connection.execute(
            "SELECT source, value, updated_at FROM watermarks").fetchall()
    finally:
        connection.close()
    print(json.dumps(
        {"ledger": [{"class": c, "status": s, "count": n} for c, s, n in rows],
         "watermarks": [{"source": s, "value": v, "updated_at": u}
                        for s, v, u in wm]},
        indent=2, sort_keys=True))
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Atlas outbound Telegram operational notifier")
    parser.add_argument("--config", default=CONFIG_FILE)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init", help="seed watermarks to now (no sends) — run once "
                                "at deploy so the first scan skips backlog")
    sub.add_parser("scan", help="deliver new events for all enabled classes")
    test = sub.add_parser("test", help="send one test alert of a class")
    test.add_argument("--class", dest="event_class", required=True)
    sub.add_parser("status", help="show ledger + watermark summary")
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
        if args.command == "init":
            return _cmd_init(config)
        if args.command == "scan":
            return _cmd_scan(config)
        if args.command == "test":
            return _cmd_test(config, args.event_class)
        if args.command == "status":
            return _cmd_status(config)
    except FatalTelegramError as exc:
        print("fatal: %s" % redact(str(exc)), file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
