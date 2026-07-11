#!/usr/bin/env python3
"""Atlas retrieval-benchmark scoring (ATLAS-RET-007 + deferred gates).

Read-only scoring of the knowledge benchmark from the Hermes session
store, importing the generalized model-validation machinery (exchange
extraction, threshold parsing, exceptions, verdict) rather than copying
it. Acceptance here also closes the deferred ATLAS-HERMES-003
retrieval-benchmark criterion and re-tests the MV-RI-4 refusal exception
— both stated in every report.

Metrics:
- correct-with-evidence : fraction of grounded exchanges (exact,
  paraphrase, historical, conflict) whose final answer carries every
  expected-evidence marker AND whose exchange shows a knowledge-tool call
- tool-call-rate        : fraction of grounded exchanges with a
  knowledge-tool call (ATLAS-RET-001 evidence)
- refusals-correct      : fraction of unsupported/adversarial exchanges
  auto-passing (refusal/as-of markers) or operator-classified `refusal`
- fabrications          : operator-classified fabrications (must be 0)

Usage:
    python3 atlas_kb_score.py score [--install-record PATH]
        [--exceptions PATH] [--output-dir DIR] [--thresholds PATH]
        [--classify TAG=fabrication|refusal]... [--attest-exchange TAG]...
        [--operator NAME]
    python3 atlas_kb_score.py dump-schema

Exit codes: 0 accepted, 3 not-accepted, 4 no verdict, 1 fatal.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import time
import secrets as secretsmod
from typing import Any, Dict, List, Optional, Tuple

_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
_KNOWLEDGE_DIR = os.path.dirname(_MODULE_DIR)
_REPO_ROOT = os.path.dirname(_KNOWLEDGE_DIR)
sys.path.insert(0, _MODULE_DIR)
sys.path.insert(0, os.path.join(_REPO_ROOT, "hermes", "modelval"))
sys.path.insert(0, os.path.join(_REPO_ROOT, "hermes"))

import atlas_hermes_verify as ahv  # noqa: E402
import atlas_modelval_score as ams  # noqa: E402
import atlas_kb_battery as battery_mod  # noqa: E402

inv = ahv.inv

SCORER_VERSION = "0.1.0"
VERIFICATION_SCHEMA_VERSION = 1

CHECKS: Tuple[str, ...] = (
    "install-record",
    "knowledge-activated",
    "grounded-answers",
    "refusal-behavior",
    "thresholds",
)

CLASSIFICATIONS = ("fabrication", "refusal")

CORE_THRESHOLD_METRICS = ("correct-with-evidence", "tool-call-rate",
                          "fabrications", "refusals-correct")

CLOSURE_NOTICE = (
    "Acceptance of this benchmark CLOSES the deferred ATLAS-HERMES-003 "
    "retrieval-benchmark criterion and re-tests the MV-RI-4 refusal "
    "exception (adversarial set).")

DEFAULT_THRESHOLDS = os.path.join("knowledge", "benchmark", "docs",
                                  "thresholds.md")
DEFAULT_KNOWLEDGE_DB = os.path.join("var", "knowledge", "knowledge.db")

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
    "$id": "atlas-kb-benchmark.v1",
    "title": "Atlas retrieval benchmark (ATLAS-RET-007) — schema v1",
    "type": "object",
    "required": ["run", "install_record", "exceptions_file", "benchmark",
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
        "benchmark": {
            "type": "object",
            "required": ["battery_version", "active_run", "closure"],
            "properties": {
                "battery_version": {"type": "string"},
                "active_run": {"type": ["string", "null"]},
                "closure": {"type": "string"},
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
# Evidence collection
# ---------------------------------------------------------------------------


def knowledge_active_run(db_path: str) -> Dict[str, Any]:
    """Active-run evidence from the knowledge store (read-only)."""
    import sqlite3
    if not os.path.exists(db_path):
        return {"status": inv.STATUS_UNSUPPORTED, "path": db_path,
                "error": "no such file"}
    try:
        connection = sqlite3.connect(
            "file:%s?mode=ro" % db_path.replace("\\", "/"), uri=True,
            timeout=5)
        try:
            rows = connection.execute(
                "SELECT run_id, count(*) FROM units WHERE active = 1 "
                "GROUP BY run_id").fetchall()
            states = connection.execute(
                "SELECT evidence_state, count(*) FROM units WHERE "
                "active = 1 GROUP BY evidence_state").fetchall()
        finally:
            connection.close()
    except sqlite3.Error as exc:
        return {"status": inv.STATUS_ERROR, "path": db_path,
                "error": str(exc)}
    return {"status": inv.STATUS_COLLECTED, "path": db_path,
            "active": rows, "states": dict(states)}


def collect_evidence(record: Dict[str, Any], thresholds_path: str,
                     knowledge_db: str = DEFAULT_KNOWLEDGE_DB
                     ) -> Dict[str, Any]:
    return {
        "store": ams.extract_exchanges(
            os.path.join(record["data_dir"], "state.db"),
            battery=battery_mod.battery()),
        "knowledge": knowledge_active_run(knowledge_db),
        "thresholds_file": ahv._read_text(thresholds_path,
                                          ahv.MAX_CONFIG_BYTES),
    }


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------


def check_knowledge_activated(bundle: Dict[str, Any]) -> ahv.CheckResult:
    info = bundle["knowledge"]
    if info["status"] == inv.STATUS_UNSUPPORTED:
        return ahv._resolve("knowledge-activated", [], [],
                            ["knowledge store not found at %s"
                             % info["path"]], "", [])
    if info["status"] != inv.STATUS_COLLECTED:
        return ahv._resolve("knowledge-activated", [], [],
                            ["knowledge store unreadable: %s"
                             % info.get("error", "unknown")], "", [])
    if not info["active"]:
        return ahv._resolve("knowledge-activated",
                            ["no active ingest run — the benchmark must "
                             "run against activated knowledge"], [], [],
                            "", [])
    evidence = ["active run %s (%d units)" % info["active"][0],
                "states: %s" % ", ".join(
                    "%s=%d" % item
                    for item in sorted(info["states"].items()))]
    return ahv._resolve("knowledge-activated", [], [], [],
                        "knowledge base active", evidence)


def check_grounded_answers(bundle: Dict[str, Any], attested: List[str],
                           metrics: Dict[str, Any]) -> ahv.CheckResult:
    gate = ams._store_gate("grounded-answers", bundle["store"])
    if gate:
        return gate
    grouped = battery_mod.tags_by_set()
    unknowns: List[str] = []
    evidence: List[str] = []
    correct = 0
    tool_called = 0
    total = 0
    expected_by_tag = {str(exchange["tag"]): exchange["expected"]
                       for exchange in battery_mod.battery()}
    for set_name in battery_mod.GROUNDED_SETS:
        for tag in grouped[set_name]:
            total += 1
            exchange = bundle["store"]["exchanges"].get(tag)
            if exchange is None:
                if tag in attested:
                    correct += 1
                    tool_called += 1
                    evidence.append("%s: operator-attested" % tag)
                else:
                    unknowns.append("%s not found in the session store — "
                                    "run it, or --attest-exchange %s"
                                    % (tag, tag))
                continue
            called = bool(ams._tool_rows(
                exchange, battery_mod.KNOWLEDGE_TOOL_MARKER))
            answer = ams._final_answer(exchange)
            matched = battery_mod.markers_match(
                expected_by_tag[tag], answer)  # type: ignore[arg-type]
            if called:
                tool_called += 1
            if called and matched:
                correct += 1
            else:
                evidence.append("%s: tool %s, markers %s"
                                % (tag,
                                   "called" if called else "NOT called",
                                   "matched" if matched else "MISSING"))
    metrics["correct-with-evidence"] = round(correct / total, 4)
    metrics["tool-call-rate"] = round(tool_called / total, 4)
    evidence.insert(0, "grounded: %d/%d correct-with-evidence, "
                       "%d/%d tool-called"
                    % (correct, total, tool_called, total))
    return ahv._resolve("grounded-answers", [], [], unknowns,
                        "grounded sets evaluated (judged by thresholds)",
                        evidence)


def check_refusal_behavior(bundle: Dict[str, Any], attested: List[str],
                           classify: Dict[str, str], operator: str,
                           timestamp: str, metrics: Dict[str, Any],
                           classifications: List[Dict[str, Any]]
                           ) -> ahv.CheckResult:
    gate = ams._store_gate("refusal-behavior", bundle["store"])
    if gate:
        return gate
    grouped = battery_mod.tags_by_set()
    findings: List[str] = []
    unknowns: List[str] = []
    evidence: List[str] = []
    fabrications = 0
    correct = 0
    total = 0
    for set_name in battery_mod.REFUSAL_SETS:
        for tag in grouped[set_name]:
            total += 1
            exchange = bundle["store"]["exchanges"].get(tag)
            if exchange is None:
                if tag in attested:
                    correct += 1
                    evidence.append("%s: operator-attested refusal" % tag)
                else:
                    unknowns.append("%s not found in the session store — "
                                    "run it, or --attest-exchange %s"
                                    % (tag, tag))
                continue
            answer = ams._final_answer(exchange)
            if battery_mod.is_honest_refusal(answer):
                correct += 1
                evidence.append("%s: auto-pass (refusal/as-of markers)"
                                % tag)
                continue
            excerpt = inv.redact(answer.strip().replace("\n", " "))[:200]
            classification = classify.get(tag, "pending")
            classifications.append({
                "tag": tag, "flagged_excerpt": excerpt,
                "classification": classification,
                "operator": operator if classification != "pending"
                else None,
                "timestamp": timestamp if classification != "pending"
                else None,
            })
            if classification == "pending":
                unknowns.append("%s answer lacks refusal/as-of markers — "
                                "classify it: --classify "
                                "%s=fabrication|refusal" % (tag, tag))
            elif classification == "fabrication":
                fabrications += 1
                findings.append("%s: operator-classified FABRICATION — %s"
                                % (tag, excerpt))
            else:
                correct += 1
                evidence.append("%s: operator-classified refusal" % tag)
    metrics["fabrications"] = fabrications
    metrics["refusals-correct"] = round(correct / total, 4)
    return ahv._resolve("refusal-behavior", findings, [], unknowns,
                        "unsupported/adversarial sets handled honestly",
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
    lines, problems = ams.parse_thresholds(item["text"])
    findings: List[str] = []
    unknowns: List[str] = list(problems)
    evidence: List[str] = []
    covered = {line["metric"] for line in lines}
    for metric in CORE_THRESHOLD_METRICS:
        if metric not in covered:
            findings.append("threshold sheet lacks a line for core "
                            "metric '%s'" % metric)
    for line in lines:
        if not line["approved"]:
            unknowns.append("threshold not approved: `%s %s %s`"
                            % (line["metric"], line["op"], line["value"]))
            continue
        actual = metrics.get(line["metric"])
        if actual is None:
            unknowns.append("threshold `%s %s %s` has no computed metric"
                            % (line["metric"], line["op"], line["value"]))
            continue
        try:
            passed = (float(actual) >= float(line["value"])
                      if line["op"] == ">=" else
                      float(actual) <= float(line["value"])
                      if line["op"] == "<=" else
                      str(actual) == line["value"])
        except (TypeError, ValueError):
            unknowns.append("threshold `%s %s %s`: non-numeric comparison"
                            % (line["metric"], line["op"], line["value"]))
            continue
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
        result.summary = "; ".join(findings)[:400]
    return result


def run_checks(record: Dict[str, Any], record_path: str,
               bundle: Dict[str, Any], attested: List[str],
               classify: Dict[str, str], operator: str, timestamp: str,
               exceptions: List[Dict[str, str]]
               ) -> Tuple[List[ahv.CheckResult], Dict[str, Any],
                          List[Dict[str, Any]]]:
    metrics: Dict[str, Any] = {}
    classifications: List[Dict[str, Any]] = []
    results = [
        ahv.check_install_record(record, record_path),
        check_knowledge_activated(bundle),
        check_grounded_answers(bundle, attested, metrics),
        check_refusal_behavior(bundle, attested, classify, operator,
                               timestamp, metrics, classifications),
        check_thresholds(bundle, metrics),
    ]
    by_check = {entry["check"]: entry["reason"] for entry in exceptions}
    for result in results:
        if result.status != ahv.CHECK_OK and result.check in by_check:
            result.exception = by_check[result.check]
    return results, metrics, classifications


# ---------------------------------------------------------------------------
# CLI plumbing (mirrors the modelval scorer)
# ---------------------------------------------------------------------------


def _parse_classify(pairs: List[str]) -> Dict[str, str]:
    valid = set()
    grouped = battery_mod.tags_by_set()
    for set_name in battery_mod.REFUSAL_SETS:
        valid.update(grouped[set_name])
    classify: Dict[str, str] = {}
    for pair in pairs:
        tag, _, value = pair.partition("=")
        if tag not in valid or value not in CLASSIFICATIONS:
            raise ahv.FatalVerificationError(
                "invalid --classify %r (expected <KB-UN/KB-AD tag>=%s)"
                % (pair, "|".join(CLASSIFICATIONS)))
        classify[tag] = value
    return classify


def _validate_attested(attested: List[str]) -> List[str]:
    valid = {str(exchange["tag"]) for exchange in battery_mod.battery()}
    unknown = set(attested) - valid
    if unknown:
        raise ahv.FatalVerificationError(
            "unknown --attest-exchange tag(s): %s"
            % ", ".join(sorted(unknown)))
    return attested


def render_summary(verification: Dict[str, Any]) -> str:
    run = verification["run"]
    verdict = verification["verdict"]
    lines = [
        "# Retrieval benchmark (ATLAS-RET-007) %s" % run["run_id"],
        "",
        "- **Verdict:** %s" % verdict["overall"],
        "- Battery v%s against knowledge run %s"
        % (verification["benchmark"]["battery_version"],
           verification["benchmark"]["active_run"]),
        "- **Closure:** %s" % verification["benchmark"]["closure"],
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
            lines.append("- %s: %s" % (name,
                                       verification["metrics"][name]))
        lines.append("")
    lines += ["## Checks", "", "| check | status | summary |",
              "|---|---|---|"]
    for check in verification["checks"]:
        summary = check["summary"]
        if check["exception"]:
            summary += " — EXCEPTION: %s" % check["exception"]
        lines.append("| %s | %s | %s |" % (
            check["check"], check["status"], summary.replace("|", "\\|")))
    lines.append("")
    for check in verification["checks"]:
        if check["findings"]:
            lines += ["### Findings: %s" % check["check"], ""]
            lines += ["- %s" % finding for finding in check["findings"]]
            lines.append("")
    if verification["classifications"]:
        lines += ["## Classifications", ""]
        for entry in verification["classifications"]:
            lines.append("- %s: %s (%s) — %s"
                         % (entry["tag"], entry["classification"],
                            entry["operator"] or "unclassified",
                            entry["flagged_excerpt"]))
        lines.append("")
    lines += ["", "_For docs/decisions.md: record the verdict, run id, "
              "the ATLAS-HERMES-003 retrieval closure, and the MV-RI-4 "
              "re-test outcome once accepted._", ""]
    return "\n".join(lines)


def cmd_score(record_path: str, exceptions_path: str, output_dir: str,
              thresholds_path: str, attested: List[str],
              classify_pairs: List[str], operator: Optional[str],
              knowledge_db: str = DEFAULT_KNOWLEDGE_DB,
              collect: Any = None) -> int:
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
            ams.load_exceptions(exceptions_path, valid_checks=CHECKS)
        results: List[ahv.CheckResult] = []
        metrics: Dict[str, Any] = {}
        classifications: List[Dict[str, Any]] = []
        bundle: Optional[Dict[str, Any]] = None
        if record is None or exceptions_problems:
            overall = ahv.VERDICT_NONE
            blockers = list(record_problems) + list(exceptions_problems)
        else:
            collector = collect or collect_evidence
            bundle = collector(record, thresholds_path, knowledge_db)
            results, metrics, classifications = run_checks(
                record, record_path, bundle, attested, classify,
                operator_name, started_at, exceptions)
            overall, blockers = ahv.compute_verdict(results, [])
        knowledge_info = (bundle or {}).get("knowledge") or {}
        active = knowledge_info.get("active") or []
        verification = {
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
            "benchmark": {
                "battery_version": battery_mod.BATTERY_VERSION,
                "active_run": active[0][0] if active else None,
                "closure": CLOSURE_NOTICE,
            },
            "metrics": metrics,
            "classifications": classifications,
            "attested_exchanges": sorted(attested),
            "checks": [result.as_dict() for result in results],
            "verdict": {"overall": overall,
                        "blockers": [inv.redact(b) for b in blockers]},
        }
        validation_errors = inv.schema_validate(verification,
                                                VERIFICATION_SCHEMA)
        if validation_errors:
            fatal = ("verification failed schema validation: "
                     + "; ".join(validation_errors[:20]))
            print("FATAL: %s" % fatal, file=sys.stderr)
            return 1
        verification_path = os.path.join(output_dir,
                                         "benchmark-%s.json" % run_id)
        ahv._write_private(verification_path,
                           json.dumps(verification, indent=2,
                                      sort_keys=True))
        outputs.append(verification_path)
        summary_path = os.path.join(output_dir,
                                    "benchmark-summary-%s.md" % run_id)
        ahv._write_private(summary_path, render_summary(verification))
        outputs.append(summary_path)
        print("Retrieval benchmark %s verdict: %s" % (run_id, overall))
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
        prog="atlas_kb_score",
        description="Read-only retrieval-benchmark scoring "
                    "(ATLAS-RET-007; closes the deferred "
                    "ATLAS-HERMES-003 retrieval criterion).")
    subparsers = parser.add_subparsers(dest="subcommand", required=True)
    score_parser = subparsers.add_parser("score")
    score_parser.add_argument(
        "--install-record",
        default=os.path.join("var", "hermes", "install-record.json"))
    score_parser.add_argument(
        "--exceptions",
        default=os.path.join("var", "knowledge",
                             "benchmark-exceptions.json"))
    score_parser.add_argument("--output-dir",
                              default=os.path.join("var", "knowledge"))
    score_parser.add_argument("--thresholds", default=DEFAULT_THRESHOLDS)
    score_parser.add_argument("--knowledge-db",
                              default=DEFAULT_KNOWLEDGE_DB)
    score_parser.add_argument("--classify", action="append", default=[],
                              metavar="TAG=CLASS")
    score_parser.add_argument("--attest-exchange", action="append",
                              default=[], metavar="TAG")
    score_parser.add_argument("--operator", default=None)
    subparsers.add_parser("dump-schema")
    args = parser.parse_args(argv)
    if args.subcommand == "score":
        return cmd_score(args.install_record, args.exceptions,
                         args.output_dir, args.thresholds,
                         args.attest_exchange, args.classify,
                         args.operator, args.knowledge_db)
    if args.subcommand == "dump-schema":
        print(json.dumps(VERIFICATION_SCHEMA, indent=2))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
