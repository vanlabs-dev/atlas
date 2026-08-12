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
- source adapters read existing stores read-only and surface only
  events past a persisted per-source watermark:
    chain-runtime-upgrade <- var/livedata/livedata.db   (spec_upgrades)
    gate-crossing         <- var/livedata/livedata.db   (gate_events)
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
import re
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
CREATE TABLE IF NOT EXISTS pending_signal (
    event_row_id INTEGER PRIMARY KEY,
    line TEXT NOT NULL,
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

# Interpreted-breakdown display policy (config-overridable). This is the
# PRESENTATION taxonomy — distinct from the significance policy above, which
# governs paging. Classes: core (protocol logic), node (client/network),
# noise (housekeeping). A top-level dir absent from the map is UNKNOWN and is
# surfaced on its own line, never folded into noise — the same deny-by-default
# posture the classifier takes toward never-seen dirs. Grounded in the live
# opentensor/subtensor tree.
CORE, NODE, NOISE, UNKNOWN = "core", "node", "noise", "unknown"
_ROOT_AREA = "(root)"  # synthetic bucket for repo-root files (no '/')
DEFAULT_AREA_MAP = {
    "pallets": CORE, "runtime": CORE, "precompiles": CORE,
    "common": CORE, "primitives": CORE,
    "node": NODE, "chainspecs": NODE, "chain-extensions": NODE,
    "vendor": NOISE, "website": NOISE, "docs": NOISE, "sdk": NOISE,
    ".github": NOISE, "ts-tests": NOISE, "eco-tests": NOISE, "clones": NOISE,
    "scripts": NOISE, ".maintain": NOISE, "support": NOISE,
    "ink-contract": NOISE, ".agents": NOISE, ".claude": NOISE,
    ".vscode": NOISE, _ROOT_AREA: NOISE,
}
# pallets/<name> -> the domain the pallet governs, for semantic labels.
DEFAULT_PALLET_MAP = {
    "subtensor": "staking/emissions/weights",
    "admin-utils": "governance params",
    "swap": "dTAO economics", "limit-orders": "dTAO economics",
    "alpha-assets": "dTAO economics", "transaction-fee": "dTAO economics",
    "drand": "randomness", "shield": "MEV shield",
    "commitments": "commit-reveal", "crowdloan": "crowdloan",
    "proxy": "account tooling", "utility": "account tooling",
}
DEFAULT_LIGHT_TOUCH_RATIO = 0.15

# Commit-subject conventions for the meaningful-commit filter. There is no
# recorded commit->file map, so selection ranks SUBJECTS only.
_CONV_PREFIX_RE = re.compile(r"^([a-z]+)(\([^)]*\))?!?:")
_COMMIT_NOISE_PREFIXES = frozenset(("ci", "test", "docs", "build", "style"))
_COMMIT_HIGH_PREFIXES = frozenset(("feat", "fix", "refactor", "perf"))
_RELEASE_KEYWORDS = ("spec_version", "version", "release")
_PROTOCOL_KEYWORDS = ("pallet", "runtime", "spec_version", "staking",
                      "emission", "weight", "consensus", "governance")

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


def resolve(path: str, repo_root: Optional[str] = None) -> str:
    path = os.path.expanduser(path)
    root = _REPO_ROOT if repo_root is None else repo_root
    return path if os.path.isabs(path) else os.path.join(root, path)


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
                "api_base", "db", "retry", "classes", "voice"):
        if key not in config:
            raise FatalTelegramError("config missing %r" % key)
    voice_maps(config)
    return config


def voice_maps(config: Dict[str, Any]) -> Tuple[Dict[str, str],
                                                Dict[str, str]]:
    """The REQUIRED voice maps (change: telegram-voice-overhaul): lexicon
    (concept -> the one approved word) and gloss (jargon term -> its one
    first-use parenthetical gloss), canon telegram/docs/voice.md section 2.
    Fail closed: a missing or malformed map refuses the render rather than
    falling back to untested code defaults."""
    voice = config.get("voice")
    if not isinstance(voice, dict):
        raise FatalTelegramError(
            "config missing 'voice' (lexicon + gloss maps are required; "
            "canon: telegram/docs/voice.md)")
    lexicon, gloss = voice.get("lexicon"), voice.get("gloss")
    for name, mapping in (("voice.lexicon", lexicon),
                          ("voice.gloss", gloss)):
        if (not isinstance(mapping, dict) or not mapping
                or not all(isinstance(k, str) and isinstance(v, str)
                           and k and v for k, v in mapping.items())):
            raise FatalTelegramError(
                "config %s must be a non-empty string map" % name)
    return lexicon, gloss


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


# Inline-mono markers (operator layout feedback 2026-07-15). Composed
# header lines may wrap a span in these sentinels; render_html turns the
# span into a <code> entity AFTER escaping (so the span itself is still
# escaped), render_plain strips them. Imported free text (subjects, dir
# names) never legitimately contains control chars — both renderers strip
# stray sentinels from the expandable/trailer so recorded data can never
# smuggle an unbalanced tag into the HTML body.
_MONO_OPEN = "\x01"
_MONO_CLOSE = "\x02"
# Bold-span sentinels (econ card labels). Like the mono pair: converted to
# <b>/</b> AFTER escaping in render_html body lines, stripped everywhere else.
_BOLD_OPEN = "\x03"
_BOLD_CLOSE = "\x04"


def _strip_mono(text: str) -> str:
    return (text.replace(_MONO_OPEN, "").replace(_MONO_CLOSE, "")
            .replace(_BOLD_OPEN, "").replace(_BOLD_CLOSE, ""))


def _gloss_message(headline: str, lines: List[str], expandable: str,
                   trailer: Optional[str], next_action: Optional[str],
                   glosses: Dict[str, str]
                   ) -> Tuple[str, List[str], str, Optional[str],
                              Optional[str]]:
    """Attach ' (gloss)' to the FIRST use of each glossed term across the
    message, in render order (headline -> lines -> expandable -> trailer ->
    next-action); later uses in the same message stay bare (voice canon
    section 2). A term abutting a mono sentinel keeps the gloss OUTSIDE the
    code span. Matches on word boundaries, case-insensitive, and never
    inside a hyphenated compound."""
    remaining = dict(glosses)
    parts: List[Any] = [headline, list(lines), expandable, trailer,
                        next_action]
    for index, part in enumerate(parts):
        is_scalar = not isinstance(part, list)
        texts = [part] if is_scalar else part
        for term in list(remaining):
            pattern = re.compile(r"(?<![\w-])" + re.escape(term)
                                 + r"(?![\w-])", re.IGNORECASE)
            for pos, text in enumerate(texts):
                if not text:
                    continue
                match = pattern.search(text)
                if match is None:
                    continue
                insert_at = match.end()
                if text[insert_at:insert_at + 1] == _MONO_CLOSE:
                    insert_at += 1
                gloss = " (" + _typography(remaining.pop(term)) + ")"
                texts[pos] = text[:insert_at] + gloss + text[insert_at:]
                break
        if is_scalar:
            parts[index] = texts[0]
    return (parts[0], parts[1], parts[2], parts[3], parts[4])


def render_html(headline: str, lines: List[str], expandable: str,
                trailer: Optional[str], max_chars: int,
                next_action: Optional[str] = None,
                glosses: Optional[Dict[str, str]] = None) -> str:
    """Compose the supported-tag HTML body, shrinking the expandable
    content (never the markup) until the result fits max_chars.

    Shrink order protects the verdict-led layout (voice canon): the
    expandable absorbs shrinkage first, the trailer drops next, body fact
    lines drop before the next-action line, and the headline is never
    dropped. Glosses re-apply from the unglossed base each pass so a
    dropped line never strands a later use unglossed."""
    headline = _strip_mono(_typography(headline))
    lines = [_typography(line) for line in lines]
    expandable = _strip_mono(_typography(expandable))
    trailer = _strip_mono(_typography(trailer)) if trailer else None
    # next_action keeps its mono sentinels: composed classes wrap command
    # spans in them (watchlist commit, knowledge activate) and the escape
    # pass below converts them, exactly like body lines.
    next_action = _typography(next_action) if next_action else None
    while True:
        rendered = _gloss_message(headline, lines, expandable, trailer,
                                  next_action, glosses) if glosses else (
            headline, lines, expandable, trailer, next_action)
        r_head, r_lines, r_exp, r_trailer, r_next = rendered
        parts = ["<b>%s</b>" % html_escape(r_head)]
        parts.extend(html_escape(line)
                     .replace(_MONO_OPEN, "<code>")
                     .replace(_MONO_CLOSE, "</code>")
                     .replace(_BOLD_OPEN, "<b>")
                     .replace(_BOLD_CLOSE, "</b>") for line in r_lines)
        if r_exp:
            parts.append("<blockquote expandable>%s</blockquote>"
                         % html_escape(r_exp))
        if r_trailer:
            parts.append("<i>%s</i>" % html_escape(r_trailer))
        if r_next:
            parts.append(html_escape(r_next)
                         .replace(_MONO_OPEN, "<code>")
                         .replace(_MONO_CLOSE, "</code>"))
        body = "\n".join(parts)
        if len(body) <= max_chars:
            return body
        overshoot = len(body) - max_chars
        if expandable and len(expandable) > 40:
            expandable = expandable[:max(20, len(expandable)
                                         - overshoot - 20)] + "…"
        elif trailer:
            trailer = None
        elif lines:
            lines = lines[:-1]
        elif next_action:
            next_action = None
        else:
            break  # headline alone remains: never dropped
    return "<b>%s</b>" % html_escape(headline[:max_chars - 7])


def render_plain(headline: str, lines: List[str], expandable: str,
                 trailer: Optional[str], max_chars: int,
                 next_action: Optional[str] = None,
                 glosses: Optional[Dict[str, str]] = None) -> str:
    if glosses:
        headline, lines, expandable, trailer, next_action = _gloss_message(
            headline, list(lines), expandable, trailer, next_action,
            glosses)
    parts = [headline] + list(lines)
    if expandable:
        parts.append(expandable)
    if trailer:
        parts.append(trailer)
    if next_action:
        parts.append(next_action)
    return _strip_mono(_typography("\n".join(parts)))[:max_chars]


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
    area_map = dict(DEFAULT_AREA_MAP)
    area_map.update(policy.get("area_map") or {})
    pallet_map = dict(DEFAULT_PALLET_MAP)
    pallet_map.update(policy.get("pallet_map") or {})
    return {
        "protocol_dirs": set(policy.get("protocol_dirs",
                                        DEFAULT_PROTOCOL_DIRS)),
        "churn_dirs": set(policy.get("churn_dirs", DEFAULT_CHURN_DIRS)),
        "digest_backstop_hours": float(policy.get(
            "digest_backstop_hours", DEFAULT_DIGEST_BACKSTOP_HOURS)),
        "area_map": area_map,
        "pallet_map": pallet_map,
        "light_touch_ratio": float(policy.get(
            "light_touch_ratio", DEFAULT_LIGHT_TOUCH_RATIO)),
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
    read-only. None when unavailable — the caller degrades honestly.

    Paths are resolved against the Atlas repo root (same as source_db).
    Config stores relative paths like ``var/livedata/livedata.db``; the
    hourly systemd unit has no WorkingDirectory, so opening the relative
    path from cwd would miss the store and always report live unavailable.
    """
    if not live_db:
        return None
    conn = open_source_ro(resolve(live_db))
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
        return ("live spec n/a · cannot compare · repo event only")
    if new_spec is None:
        return ("repo spec n/a · live Finney spec %d · not enacted "
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
    return ("digested %d low-signal update(s): %s · no protocol or "
            "runtime spec change" % (len(pending), items))


def _area_class(top: str, area_map: Dict[str, str]) -> str:
    """Display class for a top-level dir. Absent => UNKNOWN (surfaced,
    never hidden), mirroring the classifier's deny-by-default posture."""
    return area_map.get(top, UNKNOWN)


def _aggregate_areas(file_entries: List[Any], files_truncated: bool,
                     area_map: Dict[str, str]) -> List[Dict[str, Any]]:
    """Per-top-level-dir aggregation from recorded file entries. Repo-root
    files (no '/') group under (root). Absent additions/deletions count as 0
    for churn but still count the file. Sorted by line churn desc. When the
    file list is truncated every count is a lower bound (partial=True)."""
    agg: Dict[str, Dict[str, Any]] = {}
    for entry in file_entries:
        path = entry["path"] if isinstance(entry, dict) else entry
        top = path.split("/", 1)[0] if "/" in path else _ROOT_AREA
        area = agg.setdefault(top, {"area": top,
                                    "cls": _area_class(top, area_map),
                                    "files": 0, "adds": 0, "dels": 0,
                                    "partial": files_truncated})
        area["files"] += 1
        if isinstance(entry, dict):
            area["adds"] += entry.get("additions") or 0
            area["dels"] += entry.get("deletions") or 0
    return sorted(agg.values(),
                  key=lambda a: (-(a["adds"] + a["dels"]), -a["files"],
                                 a["area"]))


def _compact(n: int) -> str:
    """Compact line-count: 3162 -> 3.2k, 1_240_000 -> 1.2m."""
    if n < 1000:
        return str(n)
    if n < 1_000_000:
        return ("%.1fk" % (n / 1000)).replace(".0k", "k")
    return ("%.1fm" % (n / 1_000_000)).replace(".0m", "m")


def _area_churn(area: Dict[str, Any]) -> str:
    tail = " (partial)" if area["partial"] else ""
    if area["adds"] or area["dels"]:
        return "%s %d files +%s/-%s%s" % (
            area["area"], area["files"], _compact(area["adds"]),
            _compact(area["dels"]), tail)
    return "%s %d files%s" % (area["area"], area["files"], tail)


def _pallet_domains(file_entries: List[Any],
                    pallet_map: Dict[str, str]) -> List[str]:
    """Pallets touched, labelled with the domain each governs, from the
    second segment of recorded `pallets/<name>/...` paths. Order-stable,
    de-duplicated."""
    domains: List[str] = []
    seen = set()
    for entry in file_entries:
        path = entry["path"] if isinstance(entry, dict) else entry
        parts = path.split("/")
        if len(parts) >= 2 and parts[0] == "pallets" and parts[1] not in seen:
            seen.add(parts[1])
            label = pallet_map.get(parts[1])
            domains.append("%s (%s)" % (parts[1], label) if label
                           else parts[1])
    return domains


def _conv_prefix(subject: str) -> str:
    match = _CONV_PREFIX_RE.match(subject)
    return match.group(1) if match else ""


def _filter_commits(commits: List[Dict[str, Any]]) -> List[str]:
    """Rank commit SUBJECTS (no commit->file map exists, so this is a
    subject heuristic, not 'the commits that changed area X'). Drop merges
    and ci/test/docs/build/style; drop chore unless it names a release;
    rank feat/fix/refactor/perf and protocol-keyword subjects first."""
    kept: List[str] = []
    for commit in commits:
        subject = (commit.get("subject") or "").strip()
        if not subject or subject.startswith("Merge "):
            continue
        prefix = _conv_prefix(subject)
        if prefix in _COMMIT_NOISE_PREFIXES:
            continue
        if prefix == "chore" and not any(
                kw in subject.lower() for kw in _RELEASE_KEYWORDS):
            continue
        kept.append(subject)

    def rank(subject: str) -> int:
        if _conv_prefix(subject) in _COMMIT_HIGH_PREFIXES:
            return 0
        if any(kw in subject.lower() for kw in _PROTOCOL_KEYWORDS):
            return 1
        return 2

    return sorted(kept, key=rank)  # stable: original order within a rank


def _repo_verdict(rng: Dict[str, Any], live: Optional[Dict[str, Any]],
                  areas: List[Dict[str, Any]], policy: Dict[str, Any]) -> str:
    """Ordered, deterministic verdict over recorded facts only. Each rule
    assumes the earlier ones did not fire; ordering keeps it from ever
    claiming a signal the data does not support."""
    prev_spec, new_spec = rng["prev_spec"], rng["new_spec"]
    spec_changed = (prev_spec is not None and new_spec is not None
                    and prev_spec != new_spec)
    # (1) Incomplete record: a truncated file list makes any ratio a lie,
    #     and a rewritten history means the commit set is unknown.
    if rng["non_fast_forward"] or (rng["files_truncated"] and not spec_changed):
        return "large or incomplete range · review"
    # (2) Runtime spec bump: the strongest signal, outranks file-count mix.
    if spec_changed:
        return "runtime spec bump %d → %d" % (prev_spec, new_spec)
    core = [a for a in areas if a["cls"] == CORE]
    unknown = [a for a in areas if a["cls"] == UNKNOWN]
    node = [a for a in areas if a["cls"] == NODE]
    # (3) Unknown area: exactly what the classifier escalated for — surface.
    if unknown:
        return "new unmapped area: %s" % " · ".join(
            a["area"] for a in unknown[:4])
    core_churn = sum(a["adds"] + a["dels"] for a in core)
    # (4) Light touch: core exists but is a small share of LINE churn (not
    #     file count). Guarded by core_churn > 0 so it never claims a
    #     protocol touch that did not happen.
    if core_churn > 0:
        total_churn = sum(a["adds"] + a["dels"] for a in areas)
        share = core_churn / total_churn if total_churn else 1.0
        if share < policy["light_touch_ratio"]:
            return "large sync · light protocol touch"
    elif core:
        # Core files changed but no line churn recorded: fall back to file
        # share so a light touch is still recognised.
        core_files = sum(a["files"] for a in core)
        total_files = sum(a["files"] for a in areas) or 1
        if core_files / total_files < policy["light_touch_ratio"]:
            return "large sync · light protocol touch"
    # (5) Core change. The headline stays the short category only; the
    #     pallets touched and their domains are already enumerated in the
    #     body's "pallets ·" line, so repeating them here just makes the
    #     bold title wrap (operator feedback 2026-07-14: fix layout, keep
    #     the information).
    if core:
        return "core protocol change"
    # (6) Node/network only.
    if node:
        return "node / network change"
    # (7) Neutral fallback.
    return "repo change"


def _breakdown_lines(rng: Dict[str, Any], areas: List[Dict[str, Any]],
                     policy: Dict[str, Any]) -> str:
    """Interpreted breakdown: one fact per line, signal split from noise,
    built only from already-recorded fields (operator feedback 2026-07-14:
    'none of the info really tells me anything'). Groups are separated by
    a blank line (operator layout feedback 2026-07-15: break the wall of
    text) — signal, then noise/context, then commits, then the trailer."""
    core = [a for a in areas if a["cls"] == CORE]
    unknown = [a for a in areas if a["cls"] == UNKNOWN]
    node = [a for a in areas if a["cls"] == NODE]
    noise = [a for a in areas if a["cls"] == NOISE]

    signal: List[str] = []
    if core:
        signal.append("protocol changed · " + " · ".join(
            _area_churn(a) for a in core[:6]))
        domains = _pallet_domains(rng["file_entries"], policy["pallet_map"])
        if domains:
            signal.append("pallets · " + " · ".join(domains[:4]))
    if unknown:
        signal.append("NEW / unclassified area · " + " · ".join(
            _area_churn(a) for a in unknown[:6]))

    context: List[str] = []
    if node:
        context.append("node / network · " + " · ".join(
            "%s (%d)" % (a["area"], a["files"]) for a in node[:6]))
    if noise:
        context.append("housekeeping · " + " · ".join(
            "%s (%d)" % (a["area"], a["files"]) for a in noise[:8]))
    if rng["tags"]:
        context.append("tags · " + " · ".join(rng["tags"][:10]))

    commits_group: List[str] = []
    commits = _filter_commits(rng["commits"])
    if commits:
        commits_group.extend("• " + subject[:100] for subject in commits[:5])
    else:
        commits_group.append(
            "• no feature or fix commits in range (tooling only)")
    if rng["commits_truncated"]:
        commits_group.append("commit list truncated at cap · sample only")

    trailer_group: List[str] = []
    if rng["files_truncated"] or rng["non_fast_forward"]:
        trailer_group.append(
            "counts are a lower bound · change record incomplete")
    trailer_group.append("from recorded change data · effects not verified")

    groups = [signal, context, commits_group, trailer_group]
    return "\n\n".join("\n".join(g) for g in groups if g)


def _build_repo_event(rng: Dict[str, Any], live: Optional[Dict[str, Any]],
                      pending: List[Tuple[int, str, str, str]],
                      max_chars: int,
                      policy: Dict[str, Any],
                      glosses: Dict[str, str]) -> Dict[str, Any]:
    new_spec = rng["new_spec"]
    areas = _aggregate_areas(rng["file_entries"], rng["files_truncated"],
                             policy["area_map"])
    verdict = _repo_verdict(rng, live, areas, policy)
    headline = "Atlas · subtensor repo · %s" % verdict
    lines = [
        "%s%s → %s%s · %d commit(s)%s · %d file(s)%s"
        % (_MONO_OPEN, rng["prev_sha"][:12], rng["new_sha"][:12], _MONO_CLOSE,
           len(rng["commits"]), "+" if rng["commits_truncated"] else "",
           len(rng["files"]), "+" if rng["files_truncated"] else ""),
        _both_clocks_line(new_spec, live),
        "source: repo (source code), not the live chain",
    ]
    breakdown = redact(_breakdown_lines(rng, areas, policy))
    trailer = _digest_line(pending) if pending else None
    plain = render_plain(headline, lines, breakdown, trailer, max_chars,
                         glosses=glosses)
    html = render_html(headline, lines, breakdown, trailer, max_chars,
                       glosses=glosses)
    return {"event_id": "repository-update:range:%d" % rng["id"],
            "event_class": "repository-update",
            "created_at": _utc_now(), "text": plain, "html": html,
            "digest_range_ids": [row[0] for row in pending]}


def _build_digest_event(pending: List[Tuple[int, str, str, str]],
                        max_chars: int,
                        glosses: Dict[str, str]) -> Dict[str, Any]:
    headline = "Atlas · subtensor repo · low-signal digest"
    lines = ["no protocol or runtime spec change in these ranges",
             "source: repo (source code), not the live chain"]
    body = _digest_line(pending)
    plain = render_plain(headline, lines, body, None, max_chars,
                         glosses=glosses)
    html = render_html(headline, lines, body, None, max_chars,
                       glosses=glosses)
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
    _lexicon, glosses = voice_maps(config)
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
               "file_entries": files_data["files"],
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
        events.append(_build_repo_event(rng, live, pending, max_chars,
                                        policy, glosses))

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
                events.append(_build_digest_event(pending, max_chars,
                                                  glosses))

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
    _lexicon, glosses = voice_maps(config)
    events: List[Dict[str, Any]] = []
    high = last_id
    for row_id, observed_at, prev_spec, new_spec, block in rows:
        high = max(high, int(row_id))
        headline = ("Atlas · live chain upgraded · runtime spec %s → %s "
                    "enacted" % (prev_spec, new_spec))
        lines = ["the live chain changed (enacted), not the repo",
                 "reference block: %s · observed: %s"
                 % (block if block is not None else "n/a",
                    observed_at)]
        next_action = None
        if prev_spec < threshold <= new_spec:
            lines.append("governance spec %d crossed · conviction-based "
                         "subnet ownership enforcement is now enacted"
                         % threshold)
            next_action = ("next: review your subnet positions · "
                           "conviction enforcement is live")
        plain = render_plain(headline, lines, "", None, max_chars,
                             next_action=next_action, glosses=glosses)
        html = render_html(headline, lines, "", None, max_chars,
                           next_action=next_action, glosses=glosses)
        events.append({"event_id": "chain-runtime-upgrade:%s" % row_id,
                       "event_class": "chain-runtime-upgrade",
                       "created_at": _utc_now(), "text": plain,
                       "html": html})
    return events, (str(high) if high else watermark)


def schema_drift_events(source_db: str, watermark: Optional[str],
                        ctx: Optional[Dict[str, Any]] = None
                        ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """A provider reply stopped matching its pinned schema. livedata fails
    closed on drift (the operation reports live-unavailable until the
    pinned schema is updated), so every drift event carries its one
    follow-up. Reads integration_health read-only past a row-id watermark."""
    conn = open_source_ro(source_db)
    if conn is None:
        return [], watermark
    try:
        last_id = int(watermark) if watermark else 0
        rows = conn.execute(
            "SELECT id, timestamp, provider, operation, detail FROM "
            "integration_health WHERE category = 'schema-drift' AND id > ? "
            "ORDER BY id ASC LIMIT 50", (last_id,)).fetchall()
    finally:
        conn.close()

    config = (ctx or {}).get("config") or {}
    max_chars = int(config.get("message_max_chars", 3500))
    _lexicon, glosses = voice_maps(config)
    events: List[Dict[str, Any]] = []
    high = last_id
    for row_id, ts, provider, operation, detail in rows:
        high = max(high, int(row_id))
        headline = ("Atlas · schema drift · %s %s replies no longer match "
                    "the pinned schema" % (provider, operation))
        lines = [
            "provider: %s · operation: %s" % (provider, operation),
            "detail: %s" % ((detail or "n/a")[:400]),
            "the %s operation fails closed (live-unavailable) until the "
            "pinned schema is updated" % operation,
            "source: livedata integration health · observed: %s" % ts,
        ]
        next_action = ("next: review the pinned schema for %s %s"
                       % (provider, operation))
        plain = render_plain(headline, lines, "", None, max_chars,
                             next_action=next_action, glosses=glosses)
        html = render_html(headline, lines, "", None, max_chars,
                           next_action=next_action, glosses=glosses)
        events.append({"event_id": "schema-drift:%s" % row_id,
                       "event_class": "schema-drift",
                       "created_at": _utc_now(), "text": plain,
                       "html": html})
    return events, (str(high) if high else watermark)


def knowledge_ingestion_events(source_db: str, watermark: Optional[str],
                               ctx: Optional[Dict[str, Any]] = None
                               ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """A knowledge intake run staged new units. Staged units are not
    active until the operator reviews the run and activates it, so the
    next-action rides the recorded staged count (zero staged: nothing to
    review, no action line)."""
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
        staged_counts = {}
        for rid, _intake_date, _coverage_date in rows:
            staged_counts[rid] = conn.execute(
                "SELECT COUNT(*) FROM units WHERE run_id = ? AND active = 0",
                (rid,)).fetchone()[0]
    finally:
        conn.close()

    config = (ctx or {}).get("config") or {}
    max_chars = int(config.get("message_max_chars", 3500))
    _lexicon, glosses = voice_maps(config)
    events: List[Dict[str, Any]] = []
    high = watermark
    for rid, intake_date, coverage in rows:
        high = rid
        staged = staged_counts[rid]
        headline = ("Atlas · knowledge ingestion complete · %d units staged"
                    % staged)
        lines = [
            "run: %s" % rid,
            "ingested: %s · coverage: %s" % (intake_date, coverage),
            "source: knowledge intake store",
        ]
        next_action = None
        if staged > 0:
            lines.append("staged units are not active until reviewed and "
                         "activated")
            next_action = ("next: review the staged units, then run "
                           "%sactivate --run %s%s"
                           % (_MONO_OPEN, rid, _MONO_CLOSE))
        plain = render_plain(headline, lines, "", None, max_chars,
                             next_action=next_action, glosses=glosses)
        html = render_html(headline, lines, "", None, max_chars,
                           next_action=next_action, glosses=glosses)
        events.append({"event_id": "knowledge-ingestion:%s" % rid,
                       "event_class": "knowledge-ingestion",
                       "created_at": _utc_now(), "text": plain,
                       "html": html})
    return events, high


DEFAULT_GATE_COOLDOWN_HOURS = 24


def _gate_cooldown_active(store: Optional[sqlite3.Connection],
                          netuid: int, hours: float) -> bool:
    """True when a gate-crossing alert for this netuid was DELIVERED
    within the cooldown window (per-netuid paging damper — recorded
    events are never dropped, only not paged)."""
    if store is None or hours <= 0:
        return False
    cutoff = (datetime.datetime.now(tz=datetime.timezone.utc)
              - datetime.timedelta(hours=hours)).isoformat()
    row = store.execute(
        "SELECT 1 FROM events WHERE event_class = 'gate-crossing' AND "
        "status = ? AND event_id LIKE ? AND attempted_at >= ? LIMIT 1",
        (STATUS_DELIVERED, "gate-crossing:%d:%%" % netuid,
         cutoff)).fetchone()
    return row is not None


def gate_crossing_events(source_db: str, watermark: Optional[str],
                         ctx: Optional[Dict[str, Any]] = None
                         ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """Confirmed emission-gate crossings recorded by livedata (change:
    gate-crossing-signal) — a subnet's demand share crossed the spec-440
    gate bar, an economic cliff in either direction. Instant tier with a
    per-netuid cooldown: events inside the cooldown are recorded in the
    delivery ledger as suppressed, never dropped. The share is
    panel-derived (TaoSwap), the bar is chain-read; the body names both
    sources."""
    conn = open_source_ro(source_db)
    if conn is None:
        return [], watermark
    try:
        present = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND "
            "name = 'gate_events'").fetchone()
        if present is None:
            return [], watermark  # gate signal not deployed yet
        last_id = int(watermark) if watermark else 0
        # prev_theta and the bar-mode columns arrived with network-drift-443;
        # a store written before that migration simply reports them NULL and
        # the body then asserts neither a mode nor a movement.
        has_prev = "prev_theta" in {
            r[1] for r in conn.execute("PRAGMA table_info(gate_events)")}
        state_cols = {r[1] for r in
                      conn.execute("PRAGMA table_info(gate_state)")}
        has_mode = {"bar_mode", "rank", "q"} <= state_cols

        def _at_event(column: str) -> str:
            """The gate observation in force when the crossing was recorded
            — a crossing must stay interpretable with the mode of its own
            pass, not whatever the bar is doing today."""
            if not has_mode:
                return "NULL"
            return ("(SELECT s.%s FROM gate_state s "
                    " WHERE s.observed_at <= e.observed_at "
                    " ORDER BY s.id DESC LIMIT 1)" % column)

        rows = conn.execute(
            "SELECT e.id, e.observed_at, e.netuid, e.direction, e.share, "
            "e.theta, e.prev_side, e.emission_enabled, e.block_number, "
            + ("e.prev_theta, " if has_prev else "NULL, ")
            + _at_event("bar_mode") + ", "
            + _at_event("rank") + ", "
            + _at_event("q") +
            " FROM gate_events e "
            "WHERE e.id > ? ORDER BY e.id ASC LIMIT 50",
            (last_id,)).fetchall()
    finally:
        conn.close()

    ctx = ctx or {}
    config = ctx.get("config") or {}
    spec = ctx.get("spec") or {}
    store: Optional[sqlite3.Connection] = ctx.get("connection")
    max_chars = int(config.get("message_max_chars", 3500))
    _lexicon, glosses = voice_maps(config)
    cooldown_hours = float(spec.get("cooldown_hours",
                                    DEFAULT_GATE_COOLDOWN_HOURS))

    events: List[Dict[str, Any]] = []
    high = last_id
    for (row_id, observed_at, netuid, direction, share, theta,
         _prev_side, emission_enabled, block_number, prev_theta,
         bar_mode, bar_rank, bar_q) in rows:
        high = max(high, int(row_id))
        event_id = "gate-crossing:%d:%d" % (netuid, row_id)
        if store is not None and _gate_cooldown_active(
                store, netuid, cooldown_hours):
            ledger_record(store, event_id, "gate-crossing", observed_at,
                          _utc_now(), STATUS_SUPPRESSED, 0,
                          "per-netuid cooldown (%gh)" % cooldown_hours)
            continue
        fell = direction == "fell-below"
        headline = ("Atlas · subnet %d %s the bar · %s"
                    % (netuid, "fell below" if fell else "rose above",
                       "gated emission collapses toward zero" if fell else
                       "earns an amplified emission share"))
        margin_pct = ((share - theta) / theta * 100.0) if theta else 0.0
        lines = [
            "subnet %d · demand share %.3f%% · bar %.3f%% · margin %+.1f%%"
            % (netuid, share * 100.0, theta * 100.0, margin_pct),
            "demand share: TaoSwap panel · bar: chain RPC · block %s"
            % (block_number if block_number is not None else "n/a"),
            "observed: %s" % observed_at,
        ]
        # The bar's selection rule (change: network-drift-443). Never infer
        # it: a q recorded while rank mode is active is inert. The gloss
        # map carries each mode's one-line explanation at first use.
        if bar_mode == "rank":
            lines.append("bar mode: rank-pinned at N %s" % bar_rank)
        elif bar_mode == "q-mass":
            lines.append("bar mode: q-mass at q %s" % bar_q)
        # A rank-pinned bar is itself a demand share, so it moves on its own.
        # Without this a subnet the bar descended onto reads as a subnet
        # whose demand rose, which is what the 2026-08-03 reset produced.
        if prev_theta is not None and prev_theta > 0:
            bar_move = (theta - prev_theta) / prev_theta * 100.0
            crossed_by_bar = (
                (prev_theta > share >= theta) if not fell
                else (prev_theta < share <= theta))
            lines.append("bar moved %+.1f%% since the previous poll "
                         "(%.3f%% to %.3f%%)"
                         % (bar_move, prev_theta * 100.0, theta * 100.0))
            lines.append("attribution: the bar moved onto this subnet · "
                         "its demand share did not cross on its own"
                         if crossed_by_bar else
                         "attribution: the subnet's own demand share moved "
                         "across the bar")
        next_action = None
        if emission_enabled == 0:
            lines.append("subnet emission is disabled · informational · "
                         "earns zero either way")
        elif fell:
            next_action = ("next: review your subnet %d position"
                           % netuid)
        plain = render_plain(headline, lines, "", None, max_chars,
                             next_action=next_action, glosses=glosses)
        html = render_html(headline, lines, "", None, max_chars,
                           next_action=next_action, glosses=glosses)
        events.append({"event_id": event_id,
                       "event_class": "gate-crossing",
                       "created_at": _utc_now(), "text": plain,
                       "html": html})
    return events, (str(high) if high else watermark)


# ---------------------------------------------------------------------------
# Fleet-signal adapter (change: fleet-signals) — narrative-cluster /
# watchlist / econ-code instant alerts + durable signal digest lines,
# from the fleet store's signal_events queue. The fleet store is opened
# STRICTLY read-only; this class's delivery watermark lives in this
# module's own ledger like every other source.
# ---------------------------------------------------------------------------

DEFAULT_SIGNAL_BACKSTOP_HOURS = 24
_FLEET_SOURCE_LINE = "source: fleet repos (code), not the live chain"


def _pending_signal_rows(store: sqlite3.Connection
                         ) -> List[Tuple[int, str, str]]:
    return store.execute(
        "SELECT event_row_id, line, detected_at FROM pending_signal "
        "ORDER BY event_row_id ASC").fetchall()


def _signal_digest_line(pending: List[Tuple[int, str, str]]) -> str:
    return ("fleet signal digest · %d item(s): %s"
            % (len(pending), " · ".join(row[1] for row in pending[:12])))


def _subnet_label(conn: sqlite3.Connection, netuid: Optional[int]) -> str:
    """`subnet <netuid> (owner/repo)` when the fleet registry knows the
    repo, else just `subnet <netuid>`. Repo text is recorded data —
    display only."""
    if netuid is None:
        return "fleet"
    label = "subnet %d" % netuid
    try:
        row = conn.execute("SELECT github_repo FROM slots WHERE netuid = ?",
                           (netuid,)).fetchone()
    except sqlite3.Error:
        return label
    if row and row[0]:
        tail = "/".join(str(row[0]).rstrip("/").split("/")[-2:])
        if tail:
            label += " (%s)" % tail[:60]
    return label


def _entry_price_line(conn: sqlite3.Connection,
                      event_row_id: int) -> Optional[str]:
    """One entry-price line (alpha in TAO) when snapshots are available;
    None (line omitted, delivery never delayed) while pending."""
    try:
        rows = conn.execute(
            "SELECT netuid, price_tao, status FROM signal_entries "
            "WHERE event_id = ? ORDER BY netuid ASC",
            (event_row_id,)).fetchall()
    except sqlite3.Error:
        return None
    parts = []
    for netuid, price, status in rows:
        if status in ("recorded", "late") and price is not None:
            parts.append("subnet %d %.6g τ" % (netuid, price))
    return ("entry price · " + " · ".join(parts[:8])) if parts else None


def _build_cluster_event(conn: sqlite3.Connection, row_id: int,
                         payload: Dict[str, Any], created_at: str,
                         dedup_key: str, pending: List[Tuple[int, str, str]],
                         max_chars: int,
                         glosses: Dict[str, str]) -> Dict[str, Any]:
    term = str(payload.get("term") or "?")[:120]
    members = payload.get("members") or []
    first = payload.get("first_mover") or {}
    prevalence = payload.get("prevalence") or {}
    headline = "Atlas · narrative cluster · %s · %d subnets" % (
        term, len(members))
    lines = [
        "subnets · %s · adopted within %sd"
        % (" · ".join(str(m.get("netuid")) for m in members[:8]),
           payload.get("window_days", "?")),
    ]
    if first:
        lines.append("first mover · subnet %s · %s · %s%s%s"
                     % (first.get("netuid"),
                        str(first.get("adopted_at") or "")[:10],
                        _MONO_OPEN,
                        str(first.get("commit_sha") or "-")[:12],
                        _MONO_CLOSE))
    if prevalence:
        lines.append("prevalence · %s/%s active subnets"
                     % (prevalence.get("adopters", "?"),
                        prevalence.get("active_slots", "?")))
    price = _entry_price_line(conn, row_id)
    if price:
        lines.append(price)
    lines.append(_FLEET_SOURCE_LINE)
    trailer = _signal_digest_line(pending) if pending else None
    plain = render_plain(headline, lines, "", trailer, max_chars,
                         glosses=glosses)
    html = render_html(headline, lines, "", trailer, max_chars,
                       glosses=glosses)
    return {"event_id": "fleet-signal:%s" % dedup_key,
            "event_class": "narrative-cluster", "created_at": created_at,
            "text": plain, "html": html,
            "digest_signal_ids": [row[0] for row in pending]}


def _build_watchlist_event(conn: sqlite3.Connection, row_id: int,
                           payload: Dict[str, Any], created_at: str,
                           dedup_key: str,
                           pending: List[Tuple[int, str, str]],
                           max_chars: int,
                           glosses: Dict[str, str]) -> Dict[str, Any]:
    term = str(payload.get("term") or "?")[:120]
    netuid = payload.get("netuid")
    headline = "Atlas · watchlist hit · %s · %s" % (
        term, _subnet_label(conn, netuid))
    lines = []
    if payload.get("source_file"):
        lines.append("file · %s%s%s" % (
            _MONO_OPEN, str(payload["source_file"])[:120], _MONO_CLOSE))
    next_action = None
    if payload.get("commit_sha"):
        commit = str(payload["commit_sha"])[:12]
        lines.append("commit · %s%s%s" % (_MONO_OPEN, commit, _MONO_CLOSE))
        next_action = ("next: review commit %s%s%s"
                       % (_MONO_OPEN, commit, _MONO_CLOSE))
    price = _entry_price_line(conn, row_id)
    if price:
        lines.append(price)
    lines.append(_FLEET_SOURCE_LINE)
    trailer = _signal_digest_line(pending) if pending else None
    plain = render_plain(headline, lines, "", trailer, max_chars,
                         next_action=next_action, glosses=glosses)
    html = render_html(headline, lines, "", trailer, max_chars,
                       next_action=next_action, glosses=glosses)
    return {"event_id": "fleet-signal:%s" % dedup_key,
            "event_class": "watchlist", "created_at": created_at,
            "text": plain, "html": html,
            "digest_signal_ids": [row[0] for row in pending]}


# Verdict free-text bounds (repo/model-derived; escaped at render). Clipped
# at a word boundary so a card never cuts mid-word.
_WHAT_MAX = 160
_WHY_MAX = 160
_EVIDENCE_MAX = 220

_ECON_SIGNIFICANCE_CLASS = {"high": "material incentive-code change",
                            "med": "notable incentive-code change"}
_ECON_DIRECTION_LABEL = {
    "emissions_up": "emissions ↑", "emissions_down": "emissions ↓",
    "reshuffle": "winners / losers reshuffle", "neutral": "no net effect",
    "unknown": "direction unclear"}


def _clip(text: Any, limit: int) -> Optional[str]:
    """Trim to `limit` chars on a word boundary, appending … when cut.
    None/blank in → None out."""
    if text is None:
        return None
    value = " ".join(str(text).split())  # collapse whitespace/newlines
    if not value:
        return None
    if len(value) <= limit:
        return value
    return value[:limit].rsplit(" ", 1)[0].rstrip(" ,.;:—-") + "…"


def _econ_provenance(payload: Dict[str, Any],
                     price: Optional[str]) -> List[str]:
    """Provenance as its own labeled single-fact lines. Files show as
    basenames (full paths wrap into mush on a phone), capped with a +N tail."""
    commits_suffix = "+" if payload.get("commits_truncated") else ""
    prov = ["%scommits ·%s %s%s → %s%s · %s commit(s)%s"
            % (_BOLD_OPEN, _BOLD_CLOSE,
               _MONO_OPEN, str(payload.get("prev_sha") or "-")[:12],
               str(payload.get("new_sha") or "-")[:12], _MONO_CLOSE,
               payload.get("commit_count", "?"), commits_suffix)]
    files = [str(path) for path in (payload.get("files") or [])]
    if files:
        shown = [f.rstrip("/").rsplit("/", 1)[-1][:48] for f in files[:3]]
        line = "%sfiles ·%s %s" % (_BOLD_OPEN, _BOLD_CLOSE, " · ".join(shown))
        if len(files) > 3:
            line += " · +%d more" % (len(files) - 3)
        prov.append(line)
    if price:
        prov.append("%sentry ·%s %s" % (_BOLD_OPEN, _BOLD_CLOSE,
                                        price.replace("entry price · ", "")))
    return prov


def _build_econ_event(conn: sqlite3.Connection, row_id: int,
                      payload: Dict[str, Any], created_at: str,
                      dedup_key: str, pending: List[Tuple[int, str, str]],
                      max_chars: int,
                      glosses: Dict[str, str]) -> Dict[str, Any]:
    netuid = payload.get("netuid")
    label = _subnet_label(conn, netuid)
    significance = payload.get("significance")
    unjudged = bool(payload.get("unjudged"))
    price = _entry_price_line(conn, row_id)

    if unjudged:
        # Judge could not read this change — page it, but say so plainly.
        headline = "Atlas · %s · incentive-code change · unjudged" % label
        lines = ["", "verdict unavailable · judge could not read this change"]
        groups = [_econ_provenance(payload, price)]
    elif significance:
        # Meaning-first card. Each fact sits on its own line, separated by
        # blank lines, so it reads as a card at a glance rather than a
        # paragraph. Provenance tucks into the expandable blockquote.
        klass = _ECON_SIGNIFICANCE_CLASS.get(significance,
                                             "incentive-code change")
        headline = "Atlas · %s · %s" % (label, klass)
        lines = [""]  # blank line under the headline
        what = _clip(payload.get("what_changed"), _WHAT_MAX)
        why = _clip(payload.get("why_it_matters"), _WHY_MAX)
        if what:
            lines.append(what)
        if why:
            lines += ["", "%swhy ·%s %s" % (_BOLD_OPEN, _BOLD_CLOSE, why)]
        read = "%ssignificance ·%s %s%s%s · %s" % (
            _BOLD_OPEN, _BOLD_CLOSE, _BOLD_OPEN, significance, _BOLD_CLOSE,
            _ECON_DIRECTION_LABEL.get(payload.get("direction"),
                                      "direction unclear"))
        if payload.get("partial_view"):
            read += " · partial view"
        lines += ["", read]
        groups = []
        evidence = _clip(payload.get("evidence"), _EVIDENCE_MAX)
        if evidence:
            groups.append(["based on · %s" % evidence])
        groups.append(_econ_provenance(payload, price))
    else:
        # Legacy / gate-off event (no verdict in payload).
        headline = "Atlas · %s · incentive-code change" % label
        lines = []
        groups = [_econ_provenance(payload, price)]

    # Blank-line-separated groups inside one expandable blockquote (house
    # style, matching the subtensor repo breakdown).
    expandable = "\n\n".join("\n".join(g) for g in groups if g)
    trailer = _signal_digest_line(pending) if pending else None
    plain = render_plain(headline, lines, expandable, trailer, max_chars,
                         glosses=glosses)
    html = render_html(headline, lines, expandable, trailer, max_chars,
                       glosses=glosses)
    return {"event_id": "fleet-signal:%s" % dedup_key,
            "event_class": "econ-code", "created_at": created_at,
            "text": plain, "html": html,
            "digest_signal_ids": [row[0] for row in pending]}


def _build_signal_digest_event(pending: List[Tuple[int, str, str]],
                               max_chars: int,
                               glosses: Dict[str, str]) -> Dict[str, Any]:
    headline = "Atlas · fleet signal digest · %d item(s)" % len(pending)
    lines = ["adoption and dampened-signal notes · no instant alert due",
             _FLEET_SOURCE_LINE]
    body = _signal_digest_line(pending)
    plain = render_plain(headline, lines, body, None, max_chars,
                         glosses=glosses)
    html = render_html(headline, lines, body, None, max_chars,
                       glosses=glosses)
    return {"event_id": "fleet-signal-digest:%d" % pending[-1][0],
            "event_class": "signal-digest", "created_at": _utc_now(),
            "text": plain, "html": html,
            "digest_signal_ids": [row[0] for row in pending]}


def fleet_signal_events(source_db: str, watermark: Optional[str],
                        ctx: Optional[Dict[str, Any]] = None
                        ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """Fleet signal queue → tiered notifier events. Instant classes page
    (with class-specific ledger dedup via their fleet dedup keys); digest
    rows are persisted durably in pending_signal BEFORE the watermark
    passes them, ride the next instant fleet alert, and are flushed by a
    backstop digest — never paged, never dropped (churn mechanics)."""
    conn = open_source_ro(source_db)
    if conn is None:
        return [], watermark
    try:
        present = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND "
            "name = 'signal_events'").fetchone()
        if present is None:
            return [], watermark  # fleet-signals not deployed yet
        last_id = int(watermark) if watermark else 0
        rows = conn.execute(
            "SELECT id, class, tier, netuid, term, dedup_key, payload_json, "
            "created_at FROM signal_events WHERE id > ? ORDER BY id ASC "
            "LIMIT 50", (last_id,)).fetchall()

        ctx = ctx or {}
        config = ctx.get("config") or {}
        spec = ctx.get("spec") or {}
        store: Optional[sqlite3.Connection] = ctx.get("connection")
        max_chars = int(config.get("message_max_chars", 3500))
        _lexicon, glosses = voice_maps(config)

        events: List[Dict[str, Any]] = []
        high = last_id
        for (row_id, event_class, tier, _netuid, _term, dedup_key,
             payload_json, created_at) in rows:
            high = max(high, int(row_id))
            payload = json.loads(payload_json)
            if tier != "instant":
                line = redact(str(payload.get("line") or ""))[:200]
                if store is not None and line:
                    store.execute(
                        "INSERT OR IGNORE INTO pending_signal (event_row_id, "
                        "line, detected_at) VALUES (?, ?, ?)",
                        (row_id, line, _utc_now()))
                continue
            pending = _pending_signal_rows(store) if store is not None else []
            if event_class == "narrative-cluster":
                events.append(_build_cluster_event(
                    conn, row_id, payload, created_at, dedup_key, pending,
                    max_chars, glosses))
            elif event_class == "watchlist":
                events.append(_build_watchlist_event(
                    conn, row_id, payload, created_at, dedup_key, pending,
                    max_chars, glosses))
            else:  # econ-code (and any future instant class: fail visible)
                events.append(_build_econ_event(
                    conn, row_id, payload, created_at, dedup_key, pending,
                    max_chars, glosses))

        if not events and store is not None:
            pending = _pending_signal_rows(store)
            if pending:
                backstop = float(spec.get(
                    "digest_backstop_hours",
                    DEFAULT_SIGNAL_BACKSTOP_HOURS)) * 3600
                oldest = pending[0][2]
                try:
                    age = (datetime.datetime.now(tz=datetime.timezone.utc)
                           - datetime.datetime.fromisoformat(oldest)
                           ).total_seconds()
                except ValueError:
                    age = backstop + 1
                if age > backstop:
                    events.append(_build_signal_digest_event(
                        pending, max_chars, glosses))
        return events, (str(high) if high else watermark)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Chain-parameter change (change: network-drift-443) — a root-settable knob
# that governs network economics moved. Rare and unconditionally material,
# so: instant tier, NO cooldown, no digest. Suppressing the second flip of a
# switch like the Root Reborn curation gate would be the wrong failure.
# ---------------------------------------------------------------------------

_PARAM_MODE_WORDS = {
    ("EmissionBarRank", "to-rank"):
        "the bar is now rank-pinned · q is inert",
    ("EmissionBarRank", "to-qmass"):
        "the bar has fallen back to q-mass selection",
}


def chain_parameter_change_events(source_db: str, watermark: Optional[str],
                                  ctx: Optional[Dict[str, Any]] = None
                                  ) -> Tuple[List[Dict[str, Any]],
                                             Optional[str]]:
    """Root-settable chain parameters that changed value, recorded by
    livedata. Reads the transition table read-only past this class's own
    watermark, independent of every other class."""
    conn = open_source_ro(source_db)
    if conn is None:
        return [], watermark
    try:
        present = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND "
            "name = 'chain_param_events'").fetchone()
        if present is None:
            return [], watermark  # watch not deployed yet
        last_id = int(watermark) if watermark else 0
        rows = conn.execute(
            "SELECT id, item, prev_value, new_value, prev_provenance, "
            "new_provenance, observed_at, block_number "
            "FROM chain_param_events WHERE id > ? ORDER BY id ASC LIMIT 50",
            (last_id,)).fetchall()
    finally:
        conn.close()

    ctx = ctx or {}
    config = ctx.get("config") or {}
    spec = ctx.get("spec") or {}
    max_chars = int(config.get("message_max_chars", 3500))
    _lexicon, glosses = voice_maps(config)
    # Operator-supplied text: rendered through the same escaping path as
    # every other interpolated value.
    governs = dict(spec.get("governs") or {})

    events: List[Dict[str, Any]] = []
    high = last_id
    for (row_id, item, prev_value, new_value, prev_prov, new_prov,
         observed_at, block_number) in rows:
        high = max(high, int(row_id))
        headline = "Atlas · chain parameter changed · %s" % item
        lines = [
            "%s: %s to %s" % (item, prev_value, new_value),
            "source: %s to %s" % (prev_prov, new_prov),
            "reference block: %s · observed: %s"
            % (block_number if block_number is not None else "n/a",
               observed_at),
        ]
        if item == "EmissionBarRank":
            moved = ("to-qmass" if new_value == "0"
                     else "to-rank" if prev_value == "0" else None)
            if moved:
                lines.append(_PARAM_MODE_WORDS[(item, moved)])
        if governs.get(item):
            lines.append("governs: %s" % governs[item])
        next_action = None
        if item in ("EmissionBarRank", "EmissionBarQuantile",
                    "EmissionGateExponent"):
            # Explains the deliberate silence: the pass that recorded this
            # re-seeded every side rather than paging |M - N| crossings.
            lines.append("the bar was re-priced for every subnet · "
                         "per-subnet crossing alerts were withheld for "
                         "that pass by design")
            next_action = ("next: review your subnet positions against "
                           "the new gate terms")
        elif item == "RootWeightSettingEnabled":
            next_action = ("next: review root basket positions · the "
                           "curation switch changed")
        plain = render_plain(headline, lines, "", None, max_chars,
                             next_action=next_action, glosses=glosses)
        html = render_html(headline, lines, "", None, max_chars,
                           next_action=next_action, glosses=glosses)
        events.append({"event_id": "chain-parameter-change:%s" % row_id,
                       "event_class": "chain-parameter-change",
                       "created_at": _utc_now(), "text": plain,
                       "html": html})
    return events, (str(high) if high else watermark)


_ADAPTERS: Dict[str, Callable[..., Tuple[List[Dict[str, Any]],
                                         Optional[str]]]] = {
    "chain-runtime-upgrade": chain_runtime_upgrade_events,
    "chain-parameter-change": chain_parameter_change_events,
    "gate-crossing": gate_crossing_events,
    "fleet-signal": fleet_signal_events,
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
                if (status == STATUS_DELIVERED
                        and event.get("digest_signal_ids")):
                    # Same contract for fleet signal digest lines.
                    connection.executemany(
                        "DELETE FROM pending_signal WHERE event_row_id = ?",
                        [(rid,) for rid in event["digest_signal_ids"]])
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
