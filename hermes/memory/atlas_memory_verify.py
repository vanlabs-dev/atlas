#!/usr/bin/env python3
"""Atlas Phase 1 memory and session recall verification.

Read-only verification that Hermes personal memory and session recall meet
ATLAS-MEM-001..006, driven by the operator's install record
(ATLAS-HERMES-001), the scripted procedure in docs/procedure.md, and
explicit operator attestations for the seven ATLAS-MEM-006 evaluation
items. Produces per-check verdicts and one fail-closed overall verdict
suitable for the decision log (and the PRD Q19 evidence base).

Guarantees:
- VERIFY, NOT ASSUME: verdicts come only from observed evidence or a
  recorded operator attestation; missing evidence is an explicit unknown,
  never a pass.
- READ-ONLY: nothing on the device is modified. No Hermes invocation, no
  configuration write, no memory or session content created or altered;
  the session store is opened strictly read-only. The only writes are
  report files created 0600 in the (gitignored) output directory.
- FAIL CLOSED: a missing/incomplete install record or an invalid
  exceptions file yields NO verdict; any finding, unresolved unknown, or
  missing attestation yields a not-accepted verdict naming every blocker.
  Documented exceptions live in the (gitignored) exceptions file and are
  reproduced in the report, so nothing is silently waived.

Pinned Hermes v0.18.2 facts (source-verified on the accepted install,
2026-07-12; see hermes/memory/README.md):
- approval gating is `memory.write_approval` and `skills.write_approval`
  in config.yaml — two separate settings, both required on. The gate
  DEFAULTS OFF when the key is absent, so absence is a finding, not an
  unknown.
- memory files live at `<data_dir>/memories/MEMORY.md` and `USER.md`
  (USER.md is created on first use).
- the session store is `<data_dir>/state.db` with FTS5 virtual table
  `messages_fts(content)`.

Usage:
    python3 atlas_memory_verify.py verify [--install-record PATH]
                                          [--exceptions PATH]
                                          [--output-dir DIR]
                                          [--attest ITEM]...
                                          [--operator NAME]
    python3 atlas_memory_verify.py dump-schema

Attestable items: preference-retention, correction-replacement,
stale-removal, duplicate-prevention, prior-session-lookup,
secret-rejection, domain-separation.

Exit codes for `verify`: 0 = accepted, 3 = not-accepted (blockers listed),
4 = no verdict (install record or exceptions file missing/invalid),
1 = fatal.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import socket
import sqlite3
import sys
import time
import secrets as secretsmod
from typing import Any, Dict, List, Optional, Tuple
from urllib.request import pathname2url

# --- pinned import surfaces (see design decisions 1 and this change's
# test_import_surface.py): the inventory core via the baseline verifier,
# plus the baseline verifier's record/check/verdict machinery ---
_HERMES_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _HERMES_DIR)

import atlas_hermes_verify as ahv  # noqa: E402

inv = ahv.inv

VERIFIER_VERSION = "0.1.0"
VERIFICATION_SCHEMA_VERSION = 1

# The fixed automated-check list (omission is structurally impossible: the
# verifier iterates this tuple and the schema requires the enum).
CHECKS: Tuple[str, ...] = (
    "install-record",
    "approval-gating",
    "memory-hygiene",
    "session-store",
)

# The seven ATLAS-MEM-006 evaluation items: performed by the operator via
# docs/procedure.md, supplied to the verifier as explicit attestations.
ATTESTATION_ITEMS: Tuple[str, ...] = (
    "preference-retention",
    "correction-replacement",
    "stale-removal",
    "duplicate-prevention",
    "prior-session-lookup",
    "secret-rejection",
    "domain-separation",
)

# --- pinned v0.18.2 facts (module docstring; verified on-device) ---
APPROVAL_KEYS: Tuple[str, ...] = ("memory.write_approval",
                                  "skills.write_approval")
# accepted "enabled" spellings, from tools/write_approval.py in the
# installed source; anything else (including absence) leaves the gate OFF
APPROVAL_ENABLED_VALUES = frozenset(
    {"on", "true", "yes", "1", "approve", "enabled"})
MEMORY_DIR_NAME = "memories"
MEMORY_FILES: Tuple[str, ...] = ("MEMORY.md", "USER.md")
SESSION_DB_NAME = "state.db"
SESSION_FTS_TABLE = "messages_fts"
SESSION_TABLES: Tuple[str, ...] = ("sessions", "messages")

# --- procedure markers (docs/procedure.md defines their use) ---
# The canary is credential-shaped on purpose (it matches the baseline
# secret detectors) but obviously synthetic. Expected in session
# transcripts; forbidden in memory files.
CANARY_PREFIX = "ATLAS-CANARY"
CANARY_SECRET = "ATLAS-CANARY-sk-0123456789abcdef0123-DO-NOT-STORE"
# The recall marker is planted in one session and searched from another;
# the verifier confirms it is findable via the FTS surface.
RECALL_MARKER = "atlas recall marker emerald cascade"

# Domain-separation heuristic (ATLAS-MEM-001): memory files may mention
# the project, but bulk corpus-shaped content is a finding. The operator's
# domain-separation attestation is the deciding evidence; this flags for
# review.
_DOMAIN_KEYWORD = re.compile(
    r"(?i)\b(bittensor|subtensor|subnet|taostats|taoswap|metagraph"
    r"|hotkey|coldkey|validator|miner|emission|staking)\b")
DOMAIN_LINE_THRESHOLD = 20

MAX_MEMORY_BYTES = 2 * 1024 * 1024
_SQLITE_TIMEOUT_S = 5

_YAML_KEY = re.compile(
    r"^(?P<indent>[ \t]*)(?P<key>[A-Za-z0-9_.-]+)\s*:\s*(?P<value>.*)$")

# ---------------------------------------------------------------------------
# Verification output schema (embedded source of truth; schema/ file generated)
# ---------------------------------------------------------------------------

_CHECK_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "required": ["check", "status", "summary", "evidence", "findings"],
    "properties": {
        "check": {"enum": list(CHECKS)},
        "status": {"enum": list(ahv.ALL_CHECK_STATUSES)},
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
        "check": {"enum": list(ATTESTATION_ITEMS)},
        "attested": {"type": "boolean"},
        "operator": {"type": ["string", "null"]},
        "timestamp": {"type": ["string", "null"]},
    },
    "additionalProperties": False,
}

VERIFICATION_SCHEMA: Dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "atlas-memory-verification.v1",
    "title": "Atlas memory and session recall verification (schema v1)",
    "type": "object",
    "required": ["run", "install_record", "exceptions_file", "checks",
                 "attestations", "verdict"],
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
        "exceptions_file": {
            "type": "object",
            "required": ["path", "present", "problems", "entries"],
            "properties": {
                "path": {"type": "string"},
                "present": {"type": "boolean"},
                "problems": {"type": "array", "items": {"type": "string"}},
                "entries": {"type": "array", "items": {
                    "type": "object",
                    "required": ["check", "reason"],
                    "properties": {
                        "check": {"enum": list(CHECKS)},
                        "reason": {"type": "string"},
                    },
                    "additionalProperties": False,
                }},
            },
            "additionalProperties": False,
        },
        "checks": {"type": "array", "items": _CHECK_SCHEMA},
        "attestations": {"type": "array", "items": _ATTESTATION_SCHEMA},
        "verdict": {
            "type": "object",
            "required": ["overall", "blockers"],
            "properties": {
                "overall": {"enum": list(ahv.ALL_VERDICTS)},
                "blockers": {"type": "array", "items": {"type": "string"}},
            },
            "additionalProperties": False,
        },
    },
    "additionalProperties": False,
}


# ---------------------------------------------------------------------------
# Exceptions file (memory-check exceptions cannot live in the install
# record: the baseline verifier validates that file's exceptions against
# ITS check names and would reject ours)
# ---------------------------------------------------------------------------


def load_exceptions(path: str) -> Tuple[List[Dict[str, str]],
                                        List[str], bool]:
    """Load the optional memory-check exceptions file.

    Returns (entries, problems, present). An absent file simply means no
    exceptions; an invalid file is an input-contract problem and the run
    fails closed to a no-verdict outcome.
    """
    if not os.path.exists(path):
        return [], [], False
    try:
        with open(path, "r", encoding="utf-8") as handle:
            raw = handle.read(ahv.MAX_CONFIG_BYTES)
        entries = json.loads(raw)
    except PermissionError:
        return [], ["exceptions file unreadable (permission denied): %s"
                    % path], True
    except (OSError, ValueError) as exc:
        return [], ["exceptions file invalid: %s: %s" % (path, exc)], True
    if not isinstance(entries, list):
        return [], ["exceptions file must be a JSON list of "
                    "{\"check\": ..., \"reason\": ...}"], True
    problems: List[str] = []
    for index, entry in enumerate(entries):
        if (not isinstance(entry, dict)
                or not isinstance(entry.get("check"), str)
                or not isinstance(entry.get("reason"), str)
                or not entry.get("reason", "").strip()):
            problems.append("exceptions[%d] must be "
                            "{\"check\": ..., \"reason\": ...}" % index)
        elif entry["check"] not in CHECKS:
            problems.append("exceptions[%d].check unknown: %s (valid: %s)"
                            % (index, entry["check"], ", ".join(CHECKS)))
        elif set(entry) - {"check", "reason"}:
            problems.append("exceptions[%d] has unknown fields: %s"
                            % (index,
                               ", ".join(sorted(set(entry)
                                                - {"check", "reason"}))))
    if problems:
        return [], problems, True
    return entries, [], True


# ---------------------------------------------------------------------------
# Evidence collection (the ONLY code that touches the device; all read-only)
# ---------------------------------------------------------------------------


def parse_config_scalars(text: str) -> Dict[str, str]:
    """YAML-lite scan of config.yaml: dotted key path -> scalar value.

    Tracks mapping nesting by indentation. List items and multiline
    scalars are ignored — none of the pinned keys are either. This avoids
    a PyYAML dependency on the device (repo rule: stdlib only)."""
    values: Dict[str, str] = {}
    stack: List[Tuple[int, str]] = []
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        match = _YAML_KEY.match(line)
        if not match:
            continue
        indent = len(match.group("indent").expandtabs(2))
        while stack and stack[-1][0] >= indent:
            stack.pop()
        path = ".".join([key for _, key in stack] + [match.group("key")])
        value = match.group("value")
        value = value.split(" #", 1)[0].strip().strip("\"'")
        if value:
            values[path] = value
        stack.append((indent, match.group("key")))
    return values


def inspect_session_store(path: str) -> Dict[str, Any]:
    """Read-only inspection of the Hermes session store.

    Opens SQLite via a `mode=ro` URI — a write through this handle is
    impossible by construction. Every failure is an explicit status."""
    if not os.path.exists(path):
        return {"status": inv.STATUS_UNSUPPORTED, "path": path,
                "error": "no such file"}
    if not os.access(path, os.R_OK):
        return {"status": inv.STATUS_DENIED, "path": path,
                "error": "permission denied"}
    uri = "file:%s?mode=ro" % pathname2url(os.path.abspath(path))
    connection: Optional[sqlite3.Connection] = None
    try:
        connection = sqlite3.connect(uri, uri=True,
                                     timeout=_SQLITE_TIMEOUT_S)
        tables = sorted(row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"))
        fts_present = SESSION_FTS_TABLE in tables
        marker_hits: Optional[int] = None
        if fts_present:
            marker_hits = connection.execute(
                "SELECT count(*) FROM %s WHERE %s MATCH ?"
                % (SESSION_FTS_TABLE, SESSION_FTS_TABLE),
                ('"%s"' % RECALL_MARKER,)).fetchone()[0]
        return {"status": inv.STATUS_COLLECTED, "path": path,
                "tables": tables, "fts_present": fts_present,
                "marker_hits": marker_hits}
    except sqlite3.Error as exc:
        return {"status": inv.STATUS_ERROR, "path": path,
                "error": str(exc)}
    finally:
        if connection is not None:
            connection.close()


def collect_evidence(record: Dict[str, Any]) -> Dict[str, Any]:
    """Gather every observation the checks need. Read-only by
    construction: file reads and one `mode=ro` SQLite open are the
    complete external surface — no process is spawned at all."""
    memory_dir = os.path.join(record["data_dir"], MEMORY_DIR_NAME)
    return {
        "config_file": ahv._read_text(record["config_path"],
                                      ahv.MAX_CONFIG_BYTES),
        "memory_files": {
            name: ahv._read_text(os.path.join(memory_dir, name),
                                 MAX_MEMORY_BYTES)
            for name in MEMORY_FILES},
        "session_store": inspect_session_store(
            os.path.join(record["data_dir"], SESSION_DB_NAME)),
    }


# ---------------------------------------------------------------------------
# Checks (pure evaluators over the collected evidence)
# ---------------------------------------------------------------------------


def check_approval_gating(record: Dict[str, Any],
                          bundle: Dict[str, Any]) -> ahv.CheckResult:
    findings: List[str] = []
    denied: List[str] = []
    unknowns: List[str] = []
    evidence: List[str] = []
    config = bundle["config_file"]
    if config["status"] == inv.STATUS_DENIED:
        denied.append(config["path"])
    elif config["status"] != inv.STATUS_COLLECTED:
        findings.append("recorded config_path does not exist: %s — the "
                        "install record is inaccurate" % config["path"])
    else:
        scalars = parse_config_scalars(config["text"])
        for key in APPROVAL_KEYS:
            value = scalars.get(key)
            if value is None:
                findings.append(
                    "%s is not set in %s — v0.18.2 defaults the gate OFF "
                    "(ATLAS-MEM-003 requires approval-gated writes); set "
                    "`%s: on` and restart Hermes"
                    % (key, config["path"], key))
            elif value.lower() in APPROVAL_ENABLED_VALUES:
                evidence.append("%s: %s (gate on)" % (key, value))
            else:
                findings.append(
                    "%s has value '%s', which v0.18.2 treats as OFF "
                    "(enabled spellings: %s)"
                    % (key, value,
                       ", ".join(sorted(APPROVAL_ENABLED_VALUES))))
    return ahv._resolve("approval-gating", findings, denied, unknowns,
                        "memory and skill writes are approval-gated",
                        evidence)


def _scan_memory_text(name: str, item: Dict[str, Any],
                      findings: List[str], evidence: List[str]) -> None:
    text = item["text"]
    evidence.append("%s: %d bytes%s"
                    % (name, len(text.encode("utf-8", "replace")),
                       " (scan truncated at cap)"
                       if item.get("truncated") else ""))
    if CANARY_PREFIX.lower() in text.lower():
        for number, line in enumerate(text.splitlines(), 1):
            if CANARY_PREFIX.lower() in line.lower():
                findings.append(
                    "%s:%d: procedure canary present in a MEMORY FILE — "
                    "secret rejection (ATLAS-MEM-005) failed: %s"
                    % (name, number, inv.redact(line.strip())[:120]))
    ahv._scan_for_secrets(text, name, findings)
    domain_lines = sum(1 for line in text.splitlines()
                       if _DOMAIN_KEYWORD.search(line))
    evidence.append("%s: %d line(s) matching domain keywords"
                    % (name, domain_lines))
    if domain_lines >= DOMAIN_LINE_THRESHOLD:
        findings.append(
            "%s: %d lines match Bittensor domain keywords (threshold %d) "
            "— bulk domain content in personal memory violates "
            "ATLAS-MEM-001; review and relocate it"
            % (name, domain_lines, DOMAIN_LINE_THRESHOLD))


def check_memory_hygiene(record: Dict[str, Any],
                         bundle: Dict[str, Any]) -> ahv.CheckResult:
    findings: List[str] = []
    denied: List[str] = []
    unknowns: List[str] = []
    evidence: List[str] = []
    for name in MEMORY_FILES:
        item = bundle["memory_files"][name]
        if item["status"] == inv.STATUS_COLLECTED:
            _scan_memory_text(name, item, findings, evidence)
        elif item["status"] == inv.STATUS_DENIED:
            denied.append(item["path"])
        elif name == "MEMORY.md":
            unknowns.append(
                "MEMORY.md not found at %s — Hermes creates it on first "
                "memory write; has the procedure been performed?"
                % item["path"])
        else:
            evidence.append("%s not yet created (Hermes creates it on "
                            "first use) — nothing to scan" % name)
    return ahv._resolve("memory-hygiene", findings, denied, unknowns,
                        "memory files are secret-free, canary-free, and "
                        "hold no bulk domain content", evidence)


def check_session_store(record: Dict[str, Any],
                        bundle: Dict[str, Any]) -> ahv.CheckResult:
    store = bundle["session_store"]
    findings: List[str] = []
    denied: List[str] = []
    unknowns: List[str] = []
    evidence: List[str] = []
    if store["status"] == inv.STATUS_DENIED:
        denied.append(store["path"])
    elif store["status"] == inv.STATUS_UNSUPPORTED:
        unknowns.append(
            "session store not found at %s — pinned v0.18.2 location; "
            "confirm data_dir and that Hermes has run" % store["path"])
    elif store["status"] != inv.STATUS_COLLECTED:
        unknowns.append(
            "session store could not be read (%s) — if Hermes is mid-"
            "session, finish it and re-run" % store.get("error", "unknown"))
    else:
        missing = [table for table in SESSION_TABLES
                   if table not in store["tables"]]
        evidence.append("%s: %d table(s)" % (store["path"],
                                             len(store["tables"])))
        if missing:
            unknowns.append(
                "expected table(s) missing from the session store: %s — "
                "schema drift from the pinned v0.18.2 facts; re-pin "
                "before accepting" % ", ".join(missing))
        if not store["fts_present"]:
            unknowns.append(
                "FTS table '%s' missing — session search surface absent "
                "or drifted from the pinned v0.18.2 facts (ATLAS-MEM-002)"
                % SESSION_FTS_TABLE)
        else:
            hits = store["marker_hits"] or 0
            evidence.append("recall marker FTS hits: %d" % hits)
            if hits < 1:
                unknowns.append(
                    "recall marker phrase not found via FTS — plant it "
                    "per docs/procedure.md step 5, then re-run")
    return ahv._resolve("session-store", findings, denied, unknowns,
                        "session store present, FTS surface present, "
                        "recall marker findable", evidence)


def run_checks(record: Dict[str, Any], record_path: str,
               bundle: Dict[str, Any],
               exceptions: List[Dict[str, str]]) -> List[ahv.CheckResult]:
    results = [
        ahv.check_install_record(record, record_path),
        check_approval_gating(record, bundle),
        check_memory_hygiene(record, bundle),
        check_session_store(record, bundle),
    ]
    by_check = {entry["check"]: entry["reason"] for entry in exceptions}
    for result in results:
        if result.status != ahv.CHECK_OK and result.check in by_check:
            result.exception = by_check[result.check]
    return results


# ---------------------------------------------------------------------------
# Attestations (the baseline helper validates against ITS item list, so
# this module carries its own; semantics are identical)
# ---------------------------------------------------------------------------


def build_attestations(attested: List[str], operator: str,
                       timestamp: str) -> List[Dict[str, Any]]:
    supplied = set(attested)
    unknown = supplied - set(ATTESTATION_ITEMS)
    if unknown:
        raise ahv.FatalVerificationError(
            "unknown attestation(s): %s (valid: %s)"
            % (", ".join(sorted(unknown)), ", ".join(ATTESTATION_ITEMS)))
    return [{"check": item,
             "attested": item in supplied,
             "operator": operator if item in supplied else None,
             "timestamp": timestamp if item in supplied else None}
            for item in ATTESTATION_ITEMS]


# ---------------------------------------------------------------------------
# Report assembly and rendering
# ---------------------------------------------------------------------------


def build_verification(record: Optional[Dict[str, Any]], record_path: str,
                       record_present: bool, record_problems: List[str],
                       exceptions_path: str, exceptions_present: bool,
                       exceptions_problems: List[str],
                       exceptions: List[Dict[str, str]],
                       results: List[ahv.CheckResult],
                       attestations: List[Dict[str, Any]],
                       overall: str, blockers: List[str],
                       run_id: str, started_at: str) -> Dict[str, Any]:
    return {
        "run": {
            "run_id": run_id,
            "verifier_version": VERIFIER_VERSION,
            "schema_version": VERIFICATION_SCHEMA_VERSION,
            "started_at": started_at,
            "finished_at": ahv._utc_now(),
            "executing_account": ahv._account(),
            "hostname": socket.gethostname(),
        },
        "install_record": {
            "path": record_path,
            "present": record_present,
            "problems": [inv.redact(problem)
                         for problem in record_problems],
            "record": ahv._redact_tree(record) if record else None,
        },
        "exceptions_file": {
            "path": exceptions_path,
            "present": exceptions_present,
            "problems": [inv.redact(problem)
                         for problem in exceptions_problems],
            "entries": [{"check": entry["check"],
                         "reason": inv.redact(entry["reason"])}
                        for entry in exceptions],
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
        "# Memory and session recall verification %s" % run["run_id"],
        "",
        "- **Verdict:** %s" % verdict["overall"],
        "- Verifier %s, schema v%s, run as `%s` on `%s`, finished %s"
        % (run["verifier_version"], run["schema_version"],
           run["executing_account"], run["hostname"], run["finished_at"]),
        "- Install record: `%s`%s"
        % (verification["install_record"]["path"],
           "" if verification["install_record"]["present"]
           else " (MISSING)"),
        "- Exceptions file: `%s`%s"
        % (verification["exceptions_file"]["path"],
           "" if verification["exceptions_file"]["present"]
           else " (none)"),
        "",
    ]
    input_problems = (verification["install_record"]["problems"]
                      + verification["exceptions_file"]["problems"])
    if input_problems:
        lines += ["## Input problems (no verdict issued)", ""]
        lines += ["- %s" % problem for problem in input_problems]
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
    lines += ["## Attestations (ATLAS-MEM-006)", ""]
    for attestation in verification["attestations"]:
        if attestation["attested"]:
            lines.append("- %s: attested by `%s` at %s"
                         % (attestation["check"], attestation["operator"],
                            attestation["timestamp"]))
        else:
            lines.append("- %s: NOT attested" % attestation["check"])
    lines += ["",
              "_For docs/decisions.md: record the verdict, run id, and the "
              "seven-item evidence summary (the PRD Q19 evidence base) "
              "once accepted._", ""]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def cmd_verify(record_path: str, exceptions_path: str, output_dir: str,
               attested: List[str], operator: Optional[str],
               collect: Any = collect_evidence) -> int:
    os.makedirs(output_dir, exist_ok=True)
    started_at = ahv._utc_now()
    run_id = (time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
              + "-" + secretsmod.token_hex(4))
    outputs: List[str] = []
    overall: Optional[str] = None
    blockers: List[str] = []
    fatal: Optional[str] = None
    try:
        attestations = build_attestations(attested,
                                          operator or ahv._account(),
                                          started_at)
        record, record_problems, record_present = \
            ahv.load_install_record(record_path)
        exceptions, exceptions_problems, exceptions_present = \
            load_exceptions(exceptions_path)
        results: List[ahv.CheckResult] = []
        if record is None or exceptions_problems:
            overall = ahv.VERDICT_NONE
            blockers = list(record_problems) + list(exceptions_problems)
        else:
            bundle = collect(record)
            results = run_checks(record, record_path, bundle, exceptions)
            overall, blockers = ahv.compute_verdict(results, attestations)
        verification = build_verification(
            record, record_path, record_present, record_problems,
            exceptions_path, exceptions_present, exceptions_problems,
            exceptions, results, attestations, overall, blockers,
            run_id, started_at)
        validation_errors = inv.schema_validate(verification,
                                                VERIFICATION_SCHEMA)
        if validation_errors:
            fatal = ("verification failed schema validation: "
                     + "; ".join(validation_errors[:20]))
            print("FATAL: %s" % fatal, file=sys.stderr)
            return 1
        verification_path = os.path.join(output_dir,
                                         "verification-%s.json" % run_id)
        ahv._write_private(verification_path,
                           json.dumps(verification, indent=2,
                                      sort_keys=True))
        outputs.append(verification_path)
        summary_path = os.path.join(output_dir, "summary-%s.md" % run_id)
        ahv._write_private(summary_path, render_summary(verification))
        outputs.append(summary_path)
        print("Verification %s verdict: %s" % (run_id, overall))
        for blocker in blockers:
            print("  blocker: %s" % inv.redact(blocker))
        print("Report:  %s" % verification_path)
        print("Summary: %s" % summary_path)
        if overall == ahv.VERDICT_ACCEPTED:
            return 0
        return 4 if overall == ahv.VERDICT_NONE else 3
    except ahv.FatalVerificationError as exc:
        fatal = str(exc)
        print("FATAL: %s" % inv.redact(fatal), file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 — fail visibly, audit the failure
        fatal = "unhandled failure: %s" % exc
        print("FATAL: %s" % inv.redact(str(exc)), file=sys.stderr)
        return 1
    finally:
        try:
            audit = ahv.build_audit(run_id, started_at, outputs, overall,
                                    len(blockers) if overall else None,
                                    fatal)
            audit["verifier_version"] = VERIFIER_VERSION
            audit_path = os.path.join(output_dir, "audit-%s.json" % run_id)
            ahv._write_private(audit_path,
                               json.dumps(audit, indent=2, sort_keys=True))
            print("Audit:   %s" % audit_path)
        except Exception as audit_exc:  # noqa: BLE001
            print("WARNING: audit record could not be written: %s"
                  % audit_exc, file=sys.stderr)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="atlas_memory_verify",
        description="Read-only memory and session recall verification "
                    "(ATLAS-MEM-001..006). Verifies, never assumes; "
                    "observes, never mutates.")
    subparsers = parser.add_subparsers(dest="subcommand", required=True)
    verify_parser = subparsers.add_parser(
        "verify", help="run the memory/recall verification")
    verify_parser.add_argument(
        "--install-record",
        default=os.path.join("var", "hermes", "install-record.json"),
        help="path to the operator's install record JSON")
    verify_parser.add_argument(
        "--exceptions",
        default=os.path.join("var", "memory", "exceptions.json"),
        help="optional memory-check exceptions JSON "
             "(list of {check, reason})")
    verify_parser.add_argument("--output-dir",
                               default=os.path.join("var", "memory"))
    verify_parser.add_argument(
        "--attest", action="append", default=[], metavar="ITEM",
        help="attest an evaluation item you performed per "
             "docs/procedure.md: %s (repeatable)"
             % ", ".join(ATTESTATION_ITEMS))
    verify_parser.add_argument(
        "--operator", default=None,
        help="name recorded on attestations (default: invoking user)")
    subparsers.add_parser("dump-schema",
                          help="print the verification JSON schema")
    args = parser.parse_args(argv)
    if args.subcommand == "verify":
        return cmd_verify(args.install_record, args.exceptions,
                          args.output_dir, args.attest, args.operator)
    if args.subcommand == "dump-schema":
        print(json.dumps(VERIFICATION_SCHEMA, indent=2))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
