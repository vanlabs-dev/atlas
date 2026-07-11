#!/usr/bin/env python3
"""Atlas Phase 2 knowledge base — intake, store, validation, activation.

Turns the confirmed corpus snapshot (knowledge/corpus/) into
provenance-preserving knowledge units in a single SQLite/FTS5 store
(ATLAS-KB-001/002/008/009/010, ATLAS-RET-002).

Flow (all operator-invoked, on the Pi):
    ingest    hash-verify the snapshot, stage units (inactive), write the
              validation report (structure analysis, secret scan,
              duplicates, counts by evidence state, marked conflicts)
    activate  explicit approval step: activates one ingest run's units
              (deactivating prior runs) and records the approval in the
              audit table (ATLAS-KB-005/006)
    status    active run, unit counts by state, corpus hashes

Envelope: unprivileged; writes only the store and 0600 reports under the
chosen --db/--output-dir (gitignored var/knowledge/ by default); redaction
applied to report text; nothing outside this repo's snapshot and var/ is
ever written or deleted (ATLAS-KB-007 closed as not-applicable).

Validation interpretation for this curated corpus (recorded in the change
design): `confirmed` units carry the operator's curation + in-file
citations as their supporting evidence; the validator's own work is
structure analysis, secret scan, temporal-scope extraction, duplicate
detection, and known-supersession marking (supersession-markers.json).
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import re
import sqlite3
import sys
import time
import secrets as secretsmod
from typing import Any, Dict, List, Optional, Tuple

_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_MODULE_DIR)
sys.path.insert(0, os.path.join(_REPO_ROOT, "hermes"))

import atlas_hermes_verify as ahv  # noqa: E402

inv = ahv.inv

KB_VERSION = "0.1.0"
PARSER_VERSION = "1"

CORPUS_DIR = os.path.join(_MODULE_DIR, "corpus")
HASHES_FILE = os.path.join(CORPUS_DIR, "hashes.json")
MARKERS_FILE = os.path.join(_MODULE_DIR, "supersession-markers.json")
DEFAULT_DB = os.path.join("var", "knowledge", "knowledge.db")
DEFAULT_OUTPUT_DIR = os.path.join("var", "knowledge")

EVIDENCE_STATES = ("confirmed", "confirmed-historical", "superseded",
                   "conflicting", "unverified", "inference", "web-lead")

_HEADING = re.compile(r"^(#{1,2})\s+(?P<title>.+?)\s*$")
_TEMPORAL = re.compile(
    r"(?i)\b(since\s+\w+\s+20\d{2}|as of\s+\w+\s+20\d{2}"
    r"|\w+\s+20\d{2}\s+to\s+\w+\s+20\d{2}"
    r"|(?:january|february|march|april|may|june|july|august|september"
    r"|october|november|december)\s+20\d{2})")
MAX_TEMPORAL_MARKS = 6

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS intake_runs (
    run_id TEXT PRIMARY KEY,
    intake_date TEXT NOT NULL,
    coverage_date TEXT NOT NULL,
    parser_version TEXT NOT NULL,
    kb_version TEXT NOT NULL,
    files_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY,
    run_id TEXT NOT NULL,
    filename TEXT NOT NULL,
    byte_size INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    coverage_date TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS units (
    id INTEGER PRIMARY KEY,
    unit_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    source_file TEXT NOT NULL,
    source_sha256 TEXT NOT NULL,
    heading_path TEXT NOT NULL,
    line_start INTEGER NOT NULL,
    line_end INTEGER NOT NULL,
    coverage_date TEXT NOT NULL,
    temporal_scope TEXT,
    evidence_state TEXT NOT NULL,
    conflict_note TEXT,
    content TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 0
);
CREATE VIRTUAL TABLE IF NOT EXISTS units_fts USING fts5(
    heading_path, content, content=units, content_rowid=id
);
CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY,
    timestamp TEXT NOT NULL,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    detail TEXT NOT NULL
);
"""


class FatalKbError(Exception):
    """Input-contract failure; the run aborts without touching units."""


def _utc_now() -> str:
    return datetime.datetime.now(tz=datetime.timezone.utc).isoformat()


def _run_id() -> str:
    return (time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
            + "-" + secretsmod.token_hex(4))


# ---------------------------------------------------------------------------
# Corpus loading (hash-verified)
# ---------------------------------------------------------------------------


def load_corpus(corpus_dir: str = CORPUS_DIR,
                hashes_file: str = HASHES_FILE) -> Dict[str, Any]:
    """Load the snapshot, verifying every recorded hash first.

    Hashes are computed over newline-normalized bytes (CRLF→LF): git
    normalizes line endings between the Windows dev checkout and the Pi,
    so byte-exact hashing would reject identical content."""
    with open(hashes_file, "r", encoding="utf-8") as handle:
        manifest = json.load(handle)
    files: Dict[str, Dict[str, Any]] = {}
    for filename, expected in manifest["files"].items():
        path = os.path.join(corpus_dir, filename)
        with open(path, "rb") as handle:
            raw = handle.read().replace(b"\r\n", b"\n")
        actual = hashlib.sha256(raw).hexdigest()
        if actual != expected:
            raise FatalKbError(
                "corpus hash mismatch for %s: recorded %s, actual %s — "
                "re-sync the snapshot per corpus/SOURCES.md before "
                "ingesting" % (filename, expected[:12], actual[:12]))
        files[filename] = {"bytes": len(raw), "sha256": actual,
                           "text": raw.decode("utf-8")}
    return {"manifest": manifest, "files": files}


def load_markers(path: str = MARKERS_FILE) -> List[Dict[str, str]]:
    with open(path, "r", encoding="utf-8") as handle:
        markers = json.load(handle)
    for index, marker in enumerate(markers):
        if (not isinstance(marker, dict)
                or not marker.get("match")
                or marker.get("state") not in EVIDENCE_STATES
                or not marker.get("note")):
            raise FatalKbError("supersession-markers.json entry %d is "
                               "invalid" % index)
    return markers


# ---------------------------------------------------------------------------
# Unit splitting (##-section level; deeper headings stay in their section)
# ---------------------------------------------------------------------------


def split_units(filename: str, text: str) -> List[Dict[str, Any]]:
    """One unit per `#`/`##` section subtree, plus a preamble unit when a
    file has content before its first section."""
    lines = text.splitlines()
    units: List[Dict[str, Any]] = []
    current_title: Optional[str] = None
    current_start = 1
    buffer: List[str] = []

    def flush(end_line: int) -> None:
        content = "\n".join(buffer).strip()
        if not content:
            return
        title = current_title or "(preamble)"
        units.append({
            "unit_id": "%s::%s" % (filename, title),
            "source_file": filename,
            "heading_path": title,
            "line_start": current_start,
            "line_end": end_line,
            "content": content,
        })

    for number, line in enumerate(lines, 1):
        match = _HEADING.match(line)
        if match:
            flush(number - 1)
            current_title = match.group("title")
            current_start = number
            buffer = [line]
        else:
            buffer.append(line)
    flush(len(lines))
    return units


def extract_temporal_scope(content: str) -> Optional[str]:
    marks: List[str] = []
    for match in _TEMPORAL.finditer(content):
        value = match.group(0)
        if value not in marks:
            marks.append(value)
        if len(marks) >= MAX_TEMPORAL_MARKS:
            break
    return "; ".join(marks) if marks else None


def apply_markers(unit: Dict[str, Any],
                  markers: List[Dict[str, str]]) -> None:
    for marker in markers:
        if marker["match"].lower() in unit["content"].lower():
            unit["evidence_state"] = marker["state"]
            unit["conflict_note"] = marker["note"]
            return
    unit["evidence_state"] = "confirmed"
    unit["conflict_note"] = None


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


def open_store(db_path: str) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.executescript(SCHEMA_SQL)
    return connection


def _audit(connection: sqlite3.Connection, actor: str, action: str,
           detail: str) -> None:
    connection.execute(
        "INSERT INTO audit (timestamp, actor, action, detail) "
        "VALUES (?, ?, ?, ?)",
        (_utc_now(), actor, action, inv.redact(detail)))


# ---------------------------------------------------------------------------
# Ingest
# ---------------------------------------------------------------------------


def ingest(db_path: str, output_dir: str, corpus_dir: str = CORPUS_DIR,
           hashes_file: str = HASHES_FILE,
           markers_file: str = MARKERS_FILE,
           actor: Optional[str] = None) -> Tuple[str, Dict[str, Any]]:
    """Stage units + write the validation report. Returns (run_id, report)."""
    corpus = load_corpus(corpus_dir, hashes_file)
    markers = load_markers(markers_file)
    run_id = _run_id()
    coverage_date = corpus["manifest"]["coverage_date"]
    actor = actor or ahv._account()

    all_units: List[Dict[str, Any]] = []
    structure: Dict[str, Any] = {}
    secret_findings: List[str] = []
    for filename, info in corpus["files"].items():
        units = split_units(filename, info["text"])
        for unit in units:
            unit["source_sha256"] = info["sha256"]
            unit["coverage_date"] = coverage_date
            unit["temporal_scope"] = extract_temporal_scope(unit["content"])
            apply_markers(unit, markers)
        all_units.extend(units)
        ahv._scan_for_secrets(info["text"], filename, secret_findings)
        structure[filename] = {
            "bytes": info["bytes"],
            "units": len(units),
            "headings": [unit["heading_path"] for unit in units],
            "code_blocks": info["text"].count("```") // 2,
        }
    duplicate_ids = sorted({unit["unit_id"] for unit in all_units
                            if sum(1 for other in all_units
                                   if other["unit_id"] == unit["unit_id"])
                            > 1})
    counts: Dict[str, int] = {}
    for unit in all_units:
        counts[unit["evidence_state"]] = counts.get(
            unit["evidence_state"], 0) + 1

    connection = open_store(db_path)
    try:
        connection.execute(
            "INSERT INTO intake_runs (run_id, intake_date, coverage_date, "
            "parser_version, kb_version, files_json) VALUES (?, ?, ?, ?, "
            "?, ?)",
            (run_id, _utc_now(), coverage_date, PARSER_VERSION, KB_VERSION,
             json.dumps({name: {"bytes": info["bytes"],
                                "sha256": info["sha256"]}
                         for name, info in corpus["files"].items()})))
        for filename, info in corpus["files"].items():
            connection.execute(
                "INSERT INTO sources (run_id, filename, byte_size, sha256,"
                " coverage_date) VALUES (?, ?, ?, ?, ?)",
                (run_id, filename, info["bytes"], info["sha256"],
                 coverage_date))
        for unit in all_units:
            cursor = connection.execute(
                "INSERT INTO units (unit_id, run_id, source_file, "
                "source_sha256, heading_path, line_start, line_end, "
                "coverage_date, temporal_scope, evidence_state, "
                "conflict_note, content, active) VALUES "
                "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)",
                (unit["unit_id"], run_id, unit["source_file"],
                 unit["source_sha256"], unit["heading_path"],
                 unit["line_start"], unit["line_end"],
                 unit["coverage_date"], unit["temporal_scope"],
                 unit["evidence_state"], unit["conflict_note"],
                 unit["content"]))
            connection.execute(
                "INSERT INTO units_fts (rowid, heading_path, content) "
                "VALUES (?, ?, ?)",
                (cursor.lastrowid, unit["heading_path"], unit["content"]))
        _audit(connection, actor, "ingest",
               "run %s staged %d units (%s)"
               % (run_id, len(all_units),
                  ", ".join("%s=%d" % item for item in sorted(
                      counts.items()))))
        connection.commit()
    finally:
        connection.close()

    report = {
        "run_id": run_id,
        "intake_date": _utc_now(),
        "coverage_date": coverage_date,
        "parser_version": PARSER_VERSION,
        "kb_version": KB_VERSION,
        "structure": structure,
        "unit_counts_by_state": counts,
        "total_units": len(all_units),
        "duplicate_unit_ids": duplicate_ids,
        "secret_scan_findings": [inv.redact(finding)
                                 for finding in secret_findings],
        "marked_conflicts": [
            {"unit_id": unit["unit_id"], "state": unit["evidence_state"],
             "note": unit["conflict_note"]}
            for unit in all_units if unit["conflict_note"]],
        "activation": "staged — run `activate --run %s` after review"
                      % run_id,
    }
    os.makedirs(output_dir, exist_ok=True)
    report_path = os.path.join(output_dir,
                               "validation-report-%s.json" % run_id)
    ahv._write_private(report_path,
                       json.dumps(report, indent=2, sort_keys=True))
    summary_path = os.path.join(output_dir,
                                "validation-report-%s.md" % run_id)
    ahv._write_private(summary_path, render_report(report))
    print("Ingest run %s: %d units staged (not active)."
          % (run_id, len(all_units)))
    for finding in report["secret_scan_findings"]:
        print("  SECRET-SCAN FINDING: %s" % finding)
    print("Report: %s" % summary_path)
    return run_id, report


def render_report(report: Dict[str, Any]) -> str:
    lines = [
        "# Knowledge validation report %s" % report["run_id"],
        "",
        "- Coverage date: %s · parser v%s · kb v%s"
        % (report["coverage_date"], report["parser_version"],
           report["kb_version"]),
        "- Total units staged: %d" % report["total_units"],
        "- Counts by evidence state: %s"
        % ", ".join("%s=%d" % item for item in sorted(
            report["unit_counts_by_state"].items())),
        "",
        "## Structure",
        "",
    ]
    for filename, info in report["structure"].items():
        lines.append("- **%s**: %d bytes, %d units, %d code block(s)"
                     % (filename, info["bytes"], info["units"],
                        info["code_blocks"]))
        for heading in info["headings"]:
            lines.append("  - %s" % heading)
    if report["duplicate_unit_ids"]:
        lines += ["", "## Duplicate unit ids", ""]
        lines += ["- %s" % item for item in report["duplicate_unit_ids"]]
    if report["secret_scan_findings"]:
        lines += ["", "## Secret-scan findings", ""]
        lines += ["- %s" % item for item in report["secret_scan_findings"]]
    if report["marked_conflicts"]:
        lines += ["", "## Marked conflicts / supersession candidates", ""]
        for item in report["marked_conflicts"]:
            lines.append("- **%s** → %s: %s"
                         % (item["unit_id"], item["state"], item["note"]))
    lines += ["", "## Activation", "", report["activation"], ""]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Activate / status
# ---------------------------------------------------------------------------


def activate(db_path: str, run_id: str, actor: Optional[str] = None) -> int:
    actor = actor or ahv._account()
    connection = open_store(db_path)
    try:
        staged = connection.execute(
            "SELECT count(*) FROM units WHERE run_id = ?",
            (run_id,)).fetchone()[0]
        if staged == 0:
            print("FATAL: no staged units for run %s" % run_id,
                  file=sys.stderr)
            return 1
        connection.execute("UPDATE units SET active = 0 WHERE active = 1")
        connection.execute(
            "UPDATE units SET active = 1 WHERE run_id = ?", (run_id,))
        _audit(connection, actor, "activate",
               "run %s activated (%d units); prior active runs "
               "deactivated" % (run_id, staged))
        connection.commit()
    finally:
        connection.close()
    print("Activated run %s (%d units). Knowledge tools now serve it."
          % (run_id, staged))
    return 0


def status(db_path: str) -> int:
    if not os.path.exists(db_path):
        print("no knowledge store at %s — run ingest first" % db_path)
        return 3
    connection = sqlite3.connect(
        "file:%s?mode=ro" % db_path.replace("\\", "/"), uri=True)
    try:
        active = connection.execute(
            "SELECT run_id, count(*) FROM units WHERE active = 1 "
            "GROUP BY run_id").fetchall()
        states = connection.execute(
            "SELECT evidence_state, count(*) FROM units WHERE active = 1 "
            "GROUP BY evidence_state").fetchall()
        runs = connection.execute(
            "SELECT run_id, intake_date, coverage_date FROM intake_runs "
            "ORDER BY intake_date DESC LIMIT 5").fetchall()
    finally:
        connection.close()
    if active:
        for run_id, count in active:
            print("active run: %s (%d units)" % (run_id, count))
        print("states: %s" % ", ".join("%s=%d" % row for row in states))
    else:
        print("NO ACTIVE RUN — tools fail closed until `activate` is run")
    for run_id, intake_date, coverage_date in runs:
        print("run %s  ingested %s  coverage %s"
              % (run_id, intake_date[:19], coverage_date))
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="atlas_kb",
        description="Atlas knowledge base: hash-verified corpus intake, "
                    "operator-gated activation, status.")
    subparsers = parser.add_subparsers(dest="subcommand", required=True)
    for name in ("ingest", "activate", "status"):
        sub = subparsers.add_parser(name)
        sub.add_argument("--db", default=DEFAULT_DB)
        if name == "ingest":
            sub.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
            sub.add_argument("--corpus-dir", default=CORPUS_DIR)
        if name == "activate":
            sub.add_argument("--run", required=True)
        if name != "status":
            sub.add_argument("--actor", default=None)
    args = parser.parse_args(argv)
    try:
        if args.subcommand == "ingest":
            hashes = os.path.join(args.corpus_dir, "hashes.json")
            ingest(args.db, args.output_dir, args.corpus_dir, hashes,
                   actor=args.actor)
            return 0
        if args.subcommand == "activate":
            return activate(args.db, args.run, args.actor)
        if args.subcommand == "status":
            return status(args.db)
    except FatalKbError as exc:
        print("FATAL: %s" % inv.redact(str(exc)), file=sys.stderr)
        return 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
