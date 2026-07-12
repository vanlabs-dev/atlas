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
"""


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
    key = env.get(spec["key_env"], "").strip()
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
