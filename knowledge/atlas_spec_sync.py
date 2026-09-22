#!/usr/bin/env python3
"""Stable Finney spec-sync line. No timestamps. No writes.

Prints corpus=<n> live=<n> repo=<n> so a monitor can wake an agent only
when the line changes. Fail-closed numbers: a missing source prints n/a
for that field and exits 0. The agent, not this script, rewrites the corpus.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import sys

ATLAS = os.environ.get("ATLAS_ROOT", "/home/pi/atlas")
HASHES = os.path.join(ATLAS, "knowledge", "corpus", "hashes.json")
LIVE_DB = os.path.join(ATLAS, "var", "livedata", "livedata.db")
RUNTIME = os.path.join(
    ATLAS, "var", "repotrack", "subtensor", "runtime", "src", "lib.rs")
SPEC_RE = re.compile(r"spec_version:\s*(\d+)")


def corpus_spec() -> str:
    try:
        with open(HASHES, "r", encoding="utf-8") as handle:
            manifest = json.load(handle)
        value = manifest.get("grounded_spec")
        if isinstance(value, int):
            return str(value)
    except (OSError, ValueError, json.JSONDecodeError):
        pass
    return "n/a"


def live_spec() -> str:
    try:
        connection = sqlite3.connect(
            "file:%s?mode=ro" % LIVE_DB, uri=True)
        try:
            row = connection.execute(
                "SELECT new_spec FROM spec_upgrades ORDER BY id DESC LIMIT 1"
            ).fetchone()
        finally:
            connection.close()
        if row and row[0] is not None:
            return str(int(row[0]))
    except (OSError, sqlite3.Error, TypeError, ValueError):
        pass
    return "n/a"


def repo_spec() -> str:
    try:
        with open(RUNTIME, "r", encoding="utf-8") as handle:
            # The runtime manifest is near the top. Bound the read.
            text = handle.read(20000)
        match = SPEC_RE.search(text)
        if match:
            return match.group(1)
    except OSError:
        pass
    return "n/a"


def main() -> int:
    line = "corpus=%s live=%s repo=%s" % (
        corpus_spec(), live_spec(), repo_spec())
    sys.stdout.write(line + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
