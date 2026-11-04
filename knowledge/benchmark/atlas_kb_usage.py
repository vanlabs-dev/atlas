#!/usr/bin/env python3
"""Grounding usage report (change: kb-battery-honesty, audit A5).

How many Telegram user turns on Bittensor topics were answered with an
Atlas knowledge or live tool call, and how many without one. Read-only:
the Hermes session store opens `mode=ro`, and the output holds counts and
session ids only, never message text.

    python3 knowledge/benchmark/atlas_kb_usage.py report [--days 30]
        [--store ~/.hermes/state.db]

A turn is "on topic" when its text contains a word from TOPIC_WORDS. That
is a heuristic: read the counts as a trend, not a measurement of every
question. A turn is "grounded" when an Atlas tool result (TOOL_MARKERS)
appears after it and before the next user turn.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import time
from typing import Any, Dict, List, Optional

TOPIC_WORDS = (
    "alpha", "bittensor", "bonds", "burn", "childkey", "coldkey",
    "commit-reveal", "consensus", "conviction", "dtao", "emission", "epoch",
    "halving", "hotkey", "immunity", "incentive", "liquid alpha", "miner",
    "netuid", "root", "stake", "staking", "subnet", "subtensor", "tao",
    "tempo", "validator", "weights", "yuma",
)
TOOL_MARKERS = ("mcp__atlas_kb__", "mcp__atlas_live__", "mcp__atlas_fleet__",
                "mcp__atlas_repo__")
_TOPIC = re.compile(r"(?i)(?<![a-z0-9])(%s)" % "|".join(
    re.escape(word) for word in TOPIC_WORDS))


def report(store: str, days: int, now: Optional[float] = None
           ) -> Dict[str, Any]:
    since = (now if now is not None else time.time()) - days * 86400
    connection = sqlite3.connect("file:%s?mode=ro" % store, uri=True)
    try:
        sessions = [row[0] for row in connection.execute(
            "SELECT id FROM sessions WHERE source = 'telegram'")]
        grounded = ungrounded = 0
        ungrounded_sessions: Dict[str, int] = {}
        for session in sessions:
            rows = connection.execute(
                "SELECT role, content, tool_name, timestamp FROM messages "
                "WHERE session_id = ? ORDER BY id", (session,)).fetchall()
            open_turn = None  # (on_topic, grounded) of the current turn
            turns: List[Any] = []
            for role, content, tool_name, stamp in rows:
                if role == "user":
                    if open_turn is not None:
                        turns.append(open_turn)
                    on_topic = (stamp is not None and stamp >= since
                                and bool(_TOPIC.search(content or "")))
                    open_turn = [on_topic, False]
                elif (open_turn is not None and tool_name
                      and tool_name.startswith(TOOL_MARKERS)):
                    open_turn[1] = True
            if open_turn is not None:
                turns.append(open_turn)
            for on_topic, used_tool in turns:
                if not on_topic:
                    continue
                if used_tool:
                    grounded += 1
                else:
                    ungrounded += 1
                    ungrounded_sessions[str(session)] = (
                        ungrounded_sessions.get(str(session), 0) + 1)
    finally:
        connection.close()
    return {
        "window_days": days,
        "telegram_sessions": len(sessions),
        "topic_turns": grounded + ungrounded,
        "grounded": grounded,
        "ungrounded": ungrounded,
        "ungrounded_by_session": ungrounded_sessions,
        "topic_words": list(TOPIC_WORDS),
        "tool_markers": list(TOOL_MARKERS),
        "note": "heuristic topic match; counts are a trend, not a census",
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="atlas_kb_usage")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("report")
    run.add_argument("--days", type=int, default=30)
    run.add_argument("--store", default=os.path.expanduser(
        "~/.hermes/state.db"))
    args = parser.parse_args(argv)
    if not os.path.exists(args.store):
        print("no session store at %s" % args.store, file=sys.stderr)
        return 2
    try:
        result = report(args.store, args.days)
    except sqlite3.Error as exc:
        print("store unreadable: %s" % exc, file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
