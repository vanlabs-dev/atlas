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
- three source adapters read existing stores read-only and surface only
  events past a persisted per-source watermark:
    repository-update   <- var/repotrack/repotrack.db  (last_remote_sha)
    schema-drift        <- var/livedata/livedata.db     (integration_health)
    knowledge-ingestion <- var/knowledge/knowledge.db   (intake_runs)
- a **refuse-don't-truncate** scrubber gates every send, built on the
  pinned inventory redaction oracle plus the registered bot token;
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
"""

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
                 = None) -> Dict[str, Any]:
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
    payload = urllib.parse.urlencode(
        {"chat_id": chat_id, "text": text,
         "disable_web_page_preview": "true"}).encode("utf-8")

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
#   {event_id, event_class, created_at, text}
# Adapters never mutate their source and never invent data.


def repository_update_events(source_db: str, watermark: Optional[str]
                             ) -> Tuple[List[Dict[str, str]], Optional[str]]:
    conn = open_source_ro(source_db)
    if conn is None:
        return [], watermark
    try:
        row = conn.execute(
            "SELECT value FROM meta WHERE key = 'last_remote_sha'").fetchone()
        sha = row[0] if row else None
        if not sha or sha == watermark:
            return [], watermark
        detected = conn.execute(
            "SELECT value FROM meta WHERE key = 'last_detected_update'"
        ).fetchone()
        when = detected[0] if detected else _utc_now()
        text = ("Atlas • subtensor repository updated\n"
                "new head: %s\ndetected: %s" % (sha[:12], when))
        event = {"event_id": "repository-update:%s" % sha,
                 "event_class": "repository-update",
                 "created_at": _utc_now(), "text": text}
        return [event], sha
    finally:
        conn.close()


def schema_drift_events(source_db: str, watermark: Optional[str]
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


def knowledge_ingestion_events(source_db: str, watermark: Optional[str]
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


_ADAPTERS: Dict[str, Callable[[str, Optional[str]],
                              Tuple[List[Dict[str, str]], Optional[str]]]] = {
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

    text = (event["text"] or "")[:int(config.get("message_max_chars", 3500))]
    try:
        assert_sendable(text)
    except ScrubRefusal as refusal:
        ledger_record(connection, event_id, event_class, created_at,
                      _utc_now(), STATUS_SCRUB_REFUSED, 0, str(refusal))
        return STATUS_SCRUB_REFUSED

    result = send_message(config, token, chat_id, text, poster=poster)
    if result["delivered"]:
        ledger_record(connection, event_id, event_class, created_at,
                      _utc_now(), STATUS_DELIVERED, result["attempts"], None)
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
        _events, new_wm = adapter(resolve(spec["source_db"]), None)
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
        try:
            events, new_wm = adapter(source_db, wm)
        except Exception as exc:  # adapter is isolated from the scan
            summary["classes"][event_class] = {
                "error": redact(str(exc))[:200]}
            continue
        for event in events:
            try:
                status = deliver_event(connection, config, token, chat_id,
                                       event, poster=poster)
                counts[status] = counts.get(status, 0) + 1
            except Exception as exc:  # never let one event break the loop
                counts["error"] += 1
                ledger_record(connection, event["event_id"],
                              event["event_class"], event["created_at"],
                              _utc_now(), STATUS_FAILED, 0,
                              redact(str(exc)))
        if new_wm and new_wm != wm:
            watermark_set(connection, event_class, new_wm)
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
