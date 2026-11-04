"""Grounding usage report (change: kb-battery-honesty)."""

import contextlib
import io
import json
import os
import sqlite3
import sys
import tempfile
import unittest

import _helpers  # noqa: F401  (puts benchmark/ on the path)
import atlas_kb_usage as usage

NOW = 1793700000.0
SECRET_TEXT = "my private question about subnet 51 staking"


def make_store(path):
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE sessions (id TEXT, source TEXT)")
    connection.execute(
        "CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "session_id TEXT, role TEXT, content TEXT, tool_name TEXT, "
        "timestamp REAL)")
    connection.executemany("INSERT INTO sessions VALUES (?, ?)",
                           [("t1", "telegram"), ("c1", "cli")])
    rows = [
        ("t1", "user", SECRET_TEXT, None, NOW - 100),
        ("t1", "tool", "{}", "mcp__atlas_kb__knowledge_search", NOW - 99),
        ("t1", "assistant", "answer", None, NOW - 98),
        ("t1", "user", "how does yuma consensus work", None, NOW - 90),
        ("t1", "assistant", "from memory", None, NOW - 89),
        ("t1", "user", "thanks, what's for dinner", None, NOW - 80),
        ("t1", "assistant", "no idea", None, NOW - 79),
        ("t1", "user", "old subnet question", None, NOW - 40 * 86400),
        ("t1", "assistant", "old", None, NOW - 40 * 86400 + 1),
        ("t1", "user", "validator take?", None, NOW - 50),
        ("t1", "tool", "{}", "mcp__atlas_test__atlas_ping", NOW - 49),
        ("c1", "user", "subnet question on cli", None, NOW - 10),
    ]
    connection.executemany(
        "INSERT INTO messages (session_id, role, content, tool_name, "
        "timestamp) VALUES (?, ?, ?, ?, ?)", rows)
    connection.commit()
    connection.close()


class UsageReportTests(unittest.TestCase):
    def test_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = os.path.join(tmp, "state.db")
            make_store(store)
            result = usage.report(store, 30, now=NOW)
        # grounded: the staking turn; ungrounded: yuma (no tool) and the
        # validator turn (atlas_test is not an Atlas reader); dinner is off
        # topic; the old turn is outside the window; cli is not telegram
        self.assertEqual((result["grounded"], result["ungrounded"]), (1, 2))
        self.assertEqual(result["ungrounded_by_session"], {"t1": 2})
        self.assertEqual(result["telegram_sessions"], 1)
        self.assertIn("yuma", result["topic_words"])

    def test_output_has_no_message_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = os.path.join(tmp, "state.db")
            make_store(store)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(usage.main(["report", "--store", store,
                                             "--days", "30"]), 0)
        self.assertNotIn("private question", out.getvalue())
        self.assertNotIn("dinner", out.getvalue())

    def test_store_opened_read_only(self):
        with open(usage.__file__, encoding="utf-8") as handle:
            source = handle.read()
        self.assertIn("mode=ro", source)
        for verb in ("INSERT", "UPDATE", "DELETE", "CREATE", "DROP"):
            self.assertNotIn(verb, source)


if __name__ == "__main__":
    unittest.main()
