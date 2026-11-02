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
import urllib.parse
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


def _event(event_id="schema-drift:q1", **extra):
    event = {"event_id": event_id, "event_class": "schema-drift",
             "created_at": "2026-11-03T01:00:00+00:00",
             "text": "plain body", "html": "<b>html body</b>",
             "buttons": [("Open", "https://example.invalid/x")]}
    event.update(extra)
    return event


class QueueTests(unittest.TestCase):
    def setUp(self):
        tg._SECRET_VALUES.clear()
        self.tmp = tempfile.TemporaryDirectory()
        self.config = make_config(self.tmp.name)
        self.conn = tg.open_store(self.config["db"])

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def deliver(self, poster, event=None):
        return tg.deliver_event(self.conn, self.config, "tok12345", "42",
                                event or _event(), poster=poster)

    def flush(self, poster):
        return tg.flush_pending_sends(self.conn, self.config, "tok12345",
                                      "42", poster=poster)

    def queued(self):
        return self.conn.execute(
            "SELECT event_id, next_attempt_at FROM pending_send").fetchall()

    def status(self, event_id="schema-drift:q1"):
        return self.conn.execute(
            "SELECT status FROM events WHERE event_id = ?",
            (event_id,)).fetchone()[0]

    def test_network_error_queues(self):
        def dead(url, data, timeout):
            raise OSError("down")
        self.assertEqual(self.deliver(dead), tg.STATUS_QUEUED)
        self.assertEqual(len(self.queued()), 1)
        self.assertEqual(self.status(), tg.STATUS_QUEUED)

    def test_server_error_queues(self):
        self.assertEqual(self.deliver(lambda u, d, t: (503, "busy")),
                         tg.STATUS_QUEUED)

    def test_permanent_errors_are_final(self):
        for code in (400, 401, 403, 404):
            event = _event("schema-drift:p%d" % code, html=None)
            self.assertEqual(self.deliver(lambda u, d, t: (code, "no"),
                                          event), tg.STATUS_FAILED)
        self.assertEqual(self.queued(), [])

    def test_digest_is_not_queued(self):
        def dead(url, data, timeout):
            raise OSError("down")
        event = _event(digest_range_ids=[4])
        self.assertEqual(self.deliver(dead, event), tg.STATUS_FAILED)
        self.assertEqual(self.queued(), [])

    def test_queued_event_is_not_sent_twice(self):
        def dead(url, data, timeout):
            raise OSError("down")
        self.deliver(dead)
        posts = []
        self.assertEqual(
            self.deliver(lambda u, d, t: posts.append(d) or (200, OK_BODY)),
            tg.STATUS_QUEUED)
        self.assertEqual(posts, [])

    def test_flush_delivers_with_late_prefix(self):
        def dead(url, data, timeout):
            raise OSError("down")
        self.deliver(dead)
        self.conn.execute("UPDATE pending_send SET next_attempt_at = 0")
        posts = []
        counts = self.flush(
            lambda u, d, t: posts.append(d) or (200, OK_BODY))
        self.assertEqual(counts["delivered"], 1)
        self.assertEqual(self.queued(), [])
        body = urllib.parse.parse_qs(posts[0].decode())
        self.assertTrue(body["text"][0].startswith("<i>Late send. Detected "))
        self.assertIn("<tg-time", body["text"][0])
        self.assertIn("<b>html body</b>", body["text"][0])
        self.assertIn("reply_markup", body)
        self.assertEqual(self.status(), tg.STATUS_DELIVERED)
        row = self.conn.execute(
            "SELECT text, message_id FROM events").fetchone()
        self.assertTrue(row[0].startswith("Late send. Detected "))
        self.assertEqual(row[1], 777)

    def test_flush_waits_for_next_attempt(self):
        def dead(url, data, timeout):
            raise OSError("down")
        self.deliver(dead)
        posts = []
        self.flush(lambda u, d, t: posts.append(d) or (200, OK_BODY))
        self.assertEqual(posts, [])

    def test_429_stops_the_run_and_honours_retry_after(self):
        for n in (1, 2):
            self.deliver(lambda u, d, t: (503, "busy"),
                         _event("schema-drift:q%d" % n))
        self.conn.execute("UPDATE pending_send SET next_attempt_at = 0")
        posts = []

        def limited(url, data, timeout):
            posts.append(data)
            return 429, RATE_BODY
        counts = self.flush(limited)
        self.assertEqual(len(posts), 1)
        self.assertEqual(counts["requeued"], 1)
        hold = tg.rate_limited_until(self.conn)
        self.assertIsNotNone(hold)
        self.assertGreater(hold - tg._now_epoch(), 25)
        # A fresh event in the same window is held, not sent.
        self.assertEqual(self.deliver(limited, _event("schema-drift:q3")),
                         tg.STATUS_QUEUED)
        self.assertEqual(len(posts), 1)

    def test_expired_entry_dropped_as_failed(self):
        def dead(url, data, timeout):
            raise OSError("down")
        self.deliver(dead)
        self.conn.execute(
            "UPDATE pending_send SET first_attempt_at = ?",
            (tg._now_epoch() - tg.QUEUE_MAX_AGE_SECONDS - 10,))
        counts = self.flush(lambda u, d, t: (200, OK_BODY))
        self.assertEqual(counts["expired"], 1)
        self.assertEqual(self.queued(), [])
        self.assertEqual(self.status(), tg.STATUS_FAILED)

    def test_permanent_error_on_retry_is_dropped(self):
        def dead(url, data, timeout):
            raise OSError("down")
        self.deliver(dead, _event(html=None))
        self.conn.execute("UPDATE pending_send SET next_attempt_at = 0")
        counts = self.flush(lambda u, d, t: (403, "forbidden"))
        self.assertEqual(counts["failed"], 1)
        self.assertEqual(self.queued(), [])


class WithheldTests(unittest.TestCase):
    def setUp(self):
        tg._SECRET_VALUES.clear()

    def test_refusal_sends_one_fixed_notice(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = make_config(tmp)
            conn = tg.open_store(config["db"])
            posts = []

            def poster(url, data, timeout):
                posts.append(urllib.parse.parse_qs(data.decode())["text"][0])
                return 200, OK_BODY
            event = {"event_id": "schema-drift:leak",
                     "event_class": "schema-drift",
                     "created_at": tg._utc_now(),
                     "text": "Authorization: Bearer sk-verylongsecrettokenvalue1"}
            status = tg.deliver_event(conn, config, "tok12345", "42", event,
                                      poster=poster)
            self.assertEqual(status, tg.STATUS_SCRUB_REFUSED)
            self.assertEqual(len(posts), 1)
            self.assertIn("held back", posts[0])
            self.assertIn("schema-drift:leak", posts[0])
            self.assertNotIn("sk-verylong", posts[0])
            self.assertNotIn("Bearer", posts[0])
            # The refused alert is final: a second delivery sends nothing.
            tg.deliver_event(conn, config, "tok12345", "42", event,
                             poster=poster)
            self.assertEqual(len(posts), 1)
            self.assertEqual(conn.execute(
                "SELECT COUNT(*) FROM pending_send").fetchone()[0], 0)
            conn.close()


if __name__ == "__main__":
    unittest.main()
