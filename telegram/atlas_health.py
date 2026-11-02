"""Atlas out-of-band health watch (change: alert-delivery-reliability).

Runs from its own 5-minute user timer, outside Hermes and outside the alert
scan, so it can page when either of them stops. It checks:

- the Hermes gateway: unit state, restart count, and the gateway's own
  state file;
- the alert scan heartbeat the scan writes after each completed run;
- the LLM: Claude auth failures in the Hermes logs, and rewrite fallbacks
  in the Telegram ledger;
- the streak of every Atlas unit the failure notifier recorded.

Every page is a fixed template sent straight to the Bot API through the
Telegram ledger and retry queue. Nothing here calls Hermes or a model.
Each check pages once per outage and sends one recovery note.

Pure over injected readers, so the tests need neither systemd nor a Pi.
"""

from __future__ import annotations

import datetime
import json
import os
import re
import sqlite3
import subprocess
from typing import Any, Callable, Dict, List, Optional, Tuple

import atlas_telegram as tg

HEALTH_SQL = """
CREATE TABLE IF NOT EXISTS health_state (
    check_name TEXT PRIMARY KEY,
    failing_since TEXT NOT NULL,
    consecutive INTEGER NOT NULL,
    paged_at TEXT,
    detail TEXT
);
CREATE TABLE IF NOT EXISTS unit_failures (
    unit TEXT PRIMARY KEY,
    since TEXT NOT NULL,
    failures INTEGER NOT NULL,
    paged_at TEXT,
    system INTEGER NOT NULL DEFAULT 0
);
"""

DEFAULTS: Dict[str, Any] = {
    "gateway_unit": "hermes-gateway.service",
    "gateway_state_file": "~/.hermes/gateway_state.json",
    "state_max_age_minutes": 10,
    "gateway_threshold": 2,
    "heartbeat_hours": 3,
    "llm_window_hours": 2,
    "hermes_logs": ["~/.hermes/logs/agent.log", "~/.hermes/logs/errors.log"],
    # Restart=on-failure keeps this system unit out of `failed`, so
    # OnFailure= alone rarely fires; the watch checks it like the gateway.
    "dashboard_unit": "atlas-dashboard.service",
    "log_tail_bytes": 262144,
}

CHECK_GATEWAY = "gateway"
CHECK_SCAN = "scan"
CHECK_LLM = "llm"
CHECK_DASHBOARD = "dashboard"

# Rewrite fallbacks that mean the model did not answer (not a check
# rejection, budget or switch-off). `toolset-unverified` means the startup
# check could not prove the call has no tools, so no rewrite runs.
_LLM_DOWN_REASONS = ("hermes-error", "timeout", "toolset-unverified")
_LOG_TIME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")
_AUTH_FAIL = "Failed to authenticate"
_CALL_OK_RE = re.compile(r"API call #\d+: model=")

ShowFn = Callable[[str, List[str], bool], Dict[str, str]]


class Readers:
    """The seams the tests replace: systemd, files, clocks."""

    def show(self, unit: str, props: List[str],
             system: bool = False) -> Dict[str, str]:
        cmd = ["systemctl"] + ([] if system else ["--user"]) + [
            "show", unit, "-p", ",".join(props)]
        try:
            done = subprocess.run(cmd, capture_output=True, text=True,
                                  timeout=15)
        except (OSError, subprocess.TimeoutExpired):
            return {}
        out: Dict[str, str] = {}
        for line in done.stdout.splitlines():
            key, sep, value = line.partition("=")
            if sep:
                out[key] = value
        return out

    def read_text(self, path: str) -> Optional[str]:
        try:
            with open(os.path.expanduser(path), "r", encoding="utf-8",
                      errors="replace") as handle:
                return handle.read()
        except OSError:
            return None

    def tail(self, path: str, limit: int) -> str:
        try:
            with open(os.path.expanduser(path), "rb") as handle:
                handle.seek(0, os.SEEK_END)
                size = handle.tell()
                handle.seek(max(0, size - limit))
                return handle.read().decode("utf-8", "replace")
        except OSError:
            return ""

    def now(self) -> datetime.datetime:
        return datetime.datetime.now(datetime.timezone.utc)

    def now_local(self) -> datetime.datetime:
        """Naive local time: the Hermes logs stamp local wall time."""
        return datetime.datetime.now()


def health_config(config: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(DEFAULTS)
    merged.update(config.get("health") or {})
    return merged


def open_health(connection: sqlite3.Connection) -> None:
    connection.executescript(HEALTH_SQL)
    connection.commit()


def _meta_get(connection: sqlite3.Connection, key: str) -> Optional[str]:
    row = connection.execute("SELECT value FROM meta WHERE key = ?",
                             (key,)).fetchone()
    return row[0] if row else None


def _meta_set(connection: sqlite3.Connection, key: str, value: str) -> None:
    connection.execute(
        "INSERT INTO meta (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))
    connection.commit()


def _parse(value: Any) -> Optional[datetime.datetime]:
    if not isinstance(value, str):
        return None
    try:
        moment = datetime.datetime.fromisoformat(value)
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=datetime.timezone.utc)
    return moment


# ---------------------------------------------------------------------------
# Checks: each returns None when healthy, or a short plain reason
# ---------------------------------------------------------------------------

def check_gateway(readers: Readers, connection: sqlite3.Connection,
                  hcfg: Dict[str, Any]) -> Optional[str]:
    props = readers.show(hcfg["gateway_unit"],
                         ["ActiveState", "MainPID", "NRestarts"], False)
    active = props.get("ActiveState") or "unknown"
    restarts = props.get("NRestarts")
    previous = _meta_get(connection, "health:gateway_nrestarts")
    if restarts is not None and restarts.isdigit():
        _meta_set(connection, "health:gateway_nrestarts", restarts)
    if active != "active":
        return "the gateway service is %s" % active
    if (previous is not None and previous.isdigit() and restarts
            and restarts.isdigit() and int(restarts) > int(previous)):
        return "the gateway service restarted"
    raw = readers.read_text(hcfg["gateway_state_file"])
    try:
        state = json.loads(raw) if raw is not None else None
    except ValueError:
        state = None
    if not isinstance(state, dict):
        return "Atlas cannot read the gateway state file"
    if state.get("gateway_state") != "running":
        return "the gateway reports %s" % (
            tg.rec(state.get("gateway_state")) or "no state")
    updated = _parse(state.get("updated_at"))
    if updated is None:
        return "Atlas cannot read the gateway state file"
    age = (readers.now() - updated).total_seconds()
    if age > float(hcfg["state_max_age_minutes"]) * 60:
        return "the gateway stopped updating its state %d minutes ago" % (
            age // 60)
    if str(state.get("pid")) != str(props.get("MainPID")):
        return "the gateway state file is from another process"
    telegram = (state.get("platforms") or {}).get("telegram")
    if not isinstance(telegram, dict):
        return "the gateway has no Telegram link"
    if telegram.get("state") != "connected":
        return "the gateway's Telegram link is %s" % (
            tg.rec(telegram.get("state")) or "unknown")
    if telegram.get("needs_attention"):
        return "the gateway's Telegram link needs attention"
    return None


def check_dashboard(readers: Readers, connection: sqlite3.Connection,
                    hcfg: Dict[str, Any]) -> Optional[str]:
    unit = hcfg.get("dashboard_unit")
    if not unit:
        return None
    props = readers.show(unit, ["ActiveState", "NRestarts", "LoadState"],
                         True)
    if not props or props.get("LoadState") == "not-found":
        return None  # not installed here, or systemctl gave no answer
    restarts = props.get("NRestarts")
    previous = _meta_get(connection, "health:dashboard_nrestarts")
    if restarts is not None and restarts.isdigit():
        _meta_set(connection, "health:dashboard_nrestarts", restarts)
    active = props.get("ActiveState") or "unknown"
    if active != "active":
        return "the dashboard service is %s" % active
    if (previous is not None and previous.isdigit() and restarts
            and restarts.isdigit() and int(restarts) > int(previous)):
        return "the dashboard service restarted"
    return None


def check_scan(readers: Readers, connection: sqlite3.Connection,
               hcfg: Dict[str, Any]) -> Optional[str]:
    last = _parse(_meta_get(connection, tg.SCAN_HEARTBEAT_KEY))
    if last is None:
        # No scan has completed yet: measure from the first health run, so
        # a fresh deploy is not paged before the scan had a chance.
        first = _meta_get(connection, "health:first_run")
        if first is None:
            _meta_set(connection, "health:first_run",
                      readers.now().isoformat())
            return None
        last = _parse(first)
        if last is None:
            return None
    hours = (readers.now() - last).total_seconds() / 3600
    if hours > float(hcfg["heartbeat_hours"]):
        return "no alert scan has completed for %d hours" % hours
    return None


def _log_times(text: str, match: Callable[[str], bool]
               ) -> Optional[datetime.datetime]:
    newest = None
    for line in text.splitlines():
        if not match(line):
            continue
        found = _LOG_TIME_RE.match(line)
        if not found:
            continue
        try:
            moment = datetime.datetime.strptime(found.group(1),
                                                "%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
        if newest is None or moment > newest:
            newest = moment
    return newest


def check_llm(readers: Readers, connection: sqlite3.Connection,
              hcfg: Dict[str, Any]) -> Optional[str]:
    window = datetime.timedelta(hours=float(hcfg["llm_window_hours"]))
    text = "\n".join(readers.tail(path, int(hcfg["log_tail_bytes"]))
                     for path in hcfg["hermes_logs"])
    last_fail = _log_times(text, lambda line: _AUTH_FAIL in line)
    last_ok = _log_times(text, lambda line: bool(_CALL_OK_RE.search(line)))
    if (last_fail is not None and readers.now_local() - last_fail <= window
            and (last_ok is None or last_fail > last_ok)):
        return "the Claude login has expired"
    since = (readers.now() - window).isoformat()
    rows = connection.execute(
        "SELECT rewrite FROM events WHERE rewrite IS NOT NULL AND "
        "created_at >= ? ORDER BY created_at DESC", (since,)).fetchall()
    notes = [r[0] for r in rows]
    if len(notes) >= 2 and all(
            note.startswith("fallback:")
            and note[len("fallback:"):].split(":", 1)[0] in _LLM_DOWN_REASONS
            for note in notes):
        return "the plain-English rewrite failed %d times in a row" % len(
            notes)
    return None


# ---------------------------------------------------------------------------
# Paging: once per outage, one recovery note
# ---------------------------------------------------------------------------

_WORDS = {
    CHECK_GATEWAY: (
        "The Hermes gateway is down",
        "Atlas chat is not working: %s. Alerts still arrive; chat replies "
        "do not.",
        "on the Pi run %s, then %s" % (
            tg.mono("systemctl --user status hermes-gateway"),
            tg.mono("systemctl --user restart hermes-gateway")),
        "The Hermes gateway is back"),
    CHECK_SCAN: (
        "Atlas alerts are not being checked",
        "Atlas has stopped looking for new events: %s. Chain, repo and "
        "subnet changes are not being paged.",
        "on the Pi run %s" % tg.mono(
            "journalctl -b --user-unit=atlas-alerts.service -n 50"),
        "Atlas alert checks are running again"),
    CHECK_LLM: (
        "Claude is not answering for Atlas",
        "Atlas cannot reach its model: %s. Chat replies and plain-English "
        "rewrites fail; alerts still go out in template form.",
        "log in to Claude again on the Pi",
        "Claude is answering for Atlas again"),
    CHECK_DASHBOARD: (
        "The Atlas LAN board is down",
        "The rotation dashboard is not serving: %s.",
        "on the Pi run %s" % tg.mono(
            "journalctl -b -u atlas-dashboard.service -n 50"),
        "The Atlas LAN board is back"),
}


def _outage_message(check: str, reason: str, since: str) -> "tg.Message":
    headline, meaning, action, _back = _WORDS[check]
    return tg.Message(severity="act", headline=headline,
                      meaning=meaning % tg.rec(reason),
                      facts=[("Since", tg.fmt_time(since))],
                      next_action=action)


def _recovery_message(check: str, since: str) -> "tg.Message":
    _h, _m, _a, back = _WORDS[check]
    return tg.Message(severity="good", headline=back,
                      meaning="Down since %s." % tg.fmt_time(since))


SendFn = Callable[["tg.Message", str, str], bool]


def evaluate(connection: sqlite3.Connection, check: str,
             reason: Optional[str], threshold: int, now: str,
             send: SendFn) -> Optional[str]:
    """Advance one check's outage state. Returns 'paged', 'recovered' or
    None. A send that is not handed over leaves the state to retry."""
    row = connection.execute(
        "SELECT failing_since, consecutive, paged_at FROM health_state "
        "WHERE check_name = ?", (check,)).fetchone()
    if reason is None:
        if row is None:
            return None
        since, _count, paged_at = row
        if paged_at and not send(_recovery_message(check, since), "health",
                                 "health:%s:%s:recovered" % (check, since)):
            return None
        connection.execute("DELETE FROM health_state WHERE check_name = ?",
                           (check,))
        connection.commit()
        return "recovered" if paged_at else None
    if row is None:
        since, count, paged_at = now, 1, None
        connection.execute(
            "INSERT INTO health_state (check_name, failing_since, "
            "consecutive, detail) VALUES (?, ?, 1, ?)", (check, now, reason))
    else:
        since, count, paged_at = row
        count += 1
        connection.execute(
            "UPDATE health_state SET consecutive = ?, detail = ? "
            "WHERE check_name = ?", (count, reason, check))
    connection.commit()
    if paged_at or count < threshold:
        return None
    if send(_outage_message(check, reason, since), "health",
            "health:%s:%s" % (check, since)):
        connection.execute(
            "UPDATE health_state SET paged_at = ? WHERE check_name = ?",
            (now, check))
        connection.commit()
        return "paged"
    return None


# ---------------------------------------------------------------------------
# Unit failures (OnFailure= notifier): one page per unit per streak
# ---------------------------------------------------------------------------

def _inspect_command(unit: str, system: bool) -> str:
    if system:
        return "journalctl -b -u %s -n 50" % unit
    return "journalctl -b --user-unit=%s -n 50" % unit


def record_unit_failure(connection: sqlite3.Connection, unit: str,
                        system: bool, now: str, send: SendFn) -> str:
    """Called by atlas-notify-failure@<unit>. Pages on the first failure of
    a streak; later failures in the same streak only count."""
    row = connection.execute(
        "SELECT since, failures, paged_at FROM unit_failures WHERE unit = ?",
        (unit,)).fetchone()
    if row is None:
        since, failures, paged_at = now, 1, None
        connection.execute(
            "INSERT INTO unit_failures (unit, since, failures, system) "
            "VALUES (?, ?, 1, ?)", (unit, now, 1 if system else 0))
    else:
        since, failures, paged_at = row
        failures += 1
        connection.execute(
            "UPDATE unit_failures SET failures = ? WHERE unit = ?",
            (failures, unit))
    connection.commit()
    if paged_at:
        return "counted"
    msg = tg.Message(
        severity="act",
        headline="Atlas job failed: %s" % tg.rec(unit),
        meaning="The %s run ended with an error. Atlas pages once until it "
                "succeeds again." % tg.mono(unit),
        facts=[("Since", tg.fmt_time(since))],
        next_action="on the Pi run %s" % tg.mono(
            _inspect_command(unit, system)))
    if send(msg, "unit-failure", "unit-failure:%s:%s" % (unit, since)):
        connection.execute(
            "UPDATE unit_failures SET paged_at = ? WHERE unit = ?",
            (now, unit))
        connection.commit()
        return "paged"
    return "unsent"


def close_unit_streaks(connection: sqlite3.Connection,
                       readers: Readers) -> List[str]:
    """End a streak once its unit's last run succeeded. No recovery page:
    the next failure simply pages again."""
    closed = []
    for unit, system in connection.execute(
            "SELECT unit, system FROM unit_failures").fetchall():
        props = readers.show(unit, ["Result", "ActiveState"], bool(system))
        if (props.get("Result") == "success"
                and props.get("ActiveState") != "failed"):
            connection.execute("DELETE FROM unit_failures WHERE unit = ?",
                               (unit,))
            closed.append(unit)
    connection.commit()
    return closed


# ---------------------------------------------------------------------------
# One health run
# ---------------------------------------------------------------------------

def run_health(connection: sqlite3.Connection, config: Dict[str, Any],
               send: SendFn, readers: Optional[Readers] = None
               ) -> Dict[str, Any]:
    readers = readers or Readers()
    hcfg = health_config(config)
    open_health(connection)
    now = readers.now().isoformat()
    summary: Dict[str, Any] = {}
    checks: List[Tuple[str, Callable[..., Optional[str]], int]] = [
        (CHECK_GATEWAY, check_gateway, int(hcfg["gateway_threshold"])),
        (CHECK_SCAN, check_scan, 1),
        (CHECK_LLM, check_llm, 1),
        (CHECK_DASHBOARD, check_dashboard, int(hcfg["gateway_threshold"])),
    ]
    for name, check, threshold in checks:
        try:
            reason = check(readers, connection, hcfg)
        except Exception as exc:  # one broken check never stops the rest
            reason = None
            summary[name] = {"error": tg.redact(str(exc))[:200]}
            continue
        summary[name] = {"reason": reason,
                         "action": evaluate(connection, name, reason,
                                            threshold, now, send)}
    summary["units_closed"] = close_unit_streaks(connection, readers)
    return summary
