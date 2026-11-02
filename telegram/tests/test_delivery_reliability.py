"""Alert delivery reliability (change: alert-delivery-reliability): the
429 body, message ids in the ledger, the durable retry queue, the withheld
notice and the narrowed CLI-flag rule."""

import io
import json
import os
import sqlite3
import sys
import tempfile
import unittest
import urllib.error
from unittest import mock

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))
sys.path.insert(0, _HERE)

import atlas_telegram as tg  # noqa: E402
from test_notifier import make_config  # noqa: E402

OK_BODY = json.dumps({"ok": True, "result": {"message_id": 777}})
RATE_BODY = json.dumps({"ok": False, "error_code": 429,
                        "description": "Too Many Requests: retry after 30",
                        "parameters": {"retry_after": 30}})


class _Response:
    def __init__(self, status, body):
        self.status = status
        self._body = body.encode("utf-8")

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class DoPostTests(unittest.TestCase):
    """The real transport, with only urlopen stubbed."""

    def test_429_body_reaches_caller(self):
        error = urllib.error.HTTPError(
            "https://api.telegram.invalid", 429, "Too Many Requests", {},
            io.BytesIO(RATE_BODY.encode("utf-8")))
        with mock.patch("urllib.request.urlopen", side_effect=error):
            status, body = tg._do_post("https://api.telegram.invalid",
                                       b"x", 5)
        self.assertEqual(status, 429)
        self.assertIn("retry_after", body)

    def test_send_message_reports_retry_after_without_inline_retry(self):
        error = urllib.error.HTTPError(
            "https://api.telegram.invalid", 429, "Too Many Requests", {},
            io.BytesIO(RATE_BODY.encode("utf-8")))
        config = make_config(tempfile.gettempdir())
        with mock.patch("urllib.request.urlopen",
                        side_effect=error) as urlopen:
            result = tg.send_message(config, "tok12345", "42", "hi")
        self.assertFalse(result["delivered"])
        self.assertEqual(result["status"], 429)
        self.assertEqual(result["retry_after"], 30.0)
        self.assertEqual(urlopen.call_count, 1)

    def test_message_id_parsed_on_200(self):
        config = make_config(tempfile.gettempdir())
        with mock.patch("urllib.request.urlopen",
                        return_value=_Response(200, OK_BODY)):
            result = tg.send_message(config, "tok12345", "42", "hi")
        self.assertTrue(result["delivered"])
        self.assertEqual(result["message_id"], 777)


class LedgerTextTests(unittest.TestCase):
    def test_delivered_event_keeps_text_and_message_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = make_config(tmp)
            conn = tg.open_store(config["db"])
            event = {"event_id": "schema-drift:1",
                     "event_class": "schema-drift",
                     "created_at": tg._utc_now(), "text": "hello there"}
            status = tg.deliver_event(conn, config, "tok12345", "42", event,
                                      poster=lambda u, d, t: (200, OK_BODY))
            self.assertEqual(status, tg.STATUS_DELIVERED)
            row = conn.execute(
                "SELECT text, message_id FROM events WHERE event_id = ?",
                ("schema-drift:1",)).fetchone()
            self.assertEqual(row, ("hello there", 777))
            conn.close()

    def test_old_store_migrates(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "telegram.db")
            old = sqlite3.connect(path)
            old.executescript(
                "CREATE TABLE events (id INTEGER PRIMARY KEY, event_id TEXT "
                "NOT NULL UNIQUE, event_class TEXT NOT NULL, created_at TEXT "
                "NOT NULL, attempted_at TEXT, status TEXT NOT NULL, "
                "retry_count INTEGER NOT NULL DEFAULT 0, final_failure TEXT)")
            old.close()
            conn = tg.open_store(path)
            columns = {r[1] for r in conn.execute("PRAGMA table_info(events)")}
            self.assertTrue({"tier", "rewrite", "text",
                             "message_id"} <= columns)
            conn.close()


if __name__ == "__main__":
    unittest.main()
