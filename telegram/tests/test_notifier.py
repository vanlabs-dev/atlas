"""Atlas Phase 5 outbound notifier tests: scrubber refusal, ledger +
de-duplication, bounded retry / token non-leak, significance tiering over
the four verified 2026-07-12 heads, durable churn digest, repo-vs-chain
marking, chain-runtime-upgrade class, HTML rendering + 400 fallback, and
scan-loop isolation on delivery failure."""

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
        "parse_mode": "HTML",
        "governance_threshold": 425,
        "repository_update": {
            "protocol_dirs": ["pallets", "runtime", "precompiles", "common"],
            "churn_dirs": [".github", "docs", "website", "vendor", "sdk"],
            "digest_backstop_hours": 24,
        },
        "classes": {
            "chain-runtime-upgrade": {
                "enabled": True,
                "source_db": os.path.join(tmp, "livedata.db")},
            "repository-update": {
                "enabled": True,
                "source_db": os.path.join(tmp, "repotrack.db"),
                "live_db": os.path.join(tmp, "livedata.db")},
            "schema-drift": {
                "enabled": True,
                "source_db": os.path.join(tmp, "livedata.db")},
            "knowledge-ingestion": {
                "enabled": True,
                "source_db": os.path.join(tmp, "knowledge.db")},
        },
    }
    config.update(over)
    return config


# --------------------------------------------------------------------------
# Fixtures: the four verified 2026-07-12 heads (upstream ground truth).
# Range 1 spec 425→428 (significant), range 2 sdk/-only (churn),
# range 3 spec 428→429 touching pallets/runtime/common (significant),
# range 4 .github/-only (churn).
# --------------------------------------------------------------------------

SHA_BASE = "14bc6f9" + "0" * 33
SHA_1 = "647ca2b" + "0" * 33
SHA_2 = "82142f9" + "0" * 33
SHA_3 = "ff1e1ed" + "0" * 33
SHA_4 = "75798da" + "0" * 33

RANGES = [
    # (prev, new, files, prev_spec, new_spec, summary)
    (SHA_BASE, SHA_1,
     ["runtime/src/lib.rs", "pallets/subtensor/src/lib.rs", "sdk/api.rs"],
     425, 428,
     "[machine summary — not verified effect] 500 commit(s), 1200 file(s) "
     "changed. Top changed areas: sdk (700), pallets (300). Recent "
     "subjects: PR #2846 bittensor-core-exploration"),
    (SHA_1, SHA_2, ["sdk/README.md"], 428, 428,
     "[machine summary — not verified effect] 2 commit(s), 1 file(s) "
     "changed. Top changed areas: sdk (1)."),
    (SHA_2, SHA_3,
     ["pallets/subtensor/src/lib.rs", "common/src/units.rs",
      "runtime/src/lib.rs"],
     428, 429,
     "[machine summary — not verified effect] 214 commit(s), 90 file(s) "
     "changed. Top changed areas: pallets (57), common (20). Recent "
     "subjects: use Vec<PerU16> for typed units (#2867)"),
    (SHA_3, SHA_4, [".github/workflows/ci.yml"], 429, 429,
     "[machine summary — not verified effect] 1 commit(s), 1 file(s) "
     "changed. Top changed areas: .github (1)."),
]

REPO_SCHEMA = """
CREATE TABLE change_ranges (
    id INTEGER PRIMARY KEY, run_id TEXT NOT NULL, prev_sha TEXT NOT NULL,
    new_sha TEXT NOT NULL, retrieved_at TEXT NOT NULL,
    non_fast_forward INTEGER NOT NULL, commits_json TEXT NOT NULL,
    files_json TEXT NOT NULL, tags_json TEXT NOT NULL,
    index_status TEXT NOT NULL, index_detail TEXT, summary TEXT NOT NULL,
    prev_spec INTEGER, new_spec INTEGER
);
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


def seed_repotrack(path, ranges=RANGES, truncated=False, non_ff=False):
    import json
    conn = sqlite3.connect(path)
    conn.executescript(REPO_SCHEMA)
    for prev, new, files, prev_spec, new_spec, summary in ranges:
        conn.execute(
            "INSERT INTO change_ranges (run_id, prev_sha, new_sha, "
            "retrieved_at, non_fast_forward, commits_json, files_json, "
            "tags_json, index_status, summary, prev_spec, new_spec) "
            "VALUES ('r', ?, ?, 't', ?, '{}', ?, '[]', 'ok', ?, ?, ?)",
            (prev, new, 1 if non_ff else 0,
             json.dumps({"files": [{"path": item} for item in files],
                         "truncated": truncated}),
             summary, prev_spec, new_spec))
    conn.execute("INSERT INTO meta VALUES ('last_remote_sha', ?)", (SHA_4,))
    conn.commit()
    conn.close()


def seed_livedata(path, live_spec=424, upgrades=()):
    conn = sqlite3.connect(path)
    conn.executescript(
        "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, "
        "value TEXT NOT NULL);"
        "CREATE TABLE IF NOT EXISTS spec_upgrades (id INTEGER PRIMARY KEY, "
        "observed_at TEXT NOT NULL, prev_spec INTEGER NOT NULL, "
        "new_spec INTEGER NOT NULL, block_reference INTEGER);"
        "CREATE TABLE IF NOT EXISTS integration_health (id INTEGER PRIMARY "
        "KEY, timestamp TEXT, provider TEXT, operation TEXT, category TEXT, "
        "detail TEXT);")
    if live_spec is not None:
        conn.execute("INSERT INTO meta VALUES ('last_live_spec', ?)",
                     (str(live_spec),))
        conn.execute("INSERT INTO meta VALUES ('last_live_spec_block', "
                     "'8612004')")
    for prev, new, block in upgrades:
        conn.execute(
            "INSERT INTO spec_upgrades (observed_at, prev_spec, new_spec, "
            "block_reference) VALUES ('2026-07-13T00:00:00+00:00', ?, ?, ?)",
            (prev, new, block))
    conn.commit()
    conn.close()


def repo_ctx(config, connection):
    return {"config": config,
            "spec": config["classes"]["repository-update"],
            "connection": connection}


def ok_poster_factory(posts):
    def poster(url, data, timeout):
        posts.append(data.decode("utf-8"))
        return 200, '{"ok":true}'
    return poster


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
            event = {"event_id": "repository-update:deadbeef",
                     "event_class": "repository-update",
                     "created_at": tg._utc_now(), "text": "clean update"}
            first = tg.deliver_event(conn, config, "tok12345", "42", event,
                                     poster=ok_poster_factory(posts))
            self.assertEqual(first, tg.STATUS_DELIVERED)
            second = tg.deliver_event(conn, config, "tok12345", "42", event,
                                      poster=ok_poster_factory(posts))
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
            event = {"event_id": "schema-drift:leak",
                     "event_class": "schema-drift",
                     "created_at": tg._utc_now(),
                     "text": "Authorization: Bearer sk-verylongsecrettokenvalue1"}
            status = tg.deliver_event(conn, config, "tok12345", "42", event,
                                      poster=ok_poster_factory(posts))
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
            return 500, "error at " + url

        result = tg.send_message(config, "SECRETTOKEN1234567890", "42", "hi",
                                 poster=poster)
        self.assertNotIn("SECRETTOKEN1234567890", result["detail"])

    def test_parse_mode_in_payload_only_when_set(self):
        config = make_config(tempfile.gettempdir())
        seen = []

        def poster(url, data, timeout):
            seen.append(data.decode("utf-8"))
            return 200, "ok"

        tg.send_message(config, "tok", "42", "hi", poster=poster)
        self.assertNotIn("parse_mode", seen[0])
        tg.send_message(config, "tok", "42", "<b>hi</b>", poster=poster,
                        parse_mode="HTML")
        self.assertIn("parse_mode=HTML", seen[1])


class ClassifierTests(unittest.TestCase):
    """Deny-by-default significance (spec: tiered repository alerts)."""

    POLICY = {"protocol_dirs": set(tg.DEFAULT_PROTOCOL_DIRS),
              "churn_dirs": set(tg.DEFAULT_CHURN_DIRS),
              "digest_backstop_hours": 24}

    def rng(self, **over):
        base = {"files_truncated": False, "non_fast_forward": False,
                "prev_spec": 428, "new_spec": 428,
                "files": ["docs/readme.md"]}
        base.update(over)
        return base

    def classify(self, rng):
        return tg.classify_range(rng, self.POLICY)

    def test_spec_bump_significant(self):
        self.assertEqual(self.classify(
            self.rng(prev_spec=425, new_spec=428)), tg.SIGNIFICANT)

    def test_protocol_dir_significant(self):
        self.assertEqual(self.classify(
            self.rng(files=["pallets/x.rs", "docs/a.md"])), tg.SIGNIFICANT)

    def test_churn_allowlist_only_is_churn(self):
        self.assertEqual(self.classify(
            self.rng(files=["sdk/a.rs", ".github/ci.yml", "docs/x.md"])),
            tg.CHURN)

    def test_unknown_top_dir_escalates(self):
        self.assertEqual(self.classify(
            self.rng(files=["docs/a.md", "clones/new-tree/x.rs"])),
            tg.SIGNIFICANT)

    def test_root_level_file_escalates(self):
        self.assertEqual(self.classify(
            self.rng(files=["Cargo.lock"])), tg.SIGNIFICANT)

    def test_incomplete_record_escalates(self):
        self.assertEqual(self.classify(
            self.rng(files_truncated=True)), tg.SIGNIFICANT)
        self.assertEqual(self.classify(
            self.rng(non_fast_forward=True)), tg.SIGNIFICANT)

    def test_unknown_spec_with_churn_dirs_is_churn(self):
        self.assertEqual(self.classify(
            self.rng(prev_spec=None, new_spec=None,
                     files=["docs/a.md"])), tg.CHURN)


class FourHeadsTests(unittest.TestCase):
    """The verified 2026-07-12 replay: 2 significant + 2 churn."""

    def setUp(self):
        tg._SECRET_VALUES.clear()
        self.tmp = tempfile.TemporaryDirectory()
        self.config = make_config(self.tmp.name)
        seed_repotrack(self.config["classes"]["repository-update"]
                       ["source_db"])
        seed_livedata(self.config["classes"]["repository-update"]["live_db"])
        self.store = tg.open_store(self.config["db"])

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def pending(self):
        return self.store.execute(
            "SELECT range_id FROM pending_churn ORDER BY range_id"
        ).fetchall()

    def test_two_significant_two_churn_digest_rides_second(self):
        events, wm = tg.repository_update_events(
            self.config["classes"]["repository-update"]["source_db"], None,
            repo_ctx(self.config, self.store))
        self.assertEqual(wm, "4")
        self.assertEqual(len(events), 2)
        first, second = events
        self.assertIn("runtime spec bump 425→428", first["text"])
        self.assertEqual(first["digest_range_ids"], [])
        self.assertIn("runtime spec bump 428→429", second["text"])
        # The sdk/-only churn (range 2) rides the second significant alert.
        self.assertEqual(second["digest_range_ids"], [2])
        self.assertIn("sdk", second["text"])
        self.assertIn(SHA_2[:12], second["text"])
        self.assertIn("no protocol/spec change", second["text"])
        # Both churn ranges are durably pending until a digest DELIVERS.
        self.assertEqual(self.pending(), [(2,), (4,)])

    def test_both_clocks_line_and_repo_marking(self):
        events, _ = tg.repository_update_events(
            self.config["classes"]["repository-update"]["source_db"], None,
            repo_ctx(self.config, self.store))
        self.assertIn("repo spec 428 · live Finney spec 424 · Δ+4",
                      events[0]["text"])
        self.assertIn("live chain has NOT changed", events[0]["text"])
        self.assertIn("repo spec 429 · live Finney spec 424 · Δ+5",
                      events[1]["text"])
        self.assertIn("source: repository (source code)", events[1]["text"])

    def test_live_unavailable_degrades_honestly(self):
        os.remove(self.config["classes"]["repository-update"]["live_db"])
        events, _ = tg.repository_update_events(
            self.config["classes"]["repository-update"]["source_db"], None,
            repo_ctx(self.config, self.store))
        self.assertEqual(len(events), 2)
        self.assertIn("live chain spec unavailable", events[0]["text"])
        self.assertIn("repository (source-code) event", events[0]["text"])

    def test_churn_survives_scans_and_clears_only_on_delivery(self):
        posts = []
        summary = tg.notify_scan(self.config, "tok12345", "42", self.store,
                                 poster=ok_poster_factory(posts))
        counts = summary["classes"]["repository-update"]
        self.assertEqual(counts["delivered"], 2)
        # Range 2 was digested by a DELIVERED alert -> cleared; range 4
        # arrived after the last significant alert -> still pending.
        self.assertEqual(self.pending(), [(4,)])
        # An intervening empty scan does not lose it.
        summary2 = tg.notify_scan(self.config, "tok12345", "42", self.store,
                                  poster=ok_poster_factory(posts))
        self.assertEqual(
            summary2["classes"]["repository-update"]["delivered"], 0)
        self.assertEqual(self.pending(), [(4,)])

    def test_backstop_flushes_lingering_churn(self):
        posts = []
        tg.notify_scan(self.config, "tok12345", "42", self.store,
                       poster=ok_poster_factory(posts))
        self.assertEqual(self.pending(), [(4,)])
        self.config["repository_update"]["digest_backstop_hours"] = 0
        summary = tg.notify_scan(self.config, "tok12345", "42", self.store,
                                 poster=ok_poster_factory(posts))
        self.assertEqual(
            summary["classes"]["repository-update"]["delivered"], 1)
        self.assertEqual(self.pending(), [])
        self.assertIn("low-signal", posts[-1])

    def test_failed_digest_delivery_keeps_pending(self):
        def poster(url, data, timeout):
            return 500, "unavailable"

        tg.notify_scan(self.config, "tok12345", "42", self.store,
                       poster=poster)
        # Nothing delivered -> nothing cleared, both churn ranges pending.
        self.assertEqual(self.pending(), [(2,), (4,)])


class WatermarkMigrationTests(unittest.TestCase):
    def setUp(self):
        tg._SECRET_VALUES.clear()
        self.tmp = tempfile.TemporaryDirectory()
        self.config = make_config(self.tmp.name)
        self.db = self.config["classes"]["repository-update"]["source_db"]
        seed_repotrack(self.db)
        seed_livedata(self.config["classes"]["repository-update"]["live_db"])
        self.store = tg.open_store(self.config["db"])

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_legacy_sha_watermark_translates_to_range_id(self):
        # Deployed watermark is range 2's head SHA -> resume from id 2.
        events, wm = tg.repository_update_events(
            self.db, SHA_2, repo_ctx(self.config, self.store))
        self.assertEqual(wm, "4")
        self.assertEqual(len(events), 1)  # range 3 significant, range 4 churn
        self.assertIn("428→429", events[0]["text"])

    def test_unknown_sha_reseeds_to_max_without_replay(self):
        events, wm = tg.repository_update_events(
            self.db, "a" * 40, repo_ctx(self.config, self.store))
        self.assertEqual(events, [])
        self.assertEqual(wm, "4")

    def test_numeric_watermark_used_directly(self):
        events, wm = tg.repository_update_events(
            self.db, "4", repo_ctx(self.config, self.store))
        self.assertEqual(events, [])
        self.assertEqual(wm, "4")


class ChainUpgradeTests(unittest.TestCase):
    def setUp(self):
        tg._SECRET_VALUES.clear()
        self.tmp = tempfile.TemporaryDirectory()
        self.config = make_config(self.tmp.name)
        self.db = self.config["classes"]["chain-runtime-upgrade"]["source_db"]

    def tearDown(self):
        self.tmp.cleanup()

    def test_upgrade_event_fires_once_with_threshold(self):
        seed_livedata(self.db, live_spec=425,
                      upgrades=[(424, 425, 8612004)])
        ctx = {"config": self.config,
               "spec": self.config["classes"]["chain-runtime-upgrade"],
               "connection": None}
        events, wm = tg.chain_runtime_upgrade_events(self.db, None, ctx)
        self.assertEqual(len(events), 1)
        self.assertEqual(wm, "1")
        text = events[0]["text"]
        self.assertIn("LIVE CHAIN UPGRADED", text)
        self.assertIn("424 → 425", text)
        self.assertIn("8612004", text)
        self.assertIn("ENACTED", text)
        self.assertIn("LIVE network changing (enacted)", text)
        # Watermark advanced -> no re-emit.
        again, _ = tg.chain_runtime_upgrade_events(self.db, wm, ctx)
        self.assertEqual(again, [])

    def test_non_threshold_upgrade_has_no_enactment_note(self):
        seed_livedata(self.db, live_spec=429,
                      upgrades=[(428, 429, 8700000)])
        events, _ = tg.chain_runtime_upgrade_events(self.db, None, None)
        self.assertEqual(len(events), 1)
        self.assertNotIn("ENACTED", events[0]["text"])

    def test_missing_table_is_no_events_not_error(self):
        conn = sqlite3.connect(self.db)
        conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
        conn.commit()
        conn.close()
        events, wm = tg.chain_runtime_upgrade_events(self.db, None, None)
        self.assertEqual(events, [])
        self.assertIsNone(wm)


class HtmlRenderTests(unittest.TestCase):
    def setUp(self):
        tg._SECRET_VALUES.clear()

    def test_dynamic_values_escaped(self):
        body = tg.render_html("Repo — spec bump",
                              ["subject: use Vec<PerU16> & friends"],
                              "summary with <tags> & entities", None, 3500)
        self.assertIn("Vec&lt;PerU16&gt; &amp; friends", body)
        self.assertIn("&lt;tags&gt; &amp; entities", body)
        self.assertNotIn("<PerU16>", body)

    def test_only_supported_tags_and_balanced(self):
        body = tg.render_html("head", ["line"], "expand", "trail", 3500)
        self.assertTrue(body.startswith("<b>"))
        self.assertEqual(body.count("<blockquote expandable>"),
                         body.count("</blockquote>"))
        self.assertEqual(body.count("<b>"), body.count("</b>"))
        self.assertEqual(body.count("<i>"), body.count("</i>"))

    def test_oversized_content_shrinks_within_limit_balanced(self):
        body = tg.render_html("headline", ["line one", "line two"],
                              "x" * 10000, "trailer", 1000)
        self.assertLessEqual(len(body), 1000)
        self.assertEqual(body.count("<blockquote expandable>"),
                         body.count("</blockquote>"))
        self.assertIn("…", body)

    def test_escape_load_bearing_commit_subject(self):
        # A real in-range subject contains Vec<PerU16>; unescaped it
        # would 400 the send.
        self.assertEqual(tg.html_escape("Vec<PerU16>"),
                         "Vec&lt;PerU16&gt;")


class Html400FallbackTests(unittest.TestCase):
    def setUp(self):
        tg._SECRET_VALUES.clear()

    def test_400_falls_back_to_plain_once_and_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = make_config(tmp)
            conn = tg.open_store(config["db"])
            sent = []

            def poster(url, data, timeout):
                body = data.decode("utf-8")
                sent.append(body)
                if "parse_mode=HTML" in body:
                    return 400, '{"description":"can\'t parse entities"}'
                return 200, '{"ok":true}'

            event = {"event_id": "repository-update:range:9",
                     "event_class": "repository-update",
                     "created_at": tg._utc_now(),
                     "text": "plain structured text",
                     "html": "<b>bad</b> markup"}
            status = tg.deliver_event(conn, config, "tok12345", "42", event,
                                      poster=poster)
            self.assertEqual(status, tg.STATUS_DELIVERED)
            self.assertEqual(len(sent), 2)
            self.assertIn("parse_mode=HTML", sent[0])
            self.assertNotIn("parse_mode", sent[1])
            self.assertNotIn("%3Cb%3E", sent[1])  # never the raw HTML source
            row = conn.execute(
                "SELECT status, final_failure FROM events WHERE "
                "event_id = ?", (event["event_id"],)).fetchone()
            self.assertEqual(row[0], tg.STATUS_DELIVERED)
            self.assertIn("html-400-fallback", row[1])
            conn.close()

    def test_html_never_sliced_oversize_demotes_to_plain(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = make_config(tmp, message_max_chars=100)
            conn = tg.open_store(config["db"])
            sent = []

            event = {"event_id": "repository-update:range:8",
                     "event_class": "repository-update",
                     "created_at": tg._utc_now(),
                     "text": "short plain",
                     "html": "<b>" + "y" * 300 + "</b>"}
            status = tg.deliver_event(conn, config, "tok12345", "42", event,
                                      poster=ok_poster_factory(sent))
            self.assertEqual(status, tg.STATUS_DELIVERED)
            self.assertEqual(len(sent), 1)
            self.assertNotIn("parse_mode", sent[0])
            conn.close()


class EndToEndTests(unittest.TestCase):
    """Task 7.3: fixture DBs reproduce the four heads + a live spec
    change; two significant alerts (second carries the sdk digest), one
    chain upgrade first, no churn pages, trailing .github churn pending."""

    def setUp(self):
        tg._SECRET_VALUES.clear()

    def test_full_scan_replay(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = make_config(tmp)
            seed_repotrack(config["classes"]["repository-update"]
                           ["source_db"])
            seed_livedata(config["classes"]["repository-update"]["live_db"],
                          live_spec=425, upgrades=[(424, 425, 8612004)])
            store = tg.open_store(config["db"])
            posts = []
            summary = tg.notify_scan(config, "tok12345", "42", store,
                                     poster=ok_poster_factory(posts))
            self.assertEqual(
                summary["classes"]["chain-runtime-upgrade"]["delivered"], 1)
            self.assertEqual(
                summary["classes"]["repository-update"]["delivered"], 2)
            # Priority: the chain upgrade is the FIRST message out.
            self.assertIn("LIVE+CHAIN+UPGRADED",
                          posts[0].replace("%20", "+"))
            # Exactly three messages: no churn ever paged.
            self.assertEqual(len(posts), 3)
            pending = store.execute(
                "SELECT range_id FROM pending_churn").fetchall()
            self.assertEqual(pending, [(4,)])
            # HTML parse mode used for the tiered messages.
            self.assertIn("parse_mode=HTML", posts[1])
            store.close()


class ScanIsolationTests(unittest.TestCase):
    def setUp(self):
        tg._SECRET_VALUES.clear()

    def test_delivery_failure_isolated_and_recorded(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = make_config(tmp)
            seed_repotrack(config["classes"]["repository-update"]
                           ["source_db"], ranges=[RANGES[0]])
            store = tg.open_store(config["db"])

            def dead_poster(url, data, timeout):
                raise OSError("network down")

            summary = tg.notify_scan(config, "tok12345", "42", store,
                                     poster=dead_poster)
            self.assertEqual(
                summary["classes"]["repository-update"]["failed"], 1)
            row = store.execute(
                "SELECT status, final_failure FROM events "
                "WHERE event_id = 'repository-update:range:1'").fetchone()
            self.assertEqual(row[0], tg.STATUS_FAILED)
            # Watermark still advances so a flapping source cannot re-flood.
            self.assertEqual(
                tg.watermark_get(store, "repository-update"), "1")
            store.close()


class SeedWatermarkTests(unittest.TestCase):
    def setUp(self):
        tg._SECRET_VALUES.clear()

    def test_init_seeds_and_first_scan_skips_backlog(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = make_config(tmp)
            seed_repotrack(config["classes"]["repository-update"]
                           ["source_db"])
            seed_livedata(config["classes"]["repository-update"]["live_db"],
                          live_spec=424, upgrades=[(423, 424, 8500000)])
            store = tg.open_store(config["db"])
            seeded = tg.seed_watermarks(config, store)
            self.assertEqual(
                seeded["repository-update"]["seeded_to"], "4")
            self.assertEqual(
                seeded["chain-runtime-upgrade"]["seeded_to"], "1")
            # Seeding never populates the pending digest (backlog churn
            # is skipped, not digested later as stale noise).
            self.assertEqual(store.execute(
                "SELECT COUNT(*) FROM pending_churn").fetchone()[0], 0)

            posts = []
            summary = tg.notify_scan(config, "tok12345", "42", store,
                                     poster=ok_poster_factory(posts))
            self.assertEqual(
                summary["classes"]["repository-update"]["delivered"], 0)
            self.assertEqual(
                summary["classes"]["chain-runtime-upgrade"]["delivered"], 0)
            self.assertEqual(posts, [])
            store.close()


if __name__ == "__main__":
    unittest.main()
