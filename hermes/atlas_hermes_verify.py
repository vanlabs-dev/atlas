#!/usr/bin/env python3
"""Atlas Phase 1 Hermes baseline verification.

Read-only verification of a manually installed Hermes against the
ATLAS-HERMES-005 acceptance baseline, driven by the operator's install
record (ATLAS-HERMES-001) and explicit operator attestations for the
interactive checks. Produces per-check verdicts and one fail-closed
overall verdict suitable for the decision log.

Guarantees:
- VERIFY, NOT ASSUME: verdicts come only from observed evidence or a
  recorded operator attestation; missing evidence is an explicit unknown,
  never a pass.
- READ-ONLY: nothing on the device is modified. No service is started,
  stopped, restarted, enabled, or disabled; the only writes are report
  files created 0600 in the (gitignored) output directory.
- FAIL CLOSED: a missing or incomplete install record yields NO verdict;
  any finding, unresolved unknown, or missing attestation yields a
  not-accepted verdict naming every blocker. Documented exceptions must
  live in the install record and are reproduced in the report.
- Same envelope as the inventory: unprivileged, no self-elevation,
  redacted 0600 outputs, per-run audit record.

Usage:
    python3 atlas_hermes_verify.py verify [--install-record PATH]
                                          [--output-dir DIR]
                                          [--attest CHECK]...
                                          [--operator NAME]
    python3 atlas_hermes_verify.py dump-schema

Attestable checks: chat, memory-session-search, tool-call.

Exit codes for `verify`: 0 = accepted, 3 = not-accepted (blockers listed),
4 = no verdict (install record missing/incomplete), 1 = fatal.
"""

from __future__ import annotations

import argparse
import datetime
import getpass
import json
import os
import re
import shlex
import socket
import sys
import time
import secrets as secretsmod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

# --- pinned import surface from the inventory tool (see design decision 1) ---
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO_ROOT, "inventory"))

import atlas_inventory as inv  # noqa: E402

VERIFIER_VERSION = "0.1.0"
VERIFICATION_SCHEMA_VERSION = 1

CHECK_OK = "ok"
CHECK_FINDING = "finding"
CHECK_UNKNOWN = "unknown"
CHECK_DENIED = inv.STATUS_DENIED          # "permission-denied"
CHECK_UNSUPPORTED = inv.STATUS_UNSUPPORTED  # "unsupported-on-device"
ALL_CHECK_STATUSES = (CHECK_OK, CHECK_FINDING, CHECK_UNKNOWN,
                      CHECK_DENIED, CHECK_UNSUPPORTED)

VERDICT_ACCEPTED = "accepted"
VERDICT_NOT_ACCEPTED = "not-accepted"
VERDICT_NONE = "no-verdict"
ALL_VERDICTS = (VERDICT_ACCEPTED, VERDICT_NOT_ACCEPTED, VERDICT_NONE)

# The fixed automated-check list. Omission is structurally impossible: the
# verifier iterates this tuple and the schema requires one entry per check.
CHECKS: Tuple[str, ...] = (
    "install-record",
    "unprivileged-execution",
    "telemetry-disabled",
    "diagnostics",
    "service-persistence",
    "secret-free-logs",
)

# Interactive ATLAS-HERMES-005 checks: performed by the operator in a real
# Hermes session, supplied to the verifier as explicit attestations.
ATTESTATION_CHECKS: Tuple[str, ...] = (
    "chat",
    "memory-session-search",
    "tool-call",
)

# ATLAS-HERMES-001 install record contract.
REQUIRED_RECORD_FIELDS: Tuple[str, ...] = (
    "install_source",
    "installed_version",
    "install_date",
    "update_method",
    "rollback_method",
    "service_user",
    "data_dir",
    "config_path",
)
OPTIONAL_RECORD_FIELDS: Tuple[str, ...] = (
    "diagnostics_command",
    "service_unit",
    "exceptions",
    "notes",
)

SUDO_CAPABLE_GROUPS = frozenset({"sudo", "wheel", "admin"})
MAX_CONFIG_BYTES = 262144
MAX_LOG_BYTES_PER_FILE = 5 * 1024 * 1024
MAX_LOG_FILES = 64
MAX_SECRET_FINDINGS = 50
JOURNAL_LINES = "5000"
_EXCERPT_CHARS = 200

# ---------------------------------------------------------------------------
# Detection patterns
# ---------------------------------------------------------------------------

# Telemetry-shaped configuration keys (config file and .env). The Q11
# decision requires telemetry explicitly OFF; unknown states fail closed.
# no word boundaries: keys like HERMES_ANALYTICS must match through the "_"
_TELEMETRY_KEY = re.compile(
    r"(?i)(telemetry|analytics|crash[_-]?report(?:ing|s)?"
    r"|usage[_-]?stat(?:s|istics)?|tracking|sentry|posthog)")
_DISABLED_VALUES = frozenset(
    {"false", "off", "no", "disabled", "none", "0", "never"})
_ENABLED_VALUES = frozenset({"true", "on", "yes", "enabled", "1", "always"})
_KV_LINE = re.compile(
    r"^\s*(?P<key>[A-Za-z0-9_.\-]+)\s*[:=]\s*(?P<value>.*?)\s*$")

# Credential-shaped material in logs (ATLAS-HERMES-005 "logs do not contain
# secrets"). Detection runs on raw text; report excerpts are always redacted.
# Extended with OAuth shapes for the X OAuth provider decision (Q7).
_SECRET_DETECTORS: Tuple[Tuple[re.Pattern, str], ...] = (
    (re.compile(r"(?i)\b(api[_-]?key|apikey|secret|token|passwd|password"
                r"|credential|authorization)\b\s*[\"']?\s*[:=]\s*[\"']?"
                r"(?P<v>[^\s\"']{8,})"), "credential assignment"),
    (re.compile(r"(?i)\bbearer\s+(?P<v>[A-Za-z0-9._~+/=-]{16,})"),
     "bearer token"),
    (re.compile(r"\b(?P<v>eyJ[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{8,}"
                r"(?:\.[A-Za-z0-9_-]+)?)"), "JWT-shaped token"),
    (re.compile(r"\b(?P<v>xai-[A-Za-z0-9]{16,})"), "xAI API key shape"),
    (re.compile(r"\b(?P<v>sk-[A-Za-z0-9_-]{16,})"), "API key shape (sk-)"),
    (re.compile(r"(?i)\b(access|refresh)[_-]?token\b\s*[\"']?\s*[:=]\s*"
                r"[\"']?(?P<v>[^\s\"']{8,})"), "OAuth token field"),
)

_SYSTEMD_TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}")

# ---------------------------------------------------------------------------
# Verification output schema (embedded source of truth; schema/ file generated)
# ---------------------------------------------------------------------------

_CHECK_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "required": ["check", "status", "summary", "evidence", "findings"],
    "properties": {
        "check": {"enum": list(CHECKS)},
        "status": {"enum": list(ALL_CHECK_STATUSES)},
        "summary": {"type": "string"},
        "evidence": {"type": "array", "items": {"type": "string"}},
        "findings": {"type": "array", "items": {"type": "string"}},
        "guidance": {"type": ["string", "null"]},
        "exception": {"type": ["string", "null"]},
    },
    "additionalProperties": False,
}

_ATTESTATION_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "required": ["check", "attested", "operator", "timestamp"],
    "properties": {
        "check": {"enum": list(ATTESTATION_CHECKS)},
        "attested": {"type": "boolean"},
        "operator": {"type": ["string", "null"]},
        "timestamp": {"type": ["string", "null"]},
    },
    "additionalProperties": False,
}

VERIFICATION_SCHEMA: Dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "atlas-hermes-baseline-verification.v1",
    "title": "Atlas Hermes baseline verification (schema v1)",
    "type": "object",
    "required": ["run", "install_record", "checks", "attestations",
                 "verdict"],
    "properties": {
        "run": {
            "type": "object",
            "required": ["run_id", "verifier_version", "schema_version",
                         "started_at", "finished_at", "executing_account",
                         "hostname"],
            "properties": {
                "run_id": {"type": "string"},
                "verifier_version": {"type": "string"},
                "schema_version": {"enum": [VERIFICATION_SCHEMA_VERSION]},
                "started_at": {"type": "string"},
                "finished_at": {"type": "string"},
                "executing_account": {"type": "string"},
                "hostname": {"type": "string"},
            },
            "additionalProperties": False,
        },
        "install_record": {
            "type": "object",
            "required": ["path", "present", "problems"],
            "properties": {
                "path": {"type": "string"},
                "present": {"type": "boolean"},
                "problems": {"type": "array", "items": {"type": "string"}},
                "record": {"type": ["object", "null"]},
            },
            "additionalProperties": False,
        },
        "checks": {"type": "array", "items": _CHECK_SCHEMA},
        "attestations": {"type": "array", "items": _ATTESTATION_SCHEMA},
        "verdict": {
            "type": "object",
            "required": ["overall", "blockers"],
            "properties": {
                "overall": {"enum": list(ALL_VERDICTS)},
                "blockers": {"type": "array", "items": {"type": "string"}},
            },
            "additionalProperties": False,
        },
    },
    "additionalProperties": False,
}


class FatalVerificationError(Exception):
    """Raised when the verification cannot produce trustworthy output."""


# ---------------------------------------------------------------------------
# Install record (ATLAS-HERMES-001)
# ---------------------------------------------------------------------------


def load_install_record(path: str) -> Tuple[Optional[Dict[str, Any]],
                                            List[str], bool]:
    """Load and validate the operator's install record.

    Returns (record_or_None, problems, present). Any problem means the run
    fails closed to a no-verdict outcome — checks are not even attempted
    against unvalidated input.
    """
    if not os.path.exists(path):
        return None, ["install record not found: %s — copy "
                      "hermes/docs/install-record.template.json and fill in "
                      "every field" % path], False
    try:
        with open(path, "r", encoding="utf-8") as handle:
            raw = handle.read(MAX_CONFIG_BYTES)
        record = json.loads(raw)
    except PermissionError:
        return None, ["install record unreadable (permission denied): %s"
                      % path], True
    except (OSError, ValueError) as exc:
        return None, ["install record invalid: %s: %s" % (path, exc)], True
    if not isinstance(record, dict):
        return None, ["install record must be a JSON object"], True
    problems: List[str] = []
    for field_name in REQUIRED_RECORD_FIELDS:
        value = record.get(field_name)
        if not isinstance(value, str) or not value.strip():
            problems.append("missing or empty required field: %s"
                            % field_name)
        elif value.strip().upper().startswith("TODO"):
            problems.append("required field still a placeholder: %s"
                            % field_name)
    for field_name in ("diagnostics_command", "service_unit", "notes"):
        value = record.get(field_name)
        if value is not None and not isinstance(value, str):
            problems.append("optional field must be a string: %s"
                            % field_name)
    exceptions = record.get("exceptions")
    if exceptions is not None:
        if not isinstance(exceptions, list):
            problems.append("exceptions must be a list")
        else:
            for index, entry in enumerate(exceptions):
                if (not isinstance(entry, dict)
                        or not isinstance(entry.get("check"), str)
                        or not isinstance(entry.get("reason"), str)
                        or not entry.get("reason", "").strip()):
                    problems.append("exceptions[%d] must be "
                                    "{\"check\": ..., \"reason\": ...}"
                                    % index)
                elif entry["check"] not in CHECKS:
                    problems.append("exceptions[%d].check unknown: %s "
                                    "(valid: %s)"
                                    % (index, entry["check"],
                                       ", ".join(CHECKS)))
    unknown = sorted(set(record)
                     - set(REQUIRED_RECORD_FIELDS)
                     - set(OPTIONAL_RECORD_FIELDS))
    if unknown:
        problems.append("unknown fields: %s" % ", ".join(unknown))
    if problems:
        return None, problems, True
    return record, [], True


# ---------------------------------------------------------------------------
# Evidence collection (the ONLY code that touches the device; all read-only)
# ---------------------------------------------------------------------------


def _read_text(path: str, limit: int) -> Dict[str, Any]:
    """Read a file fail-closed: explicit status, never an exception."""
    try:
        size = os.path.getsize(path)
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            text = handle.read(limit)
        return {"status": inv.STATUS_COLLECTED, "path": path, "text": text,
                "truncated": size > limit}
    except FileNotFoundError:
        return {"status": inv.STATUS_UNSUPPORTED, "path": path,
                "error": "no such file"}
    except PermissionError:
        return {"status": inv.STATUS_DENIED, "path": path,
                "error": "permission denied"}
    except OSError as exc:
        return {"status": inv.STATUS_ERROR, "path": path, "error": str(exc)}


def _probe(item_id: str, argv: Tuple[str, ...], timeout: int = 20,
           execute: Optional[Any] = None,
           notes: str = "read-only query") -> Dict[str, Any]:
    probe = inv.Probe(item_id, "hermes_installation", "cmd", argv,
                      parser="lines", timeout=timeout, notes=notes)
    return inv.run_probe(probe, execute)


def _find_log_files(data_dir: str) -> List[str]:
    """Locate log-like files under <data_dir>/logs, capped, never recursing
    outside the recorded data directory."""
    logs_root = os.path.join(data_dir, "logs")
    found: List[str] = []
    if not os.path.isdir(logs_root):
        return found
    for root, _dirs, files in os.walk(logs_root, followlinks=False):
        for name in sorted(files):
            found.append(os.path.join(root, name))
            if len(found) >= MAX_LOG_FILES:
                return found
    return found


def collect_evidence(record: Dict[str, Any],
                     execute: Optional[Any] = None) -> Dict[str, Any]:
    """Gather every observation the checks need. Read-only by construction:
    file reads, `ps`, `systemctl show`, `journalctl`, and the operator's
    recorded diagnostics command are the complete external surface."""
    bundle: Dict[str, Any] = {}
    bundle["config_file"] = _read_text(record["config_path"],
                                       MAX_CONFIG_BYTES)
    bundle["env_file"] = _read_text(os.path.join(record["data_dir"], ".env"),
                                    MAX_CONFIG_BYTES)
    bundle["etc_group"] = _read_text("/etc/group", MAX_CONFIG_BYTES)
    sudoers_paths = ["/etc/sudoers"]
    try:
        sudoers_paths += sorted(
            os.path.join("/etc/sudoers.d", name)
            for name in os.listdir("/etc/sudoers.d"))
    except OSError:
        pass  # directory absent or unlistable; /etc/sudoers read still tells
    bundle["sudoers"] = [_read_text(path, MAX_CONFIG_BYTES)
                         for path in sudoers_paths]
    bundle["processes"] = _probe(
        "hermes_processes", ("ps", "-eo", "user:32,pid,args", "--no-headers"),
        execute=execute, notes="process list; read-only")
    unit = record.get("service_unit")
    if unit:
        # "user:<unit>" marks a `systemd --user` unit; only inspectable when
        # the verifier runs as that user (documented in hermes/README.md)
        scope = ("--user",) if unit.startswith("user:") else ()
        unit_name = unit.split(":", 1)[1] if unit.startswith("user:") else unit
        bundle["unit_show"] = _probe(
            "hermes_unit_show",
            ("systemctl",) + scope + ("show", unit_name, "--no-pager",
             "-p", "LoadState", "-p", "UnitFileState", "-p", "ActiveState",
             "-p", "SubState", "-p", "User", "-p", "ExecMainStartTimestamp"),
            execute=execute,
            notes="'show' prints unit properties; read-only. Separate -p "
                  "flags: comma lists print nothing on some systemd "
                  "versions (observed on the Pi, Debian 13)")
        bundle["journal"] = _probe(
            "hermes_journal",
            ("journalctl",) + scope + ("-u", unit_name, "-n", JOURNAL_LINES,
             "--no-pager", "-q"),
            timeout=60, execute=execute,
            notes="journal read; may need the systemd-journal group")
    else:
        bundle["unit_show"] = None
        bundle["journal"] = None
    diagnostics_command = record.get("diagnostics_command")
    if diagnostics_command:
        try:
            argv = tuple(shlex.split(diagnostics_command))
        except ValueError as exc:
            bundle["diagnostics"] = {"status": inv.STATUS_ERROR,
                                     "error": "unparsable diagnostics "
                                              "command: %s" % exc}
            argv = ()
        if argv:
            bundle["diagnostics"] = _probe(
                "hermes_diagnostics", argv, timeout=120, execute=execute,
                notes="operator-recorded official diagnostics; the operator "
                      "asserts it is read-only when recording it")
    else:
        bundle["diagnostics"] = None
    log_reads: List[Dict[str, Any]] = []
    for path in _find_log_files(record["data_dir"]):
        log_reads.append(_read_text(path, MAX_LOG_BYTES_PER_FILE))
    bundle["log_files"] = log_reads
    return bundle


# ---------------------------------------------------------------------------
# Check model
# ---------------------------------------------------------------------------


@dataclass
class CheckResult:
    check: str
    status: str
    summary: str
    evidence: List[str] = field(default_factory=list)
    findings: List[str] = field(default_factory=list)
    guidance: Optional[str] = None
    exception: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "check": self.check,
            "status": self.status,
            "summary": inv.redact(self.summary),
            "evidence": [inv.redact(item) for item in self.evidence],
            "findings": [inv.redact(item) for item in self.findings],
            "guidance": inv.redact(self.guidance) if self.guidance else None,
            "exception": self.exception,
        }


def _resolve(check: str, findings: List[str], denied: List[str],
             unknowns: List[str], ok_summary: str,
             evidence: List[str]) -> CheckResult:
    """Shared fail-closed status resolution: findings dominate, then denied
    evidence, then indeterminate state; ok only when everything observed."""
    if findings:
        return CheckResult(check, CHECK_FINDING,
                           "%d finding(s)" % len(findings),
                           evidence, findings)
    if denied:
        return CheckResult(check, CHECK_DENIED,
                           "insufficient privilege for: %s"
                           % "; ".join(denied), evidence,
                           guidance="re-run under sudo per the operational "
                                    "note in docs/decisions.md, or record a "
                                    "documented exception")
    if unknowns:
        return CheckResult(check, CHECK_UNKNOWN,
                           "; ".join(unknowns), evidence,
                           guidance="resolve the unknown state or record a "
                                    "documented exception in the install "
                                    "record")
    return CheckResult(check, CHECK_OK, ok_summary, evidence)


# ---------------------------------------------------------------------------
# Checks (pure evaluators over the collected evidence)
# ---------------------------------------------------------------------------


def check_install_record(record: Dict[str, Any],
                         record_path: str) -> CheckResult:
    evidence = ["%s: %s" % (name, record[name])
                for name in REQUIRED_RECORD_FIELDS]
    for name in ("diagnostics_command", "service_unit"):
        evidence.append("%s: %s" % (name, record.get(name) or "(not set)"))
    for entry in record.get("exceptions") or []:
        evidence.append("exception[%s]: %s"
                        % (entry["check"], entry["reason"]))
    return CheckResult("install-record", CHECK_OK,
                       "all %d ATLAS-HERMES-001 fields recorded at %s"
                       % (len(REQUIRED_RECORD_FIELDS), record_path),
                       evidence)


def _parse_group_members(text: str) -> Dict[str, List[str]]:
    groups: Dict[str, List[str]] = {}
    for line in text.splitlines():
        parts = line.strip().split(":")
        if len(parts) >= 4:
            members = [m for m in parts[3].split(",") if m]
            groups[parts[0]] = members
    return groups


def check_unprivileged_execution(record: Dict[str, Any],
                                 bundle: Dict[str, Any]) -> CheckResult:
    user = record["service_user"]
    findings: List[str] = []
    denied: List[str] = []
    unknowns: List[str] = []
    evidence: List[str] = []
    if user == "root":
        findings.append("service_user is root (ATLAS-HERMES-002 forbids)")
    group_item = bundle["etc_group"]
    user_sudo_groups: List[str] = []
    if group_item["status"] == inv.STATUS_COLLECTED:
        groups = _parse_group_members(group_item["text"])
        for group_name in sorted(SUDO_CAPABLE_GROUPS):
            if user in groups.get(group_name, []):
                user_sudo_groups.append(group_name)
                findings.append(
                    "%s holds general sudo rights via group '%s' "
                    "(ATLAS-HERMES-002: no general sudo in normal operation)"
                    % (user, group_name))
        evidence.append("/etc/group: %s member of sudo-capable groups: %s"
                        % (user, ", ".join(user_sudo_groups) or "none"))
    elif group_item["status"] == inv.STATUS_DENIED:
        denied.append("/etc/group")
    else:
        unknowns.append("/etc/group not readable: %s"
                        % group_item.get("error", "unknown"))
    for sudo_item in bundle["sudoers"]:
        if sudo_item["status"] == inv.STATUS_DENIED:
            denied.append(sudo_item["path"])
        elif sudo_item["status"] == inv.STATUS_COLLECTED:
            for line in sudo_item["text"].splitlines():
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                first = stripped.split()[0]
                if first == user or first in ("%" + g
                                              for g in user_sudo_groups):
                    findings.append("sudoers grant in %s applies to %s: %s"
                                    % (sudo_item["path"], user, stripped))
    processes = bundle["processes"]
    if processes["status"] == inv.STATUS_COLLECTED:
        lines = (processes.get("data") or {}).get("text_lines") or []
        hermes_lines = [line for line in lines
                        if "hermes" in line.lower()
                        and "atlas_hermes_verify" not in line]
        if hermes_lines:
            for line in hermes_lines:
                owner = line.split()[0] if line.split() else "?"
                evidence.append("process: %s" % line.strip()[:160])
                if owner == "root":
                    findings.append("hermes process running as root: %s"
                                    % line.strip()[:160])
                elif owner != user:
                    findings.append("hermes process runs as '%s' but the "
                                    "install record says '%s'"
                                    % (owner, user))
        else:
            evidence.append("no hermes process observed at verification "
                            "time (service state is covered by the "
                            "service-persistence check)")
    elif processes["status"] == inv.STATUS_DENIED:
        denied.append("process list")
    else:
        unknowns.append("process list unavailable: %s"
                        % processes.get("error", "unknown"))
    unit_show = bundle.get("unit_show")
    if unit_show and unit_show["status"] == inv.STATUS_COLLECTED:
        props = _unit_props(unit_show)
        unit_user = props.get("User", "")
        user_scoped = str(record.get("service_unit", "")).startswith("user:")
        if unit_user:
            evidence.append("unit User=%s" % unit_user)
            if unit_user != user:
                findings.append("service unit runs as '%s' but the install "
                                "record says '%s'" % (unit_user, user))
        elif props.get("LoadState") == "loaded" and not user_scoped:
            findings.append("service unit sets no User= (systemd system "
                            "units default to root)")
    return _resolve("unprivileged-execution", findings, denied, unknowns,
                    "%s is unprivileged with no sudo rights found" % user,
                    evidence)


def _classify_value(raw_value: str) -> Optional[bool]:
    """True = telemetry enabled, False = disabled, None = indeterminate."""
    value = raw_value.split("#", 1)[0].strip().strip("\"'").lower()
    if value in _DISABLED_VALUES:
        return False
    if value in _ENABLED_VALUES:
        return True
    return None


def _scan_telemetry(text: str, origin: str,
                    enabled: List[str], disabled: List[str],
                    indeterminate: List[str]) -> None:
    for number, line in enumerate(text.splitlines(), 1):
        match = _KV_LINE.match(line)
        if not match or not _TELEMETRY_KEY.search(match.group("key")):
            continue
        verdict = _classify_value(match.group("value"))
        location = "%s:%d %s" % (origin, number, match.group("key"))
        if verdict is False:
            disabled.append(location)
        elif verdict is True:
            enabled.append(location)
        else:
            indeterminate.append(location)


def check_telemetry_disabled(record: Dict[str, Any],
                             bundle: Dict[str, Any]) -> CheckResult:
    findings: List[str] = []
    denied: List[str] = []
    unknowns: List[str] = []
    evidence: List[str] = []
    enabled: List[str] = []
    disabled: List[str] = []
    indeterminate: List[str] = []
    config = bundle["config_file"]
    if config["status"] == inv.STATUS_COLLECTED:
        _scan_telemetry(config["text"], config["path"],
                        enabled, disabled, indeterminate)
    elif config["status"] == inv.STATUS_DENIED:
        denied.append(config["path"])
    else:
        findings.append("recorded config_path does not exist: %s — the "
                        "install record is inaccurate" % config["path"])
    env_file = bundle["env_file"]
    if env_file["status"] == inv.STATUS_COLLECTED:
        _scan_telemetry(env_file["text"], env_file["path"],
                        enabled, disabled, indeterminate)
    elif env_file["status"] == inv.STATUS_DENIED:
        denied.append(env_file["path"])
    # an absent .env is fine; telemetry evidence then rests on the config
    for location in enabled:
        findings.append("telemetry-shaped setting is ENABLED: %s (Q11 "
                        "decision: all telemetry off)" % location)
    for location in indeterminate:
        unknowns.append("telemetry-shaped setting has an indeterminate "
                        "value: %s" % location)
    evidence += ["telemetry setting disabled: %s" % loc for loc in disabled]
    if (not findings and not denied and not unknowns and not disabled):
        unknowns.append(
            "no telemetry-shaped setting found in %s — cannot confirm the "
            "Q11 decision" % config["path"])
        return _resolve("telemetry-disabled", findings, denied, unknowns,
                        "", evidence)
    return _resolve("telemetry-disabled", findings, denied, unknowns,
                    "telemetry explicitly disabled (%d setting(s))"
                    % len(disabled), evidence)


def check_diagnostics(record: Dict[str, Any],
                      bundle: Dict[str, Any]) -> CheckResult:
    diagnostics = bundle["diagnostics"]
    if diagnostics is None:
        return CheckResult(
            "diagnostics", CHECK_UNSUPPORTED,
            "no diagnostics_command recorded",
            guidance="record the official Hermes diagnostics command in the "
                     "install record if one exists, or record an exception "
                     "documenting that this Hermes version ships none")
    if diagnostics["status"] == inv.STATUS_COLLECTED:
        lines = (diagnostics.get("data") or {}).get("text_lines") or []
        tail = lines[-10:]
        return CheckResult("diagnostics", CHECK_OK,
                           "diagnostics command exited 0",
                           ["diagnostics output (tail): %s" % line
                            for line in tail])
    if diagnostics["status"] == inv.STATUS_DENIED:
        return _resolve("diagnostics", [], ["diagnostics command"], [],
                        "", [])
    return CheckResult(
        "diagnostics", CHECK_FINDING, "diagnostics did not pass",
        findings=["diagnostics command failed: %s"
                  % diagnostics.get("error", "unknown error")],
        guidance="fix the failure, or record a documented exception naming "
                 "the failing item")


def _unit_props(unit_show: Dict[str, Any]) -> Dict[str, str]:
    lines = (unit_show.get("data") or {}).get("text_lines") or []
    props: Dict[str, str] = {}
    for line in lines:
        if "=" in line:
            key, _, value = line.partition("=")
            props[key.strip()] = value.strip()
    return props


def check_service_persistence(record: Dict[str, Any],
                              bundle: Dict[str, Any]) -> CheckResult:
    unit_show = bundle.get("unit_show")
    if unit_show is None:
        return CheckResult(
            "service-persistence", CHECK_UNSUPPORTED,
            "no service_unit recorded — boot persistence and restart "
            "behavior cannot be evidenced",
            guidance="create a service unit for Hermes and record it, or "
                     "record an exception documenting how Hermes is kept "
                     "running and why no unit exists")
    if unit_show["status"] == inv.STATUS_DENIED:
        return _resolve("service-persistence", [], ["systemctl show"], [],
                        "", [])
    if unit_show["status"] != inv.STATUS_COLLECTED:
        return _resolve("service-persistence", [], [],
                        ["systemctl unavailable: %s"
                         % unit_show.get("error", "unknown")], "", [])
    props = _unit_props(unit_show)
    unit = record["service_unit"]
    findings: List[str] = []
    unknowns: List[str] = []
    evidence = ["%s %s=%s" % (unit, key, props.get(key, ""))
                for key in ("LoadState", "UnitFileState", "ActiveState",
                            "SubState", "ExecMainStartTimestamp")]
    if props.get("LoadState") != "loaded":
        findings.append("recorded service_unit '%s' is not loaded "
                        "(LoadState=%s) — the install record is inaccurate"
                        % (unit, props.get("LoadState", "?")))
        return _resolve("service-persistence", findings, [], [], "",
                        evidence)
    if props.get("UnitFileState") not in ("enabled", "enabled-runtime",
                                          "static"):
        findings.append("unit is not enabled at boot (UnitFileState=%s)"
                        % props.get("UnitFileState", "?"))
    if props.get("ActiveState") != "active":
        findings.append("unit is not active (ActiveState=%s)"
                        % props.get("ActiveState", "?"))
    timestamp_match = _SYSTEMD_TIMESTAMP.search(
        props.get("ExecMainStartTimestamp", ""))
    if timestamp_match:
        started = timestamp_match.group(0)
        evidence.append("main process started %s (install date %s)"
                        % (started, record["install_date"]))
        if started[:10] < record["install_date"][:10]:
            unknowns.append("service start predates the recorded install "
                            "date — evidence inconsistent")
    elif not findings:
        unknowns.append("no readable start timestamp — cannot evidence the "
                        "operator's post-install restart")
    return _resolve("service-persistence", findings, [], unknowns,
                    "unit loaded, enabled, active; restart evidenced by "
                    "start timestamp", evidence)


def _redacted_excerpt(line: str, span: Tuple[int, int]) -> str:
    excerpt = line[:span[0]] + inv.REDACTION_MARKER + line[span[1]:]
    return inv.redact(excerpt.strip())[:_EXCERPT_CHARS]


def _scan_for_secrets(text: str, origin: str,
                      findings: List[str]) -> None:
    for number, line in enumerate(text.splitlines(), 1):
        if len(findings) >= MAX_SECRET_FINDINGS:
            findings.append("further matches suppressed after %d findings"
                            % MAX_SECRET_FINDINGS)
            return
        for pattern, label in _SECRET_DETECTORS:
            match = pattern.search(line)
            if match:
                span = (match.start("v"), match.end("v")) \
                    if "v" in (pattern.groupindex or {}) else match.span()
                findings.append("%s:%d: %s — %s"
                                % (origin, number, label,
                                   _redacted_excerpt(line, span)))
                break  # one finding per line is enough evidence


def check_secret_free_logs(record: Dict[str, Any],
                           bundle: Dict[str, Any]) -> CheckResult:
    findings: List[str] = []
    denied: List[str] = []
    unknowns: List[str] = []
    evidence: List[str] = []
    scanned = 0
    for item in bundle["log_files"]:
        if item["status"] == inv.STATUS_COLLECTED:
            scanned += 1
            _scan_for_secrets(item["text"], item["path"], findings)
            if item.get("truncated"):
                evidence.append("%s scanned to the %d-byte cap only"
                                % (item["path"], MAX_LOG_BYTES_PER_FILE))
        elif item["status"] == inv.STATUS_DENIED:
            denied.append(item["path"])
    journal = bundle.get("journal")
    if journal is not None:
        if journal["status"] == inv.STATUS_COLLECTED:
            lines = (journal.get("data") or {}).get("text_lines") or []
            _scan_for_secrets("\n".join(lines),
                              "journal:%s" % record.get("service_unit"),
                              findings)
            scanned += 1
        elif journal["status"] == inv.STATUS_DENIED:
            denied.append("journal (journalctl -u %s)"
                          % record.get("service_unit"))
    if scanned == 0 and not denied:
        unknowns.append("no readable logs found under %s/logs — confirm "
                        "the log location before accepting"
                        % record["data_dir"])
    evidence.insert(0, "scanned %d log source(s) for credential-shaped "
                       "material" % scanned)
    return _resolve("secret-free-logs", findings, denied, unknowns,
                    "no credential-shaped material in %d log source(s)"
                    % scanned, evidence)


def run_checks(record: Dict[str, Any], record_path: str,
               bundle: Dict[str, Any]) -> List[CheckResult]:
    results = [
        check_install_record(record, record_path),
        check_unprivileged_execution(record, bundle),
        check_telemetry_disabled(record, bundle),
        check_diagnostics(record, bundle),
        check_service_persistence(record, bundle),
        check_secret_free_logs(record, bundle),
    ]
    exceptions = {entry["check"]: entry["reason"]
                  for entry in record.get("exceptions") or []}
    for result in results:
        if result.status != CHECK_OK and result.check in exceptions:
            result.exception = exceptions[result.check]
    return results


# ---------------------------------------------------------------------------
# Attestations and verdict
# ---------------------------------------------------------------------------


def build_attestations(attested: List[str], operator: str,
                       timestamp: str) -> List[Dict[str, Any]]:
    supplied = set(attested)
    unknown = supplied - set(ATTESTATION_CHECKS)
    if unknown:
        raise FatalVerificationError(
            "unknown attestation(s): %s (valid: %s)"
            % (", ".join(sorted(unknown)), ", ".join(ATTESTATION_CHECKS)))
    return [{"check": check,
             "attested": check in supplied,
             "operator": operator if check in supplied else None,
             "timestamp": timestamp if check in supplied else None}
            for check in ATTESTATION_CHECKS]


def compute_verdict(results: List[CheckResult],
                    attestations: List[Dict[str, Any]]
                    ) -> Tuple[str, List[str]]:
    """Fail-closed: accepted only when every automated check is ok or
    carries a documented exception, and every interactive check is
    attested. Everything else blocks, by name."""
    blockers: List[str] = []
    for result in results:
        if result.status == CHECK_OK:
            continue
        if result.exception:
            continue  # documented exception, reproduced in the report
        blockers.append("check '%s' is %s: %s"
                        % (result.check, result.status, result.summary))
    for attestation in attestations:
        if not attestation["attested"]:
            blockers.append("interactive check '%s' is not attested "
                            "(pass --attest %s after performing it)"
                            % (attestation["check"], attestation["check"]))
    return (VERDICT_ACCEPTED if not blockers else VERDICT_NOT_ACCEPTED,
            blockers)


# ---------------------------------------------------------------------------
# Report assembly and rendering
# ---------------------------------------------------------------------------


def _utc_now() -> str:
    return datetime.datetime.now(tz=datetime.timezone.utc).isoformat()


def _account() -> str:
    try:
        return getpass.getuser()
    except (KeyError, OSError):
        return "uid:%s" % os.getuid() if hasattr(os, "getuid") else "unknown"


def _redact_tree(value: Any) -> Any:
    if isinstance(value, str):
        return inv.redact(value)
    if isinstance(value, list):
        return [_redact_tree(item) for item in value]
    if isinstance(value, dict):
        return {key: _redact_tree(item) for key, item in value.items()}
    return value


def _write_private(path: str, content: str) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(content)


def build_verification(record: Optional[Dict[str, Any]], record_path: str,
                       record_present: bool, problems: List[str],
                       results: List[CheckResult],
                       attestations: List[Dict[str, Any]],
                       overall: str, blockers: List[str],
                       run_id: str, started_at: str) -> Dict[str, Any]:
    return {
        "run": {
            "run_id": run_id,
            "verifier_version": VERIFIER_VERSION,
            "schema_version": VERIFICATION_SCHEMA_VERSION,
            "started_at": started_at,
            "finished_at": _utc_now(),
            "executing_account": _account(),
            "hostname": socket.gethostname(),
        },
        "install_record": {
            "path": record_path,
            "present": record_present,
            "problems": [inv.redact(problem) for problem in problems],
            "record": _redact_tree(record) if record else None,
        },
        "checks": [result.as_dict() for result in results],
        "attestations": attestations,
        "verdict": {"overall": overall, "blockers":
                    [inv.redact(blocker) for blocker in blockers]},
    }


def render_summary(verification: Dict[str, Any]) -> str:
    run = verification["run"]
    verdict = verification["verdict"]
    lines = [
        "# Hermes baseline verification %s" % run["run_id"],
        "",
        "- **Verdict:** %s" % verdict["overall"],
        "- Verifier %s, schema v%s, run as `%s` on `%s`, finished %s"
        % (run["verifier_version"], run["schema_version"],
           run["executing_account"], run["hostname"], run["finished_at"]),
        "- Install record: `%s`%s"
        % (verification["install_record"]["path"],
           "" if verification["install_record"]["present"]
           else " (MISSING)"),
        "",
    ]
    if verification["install_record"]["problems"]:
        lines += ["## Install record problems (no verdict issued)", ""]
        lines += ["- %s" % problem
                  for problem in verification["install_record"]["problems"]]
        lines.append("")
    if verdict["blockers"]:
        lines += ["## Blockers", ""]
        lines += ["- %s" % blocker for blocker in verdict["blockers"]]
        lines.append("")
    if verification["checks"]:
        lines += ["## Checks", "",
                  "| check | status | summary |",
                  "|---|---|---|"]
        for check in verification["checks"]:
            summary = check["summary"]
            if check["exception"]:
                summary += " — EXCEPTION: %s" % check["exception"]
            lines.append("| %s | %s | %s |"
                         % (check["check"], check["status"],
                            summary.replace("|", "\\|")))
        lines.append("")
        for check in verification["checks"]:
            if check["findings"]:
                lines += ["### Findings: %s" % check["check"], ""]
                lines += ["- %s" % finding for finding in check["findings"]]
                lines.append("")
    lines += ["## Attestations", ""]
    for attestation in verification["attestations"]:
        if attestation["attested"]:
            lines.append("- %s: attested by `%s` at %s"
                         % (attestation["check"], attestation["operator"],
                            attestation["timestamp"]))
        else:
            lines.append("- %s: NOT attested" % attestation["check"])
    lines += ["",
              "_For docs/decisions.md: record the verdict, run id, and the "
              "install-record summary once accepted._", ""]
    return "\n".join(lines)


def build_audit(run_id: str, started_at: str, outputs: List[str],
                overall: Optional[str], blocker_count: Optional[int],
                fatal: Optional[str]) -> Dict[str, Any]:
    return {
        "run_id": run_id,
        "started_at": started_at,
        "finished_at": _utc_now(),
        "verifier_version": VERIFIER_VERSION,
        "schema_version": VERIFICATION_SCHEMA_VERSION,
        "executing_account": _account(),
        "outputs": outputs,
        "verdict": overall,
        "blocker_count": blocker_count,
        "fatal": inv.redact(fatal) if fatal else None,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def cmd_verify(record_path: str, output_dir: str, attested: List[str],
               operator: Optional[str],
               execute: Optional[Any] = None,
               collect: Any = collect_evidence) -> int:
    os.makedirs(output_dir, exist_ok=True)
    started_at = _utc_now()
    run_id = (time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
              + "-" + secretsmod.token_hex(4))
    outputs: List[str] = []
    overall: Optional[str] = None
    blockers: List[str] = []
    fatal: Optional[str] = None
    try:
        attestations = build_attestations(attested, operator or _account(),
                                          started_at)
        record, problems, present = load_install_record(record_path)
        if record is None:
            overall = VERDICT_NONE
            blockers = list(problems)
            results: List[CheckResult] = []
        else:
            bundle = collect(record, execute)
            results = run_checks(record, record_path, bundle)
            overall, blockers = compute_verdict(results, attestations)
        verification = build_verification(record, record_path, present,
                                          problems, results, attestations,
                                          overall, blockers, run_id,
                                          started_at)
        validation_errors = inv.schema_validate(verification,
                                                VERIFICATION_SCHEMA)
        if validation_errors:
            fatal = ("verification failed schema validation: "
                     + "; ".join(validation_errors[:20]))
            print("FATAL: %s" % fatal, file=sys.stderr)
            return 1
        verification_path = os.path.join(output_dir,
                                         "verification-%s.json" % run_id)
        _write_private(verification_path,
                       json.dumps(verification, indent=2, sort_keys=True))
        outputs.append(verification_path)
        summary_path = os.path.join(output_dir, "summary-%s.md" % run_id)
        _write_private(summary_path, render_summary(verification))
        outputs.append(summary_path)
        print("Verification %s verdict: %s" % (run_id, overall))
        for blocker in blockers:
            print("  blocker: %s" % inv.redact(blocker))
        print("Report:  %s" % verification_path)
        print("Summary: %s" % summary_path)
        if overall == VERDICT_ACCEPTED:
            return 0
        return 4 if overall == VERDICT_NONE else 3
    except FatalVerificationError as exc:
        fatal = str(exc)
        print("FATAL: %s" % inv.redact(fatal), file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 — fail visibly, audit the failure
        fatal = "unhandled failure: %s" % exc
        print("FATAL: %s" % inv.redact(str(exc)), file=sys.stderr)
        return 1
    finally:
        try:
            audit = build_audit(run_id, started_at, outputs, overall,
                                len(blockers) if overall else None, fatal)
            audit_path = os.path.join(output_dir, "audit-%s.json" % run_id)
            _write_private(audit_path,
                           json.dumps(audit, indent=2, sort_keys=True))
            print("Audit:   %s" % audit_path)
        except Exception as audit_exc:  # noqa: BLE001
            print("WARNING: audit record could not be written: %s"
                  % audit_exc, file=sys.stderr)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="atlas_hermes_verify",
        description="Read-only Hermes baseline verification "
                    "(ATLAS-HERMES-001/002/005). Verifies, never assumes; "
                    "observes, never mutates.")
    subparsers = parser.add_subparsers(dest="subcommand", required=True)
    verify_parser = subparsers.add_parser(
        "verify", help="run the post-install baseline verification")
    verify_parser.add_argument(
        "--install-record",
        default=os.path.join("var", "hermes", "install-record.json"),
        help="path to the operator's install record JSON")
    verify_parser.add_argument("--output-dir",
                               default=os.path.join("var", "hermes"))
    verify_parser.add_argument(
        "--attest", action="append", default=[], metavar="CHECK",
        help="attest an interactive check you performed: %s (repeatable)"
             % ", ".join(ATTESTATION_CHECKS))
    verify_parser.add_argument(
        "--operator", default=None,
        help="name recorded on attestations (default: invoking user)")
    subparsers.add_parser("dump-schema",
                          help="print the verification JSON schema")
    args = parser.parse_args(argv)
    if args.subcommand == "verify":
        return cmd_verify(args.install_record, args.output_dir,
                          args.attest, args.operator)
    if args.subcommand == "dump-schema":
        print(json.dumps(VERIFICATION_SCHEMA, indent=2))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
