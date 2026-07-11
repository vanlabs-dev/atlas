"""Test helpers: imports plus fixture builders for stores and batteries."""

import json
import os
import sqlite3
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_KNOWLEDGE_DIR = os.path.dirname(_HERE)
_REPO_ROOT = os.path.dirname(_KNOWLEDGE_DIR)
sys.path.insert(0, os.path.join(_KNOWLEDGE_DIR, "benchmark"))
sys.path.insert(0, _KNOWLEDGE_DIR)

import atlas_kb as akb  # noqa: E402
import atlas_kb_battery as kbb  # noqa: E402
import atlas_kb_score as kbs  # noqa: E402

ahv = akb.ahv
ams = kbs.ams
inv = akb.inv

SERVER_SOURCE = os.path.join(_KNOWLEDGE_DIR, "atlas_kb_server.py")
KB_SOURCE = os.path.join(_KNOWLEDGE_DIR, "atlas_kb.py")
CORPUS_DIR = akb.CORPUS_DIR

APPROVED_SHEET = "\n".join(
    "- [x] approved `%s`" % expr for expr in (
        "correct-with-evidence >= 0.9",
        "tool-call-rate >= 0.9",
        "fabrications == 0",
        "refusals-correct >= 0.9",
    )) + "\n"


def make_record(**overrides):
    record = {
        "install_source": "github.com/example/hermes-agent",
        "installed_version": "commit abc1234",
        "install_date": "2026-07-11",
        "update_method": "git pull",
        "rollback_method": "git checkout previous",
        "service_user": "pi",
        "data_dir": "/home/pi/.hermes",
        "config_path": "/home/pi/.hermes/config.yaml",
    }
    record.update(overrides)
    return {key: value for key, value in record.items() if value is not None}


def ingest_real_corpus(tmp_dir, activate=True):
    """Ingest the actual repo corpus snapshot into a tmp store."""
    db = os.path.join(tmp_dir, "kb.db")
    run_id, report = akb.ingest(db, tmp_dir)
    if activate:
        akb.activate(db, run_id, actor="test")
    return db, run_id, report


def call_server(db, requests, timeout=30):
    """Drive atlas_kb_server.py over pipes; returns payloads by id."""
    stdin = "\n".join(json.dumps(request) for request in requests) + "\n"
    completed = subprocess.run(
        [sys.executable, SERVER_SOURCE, "--db", db],
        input=stdin, capture_output=True, text=True, timeout=timeout)
    payloads = {}
    for line in completed.stdout.strip().splitlines():
        response = json.loads(line)
        result = response.get("result") or {}
        if "content" in result:
            payloads[response["id"]] = json.loads(
                result["content"][0]["text"])
        else:
            payloads[response["id"]] = result
    return payloads


def tool_call(request_id, name, arguments=None):
    return {"jsonrpc": "2.0", "id": request_id, "method": "tools/call",
            "params": {"name": name, "arguments": arguments or {}}}


def green_grounded_answer(exchange):
    expected = exchange["expected"]
    return ("According to the knowledge base: "
            + " ".join(group[0] for group in expected)
            + " (source: ground-truth.md, coverage June 2026).")


def make_session_store(path, overrides=None, skip_tags=(),
                       drop_tool_for=()):
    """Fixture Hermes state.db containing green benchmark exchanges."""
    overrides = overrides or {}
    connection = sqlite3.connect(path)
    try:
        connection.execute("CREATE TABLE sessions (id INTEGER PRIMARY "
                           "KEY)")
        connection.execute(
            "CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " session_id INTEGER, role TEXT, content TEXT,"
            " tool_name TEXT, timestamp REAL)")
        base_ts = 1783800000.0
        for index, exchange in enumerate(kbb.battery()):
            tag = str(exchange["tag"])
            if tag in skip_tags:
                continue
            session_id = index + 1
            start = base_ts + index * 60
            rows = [(session_id, "user", exchange["prompt"], None, start)]
            if (exchange["set"] in kbb.GROUNDED_SETS
                    and tag not in drop_tool_for):
                rows.append((session_id, "tool",
                             '{"status": "ok"}',
                             "mcp__atlas_kb__knowledge_search",
                             start + 1.0))
            if tag in overrides:
                answer = overrides[tag]
            elif exchange["set"] in kbb.GROUNDED_SETS:
                answer = green_grounded_answer(exchange)
            else:
                answer = ("I cannot verify live data — the knowledge "
                          "base is a snapshot, not a live source.")
            rows.append((session_id, "assistant", answer, None,
                         start + 3.0))
            connection.executemany(
                "INSERT INTO messages (session_id, role, content, "
                "tool_name, timestamp) VALUES (?, ?, ?, ?, ?)", rows)
        connection.commit()
    finally:
        connection.close()
    return path


def make_bundle(tmp_dir, kb_db=None, **store_kwargs):
    """Green benchmark evidence bundle over fixture stores."""
    store_path = os.path.join(tmp_dir, "state.db")
    if not os.path.exists(store_path):
        make_session_store(store_path, **store_kwargs)
    if kb_db is None:
        kb_db, _run, _report = ingest_real_corpus(tmp_dir)
    return {
        "store": ams.extract_exchanges(store_path,
                                       battery=kbb.battery()),
        "knowledge": kbs.knowledge_active_run(kb_db),
        "thresholds_file": {"status": "collected", "path": "/x/t.md",
                            "text": APPROVED_SHEET, "truncated": False},
    }


def results_by_check(results):
    return {result.check: result for result in results}


def run_all(bundle, attested=(), classify=None, exceptions=()):
    results, metrics, classifications = kbs.run_checks(
        make_record(), "record.json", bundle, list(attested),
        classify or {}, "op", "t0", list(exceptions))
    return results, metrics, classifications
