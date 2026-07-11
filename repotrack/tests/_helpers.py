"""Test helpers: throwaway origin repos, pinned configs, server driver."""

import json
import os
import sqlite3
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPOTRACK_DIR = os.path.dirname(_HERE)
_REPO_ROOT = os.path.dirname(_REPOTRACK_DIR)
sys.path.insert(0, _REPOTRACK_DIR)

import atlas_repo as arp  # noqa: E402

SERVER_SOURCE = os.path.join(_REPOTRACK_DIR, "atlas_repo_server.py")
REPO_SOURCE = os.path.join(_REPOTRACK_DIR, "atlas_repo.py")


def git(cwd, *args):
    completed = subprocess.run(
        ["git", "-C", cwd] + list(args), capture_output=True, text=True,
        encoding="utf-8", errors="replace")
    assert completed.returncode == 0, "git %s failed: %s" % (
        " ".join(args), completed.stderr)
    return completed.stdout.strip()


def make_origin(tmp_dir, files=None):
    """Non-bare fixture repository the clone fetches from."""
    origin = os.path.join(tmp_dir, "origin")
    os.makedirs(origin)
    git(origin, "init", "-b", "main")
    git(origin, "config", "user.email", "test@atlas.local")
    git(origin, "config", "user.name", "Atlas Test")
    git(origin, "config", "commit.gpgsign", "false")
    files = files or {
        "README.md": "# Fixture subtensor\nemission schedule docs\n",
        "pallets/subtensor/src/lib.rs":
            "// conviction pallet entry\npub fn set_conviction() {}\n",
        "scripts/run.sh": "#!/bin/sh\necho run\n",
    }
    for rel_path, content in files.items():
        write_origin_file(origin, rel_path, content)
    git(origin, "add", "-A")
    git(origin, "commit", "-m", "initial fixture state")
    return origin


def write_origin_file(origin, rel_path, content, binary=False):
    path = os.path.join(origin, rel_path.replace("/", os.sep))
    os.makedirs(os.path.dirname(path) or origin, exist_ok=True)
    mode = "wb" if binary else "w"
    kwargs = {} if binary else {"encoding": "utf-8", "newline": "\n"}
    with open(path, mode, **kwargs) as handle:
        handle.write(content)


def commit_origin(origin, message="update fixture"):
    git(origin, "add", "-A")
    git(origin, "commit", "-m", message)
    return git(origin, "rev-parse", "HEAD")


def make_config(tmp_dir, origin, confirmed=True, **overrides):
    """Write a pinned-identity config with absolute temp paths."""
    config = {
        "identity": {
            "owner": "fixture",
            "name": "subtensor",
            "clone_url": origin,
            "branch": "main",
        },
        "confirmed_decision": ("docs/decisions.md test entry"
                               if confirmed else None),
        "access": "anonymous",
        "update_interval_hours": 24,
        "stale_multiplier": 2,
        "clone_dir": os.path.join(tmp_dir, "clone"),
        "db": os.path.join(tmp_dir, "repotrack.db"),
        "index": {
            "extensions": [".rs", ".md", ".sh", ".txt"],
            "max_file_bytes": 4096,
        },
    }
    config.update(overrides)
    path = os.path.join(tmp_dir, "config.json")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(config, handle)
    return path, config


def run_cli(config_path, *argv):
    return arp.main(["--config", config_path] + list(argv))


def setup_tracking(tmp_dir, **config_overrides):
    """Origin + confirmed config + setup + initial index."""
    origin = make_origin(tmp_dir)
    config_path, config = make_config(tmp_dir, origin, **config_overrides)
    assert run_cli(config_path, "setup", "--actor", "test") == 0
    assert run_cli(config_path, "index", "--actor", "test") == 0
    return {"origin": origin, "config_path": config_path,
            "config": config, "clone": config["clone_dir"],
            "db": config["db"]}


def query(db, sql, params=()):
    connection = sqlite3.connect(db)
    try:
        return connection.execute(sql, params).fetchall()
    finally:
        connection.close()


def set_meta(db, key, value):
    connection = sqlite3.connect(db)
    try:
        connection.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value))
        connection.commit()
    finally:
        connection.close()


def last_run(db):
    rows = query(db, "SELECT run_id, status, error, prev_sha, new_sha, "
                     "fast_forward FROM update_runs "
                     "ORDER BY started_at DESC, run_id DESC LIMIT 1")
    if not rows:
        return None
    keys = ("run_id", "status", "error", "prev_sha", "new_sha",
            "fast_forward")
    return dict(zip(keys, rows[0]))


def change_ranges(db):
    rows = query(db, "SELECT prev_sha, new_sha, non_fast_forward, "
                     "commits_json, files_json, tags_json, index_status, "
                     "index_detail, summary FROM change_ranges ORDER BY id")
    keys = ("prev_sha", "new_sha", "non_fast_forward", "commits_json",
            "files_json", "tags_json", "index_status", "index_detail",
            "summary")
    return [dict(zip(keys, row)) for row in rows]


def call_server(config_path, requests, timeout=60):
    """Drive atlas_repo_server.py over pipes; returns payloads by id."""
    stdin = "\n".join(json.dumps(request) for request in requests) + "\n"
    completed = subprocess.run(
        [sys.executable, SERVER_SOURCE, "--config", config_path],
        input=stdin, capture_output=True, text=True, timeout=timeout,
        encoding="utf-8", errors="replace")
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
