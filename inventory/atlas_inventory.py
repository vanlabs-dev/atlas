#!/usr/bin/env python3
"""Atlas Phase 0 device inventory collector.

Read-only inventory of a Linux (Raspberry Pi) device, per Atlas PRD
requirement ATLAS-ENV-001 and OpenSpec change `atlas-phase-0-device-inventory`.

Guarantees (enforced by design, reviewed in docs/probe-review.md):

- READ-ONLY: no probe installs, removes, upgrades, stops, starts, restarts,
  enables, disables, reconfigures, or deletes anything on the device.
- NO EXECUTION OF DISCOVERED SOFTWARE: found binaries (including Hermes) are
  stat'ed, never run. No command line is ever built from collected data;
  paths discovered at runtime are only passed to os.stat()/os.lstat() syscalls.
- REDACTION: all captured command/file output passes redact() before being
  stored anywhere. Secret-bearing files are never read at all (stat only).
- NO SELF-ELEVATION: the script never invokes sudo or acquires privileges.
  Items needing more privilege are reported with status "permission-denied".
- EXPLICIT UNKNOWNS: every inventory item carries a status of
  collected | unsupported-on-device | permission-denied | error.

Single-file, standard-library-only (Python 3.9+) so it can be transferred to
the target device by pasting its text into a new file over SSH.

Usage:
    python3 atlas_inventory.py run [--output-dir DIR]
    python3 atlas_inventory.py worksheet REPORT_JSON [--output-dir DIR]
    python3 atlas_inventory.py dump-schema

Exit codes for `run`: 0 = complete collection, 3 = partial collection
(some permission-denied/error items), 1 = fatal error.
"""

from __future__ import annotations

import argparse
import datetime
import getpass
import glob as globmod
import json
import os
import re
import secrets as secretsmod
import shutil
import socket
import stat as statmod
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

SCRIPT_VERSION = "0.1.0"
SCHEMA_VERSION = 1
REDACTION_MARKER = "[REDACTED]"
MAX_CAPTURE_CHARS = 262144  # per probe; larger output is truncated with a warning
MAX_READ_FILES = 32  # per read-glob probe
MAX_READ_BYTES = 65536  # per file read by a read probe

STATUS_COLLECTED = "collected"
STATUS_UNSUPPORTED = "unsupported-on-device"
STATUS_DENIED = "permission-denied"
STATUS_ERROR = "error"
ALL_STATUSES = (STATUS_COLLECTED, STATUS_UNSUPPORTED, STATUS_DENIED, STATUS_ERROR)

# ---------------------------------------------------------------------------
# Redaction filter (single mandatory choke point for all captured output)
# ---------------------------------------------------------------------------

_SECRET_NAME = (
    r"(?:api[_-]?key|apikey|secret|token|passwd|password|pwd|credential[s]?"
    r"|auth(?:orization)?|bearer|private[_-]?key|access[_-]?key|seed(?:[_-]?phrase)?"
    r"|mnemonic|session[_-]?id|cookie)"
)

_REDACTION_RULES: List[Tuple[re.Pattern, str]] = [
    # PEM blocks (private keys, certificates — over-redaction is safe)
    (
        re.compile(r"-----BEGIN [A-Z0-9 ]+-----.*?-----END [A-Z0-9 ]+-----", re.S),
        REDACTION_MARKER,
    ),
    # Authorization headers / Bearer / Basic tokens
    (
        re.compile(r"(?i)\b(authorization\s*[:=]\s*)(\S.*)$", re.M),
        r"\1" + REDACTION_MARKER,
    ),
    (
        re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9+/=._~-]{8,}"),
        r"\1 " + REDACTION_MARKER,
    ),
    # name=value / name: value where the name looks secret-bearing
    (
        re.compile(
            r"(?i)\b([A-Za-z0-9_.-]*" + _SECRET_NAME + r"[A-Za-z0-9_.-]*)"
            r"(\s*[=:]\s*)([^\s'\"]+|'[^']*'|\"[^\"]*\")"
        ),
        r"\1\2" + REDACTION_MARKER,
    ),
    # CLI flags with a space-separated value: --password hunter2, -p hunter2 is
    # too ambiguous; restrict to explicit long flags.
    (
        re.compile(
            r"(?i)(--?(?:password|passwd|pwd|token|secret|api-?key|auth)) +(\S+)"
        ),
        r"\1 " + REDACTION_MARKER,
    ),
    # URL credentials: scheme://user:pass@host
    (
        re.compile(r"(://[^/\s:@]+):([^@\s/]+)@"),
        r"\1:" + REDACTION_MARKER + "@",
    ),
    # JWTs
    (
        re.compile(r"\beyJ[A-Za-z0-9_-]{4,}\.eyJ[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{4,}\b"),
        REDACTION_MARKER,
    ),
    # Well-known API key formats
    (re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"), REDACTION_MARKER),
    (re.compile(r"\bghp_[A-Za-z0-9]{20,}\b"), REDACTION_MARKER),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"), REDACTION_MARKER),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), REDACTION_MARKER),
    (re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b"), REDACTION_MARKER),
    (re.compile(r"\bAIza[0-9A-Za-z_-]{30,}"), REDACTION_MARKER),
]


def redact(text: str) -> str:
    """Redact secret-looking material from *text*.

    Applied to every piece of captured output before it is persisted or
    displayed. Over-redaction is acceptable; under-redaction is not.
    """
    for pattern, replacement in _REDACTION_RULES:
        text = pattern.sub(replacement, text)
    return text


def _decode(raw: bytes) -> str:
    return raw.decode("utf-8", errors="replace")


# ---------------------------------------------------------------------------
# Report schema (embedded source of truth; schema/ file is generated from it)
# ---------------------------------------------------------------------------

CATEGORIES: Tuple[str, ...] = (
    "hardware",
    "cpu_memory_storage",
    "os_kernel",
    "users_and_service_accounts",
    "packages",
    "containers",
    "systemd_services",
    "listening_ports",
    "scheduled_jobs",
    "hermes_installation",
    "repositories_and_app_dirs",
    "secret_file_locations",
    "backup_configuration",
    "firewall",
    "remote_access",
    "device_health",
)

_ENVELOPE_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "required": ["status", "command"],
    "properties": {
        "status": {"enum": list(ALL_STATUSES)},
        "command": {"type": "string"},
        "data": {},
        "error": {"type": ["string", "null"]},
        "duration_ms": {"type": "number"},
        "warnings": {"type": "array", "items": {"type": "string"}},
    },
    "additionalProperties": False,
}

_CATEGORY_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "required": ["items"],
    "properties": {
        "items": {"type": "object", "additionalProperties": _ENVELOPE_SCHEMA}
    },
    "additionalProperties": False,
}

REPORT_SCHEMA: Dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "atlas-inventory-report.v1",
    "title": "Atlas device inventory report (schema v1)",
    "type": "object",
    "required": ["run", "categories"],
    "properties": {
        "run": {
            "type": "object",
            "required": [
                "run_id",
                "script_version",
                "schema_version",
                "started_at",
                "finished_at",
                "executing_account",
                "hostname",
                "privileged",
                "complete",
            ],
            "properties": {
                "run_id": {"type": "string"},
                "script_version": {"type": "string"},
                "schema_version": {"enum": [SCHEMA_VERSION]},
                "started_at": {"type": "string"},
                "finished_at": {"type": "string"},
                "executing_account": {"type": "string"},
                "hostname": {"type": "string"},
                "privileged": {"type": "boolean"},
                "complete": {"type": "boolean"},
            },
            "additionalProperties": False,
        },
        "categories": {
            "type": "object",
            "required": list(CATEGORIES),
            "properties": {name: _CATEGORY_SCHEMA for name in CATEGORIES},
            "additionalProperties": False,
        },
    },
    "additionalProperties": False,
}


def _type_ok(value: Any, type_name: str) -> bool:
    if type_name == "object":
        return isinstance(value, dict)
    if type_name == "array":
        return isinstance(value, list)
    if type_name == "string":
        return isinstance(value, str)
    if type_name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if type_name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if type_name == "boolean":
        return isinstance(value, bool)
    if type_name == "null":
        return value is None
    return False


def schema_validate(instance: Any, schema: Dict[str, Any], path: str = "$") -> List[str]:
    """Validate *instance* against the JSON-Schema subset used by REPORT_SCHEMA.

    Supports: type (string or list), enum, required, properties,
    additionalProperties (bool or schema), items. Returns a list of error
    strings; empty means valid.
    """
    errors: List[str] = []
    if not schema:  # {} matches anything
        return errors
    declared = schema.get("type")
    if declared is not None:
        types = declared if isinstance(declared, list) else [declared]
        if not any(_type_ok(instance, t) for t in types):
            errors.append("%s: expected type %s" % (path, "/".join(types)))
            return errors
    if "enum" in schema and instance not in schema["enum"]:
        errors.append("%s: value %r not in enum %r" % (path, instance, schema["enum"]))
    if isinstance(instance, dict):
        for required_key in schema.get("required", []):
            if required_key not in instance:
                errors.append("%s: missing required key %r" % (path, required_key))
        properties = schema.get("properties", {})
        additional = schema.get("additionalProperties", True)
        for key, value in instance.items():
            child_path = "%s.%s" % (path, key)
            if key in properties:
                errors.extend(schema_validate(value, properties[key], child_path))
            elif isinstance(additional, dict):
                errors.extend(schema_validate(value, additional, child_path))
            elif additional is False:
                errors.append("%s: unexpected key" % child_path)
    if isinstance(instance, list) and "items" in schema:
        for index, item in enumerate(instance):
            errors.extend(schema_validate(item, schema["items"], "%s[%d]" % (path, index)))
    return errors


# ---------------------------------------------------------------------------
# Parsers (pure functions; every input has already been redacted)
# ---------------------------------------------------------------------------


def _parse_lines(text: str) -> Dict[str, Any]:
    return {"text_lines": [line for line in text.splitlines() if line.strip()]}


def _parse_passwd(files: List[Tuple[str, str]]) -> Dict[str, Any]:
    users = []
    for line in files[0][1].splitlines():
        parts = line.strip().split(":")
        if len(parts) >= 7 and not line.startswith("#"):
            users.append(
                {
                    "name": parts[0],
                    "uid": parts[2],
                    "gid": parts[3],
                    "home": parts[5],
                    "shell": parts[6],
                }
            )
    return {"users": users, "note": "from /etc/passwd; /etc/shadow is never read"}


def _parse_os_release(files: List[Tuple[str, str]]) -> Dict[str, Any]:
    info: Dict[str, str] = {}
    for line in files[0][1].splitlines():
        if "=" in line and not line.startswith("#"):
            key, _, value = line.partition("=")
            info[key.strip()] = value.strip().strip('"')
    return {"os_release": info}


def _parse_meminfo(files: List[Tuple[str, str]]) -> Dict[str, Any]:
    wanted = {"MemTotal", "MemFree", "MemAvailable", "SwapTotal", "SwapFree"}
    out: Dict[str, str] = {}
    for line in files[0][1].splitlines():
        key, _, value = line.partition(":")
        if key.strip() in wanted:
            out[key.strip()] = value.strip()
    return {"meminfo": out}


def _parse_df(text: str) -> Dict[str, Any]:
    rows = []
    lines = text.splitlines()
    for line in lines[1:]:  # skip header
        parts = line.split()
        if len(parts) >= 6:
            rows.append(
                {
                    "filesystem": parts[0],
                    "kb_total": parts[1],
                    "kb_used": parts[2],
                    "kb_available": parts[3],
                    "use_percent": parts[4],
                    "mounted_on": parts[5],
                }
            )
    return {"filesystems": rows}


_RELEVANT_PACKAGE_PATTERNS = re.compile(
    r"(python3|pip|git|docker|podman|containerd|node|npm|sqlite|nginx|caddy|apache2"
    r"|ufw|nftables|iptables|fail2ban|openssh|wireguard|tailscale|cron|rsync|restic"
    r"|borg|rclone|duplicity|smartmontools|nvme-cli|hermes|bittensor|subtensor|btcli"
    r"|rustc|cargo|postgresql|redis|mariadb|mysql|mosquitto|telegram)",
    re.I,
)


def _parse_dpkg_relevant(text: str) -> Dict[str, Any]:
    total = 0
    relevant = []
    for line in text.splitlines():
        if not line.strip():
            continue
        total += 1
        name, _, version = line.partition("\t")
        if _RELEVANT_PACKAGE_PATTERNS.search(name):
            relevant.append({"name": name.strip(), "version": version.strip()})
    return {
        "total_installed": total,
        "relevant": relevant,
        "note": "relevance filter per Atlas PRD ATLAS-ENV-001; full list not stored",
    }


_SSHD_DIRECTIVES = {
    "port",
    "listenaddress",
    "passwordauthentication",
    "permitrootlogin",
    "pubkeyauthentication",
    "kbdinteractiveauthentication",
    "challengeresponseauthentication",
    "x11forwarding",
    "allowusers",
    "allowgroups",
}


def _parse_sshd_config(files: List[Tuple[str, str]]) -> Dict[str, Any]:
    # Files arrive in sshd precedence order (drop-ins first, then main config).
    # sshd honours the FIRST value obtained for each keyword, so keep first-wins
    # across all files. Result stays a single-element list per directive for
    # backward-compatible consumers.
    directives: Dict[str, List[str]] = {}
    for _, content in files:
        for line in content.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            key, _, value = stripped.partition(" ")
            key = key.lower()
            if key in _SSHD_DIRECTIVES and key not in directives:
                directives[key] = [value.strip()]
    return {
        "directives": directives,
        "sources": [path for path, _ in files],
        "note": "effective directives across main config + drop-ins (first-wins); "
                "defaults apply when absent",
    }


def _parse_json_lines(text: str) -> Dict[str, Any]:
    entries = []
    bad = 0
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except ValueError:
            bad += 1
    return {"entries": entries, "unparsed_lines": bad}


def _parse_json(text: str) -> Dict[str, Any]:
    return {"json": json.loads(text)}


def _parse_find_paths(text: str) -> Dict[str, Any]:
    """Stat every path emitted by a find probe.

    NOTE: discovered paths are passed only to os.lstat() (a syscall); no
    command line is ever constructed from collected data.
    """
    entries = []
    for line in text.splitlines():
        path = line.strip()
        if path:
            entries.append(_stat_entry(path))
    return {"paths": entries}


def _parse_thermal(files: List[Tuple[str, str]]) -> Dict[str, Any]:
    zones = []
    for path, content in files:
        value = content.strip()
        zone: Dict[str, Any] = {"path": path, "raw": value}
        try:
            zone["celsius"] = round(int(value) / 1000.0, 1)
        except ValueError:
            pass
        zones.append(zone)
    return {"thermal_zones": zones}


def _parse_uptime_loadavg(files: List[Tuple[str, str]]) -> Dict[str, Any]:
    out: Dict[str, str] = {}
    for path, content in files:
        out[os.path.basename(path)] = content.strip()
    return out


PARSERS: Dict[str, Callable[..., Dict[str, Any]]] = {
    "lines": _parse_lines,
    "passwd": _parse_passwd,
    "os_release": _parse_os_release,
    "meminfo": _parse_meminfo,
    "df": _parse_df,
    "dpkg_relevant": _parse_dpkg_relevant,
    "sshd_config": _parse_sshd_config,
    "json_lines": _parse_json_lines,
    "json": _parse_json,
    "find_paths": _parse_find_paths,
    "thermal": _parse_thermal,
    "uptime_loadavg": _parse_uptime_loadavg,
}


# ---------------------------------------------------------------------------
# Probe table — THE single reviewable declaration of everything this tool does
# to the device. Every command must be read-only; see docs/probe-review.md.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Probe:
    item_id: str
    category: str
    kind: str  # "cmd" | "read" | "stat-glob" | "which"
    spec: Tuple[str, ...]  # argv for cmd; paths/globs for read & stat-glob; names for which
    parser: Optional[str] = None
    timeout: int = 20
    on_nonzero: Optional[str] = None  # None | "crontab-empty" | "partial-ok"
    missing_ok: bool = False  # read kind: absence is a finding, not a failure
    notes: str = ""

    def display_command(self) -> str:
        if self.kind == "cmd":
            return " ".join(self.spec)
        return "%s: %s" % (self.kind, " | ".join(self.spec))


PROBES: Tuple[Probe, ...] = (
    # -- hardware ----------------------------------------------------------
    Probe("model", "hardware", "read",
          ("/proc/device-tree/model", "/sys/firmware/devicetree/base/model"),
          missing_ok=True, notes="device model string; absent on non-devicetree hosts"),
    Probe("architecture", "hardware", "cmd", ("uname", "-m"), parser="lines",
          notes="machine architecture"),
    # -- cpu_memory_storage ------------------------------------------------
    Probe("cpu", "cpu_memory_storage", "cmd", ("lscpu",), parser="lines",
          notes="CPU details; read-only query"),
    Probe("memory", "cpu_memory_storage", "read", ("/proc/meminfo",),
          parser="meminfo", notes="RAM/swap totals from procfs"),
    Probe("block_devices", "cpu_memory_storage", "cmd",
          ("lsblk", "-J", "-o", "NAME,SIZE,TYPE,MOUNTPOINT,FSTYPE,MODEL"),
          parser="json", notes="block device topology; -J JSON output, read-only"),
    Probe("filesystem_usage", "cpu_memory_storage", "cmd", ("df", "-P", "-k"),
          parser="df", notes="POSIX-format filesystem usage"),
    Probe("partitions", "cpu_memory_storage", "read", ("/proc/partitions",),
          parser="lines_read", notes="partition table from procfs"),
    # -- os_kernel -----------------------------------------------------------
    Probe("os_release", "os_kernel", "read", ("/etc/os-release",),
          parser="os_release", notes="OS identification"),
    Probe("kernel", "os_kernel", "cmd", ("uname", "-a"), parser="lines",
          notes="kernel version string"),
    # -- users_and_service_accounts ----------------------------------------
    Probe("passwd_users", "users_and_service_accounts", "read", ("/etc/passwd",),
          parser="passwd",
          notes="account list; world-readable by design; /etc/shadow is NEVER read"),
    # -- packages ------------------------------------------------------------
    Probe("dpkg_packages", "packages", "cmd",
          ("dpkg-query", "-W", "-f", "${Package}\t${Version}\n"),
          parser="dpkg_relevant", timeout=60,
          notes="Debian package list; filtered to Atlas-relevant names + total count"),
    Probe("rpm_packages", "packages", "cmd",
          ("rpm", "-qa", "--qf", "%{NAME}\t%{VERSION}-%{RELEASE}\n"),
          parser="dpkg_relevant", timeout=60,
          notes="RPM fallback for non-Debian hosts; unsupported on Debian is expected"),
    # -- containers ----------------------------------------------------------
    Probe("docker_containers", "containers", "cmd",
          ("docker", "ps", "-a", "--format", "{{json .}}"), parser="json_lines",
          notes="container list; read-only"),
    Probe("docker_images", "containers", "cmd",
          ("docker", "images", "--format", "{{json .}}"), parser="json_lines",
          notes="image list; read-only"),
    Probe("podman_containers", "containers", "cmd",
          ("podman", "ps", "-a", "--format", "json"), parser="json",
          notes="podman fallback; read-only"),
    # -- systemd_services ----------------------------------------------------
    Probe("service_units", "systemd_services", "cmd",
          ("systemctl", "list-units", "--type=service", "--all", "--no-pager",
           "--plain", "--no-legend"),
          parser="lines", notes="unit states; list-* subcommands are read-only"),
    Probe("service_unit_files", "systemd_services", "cmd",
          ("systemctl", "list-unit-files", "--type=service", "--no-pager",
           "--plain", "--no-legend"),
          parser="lines", notes="installed unit files and enablement"),
    # -- listening_ports -----------------------------------------------------
    Probe("sockets", "listening_ports", "cmd", ("ss", "-tulnp"), parser="lines",
          notes="listening sockets; process names may need privilege (ports still shown)"),
    # -- scheduled_jobs ------------------------------------------------------
    Probe("user_crontab", "scheduled_jobs", "cmd", ("crontab", "-l"),
          parser="lines", on_nonzero="crontab-empty",
          notes="current user's crontab; 'no crontab' is a finding, not an error"),
    Probe("system_crontab", "scheduled_jobs", "read", ("/etc/crontab",),
          parser="lines_read", missing_ok=True, notes="system crontab"),
    Probe("cron_directories", "scheduled_jobs", "stat-glob",
          ("/etc/cron.d/*", "/etc/cron.daily/*", "/etc/cron.hourly/*",
           "/etc/cron.weekly/*", "/etc/cron.monthly/*"),
          notes="cron drop-ins; names and metadata only"),
    Probe("systemd_timers", "scheduled_jobs", "cmd",
          ("systemctl", "list-timers", "--all", "--no-pager", "--plain",
           "--no-legend"),
          parser="lines", notes="scheduled timers"),
    # -- hermes_installation -------------------------------------------------
    Probe("hermes_files", "hermes_installation", "stat-glob",
          ("~/.hermes*", "/home/*/.hermes*", "/opt/hermes*", "/usr/local/hermes*",
           "/usr/local/bin/hermes*", "/usr/bin/hermes*",
           "/etc/systemd/system/hermes*"),
          notes="prior Hermes installs; files are stat'ed, NEVER executed"),
    Probe("hermes_version_files", "hermes_installation", "read",
          ("/opt/hermes/VERSION", "/opt/hermes/version", "/usr/local/hermes/VERSION",
           "~/.hermes/VERSION"),
          missing_ok=True,
          notes="version from metadata files only; binaries are never run by design"),
    # -- repositories_and_app_dirs -------------------------------------------
    Probe("git_repositories", "repositories_and_app_dirs", "cmd",
          ("find", "/home", "/opt", "/srv", "/root", "/usr/local", "-maxdepth", "4",
           "-name", ".git", "-type", "d"),
          parser="find_paths", timeout=120, on_nonzero="partial-ok",
          notes="git repos in common locations; unreadable subtrees yield partial results"),
    Probe("application_directories", "repositories_and_app_dirs", "stat-glob",
          ("/opt/*", "/srv/*"),
          notes="installed application directories; metadata only"),
    # -- secret_file_locations -----------------------------------------------
    Probe("secret_files", "secret_file_locations", "cmd",
          ("find", "/home", "/root", "/opt", "/srv", "/etc", "-maxdepth", "5",
           "(", "-name", ".env*", "-o", "-name", "*.pem", "-o", "-name", "*.key",
           "-o", "-name", "id_rsa*", "-o", "-name", "id_ed25519*",
           "-o", "-name", "*credentials*", "-o", "-name", "*secret*", ")",
           "-type", "f"),
          parser="find_paths", timeout=120, on_nonzero="partial-ok",
          notes="secret file LOCATIONS; paths are stat'ed only — contents NEVER read"),
    # -- backup_configuration ------------------------------------------------
    Probe("backup_tools", "backup_configuration", "which",
          ("restic", "borg", "rsnapshot", "timeshift", "rclone", "duplicity"),
          notes="backup tool presence via PATH lookup only"),
    Probe("backup_configs", "backup_configuration", "stat-glob",
          ("/etc/restic*", "/etc/borg*", "/etc/rsnapshot*", "/etc/timeshift*",
           "~/.config/rclone/*", "/etc/duplicity*"),
          notes="backup configuration locations; metadata only"),
    # -- firewall --------------------------------------------------------------
    # Absolute sbin paths: these tools live in /usr/sbin, which is not on an
    # unprivileged user's PATH — a bare name yields a false "not present".
    # Reading rules still needs root (unprivileged -> permission-denied).
    Probe("ufw_status", "firewall", "cmd", ("/usr/sbin/ufw", "status", "verbose"),
          parser="lines", notes="ufw state; status subcommand is read-only (may need root)"),
    Probe("nftables_ruleset", "firewall", "cmd", ("/usr/sbin/nft", "list", "ruleset"),
          parser="lines", notes="nftables rules; list is read-only (may need root)"),
    Probe("iptables_rules", "firewall", "cmd", ("/usr/sbin/iptables", "-S"),
          parser="lines", notes="iptables rules; -S prints, never modifies (may need root)"),
    # -- remote_access ---------------------------------------------------------
    # Read drop-ins BEFORE the main file: sshd uses the first value obtained for
    # most keywords, and Debian Includes sshd_config.d/*.conf at the top of the
    # main config, so drop-ins take precedence. The parser keeps first-wins.
    Probe("sshd_config", "remote_access", "read",
          ("/etc/ssh/sshd_config.d/*.conf", "/etc/ssh/sshd_config"),
          parser="sshd_config",
          notes="effective sshd directives (drop-ins first, first-wins); no key material"),
    Probe("vpn_tools", "remote_access", "which",
          ("tailscale", "wg", "zerotier-cli", "openvpn"),
          notes="remote-access tool presence via PATH lookup only"),
    # -- device_health ----------------------------------------------------------
    Probe("thermal_zones", "device_health", "read",
          ("/sys/class/thermal/thermal_zone*/temp",),
          parser="thermal", missing_ok=True, notes="SoC temperature sensors"),
    Probe("vcgencmd_temperature", "device_health", "cmd",
          ("vcgencmd", "measure_temp"), parser="lines",
          notes="Raspberry Pi firmware temperature; measure_temp is read-only"),
    Probe("nvme_smart", "device_health", "cmd",
          ("smartctl", "-H", "-j", "/dev/nvme0"), parser="json",
          notes="NVMe SMART health; -H reads device health, changes nothing (needs root)"),
    Probe("uptime_load", "device_health", "read",
          ("/proc/uptime", "/proc/loadavg"), parser="uptime_loadavg",
          notes="uptime and load from procfs"),
)

# `lines_read` parses read-probe file lists with the plain lines parser
PARSERS["lines_read"] = lambda files: _parse_lines(files[0][1])


# ---------------------------------------------------------------------------
# Probe execution
# ---------------------------------------------------------------------------


class Executor:
    """Runs an argv (no shell). Swappable in tests."""

    def __call__(self, argv: Tuple[str, ...], timeout: int) -> Tuple[int, bytes, bytes]:
        # Ensure sbin dirs are on PATH so system tools (nft, ufw, iptables,
        # ss) resolve even when an unprivileged login PATH omits them.
        env = dict(os.environ)
        sbin = os.pathsep.join(("/usr/sbin", "/sbin"))
        env["PATH"] = sbin + os.pathsep + env.get("PATH", "")
        completed = subprocess.run(  # noqa: S603 — argv list, no shell, declared table
            list(argv), capture_output=True, timeout=timeout, env=env
        )
        return completed.returncode, completed.stdout, completed.stderr


_DENIED_PATTERNS = re.compile(
    r"permission denied|operation not permitted|must be root|are you root"
    r"|you must be root|need(?:s)? to be root|superuser|privileges required",
    re.I,
)


def _stat_entry(path: str) -> Dict[str, Any]:
    """Metadata for a path via os.lstat only. Contents are never read here."""
    entry: Dict[str, Any] = {"path": path}
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        entry["error"] = "not found"
        return entry
    except PermissionError:
        entry["error"] = "permission denied"
        return entry
    except OSError as exc:
        entry["error"] = str(exc)
        return entry
    if statmod.S_ISDIR(st.st_mode):
        entry["type"] = "dir"
    elif statmod.S_ISLNK(st.st_mode):
        entry["type"] = "symlink"
    else:
        entry["type"] = "file"
    entry["mode"] = oct(statmod.S_IMODE(st.st_mode))
    entry["uid"] = st.st_uid
    entry["gid"] = st.st_gid
    entry["size"] = st.st_size
    entry["mtime"] = datetime.datetime.fromtimestamp(
        st.st_mtime, tz=datetime.timezone.utc
    ).isoformat()
    try:  # resolve names where the platform supports it
        import pwd
        import grp

        entry["owner"] = pwd.getpwuid(st.st_uid).pw_name
        entry["group"] = grp.getgrgid(st.st_gid).gr_name
    except (ImportError, KeyError):
        pass
    return entry


def _truncate(text: str, warnings: List[str]) -> str:
    if len(text) > MAX_CAPTURE_CHARS:
        warnings.append("output truncated to %d characters" % MAX_CAPTURE_CHARS)
        return text[:MAX_CAPTURE_CHARS]
    return text


def _envelope(probe: Probe, status: str, data: Any = None, error: Optional[str] = None,
              warnings: Optional[List[str]] = None, duration_ms: float = 0.0) -> Dict[str, Any]:
    env: Dict[str, Any] = {
        "status": status,
        "command": probe.display_command(),
        "duration_ms": round(duration_ms, 1),
    }
    if data is not None:
        env["data"] = data
    if error is not None:
        env["error"] = redact(error)
    if warnings:
        env["warnings"] = [redact(w) for w in warnings]
    return env


def _run_cmd_probe(probe: Probe, execute: Executor) -> Dict[str, Any]:
    warnings: List[str] = []
    start = time.monotonic()
    try:
        returncode, stdout_raw, stderr_raw = execute(probe.spec, probe.timeout)
    except FileNotFoundError:
        return _envelope(probe, STATUS_UNSUPPORTED,
                         error="tool not present: %s" % probe.spec[0],
                         duration_ms=(time.monotonic() - start) * 1000)
    except PermissionError as exc:
        return _envelope(probe, STATUS_DENIED, error=str(exc),
                         duration_ms=(time.monotonic() - start) * 1000)
    except subprocess.TimeoutExpired:
        return _envelope(probe, STATUS_ERROR,
                         error="timed out after %ds" % probe.timeout,
                         duration_ms=(time.monotonic() - start) * 1000)
    duration = (time.monotonic() - start) * 1000
    stdout = redact(_truncate(_decode(stdout_raw), warnings))
    stderr = redact(_truncate(_decode(stderr_raw), []))
    if returncode != 0:
        if probe.on_nonzero == "crontab-empty" and "no crontab" in stderr.lower():
            return _envelope(probe, STATUS_COLLECTED, data={"text_lines": []},
                             warnings=["no crontab for this user"], duration_ms=duration)
        if probe.on_nonzero == "partial-ok" and stdout.strip():
            warnings.append("partial results; some paths unreadable: %s"
                            % stderr.strip()[:500])
        elif _DENIED_PATTERNS.search(stderr):
            return _envelope(probe, STATUS_DENIED,
                             error="exit %d: %s" % (returncode, stderr.strip()[:500]),
                             duration_ms=duration)
        else:
            return _envelope(probe, STATUS_ERROR,
                             error="exit %d: %s" % (returncode, stderr.strip()[:500]),
                             duration_ms=duration)
    parser = PARSERS.get(probe.parser or "lines", _parse_lines)
    try:
        data = parser(stdout)
    except Exception as exc:  # noqa: BLE001 — parser failure must not abort the run
        return _envelope(probe, STATUS_ERROR,
                         error="parser failed: %s" % exc, duration_ms=duration)
    return _envelope(probe, STATUS_COLLECTED, data=data, warnings=warnings,
                     duration_ms=duration)


def _expand_paths(patterns: Tuple[str, ...]) -> List[str]:
    matches: List[str] = []
    for pattern in patterns:
        expanded = os.path.expanduser(pattern)
        if globmod.has_magic(expanded):
            matches.extend(sorted(globmod.glob(expanded)))
        elif os.path.lexists(expanded):
            matches.append(expanded)
    return matches


def _run_read_probe(probe: Probe) -> Dict[str, Any]:
    warnings: List[str] = []
    start = time.monotonic()
    paths = _expand_paths(probe.spec)
    if not paths:
        duration = (time.monotonic() - start) * 1000
        if probe.missing_ok:
            return _envelope(probe, STATUS_COLLECTED, data={"present": False},
                             duration_ms=duration)
        return _envelope(probe, STATUS_UNSUPPORTED,
                         error="no such file: %s" % " | ".join(probe.spec),
                         duration_ms=duration)
    files: List[Tuple[str, str]] = []
    denied: List[str] = []
    for path in paths[:MAX_READ_FILES]:
        try:
            with open(path, "rb") as handle:
                content = redact(_decode(handle.read(MAX_READ_BYTES)))
            files.append((path, content))
        except PermissionError:
            denied.append(path)
        except OSError as exc:
            warnings.append("%s: %s" % (path, exc))
    duration = (time.monotonic() - start) * 1000
    if not files and denied:
        return _envelope(probe, STATUS_DENIED,
                         error="permission denied: %s" % ", ".join(denied),
                         duration_ms=duration)
    if not files:
        return _envelope(probe, STATUS_ERROR,
                         error="unreadable: %s" % ("; ".join(warnings) or "unknown"),
                         duration_ms=duration)
    if denied:
        warnings.append("permission denied: %s" % ", ".join(denied))
    parser = PARSERS.get(probe.parser or "", None)
    try:
        data = parser(files) if parser else {
            "files": [{"path": p, "content": c} for p, c in files]
        }
    except Exception as exc:  # noqa: BLE001
        return _envelope(probe, STATUS_ERROR, error="parser failed: %s" % exc,
                         duration_ms=duration)
    return _envelope(probe, STATUS_COLLECTED, data=data, warnings=warnings,
                     duration_ms=duration)


def _run_stat_glob_probe(probe: Probe) -> Dict[str, Any]:
    start = time.monotonic()
    matches = [_stat_entry(path) for path in _expand_paths(probe.spec)]
    return _envelope(probe, STATUS_COLLECTED, data={"matches": matches},
                     duration_ms=(time.monotonic() - start) * 1000)


def _run_which_probe(probe: Probe) -> Dict[str, Any]:
    start = time.monotonic()
    found = {name: shutil.which(name) for name in probe.spec}
    return _envelope(probe, STATUS_COLLECTED, data={"tools": found},
                     duration_ms=(time.monotonic() - start) * 1000)


def run_probe(probe: Probe, execute: Optional[Executor] = None) -> Dict[str, Any]:
    """Run one probe, never raising: every failure maps to an envelope status."""
    try:
        if probe.kind == "cmd":
            return _run_cmd_probe(probe, execute or Executor())
        if probe.kind == "read":
            return _run_read_probe(probe)
        if probe.kind == "stat-glob":
            return _run_stat_glob_probe(probe)
        if probe.kind == "which":
            return _run_which_probe(probe)
        return _envelope(probe, STATUS_ERROR, error="unknown probe kind: %s" % probe.kind)
    except Exception as exc:  # noqa: BLE001 — one probe must never abort the run
        return _envelope(probe, STATUS_ERROR, error="probe crashed: %s" % exc)


# ---------------------------------------------------------------------------
# Collector: full run, report assembly
# ---------------------------------------------------------------------------


def _utc_now() -> str:
    return datetime.datetime.now(tz=datetime.timezone.utc).isoformat()


def _account() -> str:
    try:
        return getpass.getuser()
    except Exception:  # noqa: BLE001 — minimal environments may lack user info
        try:
            return "uid:%d" % os.getuid()  # type: ignore[attr-defined]
        except AttributeError:
            return "unknown"


def collect(execute: Optional[Executor] = None,
            probes: Tuple[Probe, ...] = PROBES) -> Dict[str, Any]:
    """Run all probes and assemble a report dict (not yet validated/written)."""
    started_at = _utc_now()
    run_id = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + "-" + secretsmod.token_hex(4)
    categories: Dict[str, Any] = {name: {"items": {}} for name in CATEGORIES}
    for probe in probes:
        categories[probe.category]["items"][probe.item_id] = run_probe(probe, execute)
    statuses = [
        item["status"]
        for category in categories.values()
        for item in category["items"].values()
    ]
    complete = not any(s in (STATUS_DENIED, STATUS_ERROR) for s in statuses)
    try:
        privileged = os.geteuid() == 0  # type: ignore[attr-defined]
    except AttributeError:  # non-POSIX dev platforms
        privileged = False
    return {
        "run": {
            "run_id": run_id,
            "script_version": SCRIPT_VERSION,
            "schema_version": SCHEMA_VERSION,
            "started_at": started_at,
            "finished_at": _utc_now(),
            "executing_account": _account(),
            "hostname": socket.gethostname(),
            "privileged": privileged,
            "complete": complete,
        },
        "categories": categories,
    }


def _write_private(path: str, content: str) -> None:
    """Write with 0600 permissions (best effort on non-POSIX dev platforms)."""
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    descriptor = os.open(path, flags, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(content)


def status_summary(report: Dict[str, Any]) -> Dict[str, int]:
    summary = {status: 0 for status in ALL_STATUSES}
    for category in report["categories"].values():
        for item in category["items"].values():
            summary[item["status"]] += 1
    return summary


def item_errors(report: Dict[str, Any]) -> List[Dict[str, str]]:
    errors = []
    for category_name, category in report["categories"].items():
        for item_id, item in category["items"].items():
            if item["status"] in (STATUS_DENIED, STATUS_ERROR):
                errors.append({
                    "item": "%s.%s" % (category_name, item_id),
                    "status": item["status"],
                    "error": item.get("error", ""),
                })
    return errors


# ---------------------------------------------------------------------------
# Classification worksheet (pure function of a report; executes nothing)
# ---------------------------------------------------------------------------

DISPOSITION_PRESERVE = "preserve"
DISPOSITION_MIGRATE = "migrate"
DISPOSITION_REMOVE = "remove"
DISPOSITION_DECISION = "decision required"

_ATLAS_RELATED = re.compile(r"(hermes|bittensor|subtensor|btcli|atlas|\btao\b)", re.I)

_STOCK_SERVICE_PATTERNS = re.compile(
    r"^(systemd-|dbus|ssh|sshd|cron|getty@|serial-getty@|NetworkManager|networking"
    r"|wpa_supplicant|bluetooth|hciuart|avahi-daemon|ModemManager|polkit|udisks2"
    r"|rsyslog|dphys-swapfile|raspberrypi-|rpi-|triggerhappy|fake-hwclock|keyboard-setup"
    r"|console-setup|apt-daily|dpkg-db-backup|e2scrub|fstrim|man-db|logrotate"
    r"|plymouth|user@|ifup@|alsa-|glamor|lightdm|cups|emergency|rescue|thermald"
    r"|unattended-upgrades|packagekit|snapd|multipathd|ua-timer)",
)

_STOCK_PACKAGE_PATTERNS = re.compile(
    r"^(python3|libpython|pip|git$|git-|openssh|cron$|rsync$|iptables|nftables"
    r"|sqlite3|ca-certificates)",
)

_HERMES_VERSION_IN_PATH = re.compile(r"hermes[-_]?v?(\d+(?:\.\d+)+)", re.I)


def _version_tuple(version: str) -> Tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


@dataclass
class WorksheetRow:
    item: str
    item_type: str
    disposition: str
    evidence: str
    note: str = ""


def _classify_name(name: str, item_type: str, evidence: str,
                   stock_patterns: Optional[re.Pattern] = None,
                   match_name: Optional[str] = None) -> WorksheetRow:
    matchable = match_name if match_name is not None else name
    if _ATLAS_RELATED.search(matchable):
        return WorksheetRow(
            name, item_type, DISPOSITION_DECISION, evidence,
            "Atlas/Hermes/Bittensor-related; operator must decide before Phase 1 "
            "(PRD ATLAS-ENV-001)")
    if stock_patterns and stock_patterns.match(matchable):
        return WorksheetRow(name, item_type, DISPOSITION_PRESERVE, evidence,
                            "recognized stock OS component")
    return WorksheetRow(
        name, item_type, DISPOSITION_DECISION, evidence,
        "unrecognized: is this required by anything you want to keep?")


def build_worksheet_rows(report: Dict[str, Any]) -> List[WorksheetRow]:
    rows: List[WorksheetRow] = []
    categories = report["categories"]

    def collected(category: str, item: str) -> Optional[Dict[str, Any]]:
        envelope = categories.get(category, {}).get("items", {}).get(item)
        if envelope and envelope.get("status") == STATUS_COLLECTED:
            return envelope.get("data") or {}
        return None

    # systemd unit files
    unit_files = collected("systemd_services", "service_unit_files")
    if unit_files:
        for line in unit_files.get("text_lines", []):
            name = line.split()[0] if line.split() else ""
            if name.endswith(".service"):
                rows.append(_classify_name(
                    name, "service", "systemd_services.service_unit_files",
                    _STOCK_SERVICE_PATTERNS))

    # relevant packages
    for source_item in ("dpkg_packages", "rpm_packages"):
        packages = collected("packages", source_item)
        if packages:
            for package in packages.get("relevant", []):
                rows.append(_classify_name(
                    "%s %s" % (package["name"], package["version"]), "package",
                    "packages.%s" % source_item, _STOCK_PACKAGE_PATTERNS,
                    match_name=package["name"]))

    # containers and images
    for source_item, item_type in (("docker_containers", "container"),
                                   ("docker_images", "image")):
        entries = collected("containers", source_item)
        if entries:
            for entry in entries.get("entries", []):
                name = entry.get("Names") or entry.get("Repository") or str(entry)[:80]
                rows.append(_classify_name(str(name), item_type,
                                           "containers.%s" % source_item))

    # git repositories
    repositories = collected("repositories_and_app_dirs", "git_repositories")
    if repositories:
        for entry in repositories.get("paths", []):
            rows.append(_classify_name(entry.get("path", "?"), "repository",
                                       "repositories_and_app_dirs.git_repositories"))

    # application directories
    app_dirs = collected("repositories_and_app_dirs", "application_directories")
    if app_dirs:
        for entry in app_dirs.get("matches", []):
            rows.append(_classify_name(
                entry.get("path", "?"), "app-directory",
                "repositories_and_app_dirs.application_directories"))

    # Hermes files — the only place a `remove` may be proposed, and only with
    # explicit version evidence (duplicate older versioned install).
    hermes = collected("hermes_installation", "hermes_files")
    if hermes:
        versioned: List[Tuple[Tuple[int, ...], str]] = []
        unversioned: List[str] = []
        for entry in hermes.get("matches", []):
            path = entry.get("path", "?")
            match = _HERMES_VERSION_IN_PATH.search(path)
            if match:
                try:
                    versioned.append((_version_tuple(match.group(1)), path))
                except ValueError:
                    unversioned.append(path)
            else:
                unversioned.append(path)
        if len(versioned) >= 2:
            versioned.sort()
            newest_version, newest_path = versioned[-1]
            for version, path in versioned[:-1]:
                rows.append(WorksheetRow(
                    path, "hermes-install", DISPOSITION_REMOVE,
                    "hermes_installation.hermes_files",
                    "older versioned install (%s) superseded by %s (%s); "
                    "removal still requires ATLAS-ENV-002 approval"
                    % (".".join(map(str, version)), newest_path,
                       ".".join(map(str, newest_version)))))
            rows.append(WorksheetRow(
                newest_path, "hermes-install", DISPOSITION_DECISION,
                "hermes_installation.hermes_files",
                "newest existing Hermes install; Phase 1 decides reuse vs reinstall"))
        else:
            for _, path in versioned:
                unversioned.append(path)
        for path in unversioned:
            rows.append(WorksheetRow(
                path, "hermes-files", DISPOSITION_DECISION,
                "hermes_installation.hermes_files",
                "existing Hermes material; operator must decide before Phase 1"))
    return rows


def render_worksheet(report: Dict[str, Any]) -> str:
    rows = build_worksheet_rows(report)
    run = report["run"]
    lines = [
        "# Classification worksheet — run %s" % run["run_id"],
        "",
        "Generated from inventory report (schema v%s) collected %s on `%s`."
        % (run["schema_version"], run["started_at"], run["hostname"]),
        "",
        "**Proposals only.** Nothing has been deleted, stopped, or modified.",
        "Every `remove` proposal still requires the separate removal-plan approval",
        "(ATLAS-ENV-002). Ambiguous items default to `decision required` — please",
        "resolve each one before Phase 1 (PRD ATLAS-ENV-001).",
        "",
        "| Item | Type | Proposed disposition | Evidence | Notes / open question |",
        "|---|---|---|---|---|",
    ]
    for row in rows:
        lines.append("| `%s` | %s | **%s** | `%s` | %s |" % (
            row.item.replace("|", "\\|"), row.item_type, row.disposition,
            row.evidence, row.note.replace("|", "\\|")))
    if not rows:
        lines.append("| _no classifiable items collected_ | — | — | — | "
                     "check per-item statuses in the report |")
    summary = status_summary(report)
    lines += [
        "",
        "## Collection status summary",
        "",
        "| Status | Items |",
        "|---|---|",
    ]
    for status in ALL_STATUSES:
        lines.append("| %s | %d |" % (status, summary[status]))
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Audit record
# ---------------------------------------------------------------------------


def build_audit(report: Optional[Dict[str, Any]], run_id: str, started_at: str,
                outputs: List[str], fatal: Optional[str]) -> Dict[str, Any]:
    audit: Dict[str, Any] = {
        "run_id": run_id,
        "started_at": started_at,
        "finished_at": _utc_now(),
        "script_version": SCRIPT_VERSION,
        "schema_version": SCHEMA_VERSION,
        "executing_account": _account(),
        "outputs": outputs,
        "fatal": redact(fatal) if fatal else None,
    }
    if report is not None:
        audit["status_summary"] = status_summary(report)
        audit["errors"] = item_errors(report)
    else:
        audit["status_summary"] = None
        audit["errors"] = []
    return audit


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def cmd_run(output_dir: str, execute: Optional[Executor] = None) -> int:
    os.makedirs(output_dir, exist_ok=True)
    started_at = _utc_now()
    run_id = "unknown"
    report: Optional[Dict[str, Any]] = None
    outputs: List[str] = []
    fatal: Optional[str] = None
    exit_code = 1
    try:
        report = collect(execute=execute)
        run_id = report.get("run", {}).get("run_id") or "unknown"
        validation_errors = schema_validate(report, REPORT_SCHEMA)
        if validation_errors:
            fatal = "report failed schema validation: " + "; ".join(validation_errors[:20])
            print("FATAL: %s" % fatal, file=sys.stderr)
            return 1
        report_path = os.path.join(output_dir, "report-%s.json" % run_id)
        _write_private(report_path, json.dumps(report, indent=2, sort_keys=True))
        outputs.append(report_path)
        worksheet_path = os.path.join(output_dir,
                                      "classification-worksheet-%s.md" % run_id)
        _write_private(worksheet_path, render_worksheet(report))
        outputs.append(worksheet_path)
        summary = status_summary(report)
        complete = report["run"]["complete"]
        print("Inventory run %s finished: %s" % (
            run_id, ", ".join("%s=%d" % (k, v) for k, v in summary.items())))
        print("Report:    %s" % report_path)
        print("Worksheet: %s" % worksheet_path)
        if not complete:
            print("PARTIAL collection — review permission-denied/error items "
                  "in the report before relying on it.")
        exit_code = 0 if complete else 3
        return exit_code
    except Exception as exc:  # noqa: BLE001 — record fatal in audit, fail visibly
        fatal = "unhandled failure: %s" % exc
        print("FATAL: %s" % redact(str(exc)), file=sys.stderr)
        return 1
    finally:
        try:
            audit = build_audit(report, run_id, started_at, outputs, fatal)
            audit_path = os.path.join(output_dir, "audit-%s.json" % run_id)
            _write_private(audit_path, json.dumps(audit, indent=2, sort_keys=True))
            print("Audit:     %s" % audit_path)
        except Exception as audit_exc:  # noqa: BLE001
            print("WARNING: audit record could not be written: %s" % audit_exc,
                  file=sys.stderr)


def cmd_worksheet(report_path: str, output_dir: Optional[str]) -> int:
    with open(report_path, "r", encoding="utf-8") as handle:
        report = json.load(handle)
    validation_errors = schema_validate(report, REPORT_SCHEMA)
    if validation_errors:
        print("FATAL: report is not a valid schema-v%d inventory report:\n  %s"
              % (SCHEMA_VERSION, "\n  ".join(validation_errors[:20])), file=sys.stderr)
        return 1
    directory = output_dir or os.path.dirname(os.path.abspath(report_path))
    worksheet_path = os.path.join(
        directory, "classification-worksheet-%s.md" % report["run"]["run_id"])
    _write_private(worksheet_path, render_worksheet(report))
    print("Worksheet: %s" % worksheet_path)
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="atlas_inventory",
        description="Read-only Atlas device inventory (ATLAS-ENV-001). "
                    "Never modifies the device; never self-elevates.")
    subparsers = parser.add_subparsers(dest="subcommand", required=True)
    run_parser = subparsers.add_parser("run", help="collect a full inventory")
    run_parser.add_argument("--output-dir", default=os.path.join("var", "inventory"),
                            help="directory for report/worksheet/audit "
                                 "(default: var/inventory)")
    worksheet_parser = subparsers.add_parser(
        "worksheet", help="regenerate the classification worksheet from a report")
    worksheet_parser.add_argument("report", help="path to an existing report JSON")
    worksheet_parser.add_argument("--output-dir", default=None)
    subparsers.add_parser("dump-schema", help="print the report JSON schema")
    args = parser.parse_args(argv)
    if args.subcommand == "run":
        return cmd_run(args.output_dir)
    if args.subcommand == "worksheet":
        return cmd_worksheet(args.report, args.output_dir)
    if args.subcommand == "dump-schema":
        print(json.dumps(REPORT_SCHEMA, indent=2))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
