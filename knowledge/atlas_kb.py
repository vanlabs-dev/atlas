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
PARSER_VERSION = "3"  # 2: ISO dates in temporal scope; 3: block units
INDEX_VERSION = 2  # porter unicode61, active fact/correction units only

CORPUS_DIR = os.path.join(_MODULE_DIR, "corpus")
HASHES_FILE = os.path.join(CORPUS_DIR, "hashes.json")
MARKERS_FILE = os.path.join(_MODULE_DIR, "supersession-markers.json")
KINDS_FILE = os.path.join(_MODULE_DIR, "unit-kinds.json")
UNIT_KINDS = ("fact", "correction", "procedure")
SEARCHABLE_KINDS = ("fact", "correction")
DEFAULT_DB = os.path.join("var", "knowledge", "knowledge.db")
DEFAULT_OUTPUT_DIR = os.path.join("var", "knowledge")

EVIDENCE_STATES = ("confirmed", "confirmed-historical", "superseded",
                   "conflicting", "unverified", "inference", "web-lead")

_HEADING = re.compile(r"^(?P<level>#{1,3})\s+(?P<title>.+?)\s*$")
# A line that starts a new block at column 0: a list item, a numbered
# item, or a bold-led entry. Indented lines continue the open block.
_BLOCK_START = re.compile(r"^(?:[-*]\s|\d+[.)]\s|\*\*)")
_RULE = re.compile(r"^\s*(?:-{3,}|\*{3,}|_{3,})\s*$")
_FENCE = re.compile(r"^\s*```")
_NESTED_ITEM = re.compile(r"^\s+(?:[-*]\s|\d+[.)]\s)")
# A block longer than this is split at its nested items, so a search
# result can carry it whole (the server caps content at the same size).
BLOCK_CAP = 1500
# ISO dates (YYYY-MM-DD) count too: most corpus dates since the 2026-08
# re-syncs are ISO. Longer forms come first so a range or a "since" phrase
# is kept whole rather than split into bare dates.
_ISO_DATE = r"20\d{2}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])"
_TEMPORAL = re.compile(
    r"(?i)\b((?:from\s+)?" + _ISO_DATE + r"\s+to\s+" + _ISO_DATE
    + r"|(?:since|as of|from|until)\s+" + _ISO_DATE
    + r"|" + _ISO_DATE + r"(?![\d-])"
    + r"|since\s+\w+\s+20\d{2}|as of\s+\w+\s+20\d{2}"
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
    active INTEGER NOT NULL DEFAULT 0,
    kind TEXT NOT NULL DEFAULT 'fact'
);
CREATE TABLE IF NOT EXISTS kb_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
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
    """Block units (change: knowledge-retrieval). A unit is one top-level
    list item, numbered item, bold-led entry, or paragraph inside its
    `#`/`##`/`###` section; nested and continuation lines stay with their
    block, and a fenced code block is never split. Heading lines and
    horizontal rules belong to no unit. The heading path is the section
    title, or `## title > ### title` for a subsection; text before the
    first heading is `(preamble)`. Ids are `<file>::<path>#<n>`, n counted
    within the section from 1."""
    lines = text.splitlines()
    units: List[Dict[str, Any]] = []
    path = "(preamble)"
    parent: Optional[str] = None
    counter: Dict[str, int] = {}
    block: List[str] = []
    start = 0
    end = 0
    in_fence = False

    def emit(piece: List[str], first: int, last: int) -> None:
        content = "\n".join(piece).strip()
        if not content:
            return
        counter[path] = counter.get(path, 0) + 1
        units.append({
            "unit_id": "%s::%s#%d" % (filename, path, counter[path]),
            "source_file": filename,
            "heading_path": path,
            "line_start": first,
            "line_end": last,
            "content": content,
        })

    def flush() -> None:
        nonlocal block
        if len("\n".join(block)) <= BLOCK_CAP:
            emit(block, start, end)
        else:
            # split at nested items: the lead lines, then each item with
            # its own continuation lines
            piece: List[str] = []
            first = start
            for offset, line in enumerate(block):
                if _NESTED_ITEM.match(line) and piece:
                    emit(piece, first, start + offset - 1)
                    piece = []
                    first = start + offset
                piece.append(line)
            emit(piece, first, end)
        block = []

    for number, line in enumerate(lines, 1):
        if in_fence:
            block.append(line)
            end = number
            if _FENCE.match(line):
                in_fence = False
            continue
        match = _HEADING.match(line)
        if match:
            flush()
            level = len(match.group("level"))
            title = match.group("title")
            if level <= 2:
                parent = title
                path = title
            else:
                path = "%s > %s" % (parent, title) if parent else title
            continue
        if not line.strip() or _RULE.match(line):
            flush()
            continue
        if _BLOCK_START.match(line) and block:
            flush()
        if not block:
            start = number
        block.append(line)
        end = number
        if _FENCE.match(line):
            in_fence = True
    flush()
    return units


def load_kinds(path: str = KINDS_FILE) -> Dict[str, str]:
    """Heading path -> kind. An entry matches its exact path and every
    subsection under it (`entry > ...`); the longest matching entry wins.
    Unmapped units are `fact`."""
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    kinds = data.get("kinds") if isinstance(data, dict) else None
    if not isinstance(kinds, dict):
        raise FatalKbError("unit-kinds.json needs a \"kinds\" object")
    for heading, kind in kinds.items():
        if kind not in UNIT_KINDS or not heading:
            raise FatalKbError("unit-kinds.json entry %r is invalid"
                               % heading)
    return kinds


def kind_for(heading_path: str, kinds: Dict[str, str]) -> str:
    best = None
    for entry in kinds:
        if heading_path == entry or heading_path.startswith(entry + " > "):
            if best is None or len(entry) > len(best):
                best = entry
    return kinds[best] if best is not None else "fact"


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
    columns = {row[1] for row in connection.execute(
        "PRAGMA table_info(units)")}
    if "kind" not in columns:
        # a store written before change knowledge-retrieval
        connection.execute("ALTER TABLE units ADD COLUMN kind TEXT NOT NULL "
                           "DEFAULT 'fact'")
        connection.commit()
    return connection


def rebuild_index(connection: sqlite3.Connection) -> int:
    """Rebuild the search index from the active fact and correction units.
    Runs inside the caller's transaction; returns the indexed row count."""
    connection.execute("DROP TABLE IF EXISTS units_fts")
    connection.execute(
        "CREATE VIRTUAL TABLE units_fts USING fts5(heading_path, content, "
        "content=units, content_rowid=id, tokenize='porter unicode61')")
    connection.execute(
        "INSERT INTO units_fts (rowid, heading_path, content) "
        "SELECT id, heading_path, content FROM units WHERE active = 1 "
        "AND kind IN (%s)" % ", ".join("'%s'" % k for k in SEARCHABLE_KINDS))
    count = connection.execute(
        "SELECT count(*) FROM units_fts_docsize").fetchone()[0]
    connection.execute(
        "INSERT OR REPLACE INTO kb_meta (key, value) VALUES "
        "('index_version', ?)", (str(INDEX_VERSION),))
    return count


def index_version(connection: sqlite3.Connection) -> Optional[int]:
    """The store's rebuilt-index version, or None for an older store."""
    try:
        row = connection.execute(
            "SELECT value FROM kb_meta WHERE key = 'index_version'"
        ).fetchone()
    except sqlite3.OperationalError:
        return None
    return int(row[0]) if row else None


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
           actor: Optional[str] = None,
           kinds_file: str = KINDS_FILE) -> Tuple[str, Dict[str, Any]]:
    """Stage units + write the validation report. Returns (run_id, report)."""
    corpus = load_corpus(corpus_dir, hashes_file)
    markers = load_markers(markers_file)
    kinds = load_kinds(kinds_file)
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
            unit["kind"] = kind_for(unit["heading_path"], kinds)
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
    kind_counts: Dict[str, int] = {}
    for unit in all_units:
        kind_counts[unit["kind"]] = kind_counts.get(unit["kind"], 0) + 1

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
        # Staged units are never indexed: activation rebuilds the index
        # from the active run only (change: knowledge-retrieval).
        for unit in all_units:
            connection.execute(
                "INSERT INTO units (unit_id, run_id, source_file, "
                "source_sha256, heading_path, line_start, line_end, "
                "coverage_date, temporal_scope, evidence_state, "
                "conflict_note, content, active, kind) VALUES "
                "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)",
                (unit["unit_id"], run_id, unit["source_file"],
                 unit["source_sha256"], unit["heading_path"],
                 unit["line_start"], unit["line_end"],
                 unit["coverage_date"], unit["temporal_scope"],
                 unit["evidence_state"], unit["conflict_note"],
                 unit["content"], unit["kind"]))
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
        "unit_counts_by_kind": kind_counts,
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


UPGRADE_ACTOR = "atlas-upgrade"


def rejected_units(connection: sqlite3.Connection,
                   run_id: str) -> List[str]:
    """Units of a run that the validation report would flag: duplicate unit
    ids and secret-scan findings. The operator reads these in the report;
    the upgrade job has no reader, so it refuses them."""
    rejected = ["duplicate unit id %s" % row[0] for row in connection.execute(
        "SELECT unit_id FROM units WHERE run_id = ? GROUP BY unit_id "
        "HAVING count(*) > 1", (run_id,))]
    for unit_id, content in connection.execute(
            "SELECT unit_id, content FROM units WHERE run_id = ?",
            (run_id,)):
        findings: List[str] = []
        ahv._scan_for_secrets(content, unit_id, findings)
        rejected += ["secret-scan %s" % inv.redact(f) for f in findings]
    return rejected


def activate(db_path: str, run_id: str, actor: Optional[str] = None) -> int:
    """Activate one run. The operator activates after reading the report.
    The upgrade job activates as `atlas-upgrade` only after its gates and a
    confirmed push, and never a run with rejected units."""
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
        if actor == UPGRADE_ACTOR:
            rejected = rejected_units(connection, run_id)
            if rejected:
                print("FATAL: run %s has rejected units: %s"
                      % (run_id, "; ".join(rejected[:5])), file=sys.stderr)
                return 1
        try:
            connection.execute("UPDATE units SET active = 0 WHERE active = 1")
            connection.execute(
                "UPDATE units SET active = 1 WHERE run_id = ?", (run_id,))
            indexed = rebuild_index(connection)
            _audit(connection, actor, "activate",
                   "run %s activated (%d units, %d indexed); prior active "
                   "runs deactivated" % (run_id, staged, indexed))
            connection.commit()
        except sqlite3.Error as exc:
            connection.rollback()
            print("FATAL: activation of %s rolled back: %s"
                  % (run_id, exc), file=sys.stderr)
            return 1
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
        version = index_version(connection)
    finally:
        connection.close()
    if active:
        for run_id, count in active:
            print("active run: %s (%d units)" % (run_id, count))
        print("states: %s" % ", ".join("%s=%d" % row for row in states))
        print("index_version: %s" % (version if version is not None
                                     else "none (rebuilt at next activate)"))
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
