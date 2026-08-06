#!/usr/bin/env python3
"""Atlas Phase 4 live data — shared plumbing (store, quota, HTTP, secrets).

This module carries the fail-closed machinery every live-data component
uses (ATLAS-API-006/007/008, ATLAS-LIVE-006/007/008/009, Q29):

- `.env` loader + secret redaction (key never appears in any output);
- SQLite store: call ledger (quota windows), audit records (the
  Q29/LIVE-009 field set), integration_health events, size-capped
  labelled last-response cache;
- QuotaLedger: persisted per-minute sliding window + day/month window
  with interactive reserve; the TaoStats self-cap sits BELOW the
  provider limit by design (operator refinement 2026-07-12 — never
  fill 5/min);
- http_get: fixed-URL GETs with bounded, endpoint-specific, observable
  retries (never on 429), redacted errors, timing capture.

Adapters/validators (tasks 3.x/4.4) and the MCP server (task 5.4) build
on this after the discovery-report operator gates; nothing here invents
freshness thresholds or endpoint contracts (ATLAS-LIVE-002).

Envelope: unprivileged; writes only `var/livedata/` (gitignored, 0600).
"""

from __future__ import annotations

import datetime
import json
import os
import random
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import secrets as secretsmod
from typing import Any, Dict, List, Optional, Tuple

_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_MODULE_DIR)

LIVEDATA_VERSION = "0.1.0"
CONFIG_FILE = os.path.join(_MODULE_DIR, "config.json")
ENV_FILE = os.path.join(_REPO_ROOT, ".env")
USER_AGENT = "atlas-livedata/" + LIVEDATA_VERSION

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS calls (
    id INTEGER PRIMARY KEY,
    provider TEXT NOT NULL,
    ts REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS calls_provider_ts ON calls (provider, ts);
CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY,
    timestamp TEXT NOT NULL,
    provider TEXT NOT NULL,
    operation TEXT NOT NULL,
    params TEXT NOT NULL,
    request_started TEXT NOT NULL,
    request_finished TEXT NOT NULL,
    status_code INTEGER,
    schema_version TEXT,
    validation_result TEXT NOT NULL,
    response_sha256 TEXT,
    error_category TEXT
);
CREATE TABLE IF NOT EXISTS integration_health (
    id INTEGER PRIMARY KEY,
    timestamp TEXT NOT NULL,
    provider TEXT NOT NULL,
    operation TEXT NOT NULL,
    category TEXT NOT NULL,
    detail TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS response_cache (
    id INTEGER PRIMARY KEY,
    provider TEXT NOT NULL,
    operation TEXT NOT NULL,
    params_key TEXT NOT NULL,
    stored_at TEXT NOT NULL,
    label TEXT NOT NULL DEFAULT 'historical-snapshot',
    payload TEXT NOT NULL,
    UNIQUE (provider, operation, params_key)
);
CREATE TABLE IF NOT EXISTS provider_limits (
    provider TEXT PRIMARY KEY,
    reported_at TEXT NOT NULL,
    headers_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS spec_upgrades (
    id INTEGER PRIMARY KEY,
    observed_at TEXT NOT NULL,
    prev_spec INTEGER NOT NULL,
    new_spec INTEGER NOT NULL,
    block_reference INTEGER
);
CREATE TABLE IF NOT EXISTS gate_state (
    id INTEGER PRIMARY KEY,
    observed_at TEXT NOT NULL,
    block_hash TEXT,
    block_number INTEGER,
    gate_active INTEGER NOT NULL,
    theta REAL,
    q REAL NOT NULL,
    q_provenance TEXT NOT NULL,
    h REAL NOT NULL,
    h_provenance TEXT NOT NULL,
    endpoint TEXT NOT NULL,
    rank INTEGER,
    rank_provenance TEXT,
    bar_mode TEXT,
    above_count INTEGER
);
CREATE TABLE IF NOT EXISTS gate_sides (
    netuid INTEGER PRIMARY KEY,
    side TEXT NOT NULL,
    pending_side TEXT,
    pending_count INTEGER NOT NULL DEFAULT 0,
    miss_count INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS gate_events (
    id INTEGER PRIMARY KEY,
    observed_at TEXT NOT NULL,
    netuid INTEGER NOT NULL,
    direction TEXT NOT NULL,
    share REAL NOT NULL,
    theta REAL NOT NULL,
    prev_side TEXT NOT NULL,
    emission_enabled INTEGER,
    block_number INTEGER,
    prev_theta REAL
);
CREATE TABLE IF NOT EXISTS chain_params (
    id INTEGER PRIMARY KEY,
    item TEXT NOT NULL,
    value TEXT NOT NULL,
    provenance TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    block_number INTEGER,
    block_hash TEXT
);
CREATE INDEX IF NOT EXISTS chain_params_item_id
    ON chain_params (item, id DESC);
CREATE TABLE IF NOT EXISTS chain_param_events (
    id INTEGER PRIMARY KEY,
    item TEXT NOT NULL,
    prev_value TEXT NOT NULL,
    new_value TEXT NOT NULL,
    prev_provenance TEXT NOT NULL,
    new_provenance TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    block_number INTEGER
);
"""

META_LAST_LIVE_SPEC = "last_live_spec"
META_LAST_LIVE_SPEC_BLOCK = "last_live_spec_block"
META_LAST_LIVE_SPEC_OBSERVED = "last_live_spec_observed_at"
META_GATE_ACTIVE = "gate_active"


class FatalLiveError(Exception):
    """Input-contract failure; the operation aborts fail-closed."""


# ---------------------------------------------------------------------------
# Shared-helper access (lazy, same pattern as repotrack)
# ---------------------------------------------------------------------------

_AHV: Any = None


def _ahv() -> Any:
    global _AHV
    if _AHV is None:
        sys.path.insert(0, os.path.join(_REPO_ROOT, "hermes"))
        import atlas_hermes_verify  # noqa: E402
        _AHV = atlas_hermes_verify
    return _AHV


def write_private(path: str, content: str) -> None:
    _ahv()._write_private(path, content)


def _utc_now() -> str:
    return datetime.datetime.now(tz=datetime.timezone.utc).isoformat()


def run_id() -> str:
    return (time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
            + "-" + secretsmod.token_hex(4))


# ---------------------------------------------------------------------------
# Secrets (ATLAS-API-008): .env loader + redaction
# ---------------------------------------------------------------------------

_SECRET_VALUES: List[str] = []


def load_env(path: str = ENV_FILE) -> Dict[str, str]:
    """Parse KEY=VALUE lines. Values are registered for redaction."""
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
    for value in values.values():
        register_secret(value)
    return values


def register_secret(value: str) -> None:
    if value and len(value) >= 8 and value not in _SECRET_VALUES:
        _SECRET_VALUES.append(value)


def redact(text: str) -> str:
    """Strip registered secret values, then apply the pinned inventory
    redaction patterns. Every error/report/audit path goes through here."""
    for value in _SECRET_VALUES:
        if value in text:
            text = text.replace(value, "[REDACTED-KEY]")
    return _ahv().inv.redact(text)


def redact_tree(value: Any) -> Any:
    """Redact every string INSIDE a structure, then serialize — never
    redact serialized JSON (a pattern spanning a quote corrupts it)."""
    if isinstance(value, dict):
        return {key: redact_tree(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_tree(item) for item in value]
    if isinstance(value, str):
        return redact(value)
    return value


def provider_key(config: Dict[str, Any], provider: str,
                 env: Optional[Dict[str, str]] = None) -> Optional[str]:
    spec = config["providers"][provider]
    if spec.get("auth") != "header":
        return None
    env = env if env is not None else load_env()
    key = (env.get(spec["key_env"])
           or os.environ.get(spec["key_env"], "")).strip()
    if not key:
        raise FatalLiveError(
            "provider %s needs %s in %s (0600) — see env.example"
            % (provider, spec["key_env"], ENV_FILE))
    register_secret(key)
    return key


# ---------------------------------------------------------------------------
# Config / store
# ---------------------------------------------------------------------------


def load_config(path: str = CONFIG_FILE) -> Dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            config = json.load(handle)
    except (OSError, ValueError) as exc:
        raise FatalLiveError("cannot load config %s: %s" % (path, exc))
    for key in ("providers", "db", "output_dir", "retry",
                "request_timeout_seconds"):
        if key not in config:
            raise FatalLiveError("config missing %r" % key)
    return config


def resolve(path: str, repo_root: str = _REPO_ROOT) -> str:
    return path if os.path.isabs(path) else os.path.join(repo_root, path)


def open_store(db_path: str) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    connection = sqlite3.connect(db_path, timeout=10)
    connection.executescript(SCHEMA_SQL)
    # Additive migration (change: network-drift-443). Stores written before
    # rank-pinned bar selection lack these columns; existing rows stay NULL,
    # which readers MUST treat as "unrecorded" rather than back-filling —
    # theta really was q-mass-derived until the spec-441 bar reset.
    for table, additions in (
            ("gate_state", (("rank", "INTEGER"),
                            ("rank_provenance", "TEXT"),
                            ("bar_mode", "TEXT"),
                            ("above_count", "INTEGER"))),
            ("gate_events", (("prev_theta", "REAL"),))):
        columns = {row[1] for row in connection.execute(
            "PRAGMA table_info(%s)" % table)}
        for column, coltype in additions:
            if column not in columns:
                connection.execute("ALTER TABLE %s ADD COLUMN %s %s"
                                   % (table, column, coltype))
    connection.commit()
    return connection


def health_event(connection: sqlite3.Connection, provider: str,
                 operation: str, category: str, detail: str) -> None:
    connection.execute(
        "INSERT INTO integration_health (timestamp, provider, operation, "
        "category, detail) VALUES (?, ?, ?, ?, ?)",
        (_utc_now(), provider, operation, category, redact(detail)[:500]))
    connection.commit()


def audit_call(connection: sqlite3.Connection, provider: str,
               operation: str, params: Dict[str, Any], started: str,
               finished: str, status_code: Optional[int],
               schema_version: Optional[str], validation_result: str,
               response_sha256: Optional[str],
               error_category: Optional[str]) -> None:
    """One Q29/ATLAS-LIVE-009 audit record per provider call."""
    connection.execute(
        "INSERT INTO audit (timestamp, provider, operation, params, "
        "request_started, request_finished, status_code, schema_version, "
        "validation_result, response_sha256, error_category) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (_utc_now(), provider, operation,
         redact(json.dumps(params, sort_keys=True))[:400],
         started, finished, status_code, schema_version,
         validation_result, response_sha256, error_category))
    connection.commit()


def cache_put(connection: sqlite3.Connection, config: Dict[str, Any],
              provider: str, operation: str, params_key: str,
              payload: Dict[str, Any]) -> None:
    """Size-capped labelled last-response cache (Q29): newest per
    (provider, operation, params); oldest rows pruned beyond the cap."""
    connection.execute(
        "INSERT INTO response_cache (provider, operation, params_key, "
        "stored_at, payload) VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT(provider, operation, params_key) DO UPDATE SET "
        "stored_at = excluded.stored_at, payload = excluded.payload",
        (provider, operation, params_key, _utc_now(),
         redact(json.dumps(payload))))
    connection.execute(
        "DELETE FROM response_cache WHERE id NOT IN (SELECT id FROM "
        "response_cache ORDER BY stored_at DESC LIMIT ?)",
        (int(config.get("cache_max_rows", 200)),))
    connection.commit()


def meta_get(connection: sqlite3.Connection, key: str) -> Optional[str]:
    row = connection.execute("SELECT value FROM meta WHERE key = ?",
                             (key,)).fetchone()
    return row[0] if row else None


def meta_set(connection: sqlite3.Connection, key: str, value: str) -> None:
    connection.execute(
        "INSERT INTO meta (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value))


def record_spec_observation(connection: sqlite3.Connection,
                            values: Dict[str, Any]) -> Optional[int]:
    """Persist the last-seen live runtime `spec_version` and write one
    durable upgrade event when a *validated* chain-head response reports a
    changed value. Called only from the validated-response path — never
    from stale, cached, or failed data. Idempotent across restarts: the
    last-seen value lives in `meta`, so an already-recorded spec_version
    never re-emits. Returns the new spec_upgrades row id, or None."""
    new_spec = values.get("spec_version")
    if not isinstance(new_spec, int):
        return None
    block = values.get("block_number")
    prev_raw = meta_get(connection, META_LAST_LIVE_SPEC)
    upgrade_id: Optional[int] = None
    if prev_raw is not None and int(prev_raw) != new_spec:
        cursor = connection.execute(
            "INSERT INTO spec_upgrades (observed_at, prev_spec, new_spec, "
            "block_reference) VALUES (?, ?, ?, ?)",
            (_utc_now(), int(prev_raw), new_spec, block))
        upgrade_id = cursor.lastrowid
    meta_set(connection, META_LAST_LIVE_SPEC, str(new_spec))
    if block is not None:
        meta_set(connection, META_LAST_LIVE_SPEC_BLOCK, str(block))
    meta_set(connection, META_LAST_LIVE_SPEC_OBSERVED, _utc_now())
    connection.commit()
    return upgrade_id


def cache_get(connection: sqlite3.Connection, provider: str,
              operation: str, params_key: str
              ) -> Optional[Dict[str, Any]]:
    row = connection.execute(
        "SELECT stored_at, label, payload FROM response_cache WHERE "
        "provider = ? AND operation = ? AND params_key = ?",
        (provider, operation, params_key)).fetchone()
    if row is None:
        return None
    return {"stored_at": row[0], "label": row[1],
            "payload": json.loads(row[2])}


# ---------------------------------------------------------------------------
# Quota ledger (ATLAS-LIVE-006/007) — persisted, headroom by design
# ---------------------------------------------------------------------------


def _window_start(kind: str,
                  now: datetime.datetime) -> datetime.datetime:
    if kind == "day":
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    if kind == "month":
        return now.replace(day=1, hour=0, minute=0, second=0,
                           microsecond=0)
    raise FatalLiveError("unknown quota window kind %r" % kind)


class QuotaLedger:
    """Persisted call ledger. `acquire` must succeed before any provider
    request; every acquisition is recorded whether or not the HTTP call
    later succeeds (a call is a call)."""

    def __init__(self, connection: sqlite3.Connection,
                 config: Dict[str, Any]):
        self.connection = connection
        self.config = config

    def _quota(self, provider: str) -> Dict[str, Any]:
        return self.config["providers"][provider].get("quota", {})

    def usage(self, provider: str,
              now: Optional[float] = None) -> Dict[str, Any]:
        now = now if now is not None else time.time()
        quota = self._quota(provider)
        minute_count = self.connection.execute(
            "SELECT count(*) FROM calls WHERE provider = ? AND ts > ?",
            (provider, now - 60)).fetchone()[0]
        last_ts = self.connection.execute(
            "SELECT max(ts) FROM calls WHERE provider = ?",
            (provider,)).fetchone()[0]
        usage: Dict[str, Any] = {
            "provider": provider,
            "minute_count": minute_count,
            "per_minute_cap": quota.get("per_minute_cap"),
            "last_call_ts": last_ts,
            "estimate_source": "local-ledger",
        }
        if quota.get("window_limit"):
            now_dt = datetime.datetime.fromtimestamp(
                now, tz=datetime.timezone.utc)
            start = _window_start(quota["window_kind"], now_dt).timestamp()
            window_count = self.connection.execute(
                "SELECT count(*) FROM calls WHERE provider = ? AND ts >= ?",
                (provider, start)).fetchone()[0]
            usage.update({
                "window_kind": quota["window_kind"],
                "window_limit": quota["window_limit"],
                "window_count": window_count,
                "window_remaining": quota["window_limit"] - window_count,
                "interactive_reserve_fraction":
                    quota.get("interactive_reserve_fraction"),
            })
        reported = self.connection.execute(
            "SELECT reported_at, headers_json FROM provider_limits WHERE "
            "provider = ?", (provider,)).fetchone()
        if reported:
            usage["provider_reported"] = {
                "reported_at": reported[0],
                "headers": json.loads(reported[1]),
            }
        return usage

    def acquire(self, provider: str, interactive: bool = True,
                now: Optional[float] = None) -> Optional[Dict[str, Any]]:
        """Return None when the call may proceed (and record it), or a
        structured refusal dict. The per-minute self-cap is strictly
        below any provider limit — headroom by design."""
        now = now if now is not None else time.time()
        quota = self._quota(provider)
        usage = self.usage(provider, now)
        spacing = quota.get("min_spacing_seconds")
        if (spacing and usage["last_call_ts"] is not None
                and now - usage["last_call_ts"] < spacing):
            return {"category": "paced",
                    "message": "provider %s pacing: %.1fs between calls"
                               % (provider, spacing),
                    "retry_safe": True}
        cap = quota.get("per_minute_cap")
        if cap and usage["minute_count"] >= cap:
            return {"category": "paced",
                    "message": "provider %s self-cap reached (%d/min, "
                               "below the provider limit by design)"
                               % (provider, cap),
                    "retry_safe": True}
        if quota.get("window_limit"):
            limit = usage["window_limit"]
            if not interactive:
                fraction = quota.get("interactive_reserve_fraction")
                if fraction:
                    limit = int(limit * fraction)
            if usage["window_count"] >= limit:
                return {"category": "quota-exhausted",
                        "message": "provider %s %s budget spent "
                                   "(%d/%d used%s)"
                                   % (provider, usage["window_kind"],
                                      usage["window_count"],
                                      usage["window_limit"],
                                      "" if interactive else
                                      "; interactive reserve active"),
                        "retry_safe": False}
        self.connection.execute(
            "INSERT INTO calls (provider, ts) VALUES (?, ?)",
            (provider, now))
        # prune entries older than any window we still need
        self.connection.execute(
            "DELETE FROM calls WHERE provider = ? AND ts < ?",
            (provider, now - 40 * 24 * 3600))
        self.connection.commit()
        return None

    def record_reported_limits(self, provider: str,
                               headers: Dict[str, str]) -> None:
        interesting = {key: value for key, value in headers.items()
                       if "limit" in key.lower() or "quota" in key.lower()
                       or "remaining" in key.lower()
                       or "retry-after" in key.lower()}
        if not interesting:
            return
        self.connection.execute(
            "INSERT INTO provider_limits (provider, reported_at, "
            "headers_json) VALUES (?, ?, ?) ON CONFLICT(provider) DO "
            "UPDATE SET reported_at = excluded.reported_at, headers_json "
            "= excluded.headers_json",
            (provider, _utc_now(), json.dumps(interesting)))
        self.connection.commit()


# ---------------------------------------------------------------------------
# HTTP (bounded observable retries — ATLAS-LIVE-008)
# ---------------------------------------------------------------------------


def http_get(config: Dict[str, Any], provider: str, path: str,
             params: Optional[Dict[str, Any]] = None,
             headers: Optional[Dict[str, str]] = None,
             attempts: Optional[int] = None,
             base_url: Optional[str] = None,
             timeout: Optional[float] = None) -> Dict[str, Any]:
    """One logical GET with bounded retries. Returns a result dict:
    {ok, status, headers, body(bytes), elapsed_s, attempts, error?}.
    Never retries on 429 or 4xx; never raises on HTTP failure (fail
    closed at the caller); redacts every error string."""
    spec = config["providers"][provider]
    url = (base_url or spec["base_url"]).rstrip("/") + path
    if params:
        url += "?" + urllib.parse.urlencode(
            {k: v for k, v in params.items() if v is not None})
    retry = config["retry"]
    max_attempts = attempts or retry["default_attempts"]
    request_headers = {"User-Agent": USER_AGENT,
                       "Accept": "application/json"}
    request_headers.update(headers or {})
    timeout = timeout or config["request_timeout_seconds"]

    attempt_log: List[Dict[str, Any]] = []
    for attempt in range(1, max_attempts + 1):
        started = time.time()
        try:
            request = urllib.request.Request(url, headers=request_headers)
            with urllib.request.urlopen(request,
                                        timeout=timeout) as response:
                body = response.read()
                elapsed = time.time() - started
                return {"ok": True, "status": response.status,
                        "headers": dict(response.headers),
                        "body": body, "elapsed_s": round(elapsed, 3),
                        "attempts": attempt,
                        "attempt_log": attempt_log}
        except urllib.error.HTTPError as exc:
            elapsed = time.time() - started
            status = exc.code
            body = b""
            try:
                body = exc.read()
            except OSError:
                pass
            entry = {"attempt": attempt, "status": status,
                     "elapsed_s": round(elapsed, 3)}
            attempt_log.append(entry)
            if (status in retry["retry_on_status"]
                    and status not in retry["never_retry_on_status"]
                    and attempt < max_attempts):
                time.sleep(random.uniform(*retry["jitter_seconds"]))
                continue
            return {"ok": False, "status": status,
                    "headers": dict(exc.headers or {}), "body": body,
                    "elapsed_s": round(elapsed, 3), "attempts": attempt,
                    "attempt_log": attempt_log,
                    "error": redact("HTTP %d for %s" % (status, path))}
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            elapsed = time.time() - started
            attempt_log.append({"attempt": attempt, "status": None,
                                "elapsed_s": round(elapsed, 3)})
            if attempt < max_attempts:
                time.sleep(random.uniform(*retry["jitter_seconds"]))
                continue
            return {"ok": False, "status": None, "headers": {},
                    "body": b"", "elapsed_s": round(elapsed, 3),
                    "attempts": attempt, "attempt_log": attempt_log,
                    "error": redact("connection failure for %s: %s"
                                    % (path, exc))}
    raise AssertionError("unreachable")


# ---------------------------------------------------------------------------
# Pinned-schema validation (ATLAS-API-006/007)
# ---------------------------------------------------------------------------

SCHEMAS_DIR = os.path.join(_MODULE_DIR, "schemas")
_SCHEMA_CACHE: Dict[str, Dict[str, Any]] = {}


def load_schema(name: str) -> Dict[str, Any]:
    """`name` like 'taoswap/subnets.v1' → schemas/taoswap/subnets.v1.schema.json"""
    if name not in _SCHEMA_CACHE:
        path = os.path.join(SCHEMAS_DIR, *name.split("/")) \
            + ".schema.json"
        try:
            with open(path, "r", encoding="utf-8") as handle:
                _SCHEMA_CACHE[name] = json.load(handle)
        except (OSError, ValueError) as exc:
            raise FatalLiveError("pinned schema %s unreadable: %s"
                                 % (name, exc))
    return _SCHEMA_CACHE[name]


def _type_ok(expected: str, value: Any) -> bool:
    if expected == "null":
        return value is None
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return (isinstance(value, (int, float))
                and not isinstance(value, bool))
    if expected == "string":
        return isinstance(value, str)
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    return True  # "any"


def validate_schema(schema: Dict[str, Any], value: Any,
                    path: str = "$") -> List[str]:
    """Tiny JSON-schema subset: type (str or list), required, properties,
    items. Extra fields are tolerated by design — drift means a missing
    or mistyped REQUIRED/known field (recorded schema policy)."""
    errors: List[str] = []
    expected = schema.get("type")
    if expected is not None:
        types = expected if isinstance(expected, list) else [expected]
        if not any(_type_ok(t, value) for t in types):
            return ["%s: expected %s, got %s"
                    % (path, "/".join(types), type(value).__name__)]
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                errors.append("%s: missing required %r" % (path, key))
        for key, sub in schema.get("properties", {}).items():
            if key in value:
                errors.extend(validate_schema(sub, value[key],
                                              "%s.%s" % (path, key)))
    if isinstance(value, list) and "items" in schema:
        for index, item in enumerate(value[:200]):
            errors.extend(validate_schema(schema["items"], item,
                                          "%s[%d]" % (path, index)))
            if errors:
                break  # first bad item is enough evidence
    return errors


# ---------------------------------------------------------------------------
# Per-operation post-processing (typed values + provenance extraction)
# ---------------------------------------------------------------------------


def _epoch_iso(epoch: Any) -> Optional[str]:
    try:
        return datetime.datetime.fromtimestamp(
            float(epoch), tz=datetime.timezone.utc).isoformat()
    except (TypeError, ValueError, OSError):
        return None


def _pp_price_spot_coingecko(payload, params):
    entry = payload["bittensor"]
    return {"values": {"tao_usd": entry["usd"],
                       "kind": "spot"},
            "units": "USD per TAO (spot)",
            "upstream_timestamp": _epoch_iso(entry["last_updated_at"]),
            "block_reference": None}


def _pp_price_daily_taoswap(payload, params):
    if payload.get("currency", "").upper() != "USD":
        raise FatalLiveError("provider echoed currency %r, expected USD "
                             "(TaoSwap silently ignores bad params — "
                             "client-side check per the 2.3 gate)"
                             % payload.get("currency"))
    if not payload["results"]:
        raise FatalLiveError("price-history returned no rows")
    last = payload["results"][-1]
    return {"values": {"tao_usd": last["price"], "kind": "daily-close",
                       "close_date": last["date"]},
            "units": "USD per TAO (daily close)",
            "upstream_timestamp": last["date"] + "T00:00:00+00:00",
            "block_reference": None}


_CONVICTION_KEYS = (
    "king_is_owner", "is_contested", "takeover_eligible",
    "takeover_enforced", "gate_ceiling_pct", "total_locked_pct_supply",
    "holder_count", "owner_conviction_pct", "age_days",
    "takeover_age_ok", "owner_emission_share", "as_of_block",
    "king", "total_locked",
)

_SUBNET_SCALAR_KEYS = (
    # prices / stake / pools
    ("alpha_price_tao", "price"),
    ("moving_price_tao", "moving_price"),
    ("alpha_stake", "alpha_stake"),
    ("root_in_pool", "root_in_pool"),
    ("alpha_in_pool", "alpha_in_pool"),
    ("alpha_outstanding", "alpha_outstanding"),
    ("root_proportion", "root_proportion"),
    # emission diagnostics (TaoSwap: *_percent are 0-100)
    ("emission_percent", "emission_percent"),
    ("emission_ema_percent", "emission_ema_percent"),
    ("emission_miner_burn", "emission_miner_burn"),
    ("emission_value", "emission_value"),
    ("emission_is_enabled", "emission_is_enabled"),
    ("emission_evolution_d_1", "emission_evolution_d_1"),
    ("emission_evolution_d_30", "emission_evolution_d_30"),
    ("excess_tao_emission", "excess_tao_emission"),
    ("excess_tao_emission_percent", "excess_tao_emission_percent"),
    ("tao_in_emission", "tao_in_emission"),
    ("alpha_in_emission", "alpha_in_emission"),
    ("alpha_out_emission", "alpha_out_emission"),
    # flows / activity
    ("inflow", "inflow"),
    ("outflow", "outflow"),
    ("active_miners", "active_miners"),
    ("registration_cost", "registration_cost"),
    ("tempo", "tempo"),
    ("blocks_since_epoch", "blocks_since_epoch"),
    ("volume_24h", "volume_24h"),
    ("volume_24h_usd", "volume_24h_usd"),
    ("market_cap", "market_cap"),
    ("fdv", "fdv"),
    ("holders_count", "holders_count"),
    ("top10_share", "top10_share"),
    ("hhi_normalized", "hhi_normalized"),
    ("nakamoto_coefficient", "nakamoto_coefficient"),
    ("owner", "owner"),
)


def _pp_subnets_taoswap(payload, params):
    netuid = params.get("netuid")
    rows = payload["results"]
    if netuid is not None:
        rows = [row for row in rows if row.get("id") == netuid]
        if not rows:
            raise FatalLiveError("no subnet with id %s in the provider "
                                 "response" % netuid)
    pruned = []
    for row in rows[:130]:
        conviction = row.get("conviction") or {}
        identity = row.get("identity") or {}
        dereg = row.get("dereg") or {}
        item = {
            "netuid": row.get("id"),
            "name": row.get("name"),
            "symbol": row.get("symbol"),
        }
        for out_key, src_key in _SUBNET_SCALAR_KEYS:
            item[out_key] = row.get(src_key)
        item["identity"] = {
            "name": identity.get("name"),
            "url": identity.get("url"),
            "github": identity.get("github"),
            "description": identity.get("description"),
        } if identity else None
        item["dereg"] = {
            "is_immune": dereg.get("is_immune"),
            "risk_level": dereg.get("risk_level"),
            "prune_rank": dereg.get("prune_rank"),
            "immunity_end_block": dereg.get("immunity_end_block"),
        } if dereg else None
        item["conviction"] = (
            {key: conviction.get(key) for key in _CONVICTION_KEYS}
            if conviction else None)
        # Explicit unit note for the burn field consumers.
        item["emission_miner_burn_unit"] = "percent_0_100"
        pruned.append(item)
    block = (payload.get("dereg_context") or {}).get("current_block")
    return {"values": {"subnets": pruned, "count": len(pruned)},
            "units": ("alpha prices in TAO; emission_percent / "
                      "emission_miner_burn / excess_tao_emission_percent "
                      "are 0-100 (NOT 0-1 fractions)"),
            "upstream_timestamp": None,
            "block_reference": block}


def _pp_metagraph_taoswap(payload, params):
    limit = params.get("limit")
    try:
        limit = int(limit) if limit is not None else 25
    except (TypeError, ValueError):
        limit = 25
    limit = max(1, min(limit, 64))
    subnet = payload.get("subnet") or {}
    neurons = list(payload.get("neurons") or [])

    def _emission(neuron):
        try:
            return float(neuron.get("emission") or 0)
        except (TypeError, ValueError):
            return 0.0

    neurons.sort(key=_emission, reverse=True)
    pruned = []
    for neuron in neurons[:limit]:
        pruned.append({
            "uid": neuron.get("uid"),
            "hotkey": neuron.get("hotkey"),
            "coldkey": neuron.get("coldkey"),
            "is_validator": neuron.get("is_validator"),
            "is_owner": neuron.get("is_owner"),
            "stake": neuron.get("stake"),
            "incentive": neuron.get("incentive"),
            "emission": neuron.get("emission"),
            "emission_tao": neuron.get("emission_tao"),
            "emission_usd": neuron.get("emission_usd"),
            "dividends": neuron.get("dividends"),
            "vtrust": neuron.get("vtrust"),
            "consensus": neuron.get("consensus"),
            "daily_rewards": neuron.get("daily_rewards"),
            "daily_rewards_alpha": neuron.get("daily_rewards_alpha"),
            "daily_rewards_usd": neuron.get("daily_rewards_usd"),
            "delegate_take": neuron.get("delegate_take"),
            "status": neuron.get("status"),
            "type": neuron.get("type"),
        })
    return {
        "values": {
            "netuid": subnet.get("id"),
            "name": subnet.get("name"),
            "symbol": subnet.get("symbol"),
            "subnet": {
                "price": subnet.get("price"),
                "emission_value": subnet.get("emission_value"),
                "registration_cost": subnet.get("registration_cost"),
                "blocks_since_epoch": subnet.get("blocks_since_epoch"),
                "tempo": subnet.get("tempo"),
                "owner_ss58": (subnet.get("identity") or {}).get(
                    "ss58_address"),
            },
            "neurons": pruned,
            "count": len(pruned),
            "total_neurons": payload.get("count") or len(
                payload.get("neurons") or []),
            "sorted_by": "emission_desc",
        },
        "units": "stake/emission as TaoSwap reports; incentive/dividends "
                 "fractional; emission_tao in TAO",
        "upstream_timestamp": None,
        "block_reference": None,
    }


def _pp_blocks_taoswap(payload, params):
    results = payload.get("results") or {}
    if not results:
        raise FatalLiveError("blocks endpoint returned no rows")
    # results is a map keyed by block id (string or int)
    blocks = []
    for key, row in results.items():
        if not isinstance(row, dict):
            continue
        blocks.append(row)
    if not blocks:
        raise FatalLiveError("blocks endpoint returned empty results map")
    blocks.sort(key=lambda row: int(row.get("id") or 0), reverse=True)
    head = blocks[0]
    return {
        "values": {
            "block_number": head.get("id"),
            "block_hash": (head.get("hash") or "")[:18],
            "timestamp": head.get("timestamp"),
            "is_final": head.get("is_final"),
            "extrinsics_count": head.get("extrinsics_count"),
            "events_count": head.get("events_count"),
            "spec_version": None,
            "spec_version_note": (
                "TaoSwap /blocks/ does not expose runtime spec_version; "
                "use live_chain_head (TaoStats) for that"),
        },
        "units": "block metadata only — no runtime spec",
        "upstream_timestamp": head.get("timestamp"),
        "block_reference": head.get("id"),
    }


def _pp_portfolio_balance_taoswap(payload, params):
    account = params.get("account")
    if not account:
        raise FatalLiveError("portfolio-balance requires account=ss58")
    held = payload.get("held_netuids")
    if held is None and isinstance(payload.get("results"), list):
        held = []
    return {
        "values": {
            "account": account,
            "account_known": payload.get("account_known"),
            "rank": payload.get("rank"),
            "value_change": payload.get("value_change"),
            "held_netuids": held,
            # Keep subnet_value_change / results — useful but large; cap
            # held list only. Full results stay for agent inspection.
            "subnet_value_change": payload.get("subnet_value_change"),
            "results": payload.get("results"),
            "coldkey_swap": payload.get("coldkey_swap"),
        },
        "units": "portfolio balances; some tao deltas may be in rao "
                 "(1 TAO = 1e9 rao) depending on field",
        "upstream_timestamp": ((payload.get("rank") or {}).get("as_of")
                               and (payload["rank"]["as_of"]
                                    + "T00:00:00+00:00")) or None,
        "block_reference": None,
    }


def _pp_portfolio_pnl_apy_taoswap(payload, params):
    account = params.get("account")
    if not account:
        raise FatalLiveError("portfolio-pnl-apy requires account=ss58")
    return {
        "values": {
            "account": account,
            "account_known": payload.get("account_known"),
            "as_of": payload.get("as_of"),
            "apy": payload.get("apy"),
            "pnl": payload.get("pnl"),
        },
        "units": "APY percent; PnL fields as TaoSwap reports "
                 "(some amounts in rao)",
        "upstream_timestamp": payload.get("as_of"),
        "block_reference": None,
    }


def _pp_validators_taoswap(payload, params):
    rows = payload["results"]

    def stake(row):
        try:
            return float(row.get("total_stake") or 0)
        except (TypeError, ValueError):
            return 0.0

    top = sorted(rows, key=stake, reverse=True)[:15]
    pruned = [{
        "name": (row.get("identity") or {}).get("name"),
        "hotkey": row["validator_hotkey"],
        "total_stake_tao": stake(row),
        "take": row.get("take"),
        "apy_7d": row.get("apy_7d"),
        "delegators": row.get("count_delegators"),
    } for row in top]
    return {"values": {"validators": pruned,
                       "total_listed": len(rows)},
            "units": "stake in TAO; take/apy fractional",
            "upstream_timestamp": None,
            "block_reference": None}


def _pp_network_stats_taoswap(payload, params):
    return {"values": {key: payload.get(key) for key in (
        "date", "total_staked_tao", "available_tao", "root_stake_tao",
        "subnets_stake_tao", "subnets_share_pct", "sum_alpha_price",
        "subnet_reg_cost_tao", "total_accounts", "new_accounts_today")},
        "units": "TAO",
        "upstream_timestamp": payload["date"] + "T00:00:00+00:00",
        "block_reference": None}


def _pp_subnets_taostats(payload, params):
    rows = payload["data"]
    pruned = [{
        "netuid": row["netuid"],
        "owner_ss58": (row.get("owner") or {}).get("ss58"),
        "emission": row.get("emission"),
        "kappa": row.get("kappa"),
        "immunity_period": row.get("immunity_period"),
        "activity_cutoff": row.get("activity_cutoff"),
        "active_validators": row.get("active_validators"),
        "active_miners": row.get("active_miners"),
        "max_neurons": row.get("max_neurons"),
        "registration_cost_rao": row.get("neuron_registration_cost"),
    } for row in rows[:50]]
    block = max((row["block_number"] for row in rows), default=None)
    return {"values": {"subnets": pruned, "count": len(pruned)},
            "units": "raw chain values; *_rao fields in rao "
                     "(1 TAO = 1e9 rao)",
            "upstream_timestamp": None,
            "block_reference": block}


def _pp_metagraph_taostats(payload, params):
    rows = payload["data"]
    pruned = [{
        "hotkey": row["hotkey"]["ss58"],
        "coldkey": row["coldkey"]["ss58"],
        "active": row["active"],
        "alpha_stake_rao": row.get("alpha_stake"),
        "daily_reward_rao": row.get("daily_reward"),
        "is_owner_hotkey": row.get("is_owner_hotkey"),
        "is_immunity_period": row.get("is_immunity_period"),
    } for row in rows[:25]]
    block = max((row["block_number"] for row in rows), default=None)
    return {"values": {"neurons": pruned, "count": len(pruned)},
            "units": "amounts in rao (1 TAO = 1e9 rao)",
            "upstream_timestamp": None,
            "block_reference": block}


def _pp_chain_head_taostats(payload, params):
    if not payload["data"]:
        raise FatalLiveError("block endpoint returned no rows")
    head = payload["data"][0]
    return {"values": {
        "block_number": head["block_number"],
        "spec_version": head["spec_version"],
        "spec_name": head.get("spec_name"),
        "block_hash": (head.get("hash") or "")[:18],
        "conviction_ownership_enacted": head["spec_version"] >= 425,
    },
        "units": "spec_version is the runtime version; >= 425 enacts "
                 "conviction-based subnet ownership",
        "upstream_timestamp": head["timestamp"],
        "block_reference": head["block_number"]}


def _pp_subnet_identity_taostats(payload, params):
    """One page of the netuid -> on-chain SubnetIdentity map. The endpoint
    does not carry the owner ss58, so `owner_ss58` is None (the fleet
    fingerprint keys on the normalized repo URL). Pagination metadata is
    surfaced for the aggregator to page to completion."""
    rows = payload["data"]
    pagination = payload.get("pagination") or {}
    subnets = [{"netuid": row["netuid"],
                "github_repo": row.get("github_repo"),
                "subnet_name": row.get("subnet_name"),
                "owner_ss58": None} for row in rows]
    return {"values": {"subnets": subnets, "count": len(subnets),
                       "current_page": pagination.get("current_page"),
                       "total_pages": pagination.get("total_pages"),
                       "next_page": pagination.get("next_page")},
            "units": "netuid -> on-chain SubnetIdentity.github_repo "
                     "(owner ss58 not provided by this endpoint)",
            "upstream_timestamp": None,
            "block_reference": None}


POSTPROCESSORS = {
    "price_spot_coingecko": _pp_price_spot_coingecko,
    "price_daily_taoswap": _pp_price_daily_taoswap,
    "subnets_taoswap": _pp_subnets_taoswap,
    "validators_taoswap": _pp_validators_taoswap,
    "network_stats_taoswap": _pp_network_stats_taoswap,
    "metagraph_taoswap": _pp_metagraph_taoswap,
    "blocks_taoswap": _pp_blocks_taoswap,
    "portfolio_balance_taoswap": _pp_portfolio_balance_taoswap,
    "portfolio_pnl_apy_taoswap": _pp_portfolio_pnl_apy_taoswap,
    "subnets_taostats": _pp_subnets_taostats,
    "metagraph_taostats": _pp_metagraph_taostats,
    "chain_head_taostats": _pp_chain_head_taostats,
    "subnet_identity_taostats": _pp_subnet_identity_taostats,
}


# ---------------------------------------------------------------------------
# Operation runner — the single fail-closed live pipeline
# (ATLAS-LIVE-001/002/003/004, ATLAS-API-006/007)
# ---------------------------------------------------------------------------


def _freshness_status(envelope_cfg: Dict[str, Any],
                      upstream_iso: Optional[str],
                      now: Optional[datetime.datetime] = None) -> str:
    if upstream_iso is None:
        return "unknown-upstream"
    now = now or datetime.datetime.now(tz=datetime.timezone.utc)
    try:
        upstream = datetime.datetime.fromisoformat(
            upstream_iso.replace("Z", "+00:00"))
    except ValueError:
        return "unknown-upstream"
    age = (now - upstream).total_seconds()
    limit = envelope_cfg.get("max_upstream_age_s")
    return "fresh" if limit is None or age <= limit else "aged-upstream"


def _failure(connection, config, provider, operation, params_key,
             category, message, retry_safe,
             include_last_known: bool) -> Dict[str, Any]:
    """ATLAS-LIVE-004: unavailable result; the cached value itself only
    on explicit request, clearly labelled."""
    result: Dict[str, Any] = {
        "status": "live-unavailable",
        "error": {"category": category, "message": redact(message),
                  "retry_safe": retry_safe,
                  "correlation_id": secretsmod.token_hex(6)},
    }
    snapshot = cache_get(connection, provider, operation, params_key)
    if snapshot is not None:
        result["snapshot_available"] = {"stored_at": snapshot["stored_at"],
                                        "label": snapshot["label"]}
        if include_last_known:
            result["historical_snapshot"] = snapshot
            result["snapshot_warning"] = (
                "This is a labelled historical snapshot returned on "
                "explicit request — NOT live data.")
    return result


def run_operation(connection: sqlite3.Connection, config: Dict[str, Any],
                  ledger: QuotaLedger, op_name: str,
                  dynamic_params: Optional[Dict[str, Any]] = None,
                  interactive: bool = True,
                  include_last_known: bool = False,
                  env: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    operation = config["operations"].get(op_name)
    if operation is None:
        raise FatalLiveError("unknown operation %r" % op_name)
    provider = operation["provider"]
    params = dict(operation.get("params") or {})
    params.update(dynamic_params or {})
    params_key = json.dumps(params, sort_keys=True)

    # Path templating: /metagraph/{netuid}/ → fill from params, then strip
    # path keys + client-only keys from the query string.
    path = operation["path"]
    path_keys: List[str] = []
    if "{" in path:
        path_keys = re.findall(r"\{(\w+)\}", path)
        format_kwargs = {}
        for key in path_keys:
            if params.get(key) is None:
                raise FatalLiveError(
                    "operation %s requires path param %r" % (op_name, key))
            format_kwargs[key] = params[key]
        try:
            path = path.format(**format_kwargs)
        except (KeyError, ValueError) as exc:
            raise FatalLiveError("bad path template %s: %s"
                                 % (operation["path"], exc))
    client_keys = set(operation.get("client_params") or [])
    query_params = {
        key: value for key, value in params.items()
        if key not in path_keys and key not in client_keys
        and value is not None
    }

    refusal = ledger.acquire(provider, interactive=interactive)
    if refusal is not None:
        audit_call(connection, provider, op_name, params, _utc_now(),
                   _utc_now(), None, operation["schema"], "not-attempted",
                   None, refusal["category"])
        return _failure(connection, config, provider, op_name, params_key,
                        refusal["category"], refusal["message"],
                        refusal["retry_safe"], include_last_known)

    headers: Dict[str, str] = {}
    if config["providers"][provider].get("auth") == "header":
        headers[config["providers"][provider]["auth_header"]] = \
            provider_key(config, provider, env)

    started = _utc_now()
    result = http_get(config, provider, path, params=query_params,
                      headers=headers,
                      timeout=config["providers"][provider].get(
                          "timeout_seconds"))
    finished = _utc_now()
    ledger.record_reported_limits(provider, result.get("headers", {}))
    body = result.get("body") or b""
    body_sha = __import__("hashlib").sha256(body).hexdigest() if body \
        else None

    if not result["ok"]:
        audit_call(connection, provider, op_name, params, started,
                   finished, result.get("status"), operation["schema"],
                   "not-validated", body_sha, "provider-failure")
        health_event(connection, provider, op_name, "provider-failure",
                     result.get("error") or "HTTP %s"
                     % result.get("status"))
        return _failure(connection, config, provider, op_name, params_key,
                        "provider-failure",
                        result.get("error") or "provider call failed",
                        True, include_last_known)

    try:
        payload = json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        audit_call(connection, provider, op_name, params, started,
                   finished, result["status"], operation["schema"],
                   "unparseable", body_sha, "schema-drift")
        health_event(connection, provider, op_name, "schema-drift",
                     "unparseable body: %s" % exc)
        return _failure(connection, config, provider, op_name, params_key,
                        "schema-drift", "response body is not valid JSON",
                        False, include_last_known)

    errors = validate_schema(load_schema(operation["schema"]), payload)
    if not errors:
        try:
            processed = POSTPROCESSORS[op_name](payload, params)
        except FatalLiveError as exc:
            errors = [str(exc)]
    if errors:
        audit_call(connection, provider, op_name, params, started,
                   finished, result["status"], operation["schema"],
                   "drift", body_sha, "schema-drift")
        health_event(connection, provider, op_name, "schema-drift",
                     "; ".join(errors[:3]))
        return _failure(connection, config, provider, op_name, params_key,
                        "schema-drift",
                        "response no longer matches the pinned schema "
                        "%s: %s" % (operation["schema"], errors[0]),
                        False, include_last_known)

    audit_call(connection, provider, op_name, params, started, finished,
               result["status"], operation["schema"], "valid", body_sha,
               None)
    envelope_cfg = operation["envelope"]
    response = {
        "status": "ok",
        "provider": provider,
        "operation": op_name,
        "request_completed": finished,
        "upstream_timestamp": processed["upstream_timestamp"],
        "block_reference": processed["block_reference"],
        "units": processed["units"],
        "validation_status": "valid (schema %s)" % operation["schema"],
        "freshness_status": _freshness_status(
            envelope_cfg, processed["upstream_timestamp"]),
        "values": processed["values"],
    }
    cache_put(connection, config, provider, op_name, params_key, response)
    if op_name == "chain_head_taostats":
        # Validated live chain head: persist the last-seen runtime
        # spec_version and record an upgrade event on change (the
        # chain-runtime-upgrade notifier class reads these read-only).
        record_spec_observation(connection, response["values"])
    return response


# ---------------------------------------------------------------------------
# subnet-identity aggregator — pages the identity operation to completion
# and returns the fleet-consumable netuid->identity map. A failed or
# unfinished pagination is reported degraded (complete=False) so the fleet's
# mass-discard guard treats it as untrusted and makes no destructive change.
# ---------------------------------------------------------------------------


def run_subnet_identity(connection, config, ledger, env=None,
                        max_pages: int = 200, run_op=None) -> Dict[str, Any]:
    run_op = run_op or run_operation
    subnets: List[Dict[str, Any]] = []
    last: Optional[Dict[str, Any]] = None
    page = 1
    pages_fetched = 0
    while pages_fetched < max_pages:
        result = run_op(connection, config, ledger, "subnet_identity_taostats",
                        dynamic_params={"page": page}, interactive=False,
                        env=env)
        pages_fetched += 1
        if result.get("status") != "ok":
            return {"status": "live-unavailable",
                    "freshness_status": "unknown-upstream",
                    "block_reference": None,
                    "values": {"subnets": subnets, "count": len(subnets),
                               "complete": False},
                    "error": result.get("error") or {
                        "category": "pagination-failed",
                        "message": "page %d did not validate" % page}}
        last = result
        values = result["values"]
        subnets.extend(values["subnets"])
        next_page = values.get("next_page")
        total_pages = values.get("total_pages")
        if not next_page or (total_pages and page >= total_pages):
            return {"status": "ok",
                    "freshness_status": last["freshness_status"],
                    "block_reference": None,
                    "values": {"subnets": subnets, "count": len(subnets),
                               "complete": True}}
        page = next_page if isinstance(next_page, int) else page + 1
    return {"status": "live-unavailable",
            "freshness_status": "unknown-upstream", "block_reference": None,
            "values": {"subnets": subnets, "count": len(subnets),
                       "complete": False},
            "error": {"category": "pagination-incomplete",
                      "message": "exceeded %d pages without completing"
                                 % max_pages}}


# ---------------------------------------------------------------------------
# Emission-gate poll (change: gate-crossing-signal). Reads the spec-440
# gate state — theta (EmissionGateBar), q (EmissionBarQuantile), h
# (EmissionGateExponent) — from finney via keyless allowlisted JSON-RPC
# `state_getStorage` on PINNED pre-verified keys, all at one finalized
# block. Null storage is a defined state (Substrate never writes
# ValueQuery defaults): null q/h persists the documented per-runtime
# default marked `assumed-default`; null/zero theta persists gate-inactive.
# Demand shares come from the TaoSwap subnets panel of the SAME pass,
# normalized over ALL non-root panel subnets (the chain's bar universe
# includes emission-disabled subnets — they are zeroed only after gating).
# Crossing events are hysteresis-guarded and lifecycle-safe; the notifier
# reads gate_events read-only past a row-id watermark.
# ---------------------------------------------------------------------------

GATE_PROVIDER = "finney-rpc"
GATE_OPERATION = "poll_gate"
GATE_ABOVE = "above"
GATE_BELOW = "below"
GATE_FELL_BELOW = "fell-below"
GATE_ROSE_ABOVE = "rose-above"
_GATE_ITEMS = ("EmissionGateBar", "EmissionBarQuantile",
               "EmissionGateExponent", "EmissionBarRank")
GATE_MODE_RANK = "rank"
GATE_MODE_QMASS = "q-mass"


def _rpc_call(config: Dict[str, Any], method: str, params: List[Any],
              endpoint: Optional[str] = None) -> Dict[str, Any]:
    """One JSON-RPC POST across the configured endpoint list (first
    endpoint that answers wins). Returns {ok, result?, endpoint} or
    {ok: False, error} — never raises on transport failure, redacts every
    error string. Bounded attempts per endpoint (reuses the retry policy)."""
    gcfg = config.get("gate_signal") or {}
    endpoints = [endpoint] if endpoint else list(
        gcfg.get("rpc_endpoints") or [])
    if not endpoints:
        return {"ok": False, "error": "no rpc_endpoints configured"}
    timeout = float(gcfg.get("rpc_timeout_seconds")
                    or config["request_timeout_seconds"])
    attempts = int(config["retry"]["default_attempts"])
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method,
                       "params": params}).encode("utf-8")
    last_error = "no endpoint reachable"
    for url in endpoints:
        for attempt in range(1, attempts + 1):
            try:
                request = urllib.request.Request(
                    url, data=body, method="POST",
                    headers={"User-Agent": USER_AGENT,
                             "Content-Type": "application/json",
                             "Accept": "application/json"})
                with urllib.request.urlopen(request,
                                            timeout=timeout) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                if "error" in payload and payload["error"] is not None:
                    last_error = "rpc error for %s: %s" % (
                        method, payload["error"])
                    break  # a structured RPC error will not improve on retry
                return {"ok": True, "result": payload.get("result"),
                        "endpoint": url}
            except (urllib.error.URLError, TimeoutError, OSError,
                    ValueError) as exc:
                last_error = "rpc failure for %s at %s: %s" % (
                    method, url, exc)
                if attempt < attempts:
                    time.sleep(random.uniform(
                        *config["retry"]["jitter_seconds"]))
    return {"ok": False, "error": redact(last_error)}


def _payload_bytes(hex_payload: str) -> bytes:
    if not isinstance(hex_payload, str) or not hex_payload.startswith("0x"):
        raise ValueError("not a 0x hex payload")
    return bytes.fromhex(hex_payload[2:])


def decode_u64f64(hex_payload: str) -> float:
    """Decode a SCALE U64F64 storage payload (16 bytes little-endian,
    value = raw / 2^64). Raises ValueError on any malformed input."""
    data = _payload_bytes(hex_payload)
    if len(data) != 16:
        raise ValueError("expected 16 bytes, got %d" % len(data))
    return int.from_bytes(data, "little") / float(2 ** 64)


def decode_u16(hex_payload: str) -> int:
    """Decode a SCALE u16 storage payload (2 bytes little-endian).
    Raises ValueError on any malformed input. Deliberately NOT
    interchangeable with decode_u64f64: a fixed-point payload is 16 bytes
    and fails the length check loudly rather than decoding to nonsense."""
    data = _payload_bytes(hex_payload)
    if len(data) != 2:
        raise ValueError("expected 2 bytes, got %d" % len(data))
    return int.from_bytes(data, "little")


def decode_bool(hex_payload: str) -> bool:
    """Decode a SCALE bool storage payload (1 byte, 0x00 or 0x01).
    A correct-length byte that is neither encoding is rejected — length
    checking alone would pass it."""
    data = _payload_bytes(hex_payload)
    if len(data) != 1:
        raise ValueError("expected 1 byte, got %d" % len(data))
    if data[0] not in (0, 1):
        raise ValueError("not a SCALE bool: 0x%02x" % data[0])
    return data[0] == 1


# Codec is a property of the storage item, never inferred from the payload:
# a length-based guess is unambiguous today and silently wrong for the first
# item that shares a length with another codec.
_CODECS = {"u64f64": decode_u64f64, "u16": decode_u16, "bool": decode_bool}


def decode_by_codec(codec: str, hex_payload: str) -> Any:
    """Decode a storage payload with the item's declared codec."""
    decoder = _CODECS.get(codec)
    if decoder is None:
        raise ValueError("unknown codec %r" % codec)
    return decoder(hex_payload)


def poll_gate_state(connection: sqlite3.Connection,
                    config: Dict[str, Any],
                    rpc: Optional[Any] = None) -> Dict[str, Any]:
    """Read theta/q/h at one finalized block and persist ONE gate_state
    observation. Fail-closed: transport failure or an out-of-bounds decode
    records a health event and persists nothing. Null semantics per the
    gate-crossing-signal spec: null q/h -> assumed per-runtime default;
    null/zero theta -> gate-inactive observation."""
    gcfg = config.get("gate_signal") or {}
    rpc = rpc or (lambda method, params: _rpc_call(config, method, params))
    keys = gcfg.get("storage_keys") or {}
    defaults = gcfg.get("assumed_defaults") or {}
    for item in _GATE_ITEMS:
        if item not in keys:
            raise FatalLiveError("gate_signal.storage_keys missing %r" % item)

    head = rpc("chain_getFinalizedHead", [])
    if not head.get("ok") or not head.get("result"):
        health_event(connection, GATE_PROVIDER, GATE_OPERATION,
                     "provider-failure",
                     head.get("error") or "no finalized head")
        return {"ok": False, "error": "finalized head unavailable"}
    block_hash = head["result"]
    endpoint = head.get("endpoint") or "unknown"

    header = rpc("chain_getHeader", [block_hash])
    block_number: Optional[int] = None
    if header.get("ok") and isinstance(header.get("result"), dict):
        try:
            block_number = int(str(header["result"].get("number")), 16)
        except (TypeError, ValueError):
            block_number = None

    raw: Dict[str, Optional[str]] = {}
    for item in _GATE_ITEMS:
        read = rpc("state_getStorage", [keys[item], block_hash])
        if not read.get("ok"):
            health_event(connection, GATE_PROVIDER, GATE_OPERATION,
                         "provider-failure",
                         read.get("error") or ("read failed: %s" % item))
            return {"ok": False, "error": "storage read failed: %s" % item}
        raw[item] = read.get("result")  # None == key unset on chain

    def _decode_or_default(item: str, low: float, high: float,
                           low_inclusive: bool,
                           codec: str = "u64f64") -> Tuple[Any, str]:
        value = raw[item]
        if value is None:
            default = defaults.get(item)
            if default is None:
                raise ValueError("%s unset on chain and no assumed "
                                 "default configured" % item)
            return (int(default) if codec == "u16" else float(default),
                    "assumed-default")
        decoded = decode_by_codec(codec, value)
        ok_low = decoded >= low if low_inclusive else decoded > low
        if not (ok_low and decoded <= high):
            raise ValueError("%s out of bounds: %r" % (item, decoded))
        return decoded, "explicit"

    try:
        theta_raw = raw["EmissionGateBar"]
        theta: Optional[float] = None
        if theta_raw is not None:
            theta = decode_u64f64(theta_raw)
            if not (0.0 <= theta < 1.0):
                raise ValueError("EmissionGateBar out of bounds: %r" % theta)
        q, q_provenance = _decode_or_default(
            "EmissionBarQuantile", 0.0, 1.0, low_inclusive=False)
        h, h_provenance = _decode_or_default(
            "EmissionGateExponent", 1.0, 8.0, low_inclusive=True)
        # Rank is u16, NOT fixed-point (spec 441, PR #3014). N > 0 pins theta
        # to the Nth-largest positive demand share and makes q inert.
        rank, rank_provenance = _decode_or_default(
            "EmissionBarRank", 0, 65535, low_inclusive=True, codec="u16")
    except ValueError as exc:
        health_event(connection, GATE_PROVIDER, GATE_OPERATION,
                     "validation-failure", str(exc))
        return {"ok": False, "error": "gate state failed validation"}

    gate_active = bool(theta and theta > 0.0)
    # The bar mode is a property of THIS observation: a crossing recorded
    # last week must stay interpretable with last week's mode. Derived from
    # the effective rank, including an assumed-default one.
    bar_mode = GATE_MODE_RANK if rank > 0 else GATE_MODE_QMASS
    previous = connection.execute(
        "SELECT theta FROM gate_state WHERE theta IS NOT NULL "
        "ORDER BY id DESC LIMIT 1").fetchone()
    prev_theta = previous[0] if previous else None
    connection.execute(
        "INSERT INTO gate_state (observed_at, block_hash, block_number, "
        "gate_active, theta, q, q_provenance, h, h_provenance, endpoint, "
        "rank, rank_provenance, bar_mode) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (_utc_now(), block_hash, block_number, int(gate_active),
         theta if gate_active else None, q, q_provenance, h, h_provenance,
         endpoint, rank, rank_provenance, bar_mode))
    connection.commit()
    # Bar parameters are handed to the chain-parameter watch rather than
    # re-read: one storage read per item, one durable history. This replaces
    # the ephemeral `params_changed` flag, which detected q/h moves but was
    # never persisted and never paged.
    return {"ok": True, "gate_active": gate_active, "theta": theta,
            "prev_theta": prev_theta,
            "q": q, "q_provenance": q_provenance,
            "h": h, "h_provenance": h_provenance,
            "rank": rank, "rank_provenance": rank_provenance,
            "bar_mode": bar_mode,
            "block_number": block_number, "block_hash": block_hash,
            "endpoint": endpoint,
            "bar_params": {
                "EmissionBarRank": (rank, rank_provenance),
                "EmissionBarQuantile": (q, q_provenance),
                "EmissionGateExponent": (h, h_provenance)}}


# ---------------------------------------------------------------------------
# Chain-parameter watch (change: network-drift-443). Discrete root-settable
# knobs whose flip changes network economics with no AdminUtils extrinsic
# trail. Bar parameters arrive already decoded from the gate poll (one read
# per item, one history); everything else is read here on its own pinned key.
# Deliberately NOT gated by the gate kill-switch: rolling back the gate
# signal must not silently stop watching the Root Reborn curation switch.
# ---------------------------------------------------------------------------

PARAM_PROVIDER = "finney-rpc"
PARAM_OPERATION = "watch_chain_params"
PARAM_SOURCE_GATE = "gate-poll"


def param_value_text(value: Any) -> str:
    """Canonical text form of a watched value, so persistence and equality
    are exact and stable across int/float/bool without float re-formatting
    surprises."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    raise ValueError("unsupported watched value type: %r" % type(value))


def _record_param(connection: sqlite3.Connection, item: str, value: Any,
                  provenance: str, block_number: Optional[int],
                  block_hash: Optional[str]) -> Optional[Dict[str, Any]]:
    """Persist one observation and return a transition dict when the VALUE
    changed against the last persisted observation. A first-ever observation
    seeds without a transition (nothing to differ from); a provenance-only
    change is recorded but is not a transition — governance pinning a knob
    to the value it already had by default changes nothing economically."""
    text = param_value_text(value)
    previous = connection.execute(
        "SELECT value, provenance FROM chain_params WHERE item = ? "
        "ORDER BY id DESC LIMIT 1", (item,)).fetchone()
    now = _utc_now()
    connection.execute(
        "INSERT INTO chain_params (item, value, provenance, observed_at, "
        "block_number, block_hash) VALUES (?, ?, ?, ?, ?, ?)",
        (item, text, provenance, now, block_number, block_hash))
    transition: Optional[Dict[str, Any]] = None
    if previous is not None and previous[0] != text:
        cursor = connection.execute(
            "INSERT INTO chain_param_events (item, prev_value, new_value, "
            "prev_provenance, new_provenance, observed_at, block_number) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (item, previous[0], text, previous[1], provenance, now,
             block_number))
        transition = {"id": cursor.lastrowid, "item": item,
                      "prev_value": previous[0], "new_value": text,
                      "prev_provenance": previous[1],
                      "new_provenance": provenance}
    connection.commit()
    return transition


def run_chain_param_watch(connection: sqlite3.Connection,
                          config: Dict[str, Any],
                          rpc: Optional[Any] = None,
                          bar_params: Optional[Dict[str, Any]] = None,
                          block_hash: Optional[str] = None,
                          block_number: Optional[int] = None
                          ) -> Dict[str, Any]:
    """Observe every configured watched item and record value transitions.

    `bar_params` carries the gate poll's already-decoded {item: (value,
    provenance)}; when absent (gate disabled, or the poll failed closed)
    gate-sourced items are simply not observed this pass, which is honest
    rather than silent. Independently sourced items are read at the gate
    poll's block when one is supplied, otherwise at a head obtained here.
    One unreadable item never blinds the rest."""
    pcfg = config.get("chain_params") or {}
    if not pcfg.get("enabled"):
        return {"status": "disabled"}
    rpc = rpc or (lambda method, params: _rpc_call(config, method, params))
    items = list(pcfg.get("items") or [])
    gate_values = bar_params or {}

    independent = [i for i in items
                   if i.get("source") != PARAM_SOURCE_GATE]
    if independent and block_hash is None:
        head = rpc("chain_getFinalizedHead", [])
        if not head.get("ok") or not head.get("result"):
            health_event(connection, PARAM_PROVIDER, PARAM_OPERATION,
                         "provider-failure",
                         head.get("error") or "no finalized head")
            independent = []
        else:
            block_hash = head["result"]
            header = rpc("chain_getHeader", [block_hash])
            if header.get("ok") and isinstance(header.get("result"), dict):
                try:
                    block_number = int(str(header["result"].get("number")),
                                       16)
                except (TypeError, ValueError):
                    block_number = None

    observed: List[str] = []
    skipped: List[str] = []
    transitions: List[Dict[str, Any]] = []

    for spec in items:
        item = spec.get("item")
        if not item:
            continue
        if spec.get("source") == PARAM_SOURCE_GATE:
            if item not in gate_values:
                skipped.append(item)
                continue
            value, provenance = gate_values[item]
        else:
            if item not in [i.get("item") for i in independent]:
                skipped.append(item)
                continue
            key = spec.get("key")
            if not key:
                raise FatalLiveError(
                    "chain_params item %r is independent but has no key"
                    % item)
            read = rpc("state_getStorage", [key, block_hash])
            if not read.get("ok"):
                health_event(connection, PARAM_PROVIDER, PARAM_OPERATION,
                             "provider-failure",
                             read.get("error") or ("read failed: %s" % item))
                skipped.append(item)
                continue  # one unreadable knob does not blind the others
            payload = read.get("result")
            if payload is None:
                default = spec.get("default")
                if default is None:
                    health_event(connection, PARAM_PROVIDER,
                                 PARAM_OPERATION, "validation-failure",
                                 "%s unset and no default configured" % item)
                    skipped.append(item)
                    continue
                value, provenance = default, "assumed-default"
            else:
                try:
                    value = decode_by_codec(spec.get("codec", ""), payload)
                except ValueError as exc:
                    health_event(connection, PARAM_PROVIDER,
                                 PARAM_OPERATION, "validation-failure",
                                 str(exc))
                    skipped.append(item)
                    continue
                provenance = "explicit"
        transition = _record_param(connection, item, value, provenance,
                                   block_number, block_hash)
        observed.append(item)
        if transition is not None:
            transitions.append(transition)

    return {"status": "ok", "observed": observed, "skipped": skipped,
            "transitions": transitions,
            "block_number": block_number}


def compute_demand_shares(subnets: List[Dict[str, Any]]
                          ) -> Tuple[Dict[int, float],
                                     Dict[int, Optional[bool]]]:
    """Demand shares from the validated TaoSwap panel: moving price
    weighted by (1 - miner_burn), normalized over ALL non-root panel
    subnets (emission-disabled INCLUDED — the chain zeroes them only
    after the bar is computed). Returns ({netuid: share}, {netuid:
    emission_is_enabled}); empty shares when nothing normalizes."""
    weights: Dict[int, float] = {}
    enabled: Dict[int, Optional[bool]] = {}
    for row in subnets:
        netuid = row.get("netuid")
        price = row.get("moving_price_tao")
        if not isinstance(netuid, int) or netuid == 0:
            continue
        if not isinstance(price, (int, float)) or price < 0:
            continue  # no priced entry -> no share this pass
        burn = row.get("emission_miner_burn")
        factor = 1.0
        if isinstance(burn, (int, float)):
            factor = 1.0 - min(max(float(burn), 0.0), 100.0) / 100.0
        weights[netuid] = float(price) * factor
        enabled[netuid] = (bool(row["emission_is_enabled"])
                           if row.get("emission_is_enabled") is not None
                           else None)
    total = sum(weights.values())
    if total <= 0.0:
        return {}, enabled
    return {netuid: weight / total
            for netuid, weight in weights.items()}, enabled


def update_gate_sides(connection: sqlite3.Connection,
                      gcfg: Dict[str, Any], theta: float,
                      shares: Dict[int, float],
                      enabled: Dict[int, Optional[bool]],
                      block_number: Optional[int],
                      prev_theta: Optional[float] = None
                      ) -> List[Dict[str, Any]]:
    """Advance per-netuid gate sides and record confirmed crossing events.
    Hysteresis: a side flips only after the share sits beyond the
    relative band around theta on `confirm_polls` consecutive polls.
    Lifecycle: first sight seeds silently; absence for
    `absence_clear_polls` polls clears the side (netuid-reuse guard).
    Idempotent across restarts: state lives in gate_sides."""
    band = float(gcfg.get("hysteresis_pct", 10)) / 100.0
    confirm = max(1, int(gcfg.get("confirm_polls", 2)))
    absence = max(1, int(gcfg.get("absence_clear_polls", 3)))
    upper = theta * (1.0 + band)
    lower = theta * (1.0 - band)
    now = _utc_now()

    existing = {
        row[0]: {"side": row[1], "pending_side": row[2],
                 "pending_count": row[3], "miss_count": row[4]}
        for row in connection.execute(
            "SELECT netuid, side, pending_side, pending_count, miss_count "
            "FROM gate_sides")}

    events: List[Dict[str, Any]] = []
    for netuid in sorted(shares):
        share = shares[netuid]
        zone = (GATE_ABOVE if share > upper
                else GATE_BELOW if share < lower else "band")
        row = existing.get(netuid)
        if row is None:
            seed = GATE_ABOVE if share >= theta else GATE_BELOW
            connection.execute(
                "INSERT INTO gate_sides (netuid, side, pending_side, "
                "pending_count, miss_count, updated_at) "
                "VALUES (?, ?, NULL, 0, 0, ?)", (netuid, seed, now))
            continue
        side = row["side"]
        pending_side, pending_count = row["pending_side"], row["pending_count"]
        if zone == "band" or zone == side:
            pending_side, pending_count = None, 0
        else:
            pending_count = (pending_count + 1 if pending_side == zone
                             else 1)
            pending_side = zone
            if pending_count >= confirm:
                direction = (GATE_FELL_BELOW if zone == GATE_BELOW
                             else GATE_ROSE_ABOVE)
                cursor = connection.execute(
                    "INSERT INTO gate_events (observed_at, netuid, "
                    "direction, share, theta, prev_side, emission_enabled, "
                    "block_number, prev_theta) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (now, netuid, direction, share, theta, side,
                     (None if enabled.get(netuid) is None
                      else int(bool(enabled.get(netuid)))), block_number,
                     prev_theta))
                events.append({"id": cursor.lastrowid, "netuid": netuid,
                               "direction": direction, "share": share,
                               "theta": theta, "prev_theta": prev_theta})
                side = zone
                pending_side, pending_count = None, 0
        connection.execute(
            "UPDATE gate_sides SET side = ?, pending_side = ?, "
            "pending_count = ?, miss_count = 0, updated_at = ? "
            "WHERE netuid = ?",
            (side, pending_side, pending_count, now, netuid))

    for netuid, row in existing.items():
        if netuid in shares:
            continue
        misses = row["miss_count"] + 1
        if misses >= absence:
            connection.execute("DELETE FROM gate_sides WHERE netuid = ?",
                               (netuid,))
        else:
            connection.execute(
                "UPDATE gate_sides SET miss_count = ?, updated_at = ? "
                "WHERE netuid = ?", (misses, now, netuid))
    connection.commit()
    return events


def run_gate_pass(connection: sqlite3.Connection, config: Dict[str, Any],
                  ledger: QuotaLedger, rpc: Optional[Any] = None,
                  run_op: Optional[Any] = None,
                  env: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """One full gate pass: chain state -> panel shares -> sides/events.
    Inert when the kill-switch is off. A gate-inactive -> active
    transition re-seeds every side silently (no events for the
    transition pass)."""
    gcfg = config.get("gate_signal") or {}
    if not gcfg.get("enabled"):
        return {"status": "disabled"}
    run_op = run_op or run_operation

    state = poll_gate_state(connection, config, rpc=rpc)
    if not state.get("ok"):
        return {"status": "live-unavailable", "error": state.get("error")}

    # The watch runs inside the pass so bar parameters are recorded at the
    # gate observation's own block, with no second storage read.
    watch = run_chain_param_watch(
        connection, config, rpc=rpc, bar_params=state.get("bar_params"),
        block_hash=state.get("block_hash"),
        block_number=state.get("block_number"))
    bar_param_change = [t for t in (watch.get("transitions") or [])
                        if t["item"] in _GATE_ITEMS]

    summary: Dict[str, Any] = {
        "status": "ok", "gate_active": state["gate_active"],
        "theta": state["theta"], "q": state["q"],
        "q_provenance": state["q_provenance"], "h": state["h"],
        "h_provenance": state["h_provenance"],
        "rank": state["rank"], "rank_provenance": state["rank_provenance"],
        "bar_mode": state["bar_mode"],
        "block_number": state["block_number"],
        "chain_params": watch,
    }
    was_active = meta_get(connection, META_GATE_ACTIVE) == "1"
    if not state["gate_active"]:
        meta_set(connection, META_GATE_ACTIVE, "0")
        connection.commit()
        summary["events_recorded"] = 0
        summary["note"] = "gate inactive: no crossing events by design"
        return summary
    if not was_active or bar_param_change:
        # Inactive (or first-ever) -> active: every side re-seeds silently.
        # Same treatment for a bar-parameter change: it re-prices the bar for
        # EVERY subnet at once, so the |M - N| crossings it induces belong to
        # the parameter change, not to per-subnet demand. Paging them
        # individually is what happened at the spec-441 bar reset on
        # 2026-08-03 (four subnets reported as rising when the bar had fallen
        # onto them), and it misinformed.
        connection.execute("DELETE FROM gate_sides")
        if bar_param_change:
            summary["reseeded"] = [t["item"] for t in bar_param_change]
    meta_set(connection, META_GATE_ACTIVE, "1")
    connection.commit()

    panel = run_op(connection, config, ledger, "subnets_taoswap",
                   interactive=False, env=env)
    if panel.get("status") != "ok":
        summary["panel"] = "live-unavailable"
        summary["events_recorded"] = 0
        return summary
    shares, enabled = compute_demand_shares(panel["values"]["subnets"])
    if not shares:
        summary["panel"] = "no-normalizable-shares"
        summary["events_recorded"] = 0
        return summary
    events = update_gate_sides(connection, gcfg, state["theta"], shares,
                               enabled, state["block_number"],
                               prev_theta=state.get("prev_theta"))
    summary["sides_tracked"] = connection.execute(
        "SELECT COUNT(*) FROM gate_sides").fetchone()[0]
    summary["events_recorded"] = len(events)
    summary["events"] = events

    # Rank-mode invariant: the chain pins theta to the Nth-largest POSITIVE
    # demand share, so exactly N positive shares sit at or above it. Counting
    # them cross-checks the panel data, the normalization universe, and the
    # theta read against the chain's own selection rule, for free. Counted
    # from the shares rather than from gate_sides so Atlas-side hysteresis
    # (an intentional smoothing artefact) cannot masquerade as disagreement.
    above_count: Optional[int] = None
    if state["bar_mode"] == GATE_MODE_RANK:
        above_count = sum(1 for share in shares.values()
                          if share > 0.0 and share >= state["theta"])
        rank = int(state["rank"])
        tolerance = int(gcfg.get("above_count_tolerance", 0))
        connection.execute(
            "UPDATE gate_state SET above_count = ? WHERE id = "
            "(SELECT id FROM gate_state ORDER BY id DESC LIMIT 1)",
            (above_count,))
        connection.commit()
        if abs(above_count - rank) > tolerance:
            # Information, not an error: never suppresses events or discards
            # the pass. It means Atlas and the chain disagree about demand.
            health_event(
                connection, GATE_PROVIDER, GATE_OPERATION,
                "invariant-divergence",
                "above-bar count %d vs rank %d at block %s"
                % (above_count, rank, state["block_number"]))
    summary["above_count"] = above_count
    return summary


# ---------------------------------------------------------------------------
# CLI — scheduled chain-head poll (piggybacked on the hourly repo-update
# service, before the Telegram scan line). Everything else in this module
# is served through atlas_live_server.py when Hermes asks; this entry
# point exists so a live runtime upgrade is detected promptly rather than
# only when someone queries. Spends one non-interactive TaoStats call.
# ---------------------------------------------------------------------------


def _cmd_poll_chain_head() -> int:
    config = load_config()
    env = load_env()
    connection = open_store(resolve(config["db"]))
    try:
        ledger = QuotaLedger(connection, config)
        result = run_operation(connection, config, ledger,
                               "chain_head_taostats", interactive=False,
                               env=env)
        summary: Dict[str, Any] = {"status": result["status"]}
        if result["status"] == "ok":
            summary["spec_version"] = result["values"]["spec_version"]
            summary["block_number"] = result["values"]["block_number"]
        else:
            summary["error"] = result.get("error", {}).get("category")
        row = connection.execute(
            "SELECT id, prev_spec, new_spec FROM spec_upgrades "
            "ORDER BY id DESC LIMIT 1").fetchone()
        summary["last_upgrade_event"] = (
            {"id": row[0], "prev_spec": row[1], "new_spec": row[2]}
            if row else None)
    finally:
        connection.close()
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary["status"] == "ok" else 1


def _cmd_poll_gate() -> int:
    config = load_config()
    env = load_env()
    connection = open_store(resolve(config["db"]))
    try:
        ledger = QuotaLedger(connection, config)
        summary = run_gate_pass(connection, config, ledger, env=env)
        if summary["status"] == "disabled":
            # The gate signal is rolled back, but the chain-parameter watch
            # is a separate concern: the Root Reborn curation switch has
            # nothing to do with the gate, and a rollback of one must not
            # silently stop the other. Bar parameters pause (that is where
            # their values come from); independent items keep being read.
            watch = run_chain_param_watch(connection, config)
            if watch["status"] != "disabled":
                summary = {"status": "ok", "gate": "disabled",
                           "chain_params": watch}
    finally:
        connection.close()
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary["status"] in ("ok", "disabled") else 1


def _cmd_status() -> int:
    config = load_config()
    db = resolve(config["db"])
    if not os.path.exists(db):
        print(json.dumps({"store": "absent", "db": db}))
        return 0
    connection = open_store(db)
    try:
        state_rows = connection.execute(
            "SELECT observed_at, block_number, gate_active, theta, q, "
            "q_provenance, h, h_provenance, endpoint, rank, "
            "rank_provenance, bar_mode, above_count FROM gate_state "
            "ORDER BY id DESC LIMIT 5").fetchall()
        sides = dict(connection.execute(
            "SELECT side, COUNT(*) FROM gate_sides GROUP BY side"
        ).fetchall())
        event_rows = connection.execute(
            "SELECT id, observed_at, netuid, direction, share, theta, "
            "prev_theta FROM gate_events ORDER BY id DESC LIMIT 5"
        ).fetchall()
        # Latest observation per watched item, plus recent transitions.
        param_rows = connection.execute(
            "SELECT item, value, provenance, observed_at, block_number "
            "FROM chain_params WHERE id IN "
            "(SELECT MAX(id) FROM chain_params GROUP BY item) "
            "ORDER BY item").fetchall()
        param_events = connection.execute(
            "SELECT id, item, prev_value, new_value, observed_at "
            "FROM chain_param_events ORDER BY id DESC LIMIT 5").fetchall()
        spec = {"spec_version": meta_get(connection, META_LAST_LIVE_SPEC),
                "block": meta_get(connection, META_LAST_LIVE_SPEC_BLOCK),
                "observed_at": meta_get(connection,
                                        META_LAST_LIVE_SPEC_OBSERVED)}
    finally:
        connection.close()
    print(json.dumps({
        "gate_state_recent": [
            {"observed_at": r[0], "block_number": r[1],
             "gate_active": bool(r[2]), "theta": r[3],
             "q": r[4], "q_provenance": r[5],
             "h": r[6], "h_provenance": r[7], "endpoint": r[8],
             "rank": r[9], "rank_provenance": r[10], "bar_mode": r[11],
             "above_count": r[12]}
            for r in state_rows],
        "gate_sides": sides,
        "gate_events_recent": [
            {"id": r[0], "observed_at": r[1], "netuid": r[2],
             "direction": r[3], "share": r[4], "theta": r[5],
             "prev_theta": r[6]}
            for r in event_rows],
        "chain_params_latest": [
            {"item": r[0], "value": r[1], "provenance": r[2],
             "observed_at": r[3], "block_number": r[4]}
            for r in param_rows],
        "chain_param_events_recent": [
            {"id": r[0], "item": r[1], "prev_value": r[2],
             "new_value": r[3], "observed_at": r[4]}
            for r in param_events],
        "live_spec": spec,
    }, indent=2, sort_keys=True))
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(
        description="Atlas live-data scheduled poll (the MCP server "
                    "atlas_live_server.py serves interactive queries)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("poll-chain-head",
                   help="one validated chain-head read; records the live "
                        "runtime spec_version and an upgrade event on "
                        "change (non-interactive quota)")
    sub.add_parser("poll-gate",
                   help="one emission-gate pass: theta/q/h from finney "
                        "RPC at a finalized block, demand shares from the "
                        "TaoSwap panel, hysteresis-guarded crossing "
                        "events (inert unless gate_signal.enabled)")
    sub.add_parser("status",
                   help="gate state / sides / recent crossing events + "
                        "last live spec_version")
    args = parser.parse_args(argv)
    try:
        if args.command == "poll-chain-head":
            return _cmd_poll_chain_head()
        if args.command == "poll-gate":
            return _cmd_poll_gate()
        if args.command == "status":
            return _cmd_status()
    except FatalLiveError as exc:
        print("fatal: %s" % redact(str(exc)), file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
