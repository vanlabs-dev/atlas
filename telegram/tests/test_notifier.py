"""Atlas Phase 5 outbound notifier tests: scrubber refusal, ledger +
de-duplication, bounded retry / token non-leak, source adapters with
watermarks, and scan-loop isolation on delivery failure."""

import datetime
import os
import sqlite3
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

import atlas_telegram as tg  # noqa: E402


def make_config(tmp, **over):
    config = {
        "credential_env_files": [],
        "bot_token_env": "TELEGRAM_BOT_TOKEN",
        "alert_chat_id_env": "TELEGRAM_ALERT_CHAT_ID",
        "api_base": "https://api.telegram.invalid",
        "db": os.path.join(tmp, "telegram.db"),
        "output_dir": tmp,
        "request_timeout_seconds": 5,
        "retry": {"max_attempts": 3, "retry_on_status": [500, 502, 503, 504],
                  "never_retry_on_status": [400, 401, 403, 404],
                  "backoff_seconds": [0.0, 0.0]},
        "coalesce_window_seconds": 3600,
        "message_max_chars": 3500,
        "classes": {
            "repository-update": {"enabled": True,
                                  "source_db": os.path.join(tmp, "repotrack.db")},
            "schema-drift": {"enabled": True,
                             "source_db": os.path.join(tmp, "livedata.db")},
            "knowledge-ingestion": {"enabled": True,
                                    "source_db": os.path.join(tmp, "knowledge.db")},
        },
    }
    config.update(over)
    return config


class ScrubberTests(unittest.TestCase):
    def setUp(self):
        tg._SECRET_VALUES.clear()

    def test_clean_message_passes(self):
        tg.assert_sendable("Atlas • subtensor updated\nnew head: abc123def456")

    def test_authorization_pattern_refused(self):
        with self.assertRaises(tg.ScrubRefusal):
            tg.assert_sendable("debug: Authorization: Bearer sk-"
                               "abcdefghijklmnopqrstuvwx")

    def test_named_secret_refused(self):
        with self.assertRaises(tg.ScrubRefusal):
            tg.assert_sendable("api_key=SUPERSECRETVALUE123456")

    def test_registered_token_refused(self):
        tg.register_secret("123456789:AAExampleBotTokenValue")
        with self.assertRaises(tg.ScrubRefusal):
            tg.assert_sendable("oops the token 123456789:AAExampleBotTokenValue")


class LedgerDedupTests(unittest.TestCase):
    def setUp(self):
        tg._SECRET_VALUES.clear()

    def test_lifecycle_and_dedup_within_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = make_config(tmp)
            conn = tg.open_store(config["db"])
            posts = []

            def ok_poster(url, data, timeout):
                posts.append(url)
                return 200, '{"ok":true}'

            event = {"event_id": "repository-update:deadbeef",
                     "event_class": "repository-update",
                     "created_at": tg._utc_now(), "text": "clean update"}
            first = tg.deliver_event(conn, config, "tok12345", "42", event,
                                     poster=ok_poster)
            self.assertEqual(first, tg.STATUS_DELIVERED)
            # Same event id again -> suppressed, no second post.
            second = tg.deliver_event(conn, config, "tok12345", "42", event,
                                      poster=ok_poster)
            self.assertEqual(second, tg.STATUS_SUPPRESSED)
            self.assertEqual(len(posts), 1)
            row = conn.execute(
                "SELECT status, retry_count, attempted_at FROM events "
                "WHERE event_id = ?", (event["event_id"],)).fetchone()
            self.assertEqual(row[0], tg.STATUS_DELIVERED)
            self.assertIsNotNone(row[2])
            conn.close()

    def test_not_suppressed_outside_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = make_config(tmp, coalesce_window_seconds=60)
            conn = tg.open_store(config["db"])
            old = (datetime.datetime.now(tz=datetime.timezone.utc)
                   - datetime.timedelta(seconds=120)).isoformat()
            tg.ledger_record(conn, "schema-drift:9", "schema-drift", old,
                             old, tg.STATUS_DELIVERED, 1, None)
            self.assertFalse(
                tg.ledger_seen_recent(conn, "schema-drift:9", 60))
            conn.close()

    def test_scrub_refused_records_and_does_not_send(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = make_config(tmp)
            conn = tg.open_store(config["db"])
            posts = []

            def poster(url, data, timeout):
                posts.append(url)
                return 200, "ok"

            event = {"event_id": "schema-drift:leak",
                     "event_class": "schema-drift",
                     "created_at": tg._utc_now(),
                     "text": "Authorization: Bearer sk-verylongsecrettokenvalue1"}
            status = tg.deliver_event(conn, config, "tok12345", "42", event,
                                      poster=poster)
            self.assertEqual(status, tg.STATUS_SCRUB_REFUSED)
            self.assertEqual(posts, [])
            conn.close()


class TransportTests(unittest.TestCase):
    def setUp(self):
        tg._SECRET_VALUES.clear()

    def test_delivered_on_200(self):
        config = make_config(tempfile.gettempdir())
        result = tg.send_message(config, "tok", "42", "hi",
                                 poster=lambda u, d, t: (200, "ok"))
        self.assertTrue(result["delivered"])
        self.assertEqual(result["attempts"], 1)

    def test_no_retry_on_client_error(self):
        config = make_config(tempfile.gettempdir())
        calls = {"n": 0}

        def poster(url, data, timeout):
            calls["n"] += 1
            return 403, "forbidden"

        result = tg.send_message(config, "tok", "42", "hi", poster=poster)
        self.assertFalse(result["delivered"])
        self.assertEqual(calls["n"], 1)

    def test_retries_then_fails_on_server_error(self):
        config = make_config(tempfile.gettempdir())
        calls = {"n": 0}

        def poster(url, data, timeout):
            calls["n"] += 1
            return 503, "unavailable"

        result = tg.send_message(config, "tok", "42", "hi", poster=poster)
        self.assertFalse(result["delivered"])
        self.assertEqual(calls["n"], 3)

    def test_token_never_in_detail(self):
        config = make_config(tempfile.gettempdir())
        tg.register_secret("SECRETTOKEN1234567890")

        def poster(url, data, timeout):
            # A misbehaving server echoing the URL (which contains the token).
            return 500, "error at " + url

        result = tg.send_message(config, "SECRETTOKEN1234567890", "42", "hi",
                                 poster=poster)
        self.assertNotIn("SECRETTOKEN1234567890", result["detail"])


class AdapterTests(unittest.TestCase):
    def test_missing_source_is_empty_not_error(self):
        events, wm = tg.repository_update_events("does/not/exist.db", None)
        self.assertEqual(events, [])
        self.assertIsNone(wm)

    def test_repo_update_watermark(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "repotrack.db")
            conn = sqlite3.connect(db)
            conn.executescript(
                "CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);")
            conn.execute("INSERT INTO meta VALUES ('last_remote_sha','abc123')")
            conn.execute("INSERT INTO meta VALUES "
                         "('last_detected_update','2026-07-12T00:00:00Z')")
            conn.commit()
            conn.close()
            events, wm = tg.repository_update_events(db, None)
            self.assertEqual(len(events), 1)
            self.assertEqual(wm, "abc123")
            # At the watermark -> nothing new.
            events2, wm2 = tg.repository_update_events(db, "abc123")
            self.assertEqual(events2, [])

    def test_schema_drift_watermark(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "livedata.db")
            conn = sqlite3.connect(db)
            conn.executescript(
                "CREATE TABLE integration_health (id INTEGER PRIMARY KEY, "
                "timestamp TEXT, provider TEXT, operation TEXT, category TEXT, "
                "detail TEXT);")
            conn.execute("INSERT INTO integration_health (timestamp, provider, "
                         "operation, category, detail) VALUES "
                         "('t','taostats','chain_head','schema-drift','missing "
                         "field block_number')")
            conn.execute("INSERT INTO integration_health (timestamp, provider, "
                         "operation, category, detail) VALUES "
                         "('t','taoswap','subnets','provider-failure','timeout')")
            conn.commit()
            conn.close()
            events, wm = tg.schema_drift_events(db, None)
            self.assertEqual(len(events), 1)  # only the drift row
            self.assertEqual(wm, "1")
            events2, _ = tg.schema_drift_events(db, wm)
            self.assertEqual(events2, [])


class ScanIsolationTests(unittest.TestCase):
    def setUp(self):
        tg._SECRET_VALUES.clear()

    def test_delivery_failure_isolated_and_recorded(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = make_config(tmp)
            # Seed a repo-update source so exactly one event is produced.
            repo = config["classes"]["repository-update"]["source_db"]
            conn = sqlite3.connect(repo)
            conn.executescript(
                "CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);")
            conn.execute("INSERT INTO meta VALUES ('last_remote_sha','feed01')")
            conn.commit()
            conn.close()

            store = tg.open_store(config["db"])

            def dead_poster(url, data, timeout):
                raise OSError("network down")

            summary = tg.notify_scan(config, "tok12345", "42", store,
                                     poster=dead_poster)
            # Scan completed despite the outage; the event is recorded failed.
            self.assertEqual(
                summary["classes"]["repository-update"]["failed"], 1)
            row = store.execute(
                "SELECT status, final_failure FROM events "
                "WHERE event_id = 'repository-update:feed01'").fetchone()
            self.assertEqual(row[0], tg.STATUS_FAILED)
            # Watermark still advances so a flapping source cannot re-flood.
            self.assertEqual(
                tg.watermark_get(store, "repository-update"), "feed01")
            store.close()


class SeedWatermarkTests(unittest.TestCase):
    def test_init_seeds_and_first_scan_skips_backlog(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = make_config(tmp)
            repo = config["classes"]["repository-update"]["source_db"]
            conn = sqlite3.connect(repo)
            conn.executescript(
                "CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);")
            conn.execute("INSERT INTO meta VALUES ('last_remote_sha','old99')")
            conn.commit()
            conn.close()

            store = tg.open_store(config["db"])
            seeded = tg.seed_watermarks(config, store)
            self.assertEqual(seeded["repository-update"]["seeded_to"], "old99")

            posts = []
            summary = tg.notify_scan(config, "tok12345", "42", store,
                                     poster=lambda u, d, t: posts.append(u)
                                     or (200, "ok"))
            # Backlog head was seeded, so the first scan delivers nothing.
            self.assertEqual(
                summary["classes"]["repository-update"]["delivered"], 0)
            self.assertEqual(posts, [])
            store.close()


if __name__ == "__main__":
    unittest.main()
