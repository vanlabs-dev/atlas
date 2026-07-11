#!/usr/bin/env python3
"""Atlas Phase 0 hardening assessment.

Read-only evaluation of the target device's security posture against the
ATLAS-ENV-003 area list. Grounded in the latest device-inventory report plus
minimal supplementary read-only probes. Produces per-area verdicts and a
proposed (NEVER applied) hardening plan for operator approval.

Guarantees:
- ASSESS, NOT ASSUME: verdicts come only from observed evidence; missing
  evidence is reported as missing, never substituted with defaults.
- READ-ONLY: nothing on the device is modified; probes reuse the inventory
  tool's reviewed read-only machinery.
- PROPOSE, NOT APPLY: the plan lists what *would* change; application is a
  separate approved OpenSpec change.
- Same envelope as the inventory: unprivileged, no self-elevation, redacted
  0600 outputs, per-run audit record.

Usage:
    python3 atlas_hardening.py assess [--inventory-report PATH]
                                      [--output-dir DIR]
                                      [--max-report-age-hours N]
    python3 atlas_hardening.py dump-schema

Exit codes for `assess`: 0 = complete, 3 = incomplete evidence, 1 = fatal.
"""

from __future__ import annotations

import argparse
import datetime
import getpass
import glob as globmod
import json
import os
import secrets as secretsmod
import socket
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

# --- pinned import surface from the inventory tool (see design D1) -----------
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO_ROOT, "inventory"))

import atlas_inventory as inv  # noqa: E402

ASSESSOR_VERSION = "0.1.0"
ASSESSMENT_SCHEMA_VERSION = 1
DEFAULT_MAX_REPORT_AGE_HOURS = 72

VERDICT_OK = "ok"
VERDICT_FINDING = "finding"
VERDICT_DECISION = "decision-required"
VERDICT_NA = "not-applicable-yet"
ALL_VERDICTS = (VERDICT_OK, VERDICT_FINDING, VERDICT_DECISION, VERDICT_NA)

# The fixed ATLAS-ENV-003 area list. Omission is structurally impossible:
# the assessor iterates this tuple and the schema requires one entry per area.
AREAS: Tuple[str, ...] = (
    "unprivileged-service-execution",
    "ssh-authentication-and-exposed-ports",
    "firewall-rules",
    "unattended-security-updates",
    "secret-file-permissions",
    "log-permissions",
    "backup-encryption-and-destination",
    "service-restart-policy",
    "time-synchronization",
    "disk-space-thresholds",
    "remote-frontend-exposure",
)

# ---------------------------------------------------------------------------
# Baseline expectations (design D4) — the assessor's opinion, reviewable in
# one place. Expectations produce PROPOSALS; the operator approves or strikes.
# ---------------------------------------------------------------------------

EXPECTATIONS: Dict[str, str] = {
    "unprivileged-service-execution":
        "Atlas/Hermes services run as dedicated unprivileged accounts "
        "(ATLAS-HERMES-002, ATLAS-SEC-001).",
    "ssh-authentication-and-exposed-ports":
        "SSH key-only authentication (PasswordAuthentication no), root login "
        "not password-based, X11Forwarding off, no unexpected listening "
        "services on non-loopback interfaces.",
    "firewall-rules":
        "A host firewall is installed and active with default-deny inbound, "
        "allowing SSH (and loopback/established traffic).",
    "unattended-security-updates":
        "Unattended security updates enabled, or a documented manual update "
        "process exists (ATLAS-ENV-003).",
    "secret-file-permissions":
        "Secret-bearing files are owner-only (no group/other read), "
        "excluding public certificate stores (ATLAS-SEC-002).",
    "log-permissions":
        "No world-writable log files or directories under /var/log "
        "(ATLAS-SEC-007 context).",
    "backup-encryption-and-destination":
        "An external or remote encrypted backup destination is selected and "
        "configured (ATLAS-BACKUP-002).",
    "service-restart-policy":
        "Critical services (sshd now; Atlas services at Phase 1) have a "
        "restart-on-failure policy.",
    "time-synchronization":
        "NTP time synchronization is active and synchronized "
        "(ATLAS-ENV-003, needed for honest timestamps).",
    "disk-space-thresholds":
        "Disk usage thresholds are defined for warning and for stopping "
        "nonessential retention (ATLAS-BACKUP-005).",
    "remote-frontend-exposure":
        "Any frontend binds to localhost by default; exposure requires an "
        "explicit approved design (ATLAS-SEC-004, ATLAS-OPS-006).",
}

# ---------------------------------------------------------------------------
# Supplementary read-only probes (design D2) — only facts the inventory
# does not capture. Reviewed in docs/probe-review.md.
# ---------------------------------------------------------------------------

SUPPLEMENTARY_PROBES: Tuple[inv.Probe, ...] = (
    inv.Probe("time_sync", "device_health", "cmd",
              ("timedatectl", "show",
               "--property=NTP,NTPSynchronized,Timezone"),
              parser="lines",
              notes="'show' prints properties; read-only"),
    inv.Probe("auto_upgrades_config", "os_kernel", "read",
              ("/etc/apt/apt.conf.d/20auto-upgrades",
               "/etc/apt/apt.conf.d/50unattended-upgrades"),
              missing_ok=True,
              notes="apt periodic/unattended-upgrades config; file read"),
    inv.Probe("var_log_perms", "os_kernel", "stat-glob",
              ("/var/log", "/var/log/*"),
              notes="log ownership/permissions; lstat only, contents never read"),
    inv.Probe("sshd_restart_policy", "systemd_services", "cmd",
              ("systemctl", "show", "ssh.service", "-p", "Restart",
               "--no-pager"),
              parser="lines",
              notes="'show' prints unit properties; read-only"),
)

# ---------------------------------------------------------------------------
# Assessment output schema (embedded source of truth; schema/ file generated)
# ---------------------------------------------------------------------------

_REMEDIATION_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "required": ["proposal", "why", "commands", "impact", "rollback"],
    "properties": {
        "proposal": {"type": "string"},
        "why": {"type": "string"},
        "commands": {"type": "array", "items": {"type": "string"}},
        "impact": {"type": "string"},
        "rollback": {"type": "string"},
    },
    "additionalProperties": False,
}

_ISSUE_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "required": ["issue", "evidence", "remediation"],
    "properties": {
        "issue": {"type": "string"},
        "evidence": {"type": "array", "items": {"type": "string"}},
        "remediation": _REMEDIATION_SCHEMA,
    },
    "additionalProperties": False,
}

_AREA_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "required": ["area", "verdict", "summary", "expectation",
                 "evidence", "evidence_complete", "issues"],
    "properties": {
        "area": {"enum": list(AREAS)},
        "verdict": {"enum": list(ALL_VERDICTS)},
        "summary": {"type": "string"},
        "expectation": {"type": "string"},
        "evidence": {"type": "array", "items": {"type": "string"}},
        "evidence_complete": {"type": "boolean"},
        "issues": {"type": "array", "items": _ISSUE_SCHEMA},
        "decision": {"type": ["string", "null"]},
        "reassess_when": {"type": ["string", "null"]},
    },
    "additionalProperties": False,
}

ASSESSMENT_SCHEMA: Dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "atlas-hardening-assessment.v1",
    "title": "Atlas hardening assessment (schema v1)",
    "type": "object",
    "required": ["run", "consumed_inventory", "areas"],
    "properties": {
        "run": {
            "type": "object",
            "required": ["run_id", "assessor_version", "schema_version",
                         "started_at", "finished_at", "executing_account",
                         "hostname", "complete"],
            "properties": {
                "run_id": {"type": "string"},
                "assessor_version": {"type": "string"},
                "schema_version": {"enum": [ASSESSMENT_SCHEMA_VERSION]},
                "started_at": {"type": "string"},
                "finished_at": {"type": "string"},
                "executing_account": {"type": "string"},
                "hostname": {"type": "string"},
                "complete": {"type": "boolean"},
            },
            "additionalProperties": False,
        },
        "consumed_inventory": {
            "type": "object",
            "required": ["run_id", "path", "age_hours", "stale"],
            "properties": {
                "run_id": {"type": "string"},
                "path": {"type": "string"},
                "age_hours": {"type": "number"},
                "stale": {"type": "boolean"},
            },
            "additionalProperties": False,
        },
        "supplementary_probes": {
            "type": "object",
            "additionalProperties": inv._ENVELOPE_SCHEMA,
        },
        "areas": {"type": "array", "items": _AREA_SCHEMA},
    },
    "additionalProperties": False,
}


# ---------------------------------------------------------------------------
# Evidence layer
# ---------------------------------------------------------------------------


class FatalAssessmentError(Exception):
    """Raised when the assessment cannot produce trustworthy verdicts."""


def find_latest_report(directory: str) -> Optional[str]:
    reports = sorted(globmod.glob(os.path.join(directory, "report-*.json")))
    return reports[-1] if reports else None


def load_inventory_report(path: str,
                          max_age_hours: float = DEFAULT_MAX_REPORT_AGE_HOURS,
                          now: Optional[datetime.datetime] = None
                          ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Load + schema-validate an inventory report; compute staleness.

    Returns (report, consumed_inventory_block). Raises FatalAssessmentError
    on unreadable or schema-invalid input — no verdicts from bad evidence.
    """
    try:
        with open(path, "r", encoding="utf-8") as handle:
            report = json.load(handle)
    except (OSError, ValueError) as exc:
        raise FatalAssessmentError("cannot read inventory report %s: %s"
                                   % (path, exc))
    errors = inv.schema_validate(report, inv.REPORT_SCHEMA)
    if errors:
        raise FatalAssessmentError(
            "inventory report failed schema validation: %s"
            % "; ".join(errors[:10]))
    now = now or datetime.datetime.now(tz=datetime.timezone.utc)
    try:
        finished = datetime.datetime.fromisoformat(report["run"]["finished_at"])
        age_hours = max((now - finished).total_seconds() / 3600.0, 0.0)
    except ValueError:
        age_hours = float("inf")
    consumed = {
        "run_id": report["run"]["run_id"],
        "path": path,
        "age_hours": round(age_hours, 1) if age_hours != float("inf") else -1.0,
        "stale": age_hours > max_age_hours,
    }
    return report, consumed


def run_supplementary_probes(execute: Optional[Any] = None) -> Dict[str, Any]:
    return {probe.item_id: inv.run_probe(probe, execute)
            for probe in SUPPLEMENTARY_PROBES}


@dataclass
class Evidence:
    """Uniform accessor over inventory items and supplementary probes."""

    inventory: Dict[str, Any]
    probes: Dict[str, Any]

    def inv_item(self, category: str, item: str) -> Optional[Dict[str, Any]]:
        return (self.inventory.get("categories", {})
                .get(category, {}).get("items", {}).get(item))

    def inv_data(self, category: str, item: str) -> Optional[Dict[str, Any]]:
        envelope = self.inv_item(category, item)
        if envelope and envelope.get("status") == inv.STATUS_COLLECTED:
            return envelope.get("data") or {}
        return None

    def inv_ref(self, category: str, item: str) -> str:
        return "inventory:%s:%s.%s" % (
            self.inventory.get("run", {}).get("run_id", "?"), category, item)

    def probe_data(self, item_id: str) -> Optional[Dict[str, Any]]:
        envelope = self.probes.get(item_id)
        if envelope and envelope.get("status") == inv.STATUS_COLLECTED:
            return envelope.get("data") or {}
        return None

    def probe_ref(self, item_id: str) -> str:
        return "probe:%s" % item_id


# ---------------------------------------------------------------------------
# Verdict model
# ---------------------------------------------------------------------------


@dataclass
class Issue:
    issue: str
    evidence: List[str]
    proposal: str
    why: str
    commands: List[str]
    impact: str
    rollback: str

    def as_dict(self) -> Dict[str, Any]:
        return {
            "issue": self.issue,
            "evidence": self.evidence,
            "remediation": {
                "proposal": self.proposal,
                "why": self.why,
                "commands": self.commands,
                "impact": self.impact,
                "rollback": self.rollback,
            },
        }


@dataclass
class AreaResult:
    area: str
    verdict: str
    summary: str
    evidence: List[str] = field(default_factory=list)
    evidence_complete: bool = True
    issues: List[Issue] = field(default_factory=list)
    decision: Optional[str] = None
    reassess_when: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "area": self.area,
            "verdict": self.verdict,
            "summary": self.summary,
            "expectation": EXPECTATIONS[self.area],
            "evidence": self.evidence,
            "evidence_complete": self.evidence_complete,
            "issues": [issue.as_dict() for issue in self.issues],
            "decision": self.decision,
            "reassess_when": self.reassess_when,
        }


def _missing_evidence(area: str, what: str, refs: List[str]) -> AreaResult:
    """Missing evidence is itself a finding — never an assumption."""
    return AreaResult(
        area=area, verdict=VERDICT_FINDING,
        summary="Evidence unavailable: %s. No state was assumed." % what,
        evidence=refs, evidence_complete=False,
        issues=[Issue(
            issue="insufficient evidence: %s" % what,
            evidence=refs,
            proposal="Re-run the device inventory (privileged if the gap was "
                     "permission-denied), then re-assess.",
            why="ATLAS-ENV-003 requires observed state; this area could not "
                "be observed.",
            commands=["python3 inventory/atlas_inventory.py run "
                      "--output-dir var/inventory",
                      "python3 hardening/atlas_hardening.py assess"],
            impact="None — evidence gathering only.",
            rollback="Not applicable.",
        )])


# ---------------------------------------------------------------------------
# Area evaluators (pure functions: Evidence -> AreaResult)
# ---------------------------------------------------------------------------


def _eval_unprivileged_services(ev: Evidence) -> AreaResult:
    hermes = ev.inv_data("hermes_installation", "hermes_files")
    refs = [ev.inv_ref("hermes_installation", "hermes_files")]
    if hermes is None:
        return _missing_evidence("unprivileged-service-execution",
                                 "hermes installation state", refs)
    if hermes.get("matches"):
        return AreaResult(
            "unprivileged-service-execution", VERDICT_FINDING,
            "Hermes material exists before a service-account design was "
            "approved.", refs,
            issues=[Issue(
                "Hermes files present pre-Phase-1", refs,
                proposal="Review how the existing Hermes material runs and as "
                         "which user before Phase 1.",
                why="ATLAS-HERMES-002 requires a dedicated unprivileged "
                    "account.",
                commands=["# review only"], impact="None.", rollback="N/A.")])
    return AreaResult(
        "unprivileged-service-execution", VERDICT_NA,
        "No Atlas or Hermes services exist yet on the clean baseline; the "
        "dedicated unprivileged service account is designed in Phase 1.",
        refs, reassess_when="Phase 1 Hermes installation "
                            "(atlas-phase-1-hermes-baseline)")


_STOCK_PUBLIC_PORTS = {"22"}  # sshd expected; everything else non-loopback is reviewed


def _eval_ssh_and_ports(ev: Evidence) -> AreaResult:
    sshd = ev.inv_data("remote_access", "sshd_config")
    sockets = ev.inv_data("listening_ports", "sockets")
    refs = [ev.inv_ref("remote_access", "sshd_config"),
            ev.inv_ref("listening_ports", "sockets")]
    if sshd is None or sockets is None:
        return _missing_evidence("ssh-authentication-and-exposed-ports",
                                 "sshd configuration and/or socket list", refs)
    directives = sshd.get("directives", {})
    issues: List[Issue] = []

    password_auth = directives.get("passwordauthentication", [])
    if not password_auth or password_auth[-1].lower() != "no":
        observed = (password_auth[-1] if password_auth
                    else "absent (Debian default: yes)")
        issues.append(Issue(
            "SSH password authentication enabled (observed: %s)" % observed,
            [refs[0]],
            proposal="Disable SSH password authentication (key-only login).",
            why="Password auth on a LAN device invites brute force; key auth "
                "is already working (operator uses it).",
            commands=[
                "# verify key login works FIRST, in a second session",
                "sudo sed -i 's/^#\\?PasswordAuthentication.*/"
                "PasswordAuthentication no/' /etc/ssh/sshd_config",
                "sudo systemctl reload ssh",
            ],
            impact="Password logins stop working; key access must be "
                   "confirmed before applying or you can be locked out "
                   "(physical console remains a recovery path).",
            rollback="Set 'PasswordAuthentication yes' and reload ssh."))

    x11 = directives.get("x11forwarding", [])
    if x11 and x11[-1].lower() == "yes":
        issues.append(Issue(
            "X11Forwarding enabled", [refs[0]],
            proposal="Disable X11 forwarding over SSH.",
            why="Unneeded attack surface on a headless agent device.",
            commands=["sudo sed -i 's/^#\\?X11Forwarding.*/"
                      "X11Forwarding no/' /etc/ssh/sshd_config",
                      "sudo systemctl reload ssh"],
            impact="No X11 apps over SSH (none are needed for Atlas).",
            rollback="Set 'X11Forwarding yes' and reload ssh."))

    exposed = []
    for line in sockets.get("text_lines", []):
        parts = line.split()
        if len(parts) >= 5 and parts[1] in ("LISTEN", "UNCONN"):
            local = parts[4]
            address, _, port = local.rpartition(":")
            if (address in ("0.0.0.0", "*", "[::]", "::")
                    and port.isdigit() and port not in _STOCK_PUBLIC_PORTS):
                exposed.append("%s %s" % (parts[0], local))
    if any("111" == entry.rsplit(":", 1)[-1] for entry in exposed):
        issues.append(Issue(
            "rpcbind listening on all interfaces (port 111)", [refs[1]],
            proposal="Disable rpcbind (NFS is not used by Atlas).",
            why="Historic remote-attack surface with no purpose here.",
            commands=["sudo systemctl disable --now rpcbind.socket "
                      "rpcbind.service"],
            impact="NFS/rpc services stop working (none are planned).",
            rollback="sudo systemctl enable --now rpcbind.socket"))
    mdns = [entry for entry in exposed if entry.endswith(":5353")]
    if mdns:
        issues.append(Issue(
            "mDNS (avahi) advertising on the network (port 5353)",
            [refs[1]],
            proposal="Disable avahi-daemon unless LAN discovery of the Pi "
                     "is wanted (operator preference).",
            why="Reduces broadcast surface; purely optional on a trusted LAN.",
            commands=["sudo systemctl disable --now avahi-daemon.socket "
                      "avahi-daemon.service"],
            impact="raspberrypi.local name resolution stops; use the IP or "
                   "DHCP reservation instead.",
            rollback="sudo systemctl enable --now avahi-daemon.service"))

    verdict = VERDICT_FINDING if issues else VERDICT_OK
    summary = ("%d SSH/exposure issue(s) observed." % len(issues) if issues
               else "SSH configuration and exposed ports meet the baseline.")
    return AreaResult("ssh-authentication-and-exposed-ports", verdict,
                      summary, refs, issues=issues)


def _eval_firewall(ev: Evidence) -> AreaResult:
    refs = []
    statuses = {}
    for item in ("ufw_status", "nftables_ruleset", "iptables_rules"):
        envelope = ev.inv_item("firewall", item)
        refs.append(ev.inv_ref("firewall", item))
        statuses[item] = envelope.get("status") if envelope else None
    if any(status is None for status in statuses.values()):
        return _missing_evidence("firewall-rules", "firewall tooling state",
                                 refs)
    if any(status == inv.STATUS_DENIED for status in statuses.values()):
        return _missing_evidence(
            "firewall-rules",
            "firewall rules unreadable unprivileged", refs)
    nft = ev.inv_data("firewall", "nftables_ruleset")
    if nft and any(line.strip() for line in nft.get("text_lines", [])):
        return AreaResult("firewall-rules", VERDICT_OK,
                          "An nftables ruleset is present (review its "
                          "default-deny posture in the plan).", refs)
    ufw = ev.inv_data("firewall", "ufw_status")
    if ufw and any("Status: active" in line
                   for line in ufw.get("text_lines", [])):
        return AreaResult("firewall-rules", VERDICT_OK,
                          "ufw is active.", refs)
    return AreaResult(
        "firewall-rules", VERDICT_FINDING,
        "No host firewall is installed or active.", refs,
        issues=[Issue(
            "no firewall tooling present (ufw/nft/iptables all absent or "
            "empty)", refs,
            proposal="Install nftables with a default-deny inbound policy "
                     "allowing loopback, established traffic, and SSH.",
            why="ATLAS-SEC-004 and the PRD's local-binding posture assume "
                "host-level control of inbound traffic; the fresh install "
                "has none.",
            commands=[
                "sudo apt install nftables",
                "# write /etc/nftables.conf: policy drop on input; accept "
                "lo, ct state established,related, tcp dport 22",
                "sudo systemctl enable --now nftables",
                "# verify SSH still works from a SECOND session before "
                "closing the first",
            ],
            impact="Inbound traffic other than SSH is dropped; any future "
                   "service (health endpoint, frontend) needs an explicit "
                   "rule — which is exactly the intended posture.",
            rollback="sudo systemctl disable --now nftables (console access "
                     "as fallback if SSH is cut).")])


def _eval_unattended_updates(ev: Evidence) -> AreaResult:
    data = ev.probe_data("auto_upgrades_config")
    refs = [ev.probe_ref("auto_upgrades_config")]
    if data is None:
        return _missing_evidence("unattended-security-updates",
                                 "apt auto-upgrade configuration", refs)
    if data.get("present") is False:
        return AreaResult(
            "unattended-security-updates", VERDICT_FINDING,
            "Unattended security updates are not configured.", refs,
            issues=[Issue(
                "no unattended-upgrades configuration present", refs,
                proposal="Install and enable unattended-upgrades for "
                         "security updates.",
                why="A long-running headless device needs security patches "
                    "without manual attention; ATLAS-SEC-006 excludes only "
                    "automatic MAJOR upgrades, not security patches.",
                commands=["sudo apt install unattended-upgrades",
                          "sudo dpkg-reconfigure -plow unattended-upgrades"],
                impact="Security updates apply automatically (Debian "
                       "security pocket only by default); reboots remain "
                       "manual.",
                rollback="sudo dpkg-reconfigure -plow unattended-upgrades "
                         "(disable), or remove the package.")])
    enabled = False
    for entry in data.get("files", []):
        content = entry.get("content", "")
        if ("APT::Periodic::Unattended-Upgrade" in content
                and '"1"' in content.split(
                    "APT::Periodic::Unattended-Upgrade", 1)[1][:20]):
            enabled = True
    if enabled:
        return AreaResult("unattended-security-updates", VERDICT_OK,
                          "Unattended upgrades are enabled.", refs)
    return AreaResult(
        "unattended-security-updates", VERDICT_FINDING,
        "Unattended-upgrades config exists but the periodic run is not "
        "enabled.", refs,
        issues=[Issue(
            "APT::Periodic::Unattended-Upgrade not set to 1", refs,
            proposal="Enable the periodic unattended-upgrade run.",
            why="Config present but inert provides no patching.",
            commands=["sudo dpkg-reconfigure -plow unattended-upgrades"],
            impact="Security updates apply automatically.",
            rollback="Re-run and disable.")])


_PUBLIC_PATH_MARKERS = ("/etc/ssl/certs/", "/etc/xdg/", ".desktop")


def _eval_secret_file_permissions(ev: Evidence) -> AreaResult:
    data = ev.inv_data("secret_file_locations", "secret_files")
    refs = [ev.inv_ref("secret_file_locations", "secret_files")]
    if data is None:
        return _missing_evidence("secret-file-permissions",
                                 "secret file locations", refs)
    issues: List[Issue] = []
    for entry in data.get("paths", []):
        path = entry.get("path", "")
        mode = entry.get("mode")
        if not mode or any(marker in path for marker in _PUBLIC_PATH_MARKERS):
            continue
        try:
            loose = int(mode, 8) & 0o077
        except ValueError:
            continue
        if loose:
            issues.append(Issue(
                "secret-pattern file readable beyond owner: %s (mode %s)"
                % (path, mode), refs,
                proposal="Tighten permissions to owner-only.",
                why="ATLAS-SEC-002: secrets must be readable only by the "
                    "account that needs them.",
                commands=["sudo chmod 600 '%s'" % path],
                impact="Other accounts lose read access (verify nothing "
                       "legitimately reads it first).",
                rollback="Restore the previous mode (%s)." % mode))
    verdict = VERDICT_FINDING if issues else VERDICT_OK
    summary = ("%d loosely-permissioned secret-pattern file(s)." % len(issues)
               if issues else
               "All secret-pattern files are owner-only (public cert stores "
               "excluded).")
    return AreaResult("secret-file-permissions", verdict, summary, refs,
                      issues=issues)


def _eval_log_permissions(ev: Evidence) -> AreaResult:
    data = ev.probe_data("var_log_perms")
    refs = [ev.probe_ref("var_log_perms")]
    if data is None:
        return _missing_evidence("log-permissions", "/var/log permissions",
                                 refs)
    issues: List[Issue] = []
    for entry in data.get("matches", []):
        mode = entry.get("mode")
        path = entry.get("path", "")
        if not mode:
            continue
        try:
            world_writable = int(mode, 8) & 0o002
        except ValueError:
            continue
        if world_writable and entry.get("type") != "symlink":
            issues.append(Issue(
                "world-writable log path: %s (mode %s)" % (path, mode), refs,
                proposal="Remove world-write permission.",
                why="World-writable logs allow tampering with audit trails.",
                commands=["sudo chmod o-w '%s'" % path],
                impact="Non-privileged processes can no longer write it "
                       "directly (normal logging goes via syslog/journald).",
                rollback="Restore the previous mode (%s)." % mode))
    verdict = VERDICT_FINDING if issues else VERDICT_OK
    summary = ("%d world-writable log path(s)." % len(issues) if issues
               else "No world-writable files under /var/log.")
    return AreaResult("log-permissions", verdict, summary, refs, issues=issues)


def _eval_backup(ev: Evidence) -> AreaResult:
    tools = ev.inv_data("backup_configuration", "backup_tools")
    refs = [ev.inv_ref("backup_configuration", "backup_tools"),
            ev.inv_ref("backup_configuration", "backup_configs")]
    installed = ([name for name, path in tools.get("tools", {}).items()
                  if path] if tools else [])
    return AreaResult(
        "backup-encryption-and-destination", VERDICT_DECISION,
        "No backup tooling or destination exists (observed: %s). The "
        "destination is an operator decision the assessor must not invent."
        % (", ".join(installed) if installed else "none installed"),
        refs, evidence_complete=tools is not None,
        decision="PRD §21 Q10: select an external/remote encrypted backup "
                 "destination (ATLAS-BACKUP-002 rejects same-NVMe-only "
                 "backups). Tool proposal (e.g. restic) follows the "
                 "destination choice.")


def _eval_restart_policy(ev: Evidence) -> AreaResult:
    data = ev.probe_data("sshd_restart_policy")
    refs = [ev.probe_ref("sshd_restart_policy")]
    if data is None:
        return _missing_evidence("service-restart-policy",
                                 "sshd restart policy", refs)
    lines = data.get("text_lines", [])
    restart = ""
    for line in lines:
        if line.startswith("Restart="):
            restart = line.partition("=")[2].strip()
    if restart in ("on-failure", "always"):
        return AreaResult(
            "service-restart-policy", VERDICT_OK,
            "sshd restart policy is '%s'. Atlas/Hermes service policies are "
            "designed at Phase 1 install." % restart, refs)
    return AreaResult(
        "service-restart-policy", VERDICT_FINDING,
        "sshd restart policy is '%s' (expected on-failure/always)."
        % (restart or "unknown"), refs,
        issues=[Issue(
            "sshd lacks a restart-on-failure policy", refs,
            proposal="Add a systemd drop-in setting Restart=on-failure for "
                     "ssh.service.",
            why="SSH is the only management path to the headless device; it "
                "should self-recover.",
            commands=["sudo systemctl edit ssh.service  # add "
                      "[Service] Restart=on-failure"],
            impact="sshd restarts automatically after crashes.",
            rollback="Remove the drop-in and daemon-reload.")])


def _eval_time_sync(ev: Evidence) -> AreaResult:
    data = ev.probe_data("time_sync")
    refs = [ev.probe_ref("time_sync")]
    if data is None:
        return _missing_evidence("time-synchronization",
                                 "timedatectl properties", refs)
    props = {}
    for line in data.get("text_lines", []):
        key, _, value = line.partition("=")
        props[key.strip()] = value.strip()
    if props.get("NTP") == "yes" and props.get("NTPSynchronized") == "yes":
        return AreaResult("time-synchronization", VERDICT_OK,
                          "NTP is active and synchronized (timezone: %s)."
                          % props.get("Timezone", "?"), refs)
    return AreaResult(
        "time-synchronization", VERDICT_FINDING,
        "NTP not active/synchronized (NTP=%s, NTPSynchronized=%s)."
        % (props.get("NTP", "?"), props.get("NTPSynchronized", "?")), refs,
        issues=[Issue(
            "time synchronization not confirmed", refs,
            proposal="Enable systemd-timesyncd NTP synchronization.",
            why="Atlas freshness and provenance guarantees depend on honest "
                "timestamps (PRD §5.2).",
            commands=["sudo timedatectl set-ntp true"],
            impact="System clock tracks NTP.",
            rollback="sudo timedatectl set-ntp false")])


def _eval_disk_thresholds(ev: Evidence) -> AreaResult:
    data = ev.inv_data("cpu_memory_storage", "filesystem_usage")
    refs = [ev.inv_ref("cpu_memory_storage", "filesystem_usage")]
    root_use = "?"
    if data:
        for filesystem in data.get("filesystems", []):
            if filesystem.get("mounted_on") == "/":
                root_use = filesystem.get("use_percent", "?")
    return AreaResult(
        "disk-space-thresholds", VERDICT_DECISION,
        "No thresholds are defined yet. Observed root filesystem usage: %s. "
        "Proposed candidates: warn at 80%%, stop nonessential "
        "ingestion/retention at 90%% (ATLAS-BACKUP-005)." % root_use,
        refs, evidence_complete=data is not None,
        decision="Confirm or adjust the proposed 80%/90% disk thresholds; "
                 "they become configuration in the Atlas service phases.")


def _eval_frontend_exposure(ev: Evidence) -> AreaResult:
    return AreaResult(
        "remote-frontend-exposure", VERDICT_NA,
        "No frontend exists yet. Principle on record: bind to localhost by "
        "default; any LAN/remote exposure needs an explicit approved design "
        "(ATLAS-SEC-004, ATLAS-OPS-006).",
        [], reassess_when="Phase 6 monitoring frontend "
                          "(atlas-phase-6-monitoring-frontend)")


EVALUATORS = {
    "unprivileged-service-execution": _eval_unprivileged_services,
    "ssh-authentication-and-exposed-ports": _eval_ssh_and_ports,
    "firewall-rules": _eval_firewall,
    "unattended-security-updates": _eval_unattended_updates,
    "secret-file-permissions": _eval_secret_file_permissions,
    "log-permissions": _eval_log_permissions,
    "backup-encryption-and-destination": _eval_backup,
    "service-restart-policy": _eval_restart_policy,
    "time-synchronization": _eval_time_sync,
    "disk-space-thresholds": _eval_disk_thresholds,
    "remote-frontend-exposure": _eval_frontend_exposure,
}
assert set(EVALUATORS) == set(AREAS)


def assess(inventory_report: Dict[str, Any],
           probes: Dict[str, Any]) -> List[AreaResult]:
    evidence = Evidence(inventory_report, probes)
    results = []
    for area in AREAS:  # fixed order; omission structurally impossible
        try:
            results.append(EVALUATORS[area](evidence))
        except Exception as exc:  # noqa: BLE001 — one evaluator must not sink the run
            results.append(_missing_evidence(
                area, "evaluator failed: %s" % exc, []))
    return results


# ---------------------------------------------------------------------------
# Outputs
# ---------------------------------------------------------------------------


def _utc_now() -> str:
    return datetime.datetime.now(tz=datetime.timezone.utc).isoformat()


def _account() -> str:
    try:
        return getpass.getuser()
    except Exception:  # noqa: BLE001
        return "unknown"


def _write_private(path: str, content: str) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(inv.redact(content))


def build_assessment(consumed: Dict[str, Any], probes: Dict[str, Any],
                     results: List[AreaResult], started_at: str,
                     run_id: str) -> Dict[str, Any]:
    complete = all(result.evidence_complete for result in results)
    return {
        "run": {
            "run_id": run_id,
            "assessor_version": ASSESSOR_VERSION,
            "schema_version": ASSESSMENT_SCHEMA_VERSION,
            "started_at": started_at,
            "finished_at": _utc_now(),
            "executing_account": _account(),
            "hostname": socket.gethostname(),
            "complete": complete,
        },
        "consumed_inventory": consumed,
        "supplementary_probes": probes,
        "areas": [result.as_dict() for result in results],
    }


_VERDICT_BADGES = {
    VERDICT_OK: "✅ ok",
    VERDICT_FINDING: "⚠️ finding",
    VERDICT_DECISION: "🟡 decision required",
    VERDICT_NA: "⏸ not applicable yet",
}


def render_plan(assessment: Dict[str, Any]) -> str:
    run = assessment["run"]
    consumed = assessment["consumed_inventory"]
    lines = [
        "# Proposed hardening plan — run %s" % run["run_id"],
        "",
        "Assessment of `%s` on %s, from inventory run `%s` (age %.1f h%s)."
        % (run["hostname"], run["started_at"], consumed["run_id"],
           consumed["age_hours"],
           ", STALE — consider re-running the inventory"
           if consumed["stale"] else ""),
        "",
        "**Nothing in this plan has been executed.** Every item below is a",
        "proposal requiring explicit operator approval; application happens",
        "only through a separate approved OpenSpec change (ATLAS-ENV-003).",
        "Tick `[x] approved` on items you accept; strike or annotate the",
        "rest. `decision required` items need answers in docs/decisions.md.",
        "",
        "## Verdict summary",
        "",
        "| Area | Verdict | Summary |",
        "|---|---|---|",
    ]
    for area in assessment["areas"]:
        lines.append("| %s | %s | %s |" % (
            area["area"], _VERDICT_BADGES[area["verdict"]],
            area["summary"].replace("|", "\\|")))
    lines += ["", "## Proposed changes", ""]
    item_number = 0
    for area in assessment["areas"]:
        for issue in area["issues"]:
            item_number += 1
            remediation = issue["remediation"]
            lines += [
                "### %d. %s" % (item_number, remediation["proposal"]),
                "",
                "- [ ] approved",
                "",
                "**Area:** %s" % area["area"],
                "**Issue:** %s" % issue["issue"],
                "**Why:** %s" % remediation["why"],
                "**Evidence:** %s" % ", ".join("`%s`" % ref
                                               for ref in issue["evidence"]),
                "**Impact:** %s" % remediation["impact"],
                "**Rollback:** %s" % remediation["rollback"],
                "",
                "Commands that WOULD run (not executed):",
                "",
                "```sh",
            ]
            lines += remediation["commands"]
            lines += ["```", ""]
    if item_number == 0:
        lines += ["_No findings — no changes proposed._", ""]
    decisions = [area for area in assessment["areas"]
                 if area["verdict"] == VERDICT_DECISION]
    if decisions:
        lines += ["## Decisions required (answer in docs/decisions.md)", ""]
        for area in decisions:
            lines += ["- **%s** — %s" % (area["area"], area["decision"]), ""]
    incomplete = [area["area"] for area in assessment["areas"]
                  if not area["evidence_complete"]]
    if incomplete:
        lines += ["## Incomplete evidence", "",
                  "These areas could not be fully observed: %s. Their "
                  "verdicts state so explicitly; nothing was assumed."
                  % ", ".join(incomplete), ""]
    return "\n".join(lines)


def build_audit(run_id: str, started_at: str, outputs: List[str],
                results: Optional[List[AreaResult]],
                fatal: Optional[str]) -> Dict[str, Any]:
    verdict_counts: Optional[Dict[str, int]] = None
    if results is not None:
        verdict_counts = {verdict: 0 for verdict in ALL_VERDICTS}
        for result in results:
            verdict_counts[result.verdict] += 1
    return {
        "run_id": run_id,
        "started_at": started_at,
        "finished_at": _utc_now(),
        "assessor_version": ASSESSOR_VERSION,
        "schema_version": ASSESSMENT_SCHEMA_VERSION,
        "executing_account": _account(),
        "outputs": outputs,
        "verdict_counts": verdict_counts,
        "fatal": inv.redact(fatal) if fatal else None,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def cmd_assess(inventory_report_path: Optional[str], output_dir: str,
               max_age_hours: float,
               execute: Optional[Any] = None) -> int:
    os.makedirs(output_dir, exist_ok=True)
    started_at = _utc_now()
    run_id = (time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
              + "-" + secretsmod.token_hex(4))
    outputs: List[str] = []
    results: Optional[List[AreaResult]] = None
    fatal: Optional[str] = None
    try:
        path = inventory_report_path or find_latest_report(
            os.path.join("var", "inventory"))
        if not path:
            raise FatalAssessmentError(
                "no inventory report found in var/inventory/ — run the "
                "inventory first, or pass --inventory-report")
        report, consumed = load_inventory_report(path, max_age_hours)
        if consumed["stale"]:
            print("WARNING: inventory report is %.1f hours old (max %.0f) — "
                  "consider re-running the inventory."
                  % (consumed["age_hours"], max_age_hours), file=sys.stderr)
        probes = run_supplementary_probes(execute)
        results = assess(report, probes)
        assessment = build_assessment(consumed, probes, results, started_at,
                                      run_id)
        validation_errors = inv.schema_validate(assessment, ASSESSMENT_SCHEMA)
        if validation_errors:
            fatal = ("assessment failed schema validation: "
                     + "; ".join(validation_errors[:20]))
            print("FATAL: %s" % fatal, file=sys.stderr)
            return 1
        assessment_path = os.path.join(output_dir,
                                       "assessment-%s.json" % run_id)
        _write_private(assessment_path,
                       json.dumps(assessment, indent=2, sort_keys=True))
        outputs.append(assessment_path)
        plan_path = os.path.join(output_dir,
                                 "hardening-plan-%s.md" % run_id)
        _write_private(plan_path, render_plan(assessment))
        outputs.append(plan_path)
        counts = {verdict: 0 for verdict in ALL_VERDICTS}
        for result in results:
            counts[result.verdict] += 1
        complete = assessment["run"]["complete"]
        print("Assessment %s finished: %s"
              % (run_id, ", ".join("%s=%d" % item for item in counts.items())))
        print("Assessment: %s" % assessment_path)
        print("Plan:       %s" % plan_path)
        if not complete:
            print("INCOMPLETE evidence for some areas — see the plan.")
        return 0 if complete else 3
    except FatalAssessmentError as exc:
        fatal = str(exc)
        print("FATAL: %s" % inv.redact(fatal), file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 — fail visibly, audit the failure
        fatal = "unhandled failure: %s" % exc
        print("FATAL: %s" % inv.redact(str(exc)), file=sys.stderr)
        return 1
    finally:
        try:
            audit = build_audit(run_id, started_at, outputs, results, fatal)
            audit_path = os.path.join(output_dir, "audit-%s.json" % run_id)
            _write_private(audit_path,
                           json.dumps(audit, indent=2, sort_keys=True))
            print("Audit:      %s" % audit_path)
        except Exception as audit_exc:  # noqa: BLE001
            print("WARNING: audit record could not be written: %s"
                  % audit_exc, file=sys.stderr)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="atlas_hardening",
        description="Read-only hardening assessment (ATLAS-ENV-003). "
                    "Assesses, never assumes; proposes, never applies.")
    subparsers = parser.add_subparsers(dest="subcommand", required=True)
    assess_parser = subparsers.add_parser(
        "assess", help="run a full hardening assessment")
    assess_parser.add_argument("--inventory-report", default=None,
                               help="path to an inventory report JSON "
                                    "(default: newest in var/inventory/)")
    assess_parser.add_argument("--output-dir",
                               default=os.path.join("var", "hardening"))
    assess_parser.add_argument("--max-report-age-hours", type=float,
                               default=DEFAULT_MAX_REPORT_AGE_HOURS)
    subparsers.add_parser("dump-schema",
                          help="print the assessment JSON schema")
    args = parser.parse_args(argv)
    if args.subcommand == "assess":
        return cmd_assess(args.inventory_report, args.output_dir,
                          args.max_report_age_hours)
    if args.subcommand == "dump-schema":
        print(json.dumps(ASSESSMENT_SCHEMA, indent=2))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
