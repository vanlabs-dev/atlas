#!/usr/bin/env python3
"""Atlas Phase 1 model validation scoring (ATLAS-HERMES-003).

Read-only scoring of the model-validation battery from the Hermes session
store. The battery (atlas_modelval_battery.py) is executed through the
live Hermes deployment beforehand — by run_battery.py or by the operator
following battery.md; this scorer only reads evidence and judges it
against the operator-approved threshold sheet.

Guarantees (same envelope as the repo's other verifiers):
- READ-ONLY: the session store is opened via a `mode=ro` SQLite URI; no
  Hermes invocation, no config/memory/session writes. The only writes are
  0600 reports in the (gitignored) output directory.
- FAIL CLOSED: missing/incomplete install record or invalid exceptions
  file → no verdict. Unevidenced exchanges need an explicit
  `--attest-exchange`; flagged refusal-to-invent answers need an explicit
  `--classify`; unapproved thresholds block. Every blocker is named.
- The retrieval-benchmark criterion of ATLAS-HERMES-003 is DEFERRED to
  Phase 2 by recorded decision; every report reproduces that deferral so
  acceptance cannot be mistaken for full closure.

Usage:
    python3 atlas_modelval_score.py score
        [--install-record PATH] [--exceptions PATH] [--output-dir DIR]
        [--thresholds PATH]
        [--classify TAG=fabrication|refusal]...
        [--attest-exchange TAG]... [--operator NAME]
    python3 atlas_modelval_score.py dump-schema
    python3 atlas_modelval_score.py dump-battery

Exit codes for `score`: 0 = accepted, 3 = not-accepted (blockers listed),
4 = no verdict (inputs missing/invalid), 1 = fatal.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import socket
import sqlite3
import statistics
import sys
import time
import secrets as secretsmod
from typing import Any, Dict, List, Optional, Tuple
from urllib.request import pathname2url

_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
_HERMES_DIR = os.path.dirname(_MODULE_DIR)
_REPO_ROOT = os.path.dirname(_HERMES_DIR)
sys.path.insert(0, _MODULE_DIR)
sys.path.insert(0, os.path.join(_HERMES_DIR, "memory"))
sys.path.insert(0, _HERMES_DIR)

import atlas_hermes_verify as ahv  # noqa: E402
import atlas_memory_verify as amv  # noqa: E402
import atlas_modelval_battery as battery_mod  # noqa: E402

inv = ahv.inv

SCORER_VERSION = "0.1.0"
VERIFICATION_SCHEMA_VERSION = 1

CHECKS: Tuple[str, ...] = (
    "install-record",
    "tool-calling",
    "context-window",
    "refusal-to-invent",
    "latency",
    "thresholds",
    "cost-privacy-reviews",
    "replaceability",
)

CLASSIFICATIONS = ("fabrication", "refusal")

# Core metrics the threshold sheet must cover (plus >=1 context-recall-*)
CORE_THRESHOLD_METRICS = ("tool-call-success", "fabrications",
                          "latency-median-la")

DEFERRAL_NOTICE = (
    "ATLAS-HERMES-003 'Bittensor retrieval benchmark performance' is "
    "DEFERRED to Phase 2 by recorded decision (retrieval does not exist "
    "before Phase 2); this verdict does NOT cover it.")

DEFAULT_THRESHOLDS = os.path.join("hermes", "modelval", "docs",
                                  "thresholds.md")
REVIEW_FILES = ("cost-review.md", "privacy-review.md")
DOCS_DIR = os.path.join(_MODULE_DIR, "docs")

# Repo code that must not hard-code the model id (replaceability)
CODE_DIRS = ("inventory", "hardening", "hermes")

_THRESHOLD_LINE = re.compile(
    r"^- \[(?P<approved>[ x])\] approved\s+`(?P<metric>[a-zA-Z0-9-]+)\s*"
    r"(?P<op>>=|<=|==)\s*(?P<value>[A-Za-z0-9.]+)`\s*$")
_REVIEWED_LINE = re.compile(r"^Reviewed:\s*\d{4}-\d{2}-\d{2}",
                            re.MULTILINE)
_SIGNOFF_LINE = re.compile(r"^Signed-off-by:\s*(?!TODO\b)(\S.+)$",
                           re.MULTILINE)
_DIGIT = re.compile(r"\d")

MAX_CONTENT_CHARS = 20000
_SQLITE_TIMEOUT_S = 5

# ---------------------------------------------------------------------------
# Output schema (embedded source of truth; schema/ file generated)
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

VERIFICATION_SCHEMA: Dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "atlas-modelval-verification.v1",
    "title": "Atlas model validation (ATLAS-HERMES-003) — schema v1",
    "type": "object",
    "required": ["run", "install_record", "exceptions_file", "battery",
                 "metrics", "classifications", "attested_exchanges",
                 "checks", "verdict"],
    "properties": {
        "run": {
            "type": "object",
            "required": ["run_id", "scorer_version", "schema_version",
                         "started_at", "finished_at", "executing_account",
                         "hostname"],
            "properties": {
                "run_id": {"type": "string"},
                "scorer_version": {"type": "string"},
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
        "battery": {
            "type": "object",
            "required": ["battery_version", "model_id", "provider",
                         "deferral"],
            "properties": {
                "battery_version": {"type": "string"},
                "model_id": {"type": ["string", "null"]},
                "provider": {"type": ["string", "null"]},
                "deferral": {"type": "string"},
            },
            "additionalProperties": False,
        },
        "metrics": {
            "type": "object",
            "additionalProperties": {"type": ["number", "string"]},
        },
        "classifications": {"type": "array", "items": {
            "type": "object",
            "required": ["tag", "flagged_excerpt", "classification",
                         "operator", "timestamp"],
            "properties": {
                "tag": {"type": "string"},
                "flagged_excerpt": {"type": "string"},
                "classification": {
                    "enum": list(CLASSIFICATIONS) + ["pending"]},
                "operator": {"type": ["string", "null"]},
                "timestamp": {"type": ["string", "null"]},
            },
            "additionalProperties": False,
        }},
        "attested_exchanges": {"type": "array",
                               "items": {"type": "string"}},
        "checks": {"type": "array", "items": _CHECK_SCHEMA},
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
# Input contracts (install record reused; module-scoped exceptions file)
# ---------------------------------------------------------------------------


def load_exceptions(path: str,
                    valid_checks: Optional[Tuple[str, ...]] = None
                    ) -> Tuple[List[Dict[str, str]], List[str], bool]:
    """Same contract as the memory verifier's, scoped to a check
    vocabulary (defaults to THIS module's; other scorers pass theirs)."""
    valid_checks = valid_checks or CHECKS
    if not os.path.exists(path):
        return [], [], False
    try:
        with open(path, "r", encoding="utf-8") as handle:
            entries = json.loads(handle.read(ahv.MAX_CONFIG_BYTES))
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
                or not entry.get("reason", "").strip()
                or set(entry) - {"check", "reason"}):
            problems.append("exceptions[%d] must be "
                            "{\"check\": ..., \"reason\": ...}" % index)
        elif entry["check"] not in valid_checks:
            problems.append("exceptions[%d].check unknown: %s (valid: %s)"
                            % (index, entry["check"],
                               ", ".join(valid_checks)))
    if problems:
        return [], problems, True
    return entries, [], True


def parse_thresholds(text: str) -> Tuple[List[Dict[str, str]], List[str]]:
    """Parse approval-marked threshold lines. Returns (lines, problems);
    each line: {metric, op, value, approved}."""
    lines: List[Dict[str, str]] = []
    for raw in text.splitlines():
        raw = raw.rstrip()
        if not raw.startswith("- ["):
            continue
        match = _THRESHOLD_LINE.match(raw)
        if not match:
            return [], ["unparseable threshold line: %s" % raw.strip()]
        lines.append({"metric": match.group("metric"),
                      "op": match.group("op"),
                      "value": match.group("value"),
                      "approved": match.group("approved") == "x"})
    if not lines:
        return [], ["no threshold lines found"]
    return lines, []


# ---------------------------------------------------------------------------
# Evidence collection (read-only by construction)
# ---------------------------------------------------------------------------


def _connect_ro(path: str) -> sqlite3.Connection:
    uri = "file:%s?mode=ro" % pathname2url(os.path.abspath(path))
    return sqlite3.connect(uri, uri=True, timeout=_SQLITE_TIMEOUT_S)


def extract_exchanges(store_path: str,
                      battery: Optional[List[Dict[str, str]]] = None
                      ) -> Dict[str, Any]:
    """Locate every battery exchange by tag: the LATEST user message
    containing `[tag]`, plus all following rows in its session up to the
    next user message. Returns {status, exchanges: {tag: {...}}}.
    `battery` defaults to this module's; other scorers pass theirs."""
    battery = battery if battery is not None else battery_mod.battery()
    if not os.path.exists(store_path):
        return {"status": inv.STATUS_UNSUPPORTED, "path": store_path,
                "error": "no such file", "exchanges": {}}
    if not os.access(store_path, os.R_OK):
        return {"status": inv.STATUS_DENIED, "path": store_path,
                "error": "permission denied", "exchanges": {}}
    exchanges: Dict[str, Any] = {}
    try:
        connection = _connect_ro(store_path)
        try:
            for exchange in battery:
                tag = exchange["tag"]
                row = connection.execute(
                    "SELECT id, session_id, timestamp FROM messages "
                    "WHERE role = 'user' AND content LIKE ? "
                    "ORDER BY id DESC LIMIT 1",
                    ("%%[%s]%%" % tag,)).fetchone()
                if row is None:
                    continue
                user_id, session_id, user_ts = row
                rows = connection.execute(
                    "SELECT role, tool_name, substr(content, 1, ?), "
                    "timestamp FROM messages WHERE session_id = ? AND "
                    "id >= ? ORDER BY id", (MAX_CONTENT_CHARS, session_id,
                                            user_id)).fetchall()
                kept: List[Tuple[str, Optional[str], str, float]] = []
                for index, item in enumerate(rows):
                    if index > 0 and item[0] == "user":
                        break
                    kept.append(item)
                exchanges[tag] = {
                    "session_id": session_id,
                    "user_ts": user_ts,
                    "rows": kept,
                }
        finally:
            connection.close()
    except sqlite3.Error as exc:
        return {"status": inv.STATUS_ERROR, "path": store_path,
                "error": str(exc), "exchanges": {}}
    return {"status": inv.STATUS_COLLECTED, "path": store_path,
            "exchanges": exchanges}


def scan_repo_for_model_id(model_id: str) -> List[str]:
    """Replaceability evidence: no Atlas repo code may hard-code the
    model identity. Scans .py files in the code directories."""
    hits: List[str] = []
    if not model_id:
        return hits
    for code_dir in CODE_DIRS:
        root_dir = os.path.join(_REPO_ROOT, code_dir)
        for root, dirs, files in os.walk(root_dir):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for name in files:
                if not name.endswith(".py"):
                    continue
                path = os.path.join(root, name)
                item = ahv._read_text(path, ahv.MAX_CONFIG_BYTES)
                if (item["status"] == inv.STATUS_COLLECTED
                        and model_id in item["text"]):
                    hits.append(os.path.relpath(path, _REPO_ROOT))
    return hits


def collect_evidence(record: Dict[str, Any],
                     thresholds_path: str) -> Dict[str, Any]:
    """Every observation the checks need. Read-only: file reads and one
    mode=ro SQLite open; no process is spawned."""
    config = ahv._read_text(record["config_path"], ahv.MAX_CONFIG_BYTES)
    scalars: Dict[str, str] = {}
    if config["status"] == inv.STATUS_COLLECTED:
        scalars = amv.parse_config_scalars(config["text"])
    model_id = scalars.get("model.default")
    return {
        "config_file": config,
        "config_scalars": scalars,
        "model_id": model_id,
        "provider": scalars.get("model.provider"),
        "store": extract_exchanges(
            os.path.join(record["data_dir"], amv.SESSION_DB_NAME)),
        "thresholds_file": ahv._read_text(thresholds_path,
                                          ahv.MAX_CONFIG_BYTES),
        "reviews": {name: ahv._read_text(os.path.join(DOCS_DIR, name),
                                         ahv.MAX_CONFIG_BYTES)
                    for name in REVIEW_FILES},
        "model_id_code_hits": scan_repo_for_model_id(model_id or ""),
    }


# ---------------------------------------------------------------------------
# Exchange helpers
# ---------------------------------------------------------------------------


def _final_answer(exchange: Dict[str, Any]) -> str:
    for role, _tool, content, _ts in reversed(exchange["rows"]):
        if role == "assistant":
            return content or ""
    return ""


# Hermes records MCP tools under a prefixed name (observed on-device:
# `mcp__atlas_test__atlas_ping`), so tool matching is by substring.
# Tools that cannot supply external data; their rows do not invalidate a
# refusal-to-invent exchange (the battery runs those with `-t todo`).
INERT_TOOL_NAMES = ("todo",)


def _tool_rows(exchange: Dict[str, Any],
               tool_name: Optional[str] = None,
               ignore_inert: bool = False) -> List[Tuple]:
    rows = [row for row in exchange["rows"]
            if row[0] == "tool" and row[1]
            and (tool_name is None or tool_name in row[1])]
    if ignore_inert:
        rows = [row for row in rows if row[1] not in INERT_TOOL_NAMES]
    return rows


def _elapsed_seconds(exchange: Dict[str, Any]) -> Optional[float]:
    stamps = [row[3] for row in exchange["rows"]
              if isinstance(row[3], (int, float))]
    if len(stamps) < 2:
        return None
    return max(stamps) - min(stamps)


def _store_gate(check: str, store: Dict[str, Any]
                ) -> Optional[ahv.CheckResult]:
    """Shared fail-closed handling when the session store is unreadable."""
    if store["status"] == inv.STATUS_COLLECTED:
        return None
    if store["status"] == inv.STATUS_DENIED:
        return ahv._resolve(check, [], [store["path"]], [], "", [])
    return ahv._resolve(check, [], [],
                        ["session store unavailable: %s (%s)"
                         % (store.get("error", "unknown"), store["path"])],
                        "", [])


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------


def check_tool_calling(store: Dict[str, Any], attested: List[str],
                       metrics: Dict[str, Any]) -> ahv.CheckResult:
    gate = _store_gate("tool-calling", store)
    if gate:
        return gate
    tags = battery_mod.tags_by_set()["tool-calling"]
    findings: List[str] = []
    unknowns: List[str] = []
    evidence: List[str] = []
    successes = 0
    tool_latencies: List[float] = []
    for tag in tags:
        exchange = store["exchanges"].get(tag)
        if exchange is None:
            if tag in attested:
                successes += 1
                evidence.append("%s: operator-attested (no store "
                                "evidence)" % tag)
            else:
                unknowns.append("%s not found in the session store — run "
                                "it, or --attest-exchange %s" % (tag, tag))
            continue
        called = bool(_tool_rows(exchange, battery_mod.TOOL_NAME))
        answer = _final_answer(exchange)
        reflected = all(expected in answer for expected
                        in battery_mod.TOOL_EXPECTED_STRINGS)
        if called and reflected:
            successes += 1
        else:
            findings.append("%s: tool call %s, expected values %s in the "
                            "final answer" % (
                                tag, "made" if called else "MISSING",
                                "present" if reflected else "ABSENT"))
        elapsed = _elapsed_seconds(exchange)
        if elapsed is not None:
            tool_latencies.append(elapsed)
    metrics["tool-call-success"] = round(successes / len(tags), 4)
    evidence.insert(0, "tool-call success: %d/%d" % (successes, len(tags)))
    if tool_latencies:
        evidence.append("tool-exchange median wall time: %.1fs "
                        "(informational)"
                        % statistics.median(tool_latencies))
    # reliability failures are reflected in the metric and judged against
    # the approved threshold; per-exchange findings here are evidence, so
    # they must not independently block below-threshold-tolerated misses
    result = ahv._resolve("tool-calling", [], [], unknowns,
                          "%d/%d tool-call exchanges succeeded"
                          % (successes, len(tags)), evidence)
    result.evidence += findings
    return result


def check_context_window(store: Dict[str, Any], attested: List[str],
                         metrics: Dict[str, Any]) -> ahv.CheckResult:
    gate = _store_gate("context-window", store)
    if gate:
        return gate
    unknowns: List[str] = []
    evidence: List[str] = []
    for tag in battery_mod.tags_by_set()["context-window"]:
        metric_name = "context-recall-%s" % tag
        exchange = store["exchanges"].get(tag)
        if exchange is None:
            if tag in attested:
                metrics[metric_name] = "pass"
                evidence.append("%s: operator-attested pass" % tag)
            else:
                metrics[metric_name] = "unevidenced"
                unknowns.append("%s not found in the session store — run "
                                "it, or --attest-exchange %s" % (tag, tag))
            continue
        code = battery_mod.cx_code_for(tag)
        recalled = code.lower() in _final_answer(exchange).lower()
        metrics[metric_name] = "pass" if recalled else "fail"
        evidence.append("%s: planted code %s"
                        % (tag, "recalled" if recalled else "NOT recalled"))
    return ahv._resolve("context-window", [], [], unknowns,
                        "context probes evaluated (judged by thresholds)",
                        evidence)


def check_refusal_to_invent(store: Dict[str, Any], attested: List[str],
                            classify: Dict[str, str],
                            operator: str, timestamp: str,
                            metrics: Dict[str, Any],
                            classifications: List[Dict[str, Any]]
                            ) -> ahv.CheckResult:
    gate = _store_gate("refusal-to-invent", store)
    if gate:
        return gate
    findings: List[str] = []
    unknowns: List[str] = []
    evidence: List[str] = []
    fabrications = 0
    for tag in battery_mod.tags_by_set()["refusal-to-invent"]:
        exchange = store["exchanges"].get(tag)
        if exchange is None:
            if tag in attested:
                evidence.append("%s: operator-attested refusal (no store "
                                "evidence)" % tag)
            else:
                unknowns.append("%s not found in the session store — run "
                                "it, or --attest-exchange %s" % (tag, tag))
            continue
        if _tool_rows(exchange, ignore_inert=True):
            unknowns.append("%s ran with data-capable tools enabled — "
                            "invalid for the refusal battery; re-run "
                            "with tools disabled" % tag)
            continue
        answer = _final_answer(exchange)
        if not _DIGIT.search(answer):
            evidence.append("%s: no value-shaped content — counted as "
                            "refusal" % tag)
            continue
        excerpt = inv.redact(answer.strip().replace("\n", " "))[:200]
        classification = classify.get(tag, "pending")
        classifications.append({
            "tag": tag, "flagged_excerpt": excerpt,
            "classification": classification,
            "operator": operator if classification != "pending" else None,
            "timestamp": timestamp if classification != "pending" else None,
        })
        if classification == "pending":
            unknowns.append("%s answer contains numbers — classify it: "
                            "--classify %s=fabrication|refusal"
                            % (tag, tag))
        elif classification == "fabrication":
            fabrications += 1
            findings.append("%s: operator-classified FABRICATION of a "
                            "current value — %s" % (tag, excerpt))
        else:
            evidence.append("%s: flagged, operator-classified as "
                            "legitimate refusal" % tag)
    metrics["fabrications"] = fabrications
    return ahv._resolve("refusal-to-invent", findings, [], unknowns,
                        "no fabricated current values", evidence)


def check_latency(store: Dict[str, Any], attested: List[str],
                  metrics: Dict[str, Any]) -> ahv.CheckResult:
    gate = _store_gate("latency", store)
    if gate:
        return gate
    tags = battery_mod.tags_by_set()["latency"]
    unknowns: List[str] = []
    evidence: List[str] = ["timestamps are float epoch seconds (sub-ms "
                           "resolution); wall time covers the full answer "
                           "— time-to-first-token is not observable in "
                           "the store"]
    timings: List[float] = []
    for tag in tags:
        exchange = store["exchanges"].get(tag)
        if exchange is None:
            if tag in attested:
                evidence.append("%s: attested run — no timing evidence, "
                                "excluded from the metric" % tag)
            else:
                unknowns.append("%s not found in the session store — run "
                                "it, or --attest-exchange %s" % (tag, tag))
            continue
        elapsed = _elapsed_seconds(exchange)
        if elapsed is None:
            unknowns.append("%s: cannot compute timing (single timestamp)"
                            % tag)
            continue
        timings.append(elapsed)
        evidence.append("%s: %.2fs" % (tag, elapsed))
    if len(timings) >= max(2, len(tags) // 2):
        metrics["latency-median-la"] = round(statistics.median(timings), 2)
        evidence.insert(1, "median over %d timed exchanges: %.2fs"
                        % (len(timings), metrics["latency-median-la"]))
    else:
        unknowns.append("too few timed latency exchanges (%d of %d)"
                        % (len(timings), len(tags)))
    return ahv._resolve("latency", [], [], unknowns,
                        "latency evidenced (judged by thresholds)",
                        evidence)


def check_thresholds(bundle: Dict[str, Any],
                     metrics: Dict[str, Any]) -> ahv.CheckResult:
    item = bundle["thresholds_file"]
    if item["status"] == inv.STATUS_DENIED:
        return ahv._resolve("thresholds", [], [item["path"]], [], "", [])
    if item["status"] != inv.STATUS_COLLECTED:
        return ahv._resolve("thresholds", [], [],
                            ["threshold sheet not found: %s"
                             % item["path"]], "", [])
    lines, problems = parse_thresholds(item["text"])
    findings: List[str] = []
    unknowns: List[str] = list(problems)
    evidence: List[str] = []
    covered = {line["metric"] for line in lines}
    for metric in CORE_THRESHOLD_METRICS:
        if metric not in covered:
            findings.append("threshold sheet lacks a line for core "
                            "metric '%s'" % metric)
    if not any(metric.startswith("context-recall-") for metric in covered):
        findings.append("threshold sheet lacks any context-recall-* line")
    for line in lines:
        if not line["approved"]:
            unknowns.append("threshold not approved: `%s %s %s` — the "
                            "operator must tick it before acceptance"
                            % (line["metric"], line["op"], line["value"]))
            continue
        actual = metrics.get(line["metric"])
        if actual is None or actual == "unevidenced":
            unknowns.append("threshold `%s %s %s` has no computed metric"
                            % (line["metric"], line["op"], line["value"]))
            continue
        if line["op"] == "==":
            passed = str(actual) == line["value"]
        else:
            try:
                actual_num = float(actual)
                target = float(line["value"])
            except (TypeError, ValueError):
                unknowns.append("threshold `%s %s %s`: non-numeric "
                                "comparison against %r"
                                % (line["metric"], line["op"],
                                   line["value"], actual))
                continue
            passed = (actual_num >= target if line["op"] == ">="
                      else actual_num <= target)
        if passed:
            evidence.append("`%s %s %s` — met (actual: %s)"
                            % (line["metric"], line["op"], line["value"],
                               actual))
        else:
            findings.append("`%s %s %s` — NOT met (actual: %s)"
                            % (line["metric"], line["op"], line["value"],
                               actual))
    result = ahv._resolve("thresholds", findings, [], unknowns,
                          "all approved thresholds met", evidence)
    if findings:
        # the verdict blocker carries the summary — name every failed
        # threshold there, not just a count
        result.summary = "; ".join(findings)[:400]
    return result


def check_reviews(bundle: Dict[str, Any]) -> ahv.CheckResult:
    findings: List[str] = []
    denied: List[str] = []
    evidence: List[str] = []
    for name, item in bundle["reviews"].items():
        if item["status"] == inv.STATUS_DENIED:
            denied.append(item["path"])
            continue
        if item["status"] != inv.STATUS_COLLECTED:
            findings.append("review document missing: %s" % item["path"])
            continue
        if not _REVIEWED_LINE.search(item["text"]):
            findings.append("%s lacks a 'Reviewed: YYYY-MM-DD' line"
                            % name)
        signoff = _SIGNOFF_LINE.search(item["text"])
        if not signoff:
            findings.append("%s lacks an operator sign-off "
                            "('Signed-off-by: <name>')" % name)
        else:
            evidence.append("%s signed off by %s"
                            % (name, signoff.group(1).strip()))
    return ahv._resolve("cost-privacy-reviews", findings, denied, [],
                        "cost and privacy reviews dated and signed off",
                        evidence)


def check_replaceability(bundle: Dict[str, Any]) -> ahv.CheckResult:
    findings: List[str] = []
    unknowns: List[str] = []
    evidence: List[str] = []
    config = bundle["config_file"]
    if config["status"] != inv.STATUS_COLLECTED:
        unknowns.append("config not readable: %s" % config["path"])
    else:
        for key in ("model.default", "model.provider"):
            value = bundle["config_scalars"].get(key)
            if value:
                evidence.append("%s present in config.yaml" % key)
            else:
                unknowns.append("%s not found in config — cannot evidence "
                                "config-only model selection" % key)
    for hit in bundle["model_id_code_hits"]:
        findings.append("repo code references the model id: %s — model "
                        "must be replaceable via configuration alone"
                        % hit)
    if bundle["model_id"]:
        evidence.append("validated model id pinned: %s (provider: %s)"
                        % (bundle["model_id"],
                           bundle["provider"] or "unknown"))
    return ahv._resolve("replaceability", findings, [], unknowns,
                        "model selection is configuration-only; no repo "
                        "code references the model id", evidence)


def run_checks(record: Dict[str, Any], record_path: str,
               bundle: Dict[str, Any], attested: List[str],
               classify: Dict[str, str], operator: str, timestamp: str,
               exceptions: List[Dict[str, str]]
               ) -> Tuple[List[ahv.CheckResult], Dict[str, Any],
                          List[Dict[str, Any]]]:
    metrics: Dict[str, Any] = {}
    classifications: List[Dict[str, Any]] = []
    store = bundle["store"]
    results = [
        ahv.check_install_record(record, record_path),
        check_tool_calling(store, attested, metrics),
        check_context_window(store, attested, metrics),
        check_refusal_to_invent(store, attested, classify, operator,
                                timestamp, metrics, classifications),
        check_latency(store, attested, metrics),
        check_thresholds(bundle, metrics),
        check_reviews(bundle),
        check_replaceability(bundle),
    ]
    by_check = {entry["check"]: entry["reason"] for entry in exceptions}
    for result in results:
        if result.status != ahv.CHECK_OK and result.check in by_check:
            result.exception = by_check[result.check]
    return results, metrics, classifications


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


def _parse_classify(pairs: List[str]) -> Dict[str, str]:
    valid_tags = set(battery_mod.tags_by_set()["refusal-to-invent"])
    classify: Dict[str, str] = {}
    for pair in pairs:
        tag, _, value = pair.partition("=")
        if tag not in valid_tags or value not in CLASSIFICATIONS:
            raise ahv.FatalVerificationError(
                "invalid --classify %r (expected <RI tag>=%s)"
                % (pair, "|".join(CLASSIFICATIONS)))
        classify[tag] = value
    return classify


def _validate_attested(attested: List[str]) -> List[str]:
    valid = {exchange["tag"] for exchange in battery_mod.battery()}
    unknown = set(attested) - valid
    if unknown:
        raise ahv.FatalVerificationError(
            "unknown --attest-exchange tag(s): %s"
            % ", ".join(sorted(unknown)))
    return attested


def build_verification(record, record_path, record_present,
                       record_problems, exceptions_path,
                       exceptions_present, exceptions_problems, exceptions,
                       bundle, results, metrics, classifications,
                       attested, overall, blockers, run_id,
                       started_at) -> Dict[str, Any]:
    return {
        "run": {
            "run_id": run_id,
            "scorer_version": SCORER_VERSION,
            "schema_version": VERIFICATION_SCHEMA_VERSION,
            "started_at": started_at,
            "finished_at": ahv._utc_now(),
            "executing_account": ahv._account(),
            "hostname": socket.gethostname(),
        },
        "install_record": {
            "path": record_path,
            "present": record_present,
            "problems": [inv.redact(p) for p in record_problems],
            "record": ahv._redact_tree(record) if record else None,
        },
        "exceptions_file": {
            "path": exceptions_path,
            "present": exceptions_present,
            "problems": [inv.redact(p) for p in exceptions_problems],
            "entries": [{"check": entry["check"],
                         "reason": inv.redact(entry["reason"])}
                        for entry in exceptions],
        },
        "battery": {
            "battery_version": battery_mod.BATTERY_VERSION,
            "model_id": (bundle or {}).get("model_id"),
            "provider": (bundle or {}).get("provider"),
            "deferral": DEFERRAL_NOTICE,
        },
        "metrics": metrics,
        "classifications": classifications,
        "attested_exchanges": sorted(attested),
        "checks": [result.as_dict() for result in results],
        "verdict": {"overall": overall,
                    "blockers": [inv.redact(b) for b in blockers]},
    }


def render_summary(verification: Dict[str, Any]) -> str:
    run = verification["run"]
    verdict = verification["verdict"]
    battery_info = verification["battery"]
    lines = [
        "# Model validation (ATLAS-HERMES-003) %s" % run["run_id"],
        "",
        "- **Verdict:** %s" % verdict["overall"],
        "- **Model:** %s (provider: %s), battery v%s"
        % (battery_info["model_id"], battery_info["provider"],
           battery_info["battery_version"]),
        "- **Deferral:** %s" % battery_info["deferral"],
        "- Scorer %s, run as `%s` on `%s`, finished %s"
        % (run["scorer_version"], run["executing_account"],
           run["hostname"], run["finished_at"]),
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
    if verification["metrics"]:
        lines += ["## Metrics", ""]
        for name in sorted(verification["metrics"]):
            lines.append("- %s: %s" % (name, verification["metrics"][name]))
        lines.append("")
    if verification["checks"]:
        lines += ["## Checks", "", "| check | status | summary |",
                  "|---|---|---|"]
        for check in verification["checks"]:
            summary = check["summary"]
            if check["exception"]:
                summary += " — EXCEPTION: %s" % check["exception"]
            lines.append("| %s | %s | %s |" % (
                check["check"], check["status"],
                summary.replace("|", "\\|")))
        lines.append("")
        for check in verification["checks"]:
            if check["findings"]:
                lines += ["### Findings: %s" % check["check"], ""]
                lines += ["- %s" % finding for finding in check["findings"]]
                lines.append("")
    if verification["classifications"]:
        lines += ["## Refusal-to-invent classifications", ""]
        for entry in verification["classifications"]:
            lines.append("- %s: %s (%s) — %s"
                         % (entry["tag"], entry["classification"],
                            entry["operator"] or "unclassified",
                            entry["flagged_excerpt"]))
        lines.append("")
    lines += ["",
              "_For docs/decisions.md: record the verdict, run id, pinned "
              "model id, and the retrieval-benchmark deferral once "
              "accepted._", ""]
    return "\n".join(lines)


def cmd_score(record_path: str, exceptions_path: str, output_dir: str,
              thresholds_path: str, attested: List[str],
              classify_pairs: List[str], operator: Optional[str],
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
        operator_name = operator or ahv._account()
        attested = _validate_attested(attested)
        classify = _parse_classify(classify_pairs)
        record, record_problems, record_present = \
            ahv.load_install_record(record_path)
        exceptions, exceptions_problems, exceptions_present = \
            load_exceptions(exceptions_path)
        results: List[ahv.CheckResult] = []
        metrics: Dict[str, Any] = {}
        classifications: List[Dict[str, Any]] = []
        bundle: Optional[Dict[str, Any]] = None
        if record is None or exceptions_problems:
            overall = ahv.VERDICT_NONE
            blockers = list(record_problems) + list(exceptions_problems)
        else:
            bundle = collect(record, thresholds_path)
            results, metrics, classifications = run_checks(
                record, record_path, bundle, attested, classify,
                operator_name, started_at, exceptions)
            overall, blockers = ahv.compute_verdict(results, [])
        verification = build_verification(
            record, record_path, record_present, record_problems,
            exceptions_path, exceptions_present, exceptions_problems,
            exceptions, bundle, results, metrics, classifications,
            attested, overall, blockers, run_id, started_at)
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
        print("Model validation %s verdict: %s" % (run_id, overall))
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
            audit["verifier_version"] = SCORER_VERSION
            audit_path = os.path.join(output_dir, "audit-%s.json" % run_id)
            ahv._write_private(audit_path,
                               json.dumps(audit, indent=2, sort_keys=True))
            print("Audit:   %s" % audit_path)
        except Exception as audit_exc:  # noqa: BLE001
            print("WARNING: audit record could not be written: %s"
                  % audit_exc, file=sys.stderr)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="atlas_modelval_score",
        description="Read-only model-validation scoring "
                    "(ATLAS-HERMES-003, retrieval benchmark deferred to "
                    "Phase 2). Observes, never mutates.")
    subparsers = parser.add_subparsers(dest="subcommand", required=True)
    score_parser = subparsers.add_parser(
        "score", help="score a completed battery from the session store")
    score_parser.add_argument(
        "--install-record",
        default=os.path.join("var", "hermes", "install-record.json"))
    score_parser.add_argument(
        "--exceptions",
        default=os.path.join("var", "modelval", "exceptions.json"))
    score_parser.add_argument("--output-dir",
                              default=os.path.join("var", "modelval"))
    score_parser.add_argument("--thresholds", default=DEFAULT_THRESHOLDS,
                              help="operator-approved threshold sheet")
    score_parser.add_argument(
        "--classify", action="append", default=[], metavar="TAG=CLASS",
        help="classify a flagged refusal-to-invent answer: "
             "<RI tag>=fabrication|refusal (repeatable)")
    score_parser.add_argument(
        "--attest-exchange", action="append", default=[], metavar="TAG",
        help="operator attestation for an exchange the store cannot "
             "evidence (repeatable)")
    score_parser.add_argument("--operator", default=None)
    subparsers.add_parser("dump-schema",
                          help="print the verification JSON schema")
    subparsers.add_parser("dump-battery",
                          help="print battery.md generated from the "
                               "battery module")
    args = parser.parse_args(argv)
    if args.subcommand == "score":
        return cmd_score(args.install_record, args.exceptions,
                         args.output_dir, args.thresholds,
                         args.attest_exchange, args.classify,
                         args.operator)
    if args.subcommand == "dump-schema":
        print(json.dumps(VERIFICATION_SCHEMA, indent=2))
        return 0
    if args.subcommand == "dump-battery":
        print(battery_mod.render_markdown())
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
