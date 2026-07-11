"""Test helpers: imports plus fixture builders for records and evidence."""

import os
import sqlite3
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

import atlas_memory_verify as amv  # noqa: E402

ahv = amv.ahv
inv = amv.inv

VERIFIER_SOURCE = os.path.join(os.path.dirname(_HERE),
                               "atlas_memory_verify.py")

GREEN_CONFIG = (
    "model:\n"
    "  default: grok\n"
    "memory:\n"
    "  memory_enabled: true\n"
    "  write_approval: on\n"
    "skills:\n"
    "  write_approval: on\n"
)


def make_record(**overrides):
    """Complete, valid install record; None removes a field."""
    record = {
        "install_source": "github.com/example/hermes-agent official "
                          "installer, cloned to /home/pi/.hermes/"
                          "hermes-agent",
        "installed_version": "commit abc1234def5678",
        "install_date": "2026-07-11",
        "update_method": "git pull in the clone, re-run installer",
        "rollback_method": "git checkout <previous>, re-run installer",
        "service_user": "pi",
        "data_dir": "/home/pi/.hermes",
        "config_path": "/home/pi/.hermes/config.yaml",
    }
    record.update(overrides)
    return {key: value for key, value in record.items() if value is not None}


def text_item(status="collected", path="/tmp/x", text="", truncated=False):
    item = {"status": status, "path": path}
    if status == "collected":
        item["text"] = text
        item["truncated"] = truncated
    else:
        item["error"] = status
    return item


def store_item(status="collected", path="/home/pi/.hermes/state.db",
               tables=("messages", "sessions", "messages_fts"),
               fts_present=True, marker_hits=1, error=None):
    if status != "collected":
        return {"status": status, "path": path, "error": error or status}
    return {"status": status, "path": path, "tables": sorted(tables),
            "fts_present": fts_present, "marker_hits": marker_hits}


def base_bundle(**overrides):
    """Evidence bundle in which every check passes for make_record()."""
    bundle = {
        "config_file": text_item(path="/home/pi/.hermes/config.yaml",
                                 text=GREEN_CONFIG),
        "memory_files": {
            "MEMORY.md": text_item(
                path="/home/pi/.hermes/memories/MEMORY.md",
                text="- Operator prefers concise answers.\n"
                     "- Atlas repo lives at ~/atlas.\n"),
            "USER.md": text_item(
                status="unsupported-on-device",
                path="/home/pi/.hermes/memories/USER.md"),
        },
        "session_store": store_item(),
    }
    bundle.update(overrides)
    return bundle


def make_session_db(path, plant_marker=True, with_fts=True,
                    with_tables=True):
    """Create a fixture SQLite session store shaped like the pinned
    v0.18.2 facts (state.db: sessions, messages, messages_fts)."""
    connection = sqlite3.connect(path)
    try:
        if with_tables:
            connection.execute(
                "CREATE TABLE sessions (id INTEGER PRIMARY KEY, "
                "title TEXT)")
            connection.execute(
                "CREATE TABLE messages (id INTEGER PRIMARY KEY, "
                "session_id INTEGER, role TEXT, content TEXT)")
        if with_fts:
            connection.execute(
                "CREATE VIRTUAL TABLE messages_fts USING fts5(content)")
            if plant_marker:
                connection.execute(
                    "INSERT INTO messages_fts (content) VALUES (?)",
                    ("Note for the record: %s." % amv.RECALL_MARKER,))
        connection.commit()
    finally:
        connection.close()
    return path


def results_by_check(results):
    return {result.check: result for result in results}
