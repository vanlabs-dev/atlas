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
from dataclasses import dataclass, field
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
    final_failure TEXT,
    tier TEXT
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
# Plain area words for the repository alert (display only).
_CHURN_AREA_WORDS = {".github": "CI", "docs": "docs", "website": "website",
                     "vendor": "vendored code", "sdk": "SDK"}
_CORE_AREA_WORDS = {"precompiles": "EVM precompiles",
                    "runtime": "runtime config", "common": "shared code",
                    "primitives": "primitives"}

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
STATUS_BRIEFED = "briefed"
TIER_INSTANT = "instant"
TIER_BRIEFING = "briefing"
# A class that records and is measured but is carried nowhere (change:
# rotation-signal-gate). The default for a newly introduced netuid-scoped
# class, so nothing new can page by accident.
TIER_SHADOW = "shadow"
STATUS_SHADOWED = "shadowed"
STATUS_UNREGISTERED = "unregistered"
DELIVERY_TIERS = (TIER_INSTANT, TIER_BRIEFING, TIER_SHADOW)
# Tier -> the ledger status for an event that is NOT paged. `instant` maps
# to None, meaning "deliver". Any value that is not a known tier (a class
# absent from the registry, or a typo) maps to `unregistered` and delivers
# nothing: drift between the class list and the registry fails closed.
NON_PAGING_STATUS: Dict[Optional[str], Optional[str]] = {
    TIER_INSTANT: None,
    TIER_BRIEFING: STATUS_BRIEFED,
    TIER_SHADOW: STATUS_SHADOWED,
}


def event_tier(config: Dict[str, Any], spec: Dict[str, Any],
               event_class: str) -> Optional[str]:
    """The registered delivery tier governing one event.

    An adapter may emit a class other than the one it is registered under
    (the fleet-signal queue emits econ-code, narrative-cluster and
    watchlist), so the event's own class wins when the registry names it.
    Otherwise the adapter's own entry governs. A class the registry does
    not name at all returns None, which delivers nothing.
    """
    own = (config.get("classes") or {}).get(event_class)
    if isinstance(own, dict) and own.get("tier") in DELIVERY_TIERS:
        return str(own["tier"])
    tier = spec.get("tier")
    return str(tier) if tier in DELIVERY_TIERS else None
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
    # Additive (change: rotation-signal-gate): rows written before the tier
    # registry stay NULL, which readers MUST treat as "unrecorded" rather
    # than back-filling as instant — those events predate the registry.
    columns = {row[1] for row in connection.execute(
        "PRAGMA table_info(events)")}
    if "tier" not in columns:
        connection.execute("ALTER TABLE events ADD COLUMN tier TEXT")
    connection.commit()
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
                  final_failure: Optional[str],
                  tier: Optional[str] = None) -> None:
    """Record one event's outcome. `tier` names the delivery tier that
    governed it (change: rotation-signal-gate), so the ledger stays a
    complete account of what was detected and why it was or was not sent."""
    connection.execute(
        "INSERT INTO events (event_id, event_class, created_at, attempted_at, "
        "status, retry_count, final_failure, tier) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(event_id) DO UPDATE SET attempted_at = excluded.attempted_at, "
        "status = excluded.status, retry_count = excluded.retry_count, "
        "final_failure = excluded.final_failure, tier = excluded.tier",
        (event_id, event_class, created_at, attempted_at, status,
         retry_count, redact(final_failure)[:400] if final_failure else None,
         tier))
    connection.commit()


def ledger_collapsed_members(connection: sqlite3.Connection,
                             event: Dict[str, Any], status: str,
                             attempted_at: Optional[str], retry_count: int,
                             detail: Optional[str],
                             tier: Optional[str] = None) -> None:
    """Ledger every collapsed row against its own event id. The page uses
    the first member's id; the rest must still be recorded so replay and
    de-duplication stay per-fact."""
    for member_id in event.get("member_ids") or []:
        if member_id == event.get("event_id"):
            continue
        ledger_record(connection, member_id, event["event_class"],
                      event["created_at"], attempted_at, status,
                      retry_count, detail, tier=tier)


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
# Telegram HTML rendering (change: telegram-alert-redesign)
# ---------------------------------------------------------------------------
# Every sender builds a Message: severity marker, plain headline, one
# meaning sentence, labelled facts, body lines, a details fold for
# provenance, an optional next action, and URL buttons. One renderer turns
# it into Telegram HTML and one into plain text. Only Bot-API tags are
# emitted (b, i, code, pre, blockquote expandable, tg-time). Every dynamic
# value passes html_escape(); a real commit subject contains `Vec<PerU16>`,
# which unescaped would 400 the send. Rendered HTML is NEVER truncated
# after rendering: the builder sheds content until the body fits, because
# a post-render slice can cut a tag and 400 every long message.


def html_escape(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))


def _typography(text: str) -> str:
    """Operator style rule (2026-07-13): message bodies never contain em
    or en dashes. Anything imported from stored data is normalized here,
    the single choke point."""
    return text.replace("—", "-").replace("–", "-")


# Inline span sentinels. Composed strings wrap spans in these; the HTML
# renderer turns them into entities AFTER escaping (so the span text is
# still escaped), the plain renderer strips them. Recorded text passes
# through rec(), which removes every sentinel, so stored data can never
# open a tag.
_MONO_OPEN, _MONO_CLOSE = "\x01", "\x02"
_BOLD_OPEN, _BOLD_CLOSE = "\x03", "\x04"
_ITAL_OPEN, _ITAL_CLOSE = "\x0e", "\x0f"
# A time token: \x05<unix>;<format>;<fallback>\x06 (see fmt_time).
_TIME_OPEN, _TIME_CLOSE = "\x05", "\x06"
_SENTINELS = (_MONO_OPEN, _MONO_CLOSE, _BOLD_OPEN, _BOLD_CLOSE,
              _ITAL_OPEN, _ITAL_CLOSE, _TIME_OPEN, _TIME_CLOSE)
_TIME_RE = re.compile("\x05(\\d+);([rwdDtT]*);([^\x05\x06]*)\x06")


def rec(value: Any) -> str:
    """Recorded text as display data: stringified, sentinel-free, dashes
    normalized. Never glossed, never interpreted as markup."""
    text = "" if value is None else str(value)
    for mark in _SENTINELS:
        text = text.replace(mark, "")
    return _typography(text)


def mono(text: Any) -> str:
    return _MONO_OPEN + rec(text) + _MONO_CLOSE


def bold(text: Any) -> str:
    return _BOLD_OPEN + rec(text) + _BOLD_CLOSE


def italic(text: Any) -> str:
    return _ITAL_OPEN + rec(text) + _ITAL_CLOSE


def _strip_mono(text: str) -> str:
    """Plain rendering of a composed string: time tokens become their
    fallback text, every other sentinel is removed."""
    text = _TIME_RE.sub(lambda m: m.group(3), text)
    for mark in _SENTINELS:
        text = text.replace(mark, "")
    return text


def _html_spans(text: str) -> str:
    """Escape, then convert sentinels to entities (after escaping, so
    the span content is escaped too)."""
    out = html_escape(text)
    out = _TIME_RE.sub(lambda m: '<tg-time unix="%s" format="%s">%s</tg-time>'
                       % (m.group(1), m.group(2), m.group(3)), out)
    for mark, tag in ((_MONO_OPEN, "<code>"), (_MONO_CLOSE, "</code>"),
                      (_BOLD_OPEN, "<b>"), (_BOLD_CLOSE, "</b>"),
                      (_ITAL_OPEN, "<i>"), (_ITAL_CLOSE, "</i>"),
                      (_TIME_OPEN, ""), (_TIME_CLOSE, "")):
        out = out.replace(mark, tag)
    return out


# Severity markers (change: telegram-alert-redesign). The first character
# of every alert. Markers change no delivery behaviour.
SEVERITY_MARK = {"act": "🔴", "watch": "🟠", "good": "🟢", "info": "🔵",
                 "done": "✅"}


@dataclass
class Message:
    """One outbound message in the house layout. `severity` is a key of
    SEVERITY_MARK, a literal marker (the pulse editions pass their own
    edition emoji), or None for no marker."""
    severity: Optional[str]
    headline: str
    meaning: Optional[str] = None
    facts: List[Tuple[str, str]] = field(default_factory=list)
    body: List[str] = field(default_factory=list)
    details: List[str] = field(default_factory=list)
    next_action: Optional[str] = None
    buttons: List[Tuple[str, str]] = field(default_factory=list)

    def plain(self, max_chars: int = 3500,
              glosses: Optional[Dict[str, str]] = None) -> str:
        return render_plain(self, max_chars, glosses)

    def html(self, max_chars: int = 3500,
             glosses: Optional[Dict[str, str]] = None) -> str:
        return render_html(self, max_chars, glosses)

    def to_dict(self) -> Dict[str, Any]:
        return {"severity": self.severity, "headline": self.headline,
                "meaning": self.meaning,
                "facts": [list(f) for f in self.facts],
                "body": list(self.body), "details": list(self.details),
                "next_action": self.next_action,
                "buttons": [list(b) for b in self.buttons]}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Message":
        return cls(severity=data.get("severity"),
                   headline=data.get("headline") or "",
                   meaning=data.get("meaning"),
                   facts=[tuple(f) for f in data.get("facts") or []],
                   body=list(data.get("body") or []),
                   details=list(data.get("details") or []),
                   next_action=data.get("next_action"),
                   buttons=[tuple(b) for b in data.get("buttons") or []])


def _gloss_text(text: str, glosses: Dict[str, str]) -> str:
    """Attach ' (gloss)' to the first use of each glossed term in ONE
    composed prose sentence (voice canon section 2). Glossing is scoped to
    the meaning sentence so it can never reach a headline or recorded
    data. Word boundaries, case-insensitive, never inside a hyphenated
    compound; a term abutting a mono sentinel keeps the gloss outside the
    code span."""
    for term, gloss in glosses.items():
        pattern = re.compile(r"(?<![\w-])" + re.escape(term) + r"(?![\w-])",
                             re.IGNORECASE)
        match = pattern.search(text)
        if match is None:
            continue
        insert_at = match.end()
        if text[insert_at:insert_at + 1] == _MONO_CLOSE:
            insert_at += 1
        text = (text[:insert_at] + " (" + _typography(gloss) + ")"
                + text[insert_at:])
    return text


def _layout(msg: Message, html: bool,
            glosses: Optional[Dict[str, str]]) -> str:
    span = _html_spans if html else _strip_mono
    mark = SEVERITY_MARK.get(msg.severity or "", msg.severity or "")
    head = _typography(msg.headline)
    first = "<b>%s</b>" % _html_spans(head) if html else _strip_mono(head)
    lines = [(mark + " " if mark else "") + first]
    if msg.meaning:
        meaning = _typography(msg.meaning)
        if glosses:
            meaning = _gloss_text(meaning, glosses)
        lines.append(span(meaning))
    block: List[str] = []
    for label, value in msg.facts:
        label_t, value_t = _typography(label), _typography(value)
        block.append(("<b>%s:</b> %s" % (html_escape(label_t),
                                          _html_spans(value_t)))
                     if html else "%s: %s" % (label_t, _strip_mono(value_t)))
    if block:
        lines.append("")
        lines.extend(block)
    if msg.body:
        lines.append("")
        lines.extend(span(_typography(line)) for line in msg.body)
    if msg.details:
        detail = "\n".join(span(_typography(line)) for line in msg.details)
        if html:
            lines.append("<blockquote expandable>%s</blockquote>" % detail)
        else:
            lines.append("")
            lines.append(detail)
    if msg.next_action:
        action = span(_typography(msg.next_action))
        lines.append(("<b>Next:</b> %s" if html else "Next: %s") % action)
    return "\n".join(lines)


def _fit(msg: Message, max_chars: int, html: bool,
         glosses: Optional[Dict[str, str]]) -> str:
    """Shed content until the rendered body fits (design D3): the details
    fold first (whole lines from the end, then a clipped last line), then
    body lines from the end, then facts from the end, then the meaning.
    The headline and the next action are never dropped."""
    work = Message(**{**msg.__dict__, "facts": list(msg.facts),
                      "body": list(msg.body), "details": list(msg.details)})
    while True:
        body = _layout(work, html, glosses)
        if len(body) <= max_chars:
            return body
        over = len(body) - max_chars
        last = _strip_mono(work.details[-1]) if work.details else ""
        if work.details and len(last) > 80 and len(last) - over - 20 >= 40:
            # A long last line (a listing) is clipped, visibly, before
            # any whole line goes.
            work.details[-1] = _clip_words(last, len(last) - over - 20)
        elif len(work.details) > 1:
            work.details.pop()
        elif work.details and len(last) > 40:
            work.details[0] = _clip_words(last, max(20, len(last) - over - 20))
        elif work.details:
            work.details = []
        elif work.body:
            work.body.pop()
        elif work.facts:
            work.facts.pop()
        elif work.meaning:
            work.meaning = None
        else:
            break
    mark = SEVERITY_MARK.get(msg.severity or "", msg.severity or "")
    room = max_chars - len(mark) - 8
    head = _strip_mono(_typography(msg.headline))[:max(room, 1)]
    return ((mark + " " if mark else "")
            + ("<b>%s</b>" % html_escape(head) if html else head))


def _clip_words(text: str, limit: int) -> str:
    """Trim to `limit` chars on a word boundary, appending … when cut."""
    text = " ".join(str(text).split())
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0].rstrip(" ,.;:-")
    return (cut or text[:limit]) + "…"


def render_html(msg: Message, max_chars: int = 3500,
                glosses: Optional[Dict[str, str]] = None) -> str:
    return _fit(msg, max_chars, True, glosses)


def render_plain(msg: Message, max_chars: int = 3500,
                 glosses: Optional[Dict[str, str]] = None) -> str:
    return _fit(msg, max_chars, False, glosses)


# ---------------------------------------------------------------------------
# Reading formats (design D4, D5)
# ---------------------------------------------------------------------------

MINUS = "−"  # minus sign in signed figures; not a dash


def plural(count: Any, word: str, many: Optional[str] = None) -> str:
    """`1 commit`, `2 commits`, with thousands separators."""
    try:
        number = int(count)
    except (TypeError, ValueError):
        return "%s %s" % (rec(count), many or word + "s")
    return "%s %s" % (fmt_int(number),
                      word if number == 1 else (many or word + "s"))


def fmt_int(value: Any) -> str:
    try:
        return "{:,}".format(int(value))
    except (TypeError, ValueError):
        return "n/a" if value is None else rec(value)


def fmt_pct(fraction: Optional[float], digits: int = 3) -> str:
    """A share stored as a fraction, shown as a percentage."""
    if fraction is None:
        return "n/a"
    return ("%%.%df%%%%" % digits) % (fraction * 100.0)


def fmt_change(pct: Optional[float], digits: int = 1) -> str:
    """A signed relative change already in percent."""
    if pct is None:
        return "n/a"
    sign = "+" if pct >= 0 else MINUS
    return ("%s%%.%df%%%%" % (sign, digits)) % abs(pct)


def fmt_tao(value: Optional[float]) -> str:
    """Three significant figures, never scientific notation."""
    if value is None:
        return "n/a"
    if value == 0:
        return "0 τ"
    import math
    places = max(0, 2 - int(math.floor(math.log10(abs(value)))))
    return ("%%.%df τ" % places) % value


def fmt_usd(value: Optional[float]) -> str:
    return "n/a" if value is None else "${:,.2f}".format(value)


def _parse_time(value: Any) -> Optional[datetime.datetime]:
    if value is None:
        return None
    try:
        if isinstance(value, (int, float)):
            return datetime.datetime.fromtimestamp(
                float(value), tz=datetime.timezone.utc)
        parsed = datetime.datetime.fromisoformat(str(value).replace(
            "Z", "+00:00"))
    except (ValueError, OverflowError, OSError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.timezone.utc)
    return parsed.astimezone(datetime.timezone.utc)


def time_fallback(moment: datetime.datetime) -> str:
    return "%s %d %s, %s UTC" % (moment.strftime("%a"), moment.day,
                                 moment.strftime("%b"),
                                 moment.strftime("%H:%M"))


def fmt_time(value: Any, fmt: str = "wDT") -> str:
    """A recorded instant as a Telegram tg-time token: the HTML body shows
    it in the reader's timezone, plain text shows the UTC fallback. A
    value that does not parse renders as recorded, marked dated."""
    moment = _parse_time(value)
    if moment is None:
        return "n/a" if value is None else "%s (dated)" % rec(value)
    return "%s%d;%s;%s%s" % (_TIME_OPEN, int(moment.timestamp()), fmt,
                             time_fallback(moment), _TIME_CLOSE)


def fmt_date(value: Any) -> str:
    moment = _parse_time(value)
    if moment is None:
        return "n/a" if value is None else rec(value)
    return "%d %s" % (moment.day, moment.strftime("%b"))


# ---------------------------------------------------------------------------
# Subnet names (design D6): the latest recorded panel-snapshot name
# ---------------------------------------------------------------------------

def subnet_names_from(conn: Optional[sqlite3.Connection]) -> Dict[int, str]:
    if conn is None:
        return {}
    try:
        present = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND "
            "name = 'panel_snapshot'").fetchone()
        if present is None:
            return {}
        rows = conn.execute(
            "SELECT netuid, name FROM panel_snapshot WHERE id IN "
            "(SELECT MAX(id) FROM panel_snapshot WHERE name IS NOT NULL "
            "AND name != '' GROUP BY netuid)").fetchall()
    except sqlite3.Error:
        return {}
    return {int(n): rec(name).strip()[:60] for n, name in rows
            if name and rec(name).strip()
            and rec(name).strip().lower() != "unknown"}


def subnet_names(live_db: Optional[str]) -> Dict[int, str]:
    if not live_db:
        return {}
    conn = open_source_ro(resolve(live_db))
    if conn is None:
        return {}
    try:
        return subnet_names_from(conn)
    finally:
        conn.close()


def live_db_path(config: Dict[str, Any]) -> str:
    return ((config.get("briefing") or {}).get("live_db")
            or "var/livedata/livedata.db")


def subnet_label(netuid: Any, names: Dict[int, str],
                 capital: bool = True) -> str:
    """`Subnet 49 (Nepher Robotics)` in alerts; the number alone when no
    name is recorded."""
    word = "Subnet" if capital else "subnet"
    try:
        number = int(netuid)
    except (TypeError, ValueError):
        return "%s %s" % (word, rec(netuid))
    name = names.get(number)
    return ("%s %d (%s)" % (word, number, name) if name
            else "%s %d" % (word, number))


def subnet_tag(netuid: Any, names: Dict[int, str]) -> str:
    """`Nepher Robotics (49)` in briefing lists."""
    try:
        number = int(netuid)
    except (TypeError, ValueError):
        return "Subnet %s" % rec(netuid)
    name = names.get(number)
    return "%s (%d)" % (name, number) if name else "Subnet %d" % number


# ---------------------------------------------------------------------------
# Links (design D7): URL buttons from configured templates
# ---------------------------------------------------------------------------

DEFAULT_LINKS = {
    "subtensor_compare":
        "https://github.com/RaoFoundation/subtensor/compare/{prev}...{new}",
    "subtensor_releases": "https://github.com/RaoFoundation/subtensor/releases",
    "github_commit": "https://github.com/{repo}/commit/{sha}",
    "github_compare": "https://github.com/{repo}/compare/{prev}...{new}",
    "atlas_commit": "https://github.com/vanlabs-dev/atlas/commit/{sha}",
    "taostats_subnet": "https://taostats.io/subnets/{netuid}",
}
_URL_VALUE_RE = re.compile(r"^[A-Za-z0-9._/-]+$")


def link(config: Optional[Dict[str, Any]], key: str,
         **values: Any) -> Optional[str]:
    """A URL from the configured template, or None when the template or a
    value is missing or unsafe. A None never blocks delivery: the button
    is just omitted."""
    links = dict(DEFAULT_LINKS)
    links.update(((config or {}).get("links") or {}))
    template = links.get(key)
    if not isinstance(template, str) or not template:
        return None
    clean = {}
    for name, value in values.items():
        text = "" if value is None else str(value).strip()
        if not text or not _URL_VALUE_RE.match(text) or ".." in text:
            return None
        clean[name] = text
    try:
        url = template.format(**clean)
    except (KeyError, IndexError, ValueError):
        return None
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        return None
    return url


def repo_slug(github_repo: Any) -> Optional[str]:
    """owner/repo from a recorded GitHub URL or slug."""
    if not github_repo:
        return None
    parts = str(github_repo).rstrip("/").removesuffix(".git").split("/")
    slug = "/".join(parts[-2:])
    return slug if len(parts) >= 2 and _URL_VALUE_RE.match(slug) else None


def button(config: Optional[Dict[str, Any]], text: str, key: str,
           **values: Any) -> List[Tuple[str, str]]:
    url = link(config, key, **values)
    return [(text, url)] if url else []


# ---------------------------------------------------------------------------
# Severity selection (design D8)
# ---------------------------------------------------------------------------

def severity_for(event_class: str, **fields: Any) -> str:
    """The marker for one event, from its class and recorded fields."""
    if event_class == "chain-runtime-upgrade":
        return "act" if fields.get("governance_crossed") else "watch"
    if event_class == "chain-parameter-change":
        return ("act" if fields.get("item") in _ACT_PARAMS else "watch")
    if event_class == "gate-crossing":
        if fields.get("emission_enabled") == 0:
            return "info"
        return "act" if fields.get("direction") == "fell-below" else "good"
    if event_class in ("fail-closed", "probe-drift", "upgrade-blocked"):
        return "act"
    if event_class == "knowledge-ingestion":
        return "watch" if fields.get("staged") else "info"
    if event_class in ("churn-digest", "signal-digest", "subnet-registry",
                       "upgrade-waiting"):
        return "info"
    if event_class in ("upgrade-updated", "upgrade-dry-run", "probe-cleared",
                       "test"):
        return "done"
    return "watch"


_ACT_PARAMS = frozenset(("EmissionBarRank", "EmissionBarQuantile",
                         "EmissionGateExponent", "SubnetEmissionEnabled"))


def message_event(msg: Message, event_id: str, event_class: str,
                  created_at: str, max_chars: int,
                  glosses: Optional[Dict[str, str]],
                  **extra: Any) -> Dict[str, Any]:
    """The scan's event dict for one Message."""
    event = {"event_id": event_id, "event_class": event_class,
             "created_at": created_at,
             "text": render_plain(msg, max_chars, glosses),
             "html": render_html(msg, max_chars, glosses),
             "buttons": list(msg.buttons)}
    event.update(extra)
    return event


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
                 = None, parse_mode: Optional[str] = None,
                 buttons: Optional[List[Tuple[str, str]]] = None
                 ) -> Dict[str, Any]:
    """Attempt delivery with bounded retry. Returns a result dict with
    delivered/attempts/status/detail. Never raises for transport or API
    failures — those are the caller's recorded terminal outcomes. The
    token is in the URL and MUST NOT appear in any returned detail.
    `buttons` ride as an inline keyboard, two URL buttons per row."""
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
              "link_preview_options": json.dumps({"is_disabled": True})}
    if parse_mode:
        fields["parse_mode"] = parse_mode
    if buttons:
        rows = [[{"text": label, "url": url} for label, url in
                 buttons[i:i + 2]] for i in range(0, len(buttons), 2)]
        fields["reply_markup"] = json.dumps({"inline_keyboard": rows})
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
    """The repo-vs-live-chain distinction, stated on every repo alert as
    one plain sentence: is this code live yet?"""
    if live is None:
        return ("Live runtime spec n/a, so Atlas cannot compare. This is a "
                "repo (source code) event only.")
    live_spec = live["spec_version"]
    if new_spec is None:
        return ("The live chain runs spec %d. This repo range records no "
                "runtime spec, so it is not live on chain." % live_spec)
    if new_spec > live_spec:
        return ("The live chain runs spec %d. These repo changes go live "
                "only when the chain upgrades." % live_spec)
    if new_spec == live_spec:
        return ("The live chain already runs spec %d. This repo range is "
                "not a new upgrade." % live_spec)
    return ("The live chain already runs spec %d, ahead of this repo "
            "range." % live_spec)


def _pending_churn_rows(store: sqlite3.Connection
                        ) -> List[Tuple[int, str, str, str]]:
    return store.execute(
        "SELECT range_id, new_sha, dominant_area, detected_at "
        "FROM pending_churn ORDER BY range_id ASC").fetchall()


def _digest_line(pending: List[Tuple[int, str, str, str]]) -> str:
    return ("Held housekeeping: %s, no protocol or runtime spec change"
            % plural(len(pending), "update"))


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
    files = plural(area["files"], "file")
    if area["adds"] or area["dels"]:
        return "%s %s +%s/-%s%s" % (
            area["area"], files, _compact(area["adds"]),
            _compact(area["dels"]), tail)
    return "%s %s%s" % (area["area"], files, tail)


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
    drop a subject that repeats an earlier one; rank feat/fix/refactor/perf
    and protocol-keyword subjects first."""
    kept: List[str] = []
    seen = set()
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
        key = " ".join(subject.lower().split())
        if key in seen:
            continue
        seen.add(key)
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


def _digest_details(pending: List[Tuple[int, str, str, str]]) -> List[str]:
    return ["%s · %s" % (_CHURN_AREA_WORDS.get(row[2], rec(row[2])),
                         mono(row[1][:8])) for row in pending]


def _sentence_case(text: str) -> str:
    """First letter up, the rest untouched (keeps acronyms like CI)."""
    return text[:1].upper() + text[1:]


def _tidy_subject(subject: str) -> str:
    """Display form of a commit subject: conventional prefix removed, its
    scope kept in parentheses at the end, first letter capitalized."""
    match = _CONV_PREFIX_RE.match(subject)
    scope = ""
    if match:
        scope = (match.group(2) or "").strip("()")
        subject = subject[match.end():].strip()
    subject = subject[:1].upper() + subject[1:]
    if scope:
        subject = "%s (%s)" % (subject, scope)
    return _clip_words(subject, 100)


def _repo_headline(rng: Dict[str, Any], live: Optional[Dict[str, Any]],
                   verdict: str, areas: List[Dict[str, Any]]) -> str:
    prev_spec, new_spec = rng["prev_spec"], rng["new_spec"]
    if (prev_spec is not None and new_spec is not None
            and prev_spec != new_spec):
        if live is None:
            return "Subtensor code moved to runtime spec %d" % new_spec
        if new_spec > live["spec_version"]:
            return ("Subtensor code for runtime spec %d is ready. Not live "
                    "yet." % new_spec)
        return ("Subtensor code moved to runtime spec %d (live chain: %d)"
                % (new_spec, live["spec_version"]))
    if verdict.startswith("large or incomplete"):
        return "Large or incomplete subtensor update: review it"
    if verdict.startswith("new unmapped area"):
        unknown = [a["area"] for a in areas if a["cls"] == UNKNOWN][:3]
        return "Subtensor code touches a new area: %s" % ", ".join(unknown)
    if verdict.startswith("large sync"):
        return "Large subtensor sync with a light protocol touch"
    if verdict == "core protocol change":
        return "Subtensor protocol code changed"
    if verdict.startswith("node"):
        return "Subtensor node code changed"
    return "Subtensor code changed"


def _build_repo_event(rng: Dict[str, Any], live: Optional[Dict[str, Any]],
                      pending: List[Tuple[int, str, str, str]],
                      max_chars: int,
                      policy: Dict[str, Any],
                      glosses: Dict[str, str],
                      config: Optional[Dict[str, Any]] = None
                      ) -> Dict[str, Any]:
    """A significant range in the house layout: headline answers "is it
    live?", the size and protocol churn are key figures, the most
    substantive commit subjects sit in the body, and the per-area counts,
    pallets, housekeeping, and provenance sit in the details fold."""
    areas = _aggregate_areas(rng["file_entries"], rng["files_truncated"],
                             policy["area_map"])
    verdict = _repo_verdict(rng, live, areas, policy)
    core = [a for a in areas if a["cls"] == CORE]
    unknown = [a for a in areas if a["cls"] == UNKNOWN]
    node = [a for a in areas if a["cls"] == NODE]
    noise = [a for a in areas if a["cls"] == NOISE]
    lower = rng["files_truncated"] or rng["non_fast_forward"]
    at_least = "at least " if lower else ""

    facts = [("Size", "%s%s, %s%s" % (
        "at least " if rng["commits_truncated"] else "",
        plural(len(rng["commits"]), "commit"),
        at_least, plural(len(rng["files"]), "file")))]
    if core:
        adds = sum(a["adds"] for a in core)
        dels = sum(a["dels"] for a in core)
        facts.append(("Protocol code", "%s+%s / %s%s lines" % (
            at_least, _compact(adds), MINUS, _compact(dels))
            if adds or dels else "%s%s" % (
                at_least, plural(sum(a["files"] for a in core), "file"))))
        words: List[str] = []
        for entry in _pallet_domains(rng["file_entries"],
                                     policy["pallet_map"]):
            name, _sep, label = entry.partition(" (")
            word = label.rstrip(")") if label else name
            word = word.replace("/", ", ")
            if word not in words:
                words.append(word)
        for area in core:
            if area["area"] != "pallets":
                word = _CORE_AREA_WORDS.get(area["area"], area["area"])
                if word not in words:
                    words.append(word)
        if words:
            facts.append(("Areas", " · ".join(rec(w) for w in words[:5])))
    if unknown:
        facts.append(("New area", " · ".join(
            rec(a["area"]) for a in unknown[:4])))

    body: List[str] = []
    commits = _filter_commits(rng["commits"])
    if commits:
        body.append(bold("Main changes"))
        body.extend("• " + rec(_tidy_subject(s)) for s in commits[:4])
    else:
        body.append("• No feature or fix commits in this range (tooling "
                    "only)")

    details = ["Range %s → %s" % (mono(rng["prev_sha"][:8]),
                                  mono(rng["new_sha"][:8])),
               "Repo spec %s · live spec %s" % (
                   ("%s → %s" % (rng["prev_spec"], rng["new_spec"])
                    if rng["prev_spec"] is not None
                    and rng["new_spec"] is not None
                    and rng["prev_spec"] != rng["new_spec"]
                    else rng["new_spec"] if rng["new_spec"] is not None
                    else "n/a"),
                   live["spec_version"] if live else "n/a")]
    details.extend(rec(_area_churn(a)) for a in core[:6])
    pallets = [entry.partition(" (")[0] for entry in _pallet_domains(
        rng["file_entries"], policy["pallet_map"])]
    if pallets:
        details.append("pallets: %s" % ", ".join(rec(p) for p in pallets[:6]))
    details.extend("new area " + rec(_area_churn(a)) for a in unknown[:6])
    if node:
        details.append("node %s (%s)" % (
            plural(sum(a["files"] for a in node), "file"),
            ", ".join("%s %d" % (rec(a["area"]), a["files"])
                      for a in node[:6])))
    if noise:
        details.append("housekeeping %s (%s)" % (
            plural(sum(a["files"] for a in noise), "file"),
            ", ".join("%s %d" % (rec(a["area"]), a["files"])
                      for a in sorted(noise, key=lambda a: -a["files"])[:6])))
    if rng["tags"]:
        details.append("tags: %s" % ", ".join(rec(t) for t in rng["tags"][:6]))
    if rng["commits_truncated"]:
        details.append("Commit list truncated at the recorder cap")
    if lower:
        details.append("Counts are a lower bound: change record incomplete")
    if pending:
        details.append(_digest_line(pending))
        details.extend(_digest_details(pending))
    details.append("Built from recorded change data. Effects not verified.")

    msg = Message(severity="watch",
                  headline=_repo_headline(rng, live, verdict, areas),
                  meaning=_both_clocks_line(rng["new_spec"], live),
                  facts=facts, body=body,
                  details=[redact(line) for line in details],
                  buttons=button(config, "View diff on GitHub",
                                 "subtensor_compare",
                                 prev=rng["prev_sha"], new=rng["new_sha"]))
    return message_event(msg, "repository-update:range:%d" % rng["id"],
                         "repository-update", _utc_now(), max_chars, glosses,
                         digest_range_ids=[row[0] for row in pending])


def _build_digest_event(pending: List[Tuple[int, str, str, str]],
                        max_chars: int,
                        glosses: Dict[str, str]) -> Dict[str, Any]:
    words: List[str] = []
    for row in pending:
        word = _CHURN_AREA_WORDS.get(row[2], rec(row[2]))
        if word not in words:
            words.append(word)
    msg = Message(severity="info",
                  headline="Subtensor: %d housekeeping update%s" % (
                      len(pending), "" if len(pending) == 1 else "s"),
                  meaning="%s only. No protocol or runtime spec change. "
                          "Repo (source code) only, not the live chain."
                          % _sentence_case(", ".join(words[:5])),
                  details=_digest_details(pending))
    return message_event(msg, "repository-churn-digest:%d" % pending[-1][0],
                         "repository-update", _utc_now(), max_chars, glosses,
                         digest_range_ids=[row[0] for row in pending])
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
                                        policy, glosses, config))

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


def _release_for_upgrade(repo_db: Optional[str], new_spec: int
                         ) -> Optional[Dict[str, str]]:
    """The tracked repository range whose recorded spec delta covers this
    upgrade: release commit subject plus top touched areas. None when the
    store, table, or a matching range is absent; the caller states that
    rather than inventing repository facts."""
    if not repo_db:
        return None
    conn = open_source_ro(resolve(repo_db))
    if conn is None:
        return None
    try:
        present = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND "
            "name = 'change_ranges'").fetchone()
        if present is None:
            return None
        row = conn.execute(
            "SELECT commits_json, files_json FROM change_ranges "
            "WHERE prev_spec IS NOT NULL AND new_spec IS NOT NULL "
            "AND prev_spec < ? AND new_spec >= ? "
            "ORDER BY id DESC LIMIT 1", (new_spec, new_spec)).fetchone()
    except sqlite3.Error:
        return None
    finally:
        conn.close()
    if row is None:
        return None
    try:
        commits = (json.loads(row[0]) or {}).get("commits") or []
        subject = str(commits[0]["subject"]) if commits else None
        files = (json.loads(row[1]) or {}).get("files") or []
    except (ValueError, TypeError, KeyError, IndexError):
        return None
    if not subject:
        return None
    counts: Dict[str, int] = {}
    for entry in files:
        path = entry.get("path") if isinstance(entry, dict) else None
        if not path:
            continue
        top = str(path).split("/", 1)[0]
        counts[top] = counts.get(top, 0) + 1
    areas = " · ".join("%s (%d)" % (name, count) for name, count in
                       sorted(counts.items(), key=lambda kv: -kv[1])[:3])
    return {"subject": subject, "areas": areas}


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
    spec = (ctx or {}).get("spec") or {}
    max_chars = int(config.get("message_max_chars", 3500))
    threshold = int(config.get("governance_threshold",
                               DEFAULT_GOVERNANCE_THRESHOLD))
    _lexicon, glosses = voice_maps(config)
    events: List[Dict[str, Any]] = []
    high = last_id
    for row_id, observed_at, prev_spec, new_spec, block in rows:
        high = max(high, int(row_id))
        crossed = prev_spec < threshold <= new_spec
        meaning = ("The live chain now runs new code (was %s). This is an "
                   "enacted live chain change, not a repo change."
                   % prev_spec)
        next_action = None
        if crossed:
            meaning += (" Governance spec %d is crossed: conviction-based "
                        "subnet ownership is now enforced." % threshold)
            next_action = ("review your subnet positions, because "
                           "conviction enforcement is live.")
        # One message explains the upgrade (change: pulse-briefing): the
        # matching repository range supplies the release subject and the
        # touched areas; its absence is stated, never guessed around.
        release = _release_for_upgrade(spec.get("repo_db"), new_spec)
        facts = [("Release", rec(release["subject"]) if release else
                  "not matched to a tracked repo range yet")]
        if release and release["areas"]:
            facts.append(("Touched", rec(release["areas"])))
        facts.append(("When", fmt_time(observed_at)))
        msg = Message(
            severity=severity_for("chain-runtime-upgrade",
                                  governance_crossed=crossed),
            headline="Bittensor upgraded to runtime spec %s" % new_spec,
            meaning=meaning, facts=facts,
            details=["Block %s" % fmt_int(block),
                     "Runtime spec %s → %s" % (prev_spec, new_spec),
                     "Source: livedata spec record (live chain)"],
            next_action=next_action,
            buttons=button(config, "Subtensor releases",
                           "subtensor_releases"))
        events.append(message_event(
            msg, "chain-runtime-upgrade:%s" % row_id,
            "chain-runtime-upgrade", _utc_now(), max_chars, glosses))
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
        name = provider_name(provider)
        msg = Message(
            severity="watch",
            headline="%s changed its reply format. %s is paused."
                     % (name, rec(operation)),
            meaning=("Atlas rejects the new replies rather than guess, so "
                     "this source shows n/a until the expected format is "
                     "updated."),
            facts=[("What changed", rec(_clip_words(detail or "n/a", 300))),
                   ("Since", fmt_time(ts))],
            details=["Provider: %s · operation: %s" % (rec(provider),
                                                        rec(operation)),
                     "Source: livedata integration health"],
            next_action="update the pinned schema for %s %s under %s."
                        % (rec(provider), rec(operation),
                           mono("livedata/schemas/%s/" % rec(provider))))
        events.append(message_event(msg, "schema-drift:%s" % row_id,
                                    "schema-drift", _utc_now(), max_chars,
                                    glosses))
    return events, (str(high) if high else watermark)


_PROVIDER_NAMES = {"coingecko": "CoinGecko", "taostats": "TaoStats",
                   "taoswap": "TaoSwap", "finney-rpc": "The chain RPC"}


def provider_name(provider: Any) -> str:
    text = rec(provider)
    return _PROVIDER_NAMES.get(text.lower(), text)


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
        details = ["Run %s" % mono(rid), "Ingested %s" % rec(intake_date),
                   "Source: knowledge intake store"]
        if staged > 0:
            msg = Message(
                severity=severity_for("knowledge-ingestion", staged=staged),
                headline="%s new knowledge unit%s waiting for review"
                         % (fmt_int(staged), "s are" if staged != 1
                            else " is"),
                meaning="Staged units stay inactive until you activate "
                        "them.",
                facts=[("Covers", "up to %s" % rec(coverage))],
                details=details,
                next_action="review the units, then run %s"
                            % mono("python3 knowledge/atlas_kb.py activate "
                                   "--run %s" % rid))
        else:
            msg = Message(
                severity=severity_for("knowledge-ingestion", staged=0),
                headline="Knowledge ingest finished, nothing new to review",
                facts=[("Covers", "up to %s" % rec(coverage))],
                details=details)
        events.append(message_event(msg, "knowledge-ingestion:%s" % rid,
                                    "knowledge-ingestion", _utc_now(),
                                    max_chars, glosses))
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
        event_cols = {r[1] for r in
                      conn.execute("PRAGMA table_info(gate_events)")}
        has_prev = "prev_theta" in event_cols
        has_hover = "hovering" in event_cols
        # Eligibility arrived with rotation-signal-gate. A store written
        # before it reports NULL, which reads as eligible: those crossings
        # were already pageable under the previous contract and must not be
        # swallowed by the upgrade.
        has_eligibility = "eligibility" in event_cols
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

        names = subnet_names_from(conn)
        has_panel = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND "
            "name = 'panel_snapshot'").fetchone() is not None

        def _price_at(netuid: int, block: Any) -> Optional[float]:
            """Alpha price from the panel snapshot at the crossing's block,
            else the latest at or below it. A recorded row, not a guess."""
            if not has_panel or block is None:
                return None
            row = conn.execute(
                "SELECT moving_price_tao FROM panel_snapshot WHERE "
                "netuid = ? AND block_number <= ? AND moving_price_tao > 0 "
                "ORDER BY block_number DESC, id DESC LIMIT 1",
                (netuid, block)).fetchone()
            return float(row[0]) if row else None

        rows = conn.execute(
            "SELECT e.id, e.observed_at, e.netuid, e.direction, e.share, "
            "e.theta, e.prev_side, e.emission_enabled, e.block_number, "
            + ("e.prev_theta, " if has_prev else "NULL, ")
            + ("e.hovering, " if has_hover else "NULL, ")
            + _at_event("bar_mode") + ", "
            + _at_event("rank") + ", "
            + _at_event("q") + ", "
            + ("COALESCE(e.eligibility, 'eligible')" if has_eligibility
               else "'eligible'") +
            " FROM gate_events e "
            "WHERE e.id > ? ORDER BY e.id ASC LIMIT 50",
            (last_id,)).fetchall()
        prices = {row[0]: _price_at(row[2], row[8]) for row in rows}
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
         _prev_side, emission_enabled, block_number, prev_theta, hovering,
         bar_mode, bar_rank, bar_q, eligibility) in rows:
        event_id = "gate-crossing:%d:%d" % (netuid, row_id)
        # Durability guard (change: rotation-signal-gate). A crossing that
        # has not settled yet is left for a later scan and the watermark
        # STOPS here, so it is reconsidered rather than lost. A crossing
        # settled as reversed is recorded and skipped: at a rank-pinned bar
        # the marginal subnet oscillates by construction, and an
        # oscillation is a state for the briefing, not a pair of pages.
        if eligibility == "pending":
            break
        high = max(high, int(row_id))
        if eligibility == "reversed":
            if store is not None:
                ledger_record(store, event_id, "gate-crossing", observed_at,
                              _utc_now(), STATUS_SUPPRESSED, 0,
                              "reversed inside the durability window",
                              tier=ctx.get("tier"))
            continue
        if hovering and store is not None:
            # A flagged hoverer's crossings are recorded, never paged
            # (change: pulse-briefing): the briefing reports them as a
            # count instead of an alert per wobble.
            ledger_record(store, event_id, "gate-crossing", observed_at,
                          _utc_now(), STATUS_SUPPRESSED, 0,
                          "hovering subnet")
            continue
        if store is not None and _gate_cooldown_active(
                store, netuid, cooldown_hours):
            ledger_record(store, event_id, "gate-crossing", observed_at,
                          _utc_now(), STATUS_SUPPRESSED, 0,
                          "per-netuid cooldown (%gh)" % cooldown_hours)
            continue
        events.append(_gate_crossing_event(
            event_id, observed_at, netuid, direction, share, theta,
            emission_enabled, block_number, prev_theta, bar_mode, bar_rank,
            bar_q, prices.get(row_id), names, config, max_chars, glosses))
    return events, (str(high) if high else watermark)


def _ordinal(value: Any) -> str:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return rec(value)
    suffix = ("th" if 10 <= number % 100 <= 20
              else {1: "st", 2: "nd", 3: "rd"}.get(number % 10, "th"))
    return "%d%s" % (number, suffix)


def _gate_crossing_event(event_id: str, observed_at: str, netuid: int,
                         direction: str, share: float, theta: float,
                         emission_enabled: Any, block_number: Any,
                         prev_theta: Optional[float], bar_mode: Any,
                         bar_rank: Any, bar_q: Any, price: Optional[float],
                         names: Dict[int, str], config: Dict[str, Any],
                         max_chars: int, glosses: Dict[str, str]
                         ) -> Dict[str, Any]:
    """One confirmed crossing in the house layout. Every figure comes from
    the recorded event, its gate observation, or the panel snapshot at
    the event's block."""
    fell = direction == "fell-below"
    label = subnet_label(netuid, names)
    verb = "fell below" if fell else "rose above"
    margin_pct = ((share - theta) / theta * 100.0) if theta else 0.0
    details: List[str] = []
    # A rank-pinned bar is itself a demand share, so it moves on its own.
    # Without this a subnet the bar descended onto reads as a subnet whose
    # demand rose, which is what the 2026-08-03 reset produced.
    cause = None
    if prev_theta is not None and prev_theta > 0:
        bar_move = (theta - prev_theta) / prev_theta * 100.0
        crossed_by_bar = ((prev_theta > share >= theta) if not fell
                          else (prev_theta < share <= theta))
        cause = ("the bar moved onto this subnet, its demand share did not "
                 "cross on its own" if crossed_by_bar else
                 "the subnet's own demand share moved across the bar")
        details.append("Bar moved %s this poll (%s → %s)" % (
            fmt_change(bar_move), fmt_pct(prev_theta), fmt_pct(theta)))
    details.append("Shares: TaoSwap panel. Bar: chain RPC.")
    details.append("Block %s · %s" % (fmt_int(block_number),
                                      fmt_time(observed_at)))
    buttons = button(config, "Subnet %d on taostats" % netuid,
                     "taostats_subnet", netuid=netuid)
    above_below = "%s %s the bar" % (fmt_change(abs(margin_pct)).lstrip("+"),
                                     "below" if margin_pct < 0 else "above")
    if emission_enabled == 0:
        msg = Message(
            severity=severity_for("gate-crossing", emission_enabled=0,
                                  direction=direction),
            headline="%s %s the emission bar, no effect" % (label, verb),
            meaning="Emission is switched off for this subnet, so it earns "
                    "zero either way.",
            details=["Demand share %s, bar %s (%s)" % (
                fmt_pct(share), fmt_pct(theta), above_below)] + details,
            buttons=buttons)
        return message_event(msg, event_id, "gate-crossing", _utc_now(),
                             max_chars, glosses)
    meaning = ("Its demand share dropped under the bar, so its gated "
               "emission collapses toward zero." if fell else
               "Its demand share passed the bar, so it now earns an "
               "amplified emission share instead of a collapsing one.")
    # The bar's selection rule (change: network-drift-443). Never infer it:
    # a q recorded while rank mode is active is inert.
    if bar_mode == "rank":
        bar_value = "%s (the %s largest demand share)" % (
            fmt_pct(theta), _ordinal(bar_rank))
    elif bar_mode == "q-mass":
        bar_value = ("%s (a quantile of the demand-share distribution, "
                     "q %s)" % (fmt_pct(theta), rec(bar_q)))
    else:
        bar_value = fmt_pct(theta)
    facts = [("Demand share", "%s, %s" % (fmt_pct(share), above_below)),
             ("Bar", bar_value)]
    if cause:
        facts.append(("Cause", cause))
    if price is not None:
        facts.append(("Price", fmt_tao(price)))
    msg = Message(
        severity=severity_for("gate-crossing", emission_enabled=1,
                              direction=direction),
        headline="%s %s the emission bar" % (label, verb),
        meaning=meaning, facts=facts, details=details,
        next_action=("review your subnet %d position." % netuid
                     if fell else None),
        buttons=buttons)
    return message_event(msg, event_id, "gate-crossing", _utc_now(),
                         max_chars, glosses)


# ---------------------------------------------------------------------------
# Fleet-signal adapter (change: fleet-signals) — narrative-cluster /
# watchlist / econ-code instant alerts + durable signal digest lines,
# from the fleet store's signal_events queue. The fleet store is opened
# STRICTLY read-only; this class's delivery watermark lives in this
# module's own ledger like every other source.
# ---------------------------------------------------------------------------

DEFAULT_SIGNAL_BACKSTOP_HOURS = 24
_SN_LINE_RE = re.compile(r"^SN(\d+)\s+(.*)$")
_SHA12_RE = re.compile(r"\b[0-9a-f]{12}\b")
_ECON_IMPACT_LABEL = {"high": "high", "med": "medium"}
_ECON_DIRECTION_LABEL = {
    "emissions_up": "emissions ↑", "emissions_down": "emissions ↓",
    "reshuffle": "winners and losers reshuffle", "neutral": "no net effect",
    "unknown": "direction unclear"}


def _pending_signal_rows(store: sqlite3.Connection
                         ) -> List[Tuple[int, str, str]]:
    return store.execute(
        "SELECT event_row_id, line, detected_at FROM pending_signal "
        "ORDER BY event_row_id ASC").fetchall()


def _riding_digest(pending: List[Tuple[int, str, str]],
                   names: Dict[int, str]) -> List[str]:
    """Pending minor signals carried in an instant alert's fold. They are
    cleared once this alert is delivered, so the items themselves ride
    here, never a pointer to a later digest."""
    if not pending:
        return []
    body, shas = _digest_items(pending, names)
    return (["Also pending, %s:" % plural(len(pending), "minor signal")]
            + body + shas)


def _subnet_label(conn: sqlite3.Connection, netuid: Optional[int],
                  names: Optional[Dict[int, str]] = None) -> str:
    """`Subnet <netuid> (Name)` from the recorded panel name; the number
    alone when none is recorded."""
    if netuid is None:
        return "Fleet"
    return subnet_label(netuid, names or {})


def _entry_price_line(conn: sqlite3.Connection,
                      event_row_id: int) -> Optional[str]:
    parts = ["subnet %d %s" % (n, fmt_tao(p))
             for n, p in _entry_prices(conn, event_row_id)]
    return ("entry price · " + " · ".join(parts[:8])) if parts else None


def _digest_items(pending: List[Tuple[int, str, str]],
                  names: Dict[int, str]
                  ) -> Tuple[List[str], List[str]]:
    """Pending fleet digest lines as (body lines, detail lines). Each item
    gets its own line, named by subnet; items of one subnet and one kind
    merge into one line with a count, their SHAs moving to the details.
    The lines are recorded fleet text: escaped data, never glossed."""
    order: List[Tuple[Any, str]] = []
    groups: Dict[Tuple[Any, str], Dict[str, Any]] = {}
    for _row_id, line, _detected in pending:
        text = rec(line)
        match = _SN_LINE_RE.match(text)
        netuid = int(match.group(1)) if match else None
        rest = match.group(2) if match else text
        shas = _SHA12_RE.findall(rest)
        kind = " ".join(_SHA12_RE.sub("", rest).split())
        kind = re.sub(r"\s+·\s+·\s+", " · ", kind).strip(" ·")
        key = (netuid, kind)
        if key not in groups:
            order.append(key)
            groups[key] = {"count": 0, "shas": []}
        groups[key]["count"] += 1
        groups[key]["shas"].extend(shas)
    body: List[str] = []
    details: List[str] = []
    for key in order:
        netuid, kind = key
        group = groups[key]
        who = subnet_tag(netuid, names) if netuid is not None else "Fleet"
        count = " (%d×)" % group["count"] if group["count"] > 1 else ""
        body.append("• %s: %s%s" % (bold(who), _clip_words(kind, 120), count))
        if group["shas"]:
            details.append("%s: %s" % (who, ", ".join(
                mono(sha[:8]) for sha in group["shas"][:6])))
    return body, details


def _slot_repo(conn: sqlite3.Connection, netuid: Any) -> Optional[str]:
    """owner/repo of a subnet's tracked repository, or None."""
    if netuid is None:
        return None
    try:
        row = conn.execute("SELECT github_repo FROM slots WHERE netuid = ?",
                           (netuid,)).fetchone()
    except sqlite3.Error:
        return None
    return repo_slug(row[0]) if row and row[0] else None


def _entry_prices(conn: sqlite3.Connection,
                  event_row_id: int) -> List[Tuple[int, float]]:
    """(netuid, alpha price) snapshots recorded for one event; empty while
    pending (the line is omitted, delivery is never delayed)."""
    try:
        rows = conn.execute(
            "SELECT netuid, price_tao, status FROM signal_entries "
            "WHERE event_id = ? ORDER BY netuid ASC",
            (event_row_id,)).fetchall()
    except sqlite3.Error:
        return []
    return [(int(n), float(p)) for n, p, status in rows
            if status in ("recorded", "late") and p is not None]


def _build_cluster_event(conn: sqlite3.Connection, row_id: int,
                         payload: Dict[str, Any], created_at: str,
                         dedup_key: str, pending: List[Tuple[int, str, str]],
                         max_chars: int,
                         glosses: Dict[str, str],
                         names: Optional[Dict[int, str]] = None,
                         config: Optional[Dict[str, Any]] = None
                         ) -> Dict[str, Any]:
    names = names or {}
    term = rec(payload.get("term") or "?")[:120]
    members = payload.get("members") or []
    first = payload.get("first_mover") or {}
    prevalence = payload.get("prevalence") or {}
    first_n = first.get("netuid")
    facts: List[Tuple[str, str]] = []
    if first:
        facts.append(("First", "%s, %s" % (
            subnet_label(first_n, names, capital=False),
            fmt_date(first.get("adopted_at")))))
    others = [m.get("netuid") for m in members if m.get("netuid") != first_n]
    if others:
        facts.append(("Then", ", ".join(
            subnet_label(n, names, capital=False) for n in others[:8])))
    prices = _entry_prices(conn, row_id)
    body = []
    if prices:
        body = [bold("Prices at detection"), " · ".join(
            "%s %s" % (subnet_tag(n, names), fmt_tao(p))
            for n, p in prices[:8])]
    details = []
    if first.get("commit_sha"):
        details.append("First commit %s in subnet %s" % (
            mono(str(first["commit_sha"])[:8]), rec(first_n)))
    details.append("Source: fleet repos (code), not the live chain")
    details.extend(_riding_digest(pending, names))
    meaning = "A shared model choice across subnets can signal a trend."
    if prevalence:
        meaning += " %s of %s active subnets now use it." % (
            rec(prevalence.get("adopters", "?")),
            rec(prevalence.get("active_slots", "?")))
    msg = Message(
        severity="watch",
        headline="%d subnets adopted %s within %s days" % (
            len(members), term, rec(payload.get("window_days", "?"))),
        meaning=meaning, facts=facts, body=body, details=details,
        buttons=button(config, "First commit", "github_commit",
                       repo=_slot_repo(conn, first_n),
                       sha=first.get("commit_sha")))
    return message_event(msg, "fleet-signal:%s" % dedup_key,
                         "narrative-cluster", created_at, max_chars, glosses,
                         digest_signal_ids=[row[0] for row in pending])


def _build_watchlist_event(conn: sqlite3.Connection, row_id: int,
                           payload: Dict[str, Any], created_at: str,
                           dedup_key: str,
                           pending: List[Tuple[int, str, str]],
                           max_chars: int,
                           glosses: Dict[str, str],
                           names: Optional[Dict[int, str]] = None,
                           config: Optional[Dict[str, Any]] = None
                           ) -> Dict[str, Any]:
    names = names or {}
    term = rec(payload.get("term") or "?")[:120]
    netuid = payload.get("netuid")
    commit = str(payload.get("commit_sha") or "")[:12] or None
    facts = []
    prices = _entry_prices(conn, row_id)
    if prices:
        facts.append(("Price at detection", fmt_tao(prices[0][1])))
    details = []
    if payload.get("source_file"):
        details.append("File %s" % mono(str(payload["source_file"])[:120]))
    if commit:
        details.append("Commit %s" % mono(commit[:8]))
    repo = _slot_repo(conn, netuid)
    if repo:
        details.append("Repo %s" % rec(repo))
    details.append("Source: fleet repos (code), not the live chain")
    details.extend(_riding_digest(pending, names))
    msg = Message(
        severity="watch",
        headline="Watchlist: %s now uses %s" % (
            _subnet_label(conn, netuid, names), term),
        meaning="A term on your watchlist appeared in this subnet's code.",
        facts=facts, details=details,
        next_action="review the commit." if commit else None,
        buttons=button(config, "Open commit", "github_commit",
                       repo=_slot_repo(conn, netuid), sha=commit))
    return message_event(msg, "fleet-signal:%s" % dedup_key, "watchlist",
                         created_at, max_chars, glosses,
                         digest_signal_ids=[row[0] for row in pending])


# Verdict free-text bounds (repo/model-derived; escaped at render). Clipped
# at a word boundary so a card never cuts mid-word.
_WHAT_MAX = 160
_WHY_MAX = 160
_EVIDENCE_MAX = 220



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


def _build_econ_event(conn: sqlite3.Connection, row_id: int,
                      payload: Dict[str, Any], created_at: str,
                      dedup_key: str, pending: List[Tuple[int, str, str]],
                      max_chars: int,
                      glosses: Dict[str, str],
                      names: Optional[Dict[int, str]] = None,
                      config: Optional[Dict[str, Any]] = None
                      ) -> Dict[str, Any]:
    """Meaning-first card: what changed leads, why it matters and the
    impact are key figures, evidence and provenance sit in the fold.
    Verdict text is model output over untrusted repos: escaped data."""
    names = names or {}
    netuid = payload.get("netuid")
    label = _subnet_label(conn, netuid, names)
    significance = payload.get("significance")
    unjudged = bool(payload.get("unjudged"))
    prices = _entry_prices(conn, row_id)
    repo = _slot_repo(conn, netuid)

    facts: List[Tuple[str, str]] = []
    body: List[str] = []
    details: List[str] = []
    meaning = None
    if unjudged:
        headline = "%s changed its incentive code (unjudged)" % label
        meaning = "Verdict unavailable: the judge could not read this change."
    elif significance:
        headline = "%s changed how miners get paid" % label
        meaning = rec(_clip(payload.get("what_changed"), _WHAT_MAX) or "")
        why = _clip(payload.get("why_it_matters"), _WHY_MAX)
        if why:
            facts.append(("Why it matters", rec(why)))
        facts.append(("Impact", "%s · %s" % (
            _ECON_IMPACT_LABEL.get(significance, rec(significance)),
            _ECON_DIRECTION_LABEL.get(payload.get("direction"),
                                      "direction unclear"))))
        if payload.get("partial_view"):
            body.append(italic("The judge saw only part of this change."))
        evidence = _clip(payload.get("evidence"), _EVIDENCE_MAX)
        if evidence:
            details.append("Evidence: %s" % rec(evidence))
    else:
        # Legacy / gate-off event (no verdict in payload).
        headline = "%s changed its incentive code" % label
    if prices:
        facts.append(("Price at detection", fmt_tao(prices[0][1])))
    details.append("%s%s · %s → %s" % (
        plural(payload.get("commit_count", "?"), "commit"),
        "+" if payload.get("commits_truncated") else "",
        mono(str(payload.get("prev_sha") or "-")[:8]),
        mono(str(payload.get("new_sha") or "-")[:8])))
    files = [str(path) for path in (payload.get("files") or [])]
    if files:
        shown = [f.rstrip("/").rsplit("/", 1)[-1][:48] for f in files[:3]]
        details.append(", ".join(rec(f) for f in shown)
                       + (", +%d more" % (len(files) - 3)
                          if len(files) > 3 else ""))
    if repo:
        details.append("Repo %s" % rec(repo))
    details.extend(_riding_digest(pending, names))
    buttons = button(config, "View commits", "github_compare", repo=repo,
                     prev=payload.get("prev_sha"), new=payload.get("new_sha"))
    if netuid is not None:
        buttons += button(config, "Subnet %s" % rec(netuid),
                          "taostats_subnet", netuid=netuid)
    msg = Message(severity="watch", headline=headline, meaning=meaning,
                  facts=facts, body=body, details=details, buttons=buttons)
    return message_event(msg, "fleet-signal:%s" % dedup_key, "econ-code",
                         created_at, max_chars, None,
                         digest_signal_ids=[row[0] for row in pending])


def _build_signal_digest_event(pending: List[Tuple[int, str, str]],
                               max_chars: int,
                               glosses: Dict[str, str],
                               names: Optional[Dict[int, str]] = None
                               ) -> Dict[str, Any]:
    body, details = _digest_items(pending, names or {})
    details.append("Source: fleet repos (code), not the live chain")
    msg = Message(
        severity=severity_for("signal-digest"),
        headline="%d minor code signal%s since the last alert" % (
            len(pending), "" if len(pending) == 1 else "s"),
        meaning="None was strong enough to page on its own.",
        body=body, details=details)
    return message_event(msg, "fleet-signal-digest:%d" % pending[-1][0],
                         "signal-digest", _utc_now(), max_chars, glosses,
                         digest_signal_ids=[row[0] for row in pending])
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
        names = subnet_names(live_db_path(config))

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
                    max_chars, glosses, names, config))
            elif event_class == "watchlist":
                events.append(_build_watchlist_event(
                    conn, row_id, payload, created_at, dedup_key, pending,
                    max_chars, glosses, names, config))
            else:  # econ-code (and any future instant class: fail visible)
                events.append(_build_econ_event(
                    conn, row_id, payload, created_at, dedup_key, pending,
                    max_chars, glosses, names, config))

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
                        pending, max_chars, glosses, names))
        return events, (str(high) if high else watermark)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Chain-parameter change (change: network-drift-443) — a root-settable knob
# that governs network economics moved. Rare and unconditionally material,
# so: instant tier, NO cooldown, no digest. Suppressing the second flip of a
# switch like `BasketTradingEnabled` would be the wrong failure.
# ---------------------------------------------------------------------------

_PROVENANCE_WORDS = {"explicit": "stored value",
                     "assumed-default": "chain default, not stored"}

_NETUID_ITEM_RE = re.compile(r"^(?P<item>[A-Za-z0-9_]+)\[(?P<netuid>\d+)\]$")
_PARAM_FETCH_LIMIT = 256
_NETUID_LIST_CAP = 40


def parse_netuid_item(name: str) -> Tuple[str, Optional[int]]:
    """Split a composite watched-item name; netuid is None for a global."""
    match = _NETUID_ITEM_RE.match(name or "")
    if match is None:
        return name, None
    return match.group("item"), int(match.group("netuid"))


def _param_event_id(row_id: int) -> str:
    return "chain-parameter-change:%s" % row_id


def _switch_body_line(base_item: str, new_value: str) -> Optional[str]:
    """The pool-side emission switch named as a switch: alpha distribution
    continues while TAO injection stops (or resumes)."""
    if base_item != "SubnetEmissionEnabled":
        return None
    if str(new_value).lower() == "true":
        return ("Root turned TAO injection back on for this subnet. Alpha "
                "distribution was never interrupted.")
    return ("Root switched off TAO injection for this subnet. Its alpha "
            "distribution continues. Its TAO share goes to the other "
            "subnets.")


def _param_value(value: Any) -> str:
    text = rec(value)
    if text.lower() in ("true", "false"):
        return "on" if text.lower() == "true" else "off"
    return fmt_int(text) if text.isdigit() else text


def _render_param_event(item: str, prev_value: str, new_value: str,
                        prev_prov: str, new_prov: str, observed_at: str,
                        block_number: Any, governs: Dict[str, str],
                        max_chars: int, glosses: Dict[str, str],
                        netuids: Optional[List[int]] = None,
                        names: Optional[Dict[int, str]] = None,
                        config: Optional[Dict[str, Any]] = None
                        ) -> Tuple[str, str, Optional[str],
                                   List[Tuple[str, str]]]:
    """Return (plain, html, next_action, buttons) for one page, single or
    collapsed. A netuid-keyed item always names its subnet."""
    names = names or {}
    base_item, item_netuid = parse_netuid_item(item)
    if netuids is None and item_netuid is not None:
        netuids = [item_netuid]
    count = len(netuids) if netuids else 0
    collapsed = count > 1
    single = netuids[0] if count == 1 else None
    where = (subnet_label(single, names) if single is not None else None)
    change = "%s → %s" % (_param_value(prev_value), _param_value(new_value))
    description = governs.get(base_item)

    meaning: Optional[str] = None
    next_action: Optional[str] = None
    if base_item == "SubnetEmissionEnabled":
        on = str(new_value).lower() == "true"
        if collapsed:
            headline = "TAO emission %s on %d subnets" % (
                "restored" if on else "switched off", count)
        else:
            headline = "%s %s TAO emission%s" % (
                where or "A subnet", "receives" if on else
                "stopped receiving", " again" if on else "")
        meaning = _switch_body_line(base_item, new_value)
        if collapsed and meaning:
            meaning = meaning.replace("this subnet", "these subnets").replace(
                "Its ", "Their ")
    elif base_item in ("EmissionBarRank", "EmissionBarQuantile",
                       "EmissionGateExponent"):
        headline = "Emission bar rule changed: %s %s" % (base_item, change)
        parts = []
        if base_item == "EmissionBarRank":
            if str(new_value) == "0":
                parts.append("The bar has fallen back to q-mass selection.")
            elif str(prev_value) == "0":
                parts.append("The bar is now rank-pinned; q is inert.")
        parts.append("The bar was re-priced for every subnet. Per-subnet "
                     "crossing alerts were withheld for that pass by "
                     "design.")
        meaning = " ".join(parts)
        next_action = "review your subnet positions against the new gate terms."
    elif collapsed:
        headline = "%s changed on %d subnets" % (base_item, count)
    elif where:
        headline = "%s: %s changed" % (where, base_item)
    else:
        headline = "Chain setting changed: %s" % base_item
    if base_item == "BasketConcentrationCap":
        next_action = ("review root basket positions; the swap_basket "
                       "concentration cap moved.")
    elif base_item == "SubnetEmissionEnabled":
        next_action = ("if you hold %s alpha, review that position."
                       % (("subnet %d" % single) if single is not None
                          else "an affected subnet's"))
    if meaning is None:
        meaning = (rec(description) if description else
                   "Atlas has no plain description of this setting yet.")
    if not description and next_action is None:
        next_action = ("add %s to %s in telegram/config.json."
                       % (base_item, mono("classes.chain-parameter-change"
                                          ".governs")))

    facts = [("Setting", "%s, %s%s" % (
        base_item, change,
        " (pool-side emission switch)"
        if base_item == "SubnetEmissionEnabled" else ""))]
    if collapsed:
        facts.append(("Subnets", fmt_int(count)))
    facts.append(("When", fmt_time(observed_at)))
    details = ["Block %s" % fmt_int(block_number),
               "Before: %s. After: %s." % (
                   _PROVENANCE_WORDS.get(prev_prov, rec(prev_prov)),
                   _PROVENANCE_WORDS.get(new_prov, rec(new_prov)))]
    if description and base_item in ("SubnetEmissionEnabled",
                                     "EmissionBarRank",
                                     "EmissionBarQuantile",
                                     "EmissionGateExponent",
                                     "BasketConcentrationCap"):
        details.append("Governs: %s" % rec(description))
    if collapsed and netuids:
        shown = netuids[:_NETUID_LIST_CAP]
        listing = ", ".join(subnet_tag(n, names) for n in shown)
        if len(netuids) > _NETUID_LIST_CAP:
            listing += " … and %d more (truncated)" % (
                len(netuids) - _NETUID_LIST_CAP)
        details.append("Subnets: %s" % listing)
    buttons = (button(config, "Subnet %d on taostats" % single,
                      "taostats_subnet", netuid=single)
               if single is not None else [])
    msg = Message(severity=severity_for("chain-parameter-change",
                                        item=base_item),
                  headline=headline, meaning=meaning, facts=facts,
                  details=details, next_action=next_action, buttons=buttons)
    return (render_plain(msg, max_chars, glosses),
            render_html(msg, max_chars, glosses), next_action, buttons)
def chain_parameter_change_events(source_db: str, watermark: Optional[str],
                                  ctx: Optional[Dict[str, Any]] = None
                                  ) -> Tuple[List[Dict[str, Any]],
                                             Optional[str]]:
    """Root-settable chain parameters that changed value, recorded by
    livedata. Reads the transition table read-only past this class's own
    watermark, independent of every other class.

    Netuid-keyed items sharing one (item, reference block) collapse into
    a single page. Each underlying row still has its own event id so the
    delivery ledger records every fact.
    """
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
            "FROM chain_param_events WHERE id > ? ORDER BY id ASC LIMIT ?",
            (last_id, _PARAM_FETCH_LIMIT)).fetchall()
    finally:
        conn.close()

    ctx = ctx or {}
    config = ctx.get("config") or {}
    spec = ctx.get("spec") or {}
    max_chars = int(config.get("message_max_chars", 3500))
    _lexicon, glosses = voice_maps(config)
    governs = dict(spec.get("governs") or {})
    names = subnet_names(source_db)

    grouped: Dict[Tuple[Any, ...], List[Any]] = {}
    order: List[Tuple[Any, ...]] = []
    high = last_id
    for row in rows:
        row_id, item, prev_value, new_value, prev_prov, new_prov, \
            observed_at, block_number = row
        high = max(high, int(row_id))
        base_item, netuid = parse_netuid_item(item)
        if netuid is None:
            key: Tuple[Any, ...] = ("global", int(row_id))
        else:
            key = ("netuid", base_item, block_number)
        if key not in grouped:
            order.append(key)
            grouped[key] = []
        grouped[key].append(row)

    events: List[Dict[str, Any]] = []
    for key in order:
        group = grouped[key]
        first = group[0]
        row_id, item, prev_value, new_value, prev_prov, new_prov, \
            observed_at, block_number = first
        member_ids = [_param_event_id(int(r[0])) for r in group]
        netuids: Optional[List[int]] = None
        if key[0] == "netuid":
            parsed = [parse_netuid_item(r[1]) for r in group]
            netuids = sorted(n for _base, n in parsed if n is not None)
            # Shared direction: all rows in the group share one block and
            # one item; mixed values are stated as-is from the first row
            # plus a count of each.
            values = {(r[2], r[3]) for r in group}
            if len(values) == 1:
                prev_value, new_value = next(iter(values))
            else:
                on_count = sum(1 for r in group if r[3] == "true")
                off_count = len(group) - on_count
                prev_value, new_value = (
                    "mixed",
                    "%d on, %d off" % (on_count, off_count))
            item = key[1]
        plain, html, _next, buttons = _render_param_event(
            item, prev_value, new_value, prev_prov, new_prov,
            observed_at, block_number, governs, max_chars, glosses,
            netuids=netuids, names=names, config=config)
        event: Dict[str, Any] = {
            "event_id": member_ids[0],
            "event_class": "chain-parameter-change",
            "created_at": _utc_now(), "text": plain, "html": html,
            "buttons": buttons}
        if len(member_ids) > 1:
            event["member_ids"] = member_ids
        events.append(event)
    return events, (str(high) if high else watermark)


def subnet_registry_events(source_db: str, watermark: Optional[str],
                           ctx: Optional[Dict[str, Any]] = None
                           ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """Netuid set and chain-name changes between consecutive panel
    snapshots (change: pulse-briefing). The first snapshot seeds the set
    silently; each later snapshot pass diffs against the one before it."""
    conn = open_source_ro(source_db)
    if conn is None:
        return [], watermark
    try:
        present = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND "
            "name = 'panel_snapshot'").fetchone()
        if present is None:
            return [], watermark  # snapshot not deployed yet
        blocks = [r[0] for r in conn.execute(
            "SELECT DISTINCT block_number FROM panel_snapshot "
            "WHERE block_number IS NOT NULL ORDER BY block_number")]
        if not blocks:
            return [], watermark
        if watermark is None:
            return [], str(blocks[-1])  # first snapshot seeds silently
        last_seen = int(watermark)

        def snap(block):
            return {r[0]: r[1] for r in conn.execute(
                "SELECT netuid, name FROM panel_snapshot "
                "WHERE block_number = ?", (block,))}

        pending = [b for b in blocks if b > last_seen]
        events: List[Dict[str, Any]] = []
        config = (ctx or {}).get("config") or {}
        max_chars = int(config.get("message_max_chars", 3500))
        _lexicon, glosses = voice_maps(config)
        prev_block = max((b for b in blocks if b <= last_seen),
                         default=None)
        for block in pending[:10]:
            if prev_block is None:
                prev_block = block
                continue
            prev, cur = snap(prev_block), snap(block)
            changes = []
            for netuid in sorted(set(cur) - set(prev)):
                changes.append((netuid, "registered", None,
                                cur.get(netuid)))
            for netuid in sorted(set(prev) - set(cur)):
                changes.append((netuid, "deregistered", prev.get(netuid),
                                None))
            for netuid in sorted(set(prev) & set(cur)):
                if (prev.get(netuid) or "") != (cur.get(netuid) or ""):
                    changes.append((netuid, "renamed", prev.get(netuid),
                                    cur.get(netuid)))
            for netuid, kind, old_name, new_name in changes:
                if kind == "renamed":
                    headline = 'Subnet %d renamed: "%s" → "%s"' % (
                        netuid, rec(old_name or "n/a"),
                        rec(new_name or "n/a"))
                elif kind == "registered":
                    headline = "Subnet %d registered%s" % (
                        netuid, (': "%s"' % rec(new_name)) if new_name
                        else "")
                else:
                    headline = "Subnet %d deregistered%s" % (
                        netuid, (' (was "%s")' % rec(old_name)) if old_name
                        else "")
                msg = Message(severity=severity_for("subnet-registry"),
                              headline=headline,
                              details=["Blocks %s → %s" % (
                                  fmt_int(prev_block), fmt_int(block)),
                                  "Source: panel snapshot"])
                events.append(message_event(
                    msg, "subnet-registry:%s:%s:%s" % (block, netuid, kind),
                    "subnet-registry", _utc_now(), max_chars, glosses))
            prev_block = block
        new_wm = str(pending[:10][-1]) if pending else watermark
        return events, new_wm
    finally:
        conn.close()


_FAIL_CLOSED_COMPONENTS = (
    # (component label, table with good observations, provider filter)
    ("gate poll", "gate_state", "finney-rpc"),
    ("chain-parameter watch", "chain_params", "finney-rpc"),
)
# component -> (what Atlas cannot read, which alerts pause)
_FAIL_CLOSED_WORDS = {
    "gate poll": ("the emission bar", "Bar-crossing"),
    "chain-parameter watch": ("chain settings", "Chain setting"),
}


def fail_closed_events(source_db: str, watermark: Optional[str],
                       ctx: Optional[Dict[str, Any]] = None
                       ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """One page per outage when a component has recorded only failures
    for longer than the configured window (change: pulse-briefing). The
    outage is keyed by its first failure, so a persisting outage never
    pages twice; recovery re-arms the key."""
    conn = open_source_ro(source_db)
    if conn is None:
        return [], watermark
    ctx = ctx or {}
    config = ctx.get("config") or {}
    spec = ctx.get("spec") or {}
    store: Optional[sqlite3.Connection] = ctx.get("connection")
    window_hours = float(spec.get("window_hours", 6))
    cutoff = (datetime.datetime.now(datetime.timezone.utc)
              - datetime.timedelta(hours=window_hours)).isoformat()
    max_chars = int(config.get("message_max_chars", 3500))
    _lexicon, glosses = voice_maps(config)
    events: List[Dict[str, Any]] = []
    try:
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'")}
        if "integration_health" not in tables:
            return [], watermark
        for component, table, provider in _FAIL_CLOSED_COMPONENTS:
            if table not in tables:
                continue
            last_good = conn.execute(
                "SELECT MAX(observed_at) FROM %s" % table).fetchone()[0]
            if last_good is not None and last_good > cutoff:
                continue  # observed inside the window: healthy
            first_fail = conn.execute(
                "SELECT MIN(timestamp) FROM integration_health "
                "WHERE provider = ? AND timestamp > COALESCE(?, '')",
                (provider, last_good)).fetchone()[0]
            if first_fail is None or first_fail > cutoff:
                continue  # no failure record, or not yet a whole window
            event_id = "fail-closed:%s:%s" % (table, first_fail)
            if store is not None and store.execute(
                    "SELECT 1 FROM events WHERE event_id = ?",
                    (event_id,)).fetchone():
                continue  # this outage already paged once
            what, paused = _FAIL_CLOSED_WORDS.get(
                component, (component, "Related"))
            msg = Message(
                severity=severity_for("fail-closed"),
                headline="Atlas can't read %s (%g+ hours)" % (
                    what, window_hours),
                meaning="The %s has recorded only failures since %s. %s "
                        "alerts are paused until it recovers." % (
                            component, fmt_time(first_fail), paused),
                facts=[("Last good reading",
                        fmt_time(last_good, "r") if last_good
                        else "none recorded")],
                details=["First failure %s" % rec(first_fail),
                         "Last good observation %s" % rec(
                             last_good or "none recorded"),
                         "Source: livedata integration health"],
                next_action="check the chain RPC from the Pi: %s"
                            % mono("python3 livedata/atlas_live.py "
                                   "poll-gate"))
            events.append(message_event(msg, event_id, "fail-closed",
                                        _utc_now(), max_chars, glosses))
    finally:
        conn.close()
    return events, watermark


_ADAPTERS: Dict[str, Callable[..., Tuple[List[Dict[str, Any]],
                                         Optional[str]]]] = {
    "chain-runtime-upgrade": chain_runtime_upgrade_events,
    "chain-parameter-change": chain_parameter_change_events,
    "subnet-registry": subnet_registry_events,
    "fail-closed": fail_closed_events,
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
                  poster: Optional[Callable[..., Tuple[int, str]]] = None,
                  tier: Optional[str] = None) -> str:
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

    result, fallback_note = send_with_fallback(
        config, token, chat_id, text, html, event.get("buttons") or [],
        poster=poster)

    if result["delivered"]:
        ledger_record(connection, event_id, event_class, created_at,
                      _utc_now(), STATUS_DELIVERED, result["attempts"],
                      fallback_note, tier=tier)
        return STATUS_DELIVERED
    ledger_record(connection, event_id, event_class, created_at, _utc_now(),
                  STATUS_FAILED, result["attempts"], result["detail"],
                  tier=tier)
    return STATUS_FAILED


def send_with_fallback(config: Dict[str, Any], token: str, chat_id: str,
                       text: str, html: Optional[str],
                       buttons: List[Tuple[str, str]],
                       poster: Optional[Callable[..., Tuple[int, str]]] = None
                       ) -> Tuple[Dict[str, Any], Optional[str]]:
    """Send HTML with its buttons. Rejected formatting must never
    suppress a message: an HTTP 400 resends once as the untagged
    structured text (never the HTML source) with the same buttons, and a
    400 on that resend sends once more without buttons. Returns the
    final result and a note naming the fallback taken, if any."""
    buttons = list(buttons or [])
    if not html:
        result = send_message(config, token, chat_id, text, poster=poster,
                              buttons=buttons)
        attempts = result["attempts"]
        note = None
    else:
        result = send_message(config, token, chat_id, html, poster=poster,
                              parse_mode="HTML", buttons=buttons)
        attempts = result["attempts"]
        note = None
        if not result["delivered"] and result.get("status") == 400:
            result = send_message(config, token, chat_id, text,
                                  poster=poster, buttons=buttons)
            attempts += result["attempts"]
            note = "html-400-fallback: delivered as plain text"
    if (not result["delivered"] and result.get("status") == 400
            and buttons):
        result = send_message(config, token, chat_id, text, poster=poster)
        attempts += result["attempts"]
        note = ((note + "; ") if note else "") + "buttons dropped after 400"
    result["attempts"] = attempts
    return result, (note if result["delivered"] else None)


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
        if spec.get("delivery_only"):
            # A tier-registry entry for a class another adapter emits (the
            # fleet-signal queue emits econ-code, narrative-cluster and
            # watchlist). It carries a tier and nothing else.
            continue
        adapter = _ADAPTERS.get(event_class)
        if adapter is None:
            summary["classes"][event_class] = {"error": "no adapter"}
            continue
        source_db = resolve(spec["source_db"])
        wm = watermark_get(connection, event_class)
        counts: Dict[str, Any] = {"delivered": 0, "suppressed": 0, "failed": 0,
                  "scrub-refused": 0, "error": 0}
        ctx = {"config": config, "spec": spec, "connection": connection}
        try:
            events, new_wm = adapter(source_db, wm, ctx)
        except Exception as exc:  # adapter is isolated from the scan
            summary["classes"][event_class] = {
                "error": redact(str(exc))[:200]}
            continue
        # Delivery tier (changes: pulse-briefing, rotation-signal-gate).
        # Only instant classes page. A briefing-tier class records its
        # events as briefed and surfaces through the pulse briefing; a
        # shadow-tier class records and is carried nowhere, so a new class
        # accrues measurement before it can ever page. A class with no
        # registered tier delivers nothing at all: drift between the class
        # list and the registry fails closed rather than paging by default.
        # Flipping the tier value is the whole rollback for one class.
        for event in events:
            # Tier is resolved PER EVENT, not per adapter: one adapter can
            # emit several registered classes (the fleet-signal queue emits
            # econ-code, narrative-cluster and watchlist), and each has to
            # be demotable on its own evidence.
            tier = event_tier(config, spec, event["event_class"])
            non_paging_status = NON_PAGING_STATUS.get(
                tier, STATUS_UNREGISTERED)
            if non_paging_status is not None:
                ledger_record(connection, event["event_id"],
                              event["event_class"], event["created_at"],
                              None, non_paging_status, 0, None,
                              tier=tier or STATUS_UNREGISTERED)
                ledger_collapsed_members(
                    connection, event, non_paging_status, None, 0, None,
                    tier=tier or STATUS_UNREGISTERED)
                counts[non_paging_status] = counts.get(
                    non_paging_status, 0) + 1
                continue
            try:
                status = deliver_event(connection, config, token, chat_id,
                                       event, poster=poster, tier=tier)
                ledger_collapsed_members(
                    connection, event, status, _utc_now(), 0, None,
                    tier=tier)
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
                ledger_collapsed_members(
                    connection, event, STATUS_FAILED, _utc_now(), 0,
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
        # The pulse briefing rides the same scan (change: pulse-briefing):
        # once per day at the configured hour, weekly on its weekday, gated
        # by durable edition watermarks. Isolated like everything else.
        try:
            import atlas_briefing
            summary["briefing"] = atlas_briefing.run_briefing(
                config, token, chat_id, connection)
        except Exception as exc:  # never let the briefing break the scan
            summary["briefing"] = {"status": "error",
                                   "error": redact(str(exc))[:200]}
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
        msg = Message(severity=severity_for("test"),
                      headline="Telegram delivery test",
                      meaning="Atlas can reach this chat. Class: %s."
                              % event_class)
        event = message_event(msg, "test:%s:%s" % (event_class, run_id()),
                              event_class, _utc_now(),
                              int(config.get("message_max_chars", 3500)),
                              None)
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
