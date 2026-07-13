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
CREATE TABLE IF NOT EXISTS spec_upgrades (
    id INTEGER PRIMARY KEY,
    observed_at TEXT NOT NULL,
    prev_spec INTEGER NOT NULL,
    new_spec INTEGER NOT NULL,
    block_reference INTEGER
);
"""

META_LAST_LIVE_SPEC = "last_live_spec"
META_LAST_LIVE_SPEC_BLOCK = "last_live_spec_block"
META_LAST_LIVE_SPEC_OBSERVED = "last_live_spec_observed_at"


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
        pruned.append({
            "netuid": row.get("id"),
            "name": row.get("name"),
            "symbol": row.get("symbol"),
            "alpha_price_tao": row.get("price"),
            "alpha_stake": row.get("alpha_stake"),
            "emission_percent": row.get("emission_percent"),
            "conviction": {key: conviction.get(key) for key in (
                "king_is_owner", "is_contested", "takeover_eligible",
                "takeover_enforced", "gate_ceiling_pct",
                "total_locked_pct_supply", "holder_count")}
            if conviction else None,
        })
    block = (payload.get("dereg_context") or {}).get("current_block")
    return {"values": {"subnets": pruned, "count": len(pruned)},
            "units": "alpha prices in TAO; percentages 0-100",
            "upstream_timestamp": None,
            "block_reference": block}


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


POSTPROCESSORS = {
    "price_spot_coingecko": _pp_price_spot_coingecko,
    "price_daily_taoswap": _pp_price_daily_taoswap,
    "subnets_taoswap": _pp_subnets_taoswap,
    "validators_taoswap": _pp_validators_taoswap,
    "network_stats_taoswap": _pp_network_stats_taoswap,
    "subnets_taostats": _pp_subnets_taostats,
    "metagraph_taostats": _pp_metagraph_taostats,
    "chain_head_taostats": _pp_chain_head_taostats,
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
    result = http_get(config, provider, operation["path"], params=params,
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
    args = parser.parse_args(argv)
    try:
        if args.command == "poll-chain-head":
            return _cmd_poll_chain_head()
    except FatalLiveError as exc:
        print("fatal: %s" % redact(str(exc)), file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
