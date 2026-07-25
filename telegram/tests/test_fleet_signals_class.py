"""fleet-signal notifier class (change: fleet-signals): adapter tiering
(instant pages, digest rows durable and never paged), house-style
rendering with entry-price lines, class-specific ledger dedup, mixed-scan
ordering below chain upgrades, read-only fleet store access, and init
watermark seeding."""

import datetime
import json
import os
import sqlite3
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

import atlas_telegram as tg  # noqa: E402
from test_notifier import make_config  # noqa: E402

FLEET_SCHEMA = """
CREATE TABLE signal_events (
    id INTEGER PRIMARY KEY, class TEXT NOT NULL, tier TEXT NOT NULL,
    netuid INTEGER, term TEXT, dedup_key TEXT NOT NULL UNIQUE,
    payload_json TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE signal_entries (
    event_id INTEGER NOT NULL, netuid INTEGER NOT NULL, price_tao REAL,
    as_of TEXT, status TEXT NOT NULL DEFAULT 'pending',
    PRIMARY KEY (event_id, netuid)
);
CREATE TABLE slots (netuid INTEGER PRIMARY KEY, github_repo TEXT);
"""


def _iso(hours_ago=0):
    return (datetime.datetime.now(tz=datetime.timezone.utc)
            - datetime.timedelta(hours=hours_ago)).isoformat()


def seed_fleet(path):
    conn = sqlite3.connect(path)
    conn.executescript(FLEET_SCHEMA)
    conn.execute("INSERT INTO slots VALUES (64, "
                 "'https://github.com/rayonlabs/chutes')")
    conn.commit()
    conn.close()


def add_event(path, event_class, tier, dedup_key, payload, netuid=None,
              term=None, created_at=None, entry=None):
    conn = sqlite3.connect(path)
    cursor = conn.execute(
        "INSERT INTO signal_events (class, tier, netuid, term, dedup_key, "
        "payload_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (event_class, tier, netuid, term, dedup_key, json.dumps(payload),
         created_at or _iso()))
    row_id = cursor.lastrowid
    if entry:
        for entry_netuid, price, status in entry:
            conn.execute(
                "INSERT INTO signal_entries VALUES (?, ?, ?, ?, ?)",
                (row_id, entry_netuid, price, _iso(), status))
    conn.commit()
    conn.close()
    return row_id


def ok_poster(sent):
    def poster(url, data, timeout):
        sent.append(data.decode("utf-8"))
        return 200, '{"ok":true}'
    return poster


class FleetSignalBase(unittest.TestCase):
    def setUp(self):
        self.tmp_ctx = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_ctx.cleanup)
        self.tmp = self.tmp_ctx.name
        self.fleet_db = os.path.join(self.tmp, "fleet.db")
        seed_fleet(self.fleet_db)
        self.config = make_config(self.tmp)
        # priority: below chain-runtime-upgrade, above repository-update —
        # rebuild the classes dict in delivery order like the shipped config
        classes = {"chain-runtime-upgrade":
                   self.config["classes"]["chain-runtime-upgrade"],
                   "fleet-signal": {"enabled": True,
                                    "source_db": self.fleet_db,
                                    "digest_backstop_hours": 24}}
        classes.update({key: value for key, value
                        in self.config["classes"].items()
                        if key != "chain-runtime-upgrade"})
        self.config["classes"] = classes
        self.store = tg.open_store(os.path.join(self.tmp, "telegram.db"))
        self.addCleanup(self.store.close)

    def scan(self, sent=None):
        sent = sent if sent is not None else []
        summary = tg.notify_scan(self.config, "tok-x", "chat-1", self.store,
                                 poster=ok_poster(sent))
        return summary, sent


CLUSTER_PAYLOAD = {
    "term": "vllm-flash", "kind": "dependency",
    "members": [{"netuid": 64, "adopted_at": "2026-07-05T00:00:00+00:00",
                 "commit_sha": "a" * 40},
                {"netuid": 19, "adopted_at": "2026-07-10T00:00:00+00:00",
                 "commit_sha": "b" * 40},
                {"netuid": 4, "adopted_at": "2026-07-14T00:00:00+00:00",
                 "commit_sha": "c" * 40}],
    "first_mover": {"netuid": 19, "adopted_at": "2026-07-05T00:00:00+00:00",
                    "commit_sha": "a1b2c3d" + "0" * 33},
    "window_days": 14, "prevalence": {"adopters": 3, "active_slots": 104},
}


class TestFleetSignalAlerts(FleetSignalBase):
    def test_cluster_pages_once_with_required_facts(self):
        add_event(self.fleet_db, "narrative-cluster", "instant",
                  "cluster:dependency:vllm-flash", CLUSTER_PAYLOAD,
                  term="vllm-flash",
                  entry=[(64, 0.0123, "recorded"), (19, 0.0021, "recorded")])
        summary, sent = self.scan()
        self.assertEqual(summary["classes"]["fleet-signal"]["delivered"], 1)
        body = sent[0]
        self.assertIn("narrative+cluster", body)  # urlencoded space
        self.assertIn("vllm-flash", body)
        self.assertIn("SN64", body)
        self.assertIn("first+mover", body)
        self.assertIn("a1b2c3d", body)
        self.assertIn("3%2F104", body)            # prevalence 3/104
        self.assertIn("entry+price", body)
        self.assertIn("0.0123", body)
        # re-scan: watermark passed, nothing re-sent
        summary, sent = self.scan()
        self.assertEqual(summary["classes"]["fleet-signal"], {
            "delivered": 0, "suppressed": 0, "failed": 0,
            "scrub-refused": 0, "error": 0})

    def test_pending_entry_omits_price_line_never_delays(self):
        add_event(self.fleet_db, "watchlist", "instant",
                  "watchlist:dependency:vllm:64:1",
                  {"term": "vllm", "kind": "dependency", "netuid": 64,
                   "epoch": 1, "commit_sha": "d" * 40,
                   "source_file": "requirements.txt"},
                  netuid=64, term="vllm",
                  entry=[(64, None, "pending")])
        summary, sent = self.scan()
        self.assertEqual(summary["classes"]["fleet-signal"]["delivered"], 1)
        self.assertNotIn("entry+price", sent[0])
        self.assertIn("watchlist+term", sent[0])
        self.assertIn("chutes", sent[0])  # repo label from slots, read-only

    def test_econ_alert_and_ledger_dedup_by_range(self):
        add_event(self.fleet_db, "econ-code", "instant", "econ:17",
                  {"netuid": 64, "range_id": 17, "prev_sha": "e" * 40,
                   "new_sha": "f" * 40, "files": ["validator/reward.py"],
                   "commit_count": 4, "commits_truncated": False},
                  netuid=64)
        summary, sent = self.scan()
        self.assertEqual(summary["classes"]["fleet-signal"]["delivered"], 1)
        self.assertIn("incentive-code+change", sent[0])
        self.assertIn("reward.py", sent[0])
        # watermark reset (operator surgery): the ledger still suppresses
        self.store.execute("UPDATE watermarks SET value = '0' WHERE "
                           "source = 'fleet-signal'")
        self.store.commit()
        summary, sent = self.scan()
        self.assertEqual(summary["classes"]["fleet-signal"]["suppressed"], 1)
        self.assertEqual(sent, [])

    def test_digest_rows_never_page_and_ride_next_instant(self):
        add_event(self.fleet_db, "signal-digest", "digest", "adopt:1",
                  {"line": "SN12 adopted sglang"})
        summary, sent = self.scan()
        self.assertEqual(summary["classes"]["fleet-signal"], {
            "delivered": 0, "suppressed": 0, "failed": 0,
            "scrub-refused": 0, "error": 0})
        self.assertEqual(sent, [])
        pending = self.store.execute(
            "SELECT line FROM pending_signal").fetchall()
        self.assertEqual(pending, [("SN12 adopted sglang",)])
        # an instant alert arrives: the digest line rides it and clears
        add_event(self.fleet_db, "econ-code", "instant", "econ:18",
                  {"netuid": 64, "range_id": 18, "prev_sha": "e" * 40,
                   "new_sha": "f" * 40, "files": ["scoring.py"],
                   "commit_count": 1, "commits_truncated": False},
                  netuid=64)
        summary, sent = self.scan()
        self.assertEqual(summary["classes"]["fleet-signal"]["delivered"], 1)
        self.assertIn("SN12+adopted+sglang", sent[0])
        self.assertEqual(self.store.execute(
            "SELECT COUNT(*) FROM pending_signal").fetchone()[0], 0)

    def test_digest_survives_failed_scan_until_delivered(self):
        add_event(self.fleet_db, "signal-digest", "digest", "adopt:2",
                  {"line": "SN9 adopted verl"})
        self.scan()  # stored durably, watermark advances past it
        add_event(self.fleet_db, "econ-code", "instant", "econ:19",
                  {"netuid": 64, "range_id": 19, "prev_sha": "e" * 40,
                   "new_sha": "f" * 40, "files": ["reward.py"],
                   "commit_count": 1, "commits_truncated": False},
                  netuid=64)

        def failing_poster(url, data, timeout):
            return 503, "unavailable"

        tg.notify_scan(self.config, "tok-x", "chat-1", self.store,
                       poster=failing_poster)
        # failed delivery: the pending line is NOT cleared
        self.assertEqual(self.store.execute(
            "SELECT COUNT(*) FROM pending_signal").fetchone()[0], 1)

    def test_backstop_flushes_stale_digest_alone(self):
        add_event(self.fleet_db, "signal-digest", "digest", "adopt:3",
                  {"line": "SN2 joined existing cluster"})
        self.scan()
        self.store.execute("UPDATE pending_signal SET detected_at = ?",
                           (_iso(hours_ago=25),))
        self.store.commit()
        summary, sent = self.scan()
        self.assertEqual(summary["classes"]["fleet-signal"]["delivered"], 1)
        self.assertIn("signal+digest", sent[0])
        self.assertEqual(self.store.execute(
            "SELECT COUNT(*) FROM pending_signal").fetchone()[0], 0)

    def test_mixed_scan_orders_chain_upgrade_first(self):
        livedata = os.path.join(self.tmp, "livedata.db")
        conn = sqlite3.connect(livedata)
        conn.executescript(
            "CREATE TABLE spec_upgrades (id INTEGER PRIMARY KEY, "
            "observed_at TEXT, prev_spec INTEGER, new_spec INTEGER, "
            "block_reference INTEGER);"
            "CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);"
            "CREATE TABLE integration_health (id INTEGER PRIMARY KEY, "
            "timestamp TEXT, provider TEXT, operation TEXT, "
            "category TEXT, detail TEXT);")
        conn.execute("INSERT INTO spec_upgrades VALUES (1, 't', 429, 430, "
                     "123)")
        conn.commit()
        conn.close()
        add_event(self.fleet_db, "econ-code", "instant", "econ:20",
                  {"netuid": 64, "range_id": 20, "prev_sha": "e" * 40,
                   "new_sha": "f" * 40, "files": ["reward.py"],
                   "commit_count": 1, "commits_truncated": False},
                  netuid=64)
        _summary, sent = self.scan()
        self.assertEqual(len(sent), 2)
        self.assertIn("LIVE+CHAIN+UPGRADED", sent[0])
        self.assertIn("incentive-code", sent[1])

    def test_fleet_store_is_never_written(self):
        add_event(self.fleet_db, "signal-digest", "digest", "adopt:4",
                  {"line": "x"})
        add_event(self.fleet_db, "econ-code", "instant", "econ:21",
                  {"netuid": 64, "range_id": 21, "prev_sha": "e" * 40,
                   "new_sha": "f" * 40, "files": ["reward.py"],
                   "commit_count": 1, "commits_truncated": False},
                  netuid=64)
        conn = sqlite3.connect(self.fleet_db)
        before = {table: conn.execute(
            "SELECT COUNT(*) FROM %s" % table).fetchone()[0]
            for table in ("signal_events", "signal_entries", "slots")}
        conn.close()
        self.scan()
        conn = sqlite3.connect(self.fleet_db)
        after = {table: conn.execute(
            "SELECT COUNT(*) FROM %s" % table).fetchone()[0]
            for table in ("signal_events", "signal_entries", "slots")}
        master = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE name LIKE "
            "'pending_%'").fetchone()[0]
        conn.close()
        self.assertEqual(before, after)
        self.assertEqual(master, 0)  # pending storage lives in telegram.db

    def test_init_seeds_watermark_without_sending(self):
        add_event(self.fleet_db, "narrative-cluster", "instant",
                  "cluster:dependency:old-term", CLUSTER_PAYLOAD)
        seeded = tg.seed_watermarks(self.config, self.store)
        self.assertEqual(seeded["fleet-signal"]["skipped"], 1)
        summary, sent = self.scan()
        self.assertEqual(sent, [])
        # idempotent: a second init never rolls the watermark back
        self.assertEqual(tg.seed_watermarks(self.config, self.store)
                         ["fleet-signal"], "already-seeded")

    def test_absent_fleet_store_is_no_events(self):
        os.remove(self.fleet_db)
        summary, sent = self.scan()
        self.assertEqual(summary["classes"]["fleet-signal"], {
            "delivered": 0, "suppressed": 0, "failed": 0,
            "scrub-refused": 0, "error": 0})


# ---------------------------------------------------------------------------
# Econ verdict card (change: econ-alert-intelligence-gate)
# ---------------------------------------------------------------------------

ECON_VERDICT_PAYLOAD = {
    "netuid": 64, "range_id": 30, "prev_sha": "a" * 40, "new_sha": "b" * 40,
    "files": ["validator/reward.py"], "commit_count": 5,
    "commits_truncated": False, "significance": "high",
    "direction": "emissions_up", "what_changed": "latency penalty removed",
    "why_it_matters": "favors slow high-quality miners",
    "evidence": "del latency_penalty", "partial_view": False,
    "unjudged": False,
}


class TestEconVerdictCard(FleetSignalBase):
    def test_material_card_leads_with_meaning(self):
        add_event(self.fleet_db, "econ-code", "instant", "econ:30",
                  ECON_VERDICT_PAYLOAD, netuid=64,
                  entry=[(64, 0.0265, "recorded")])
        _summary, sent = self.scan()
        body = sent[0]
        self.assertIn("material+incentive-code+change", body)
        self.assertIn("latency+penalty+removed", body)
        self.assertIn("favors+slow", body)
        self.assertIn("significance", body)
        self.assertIn("high", body)
        self.assertIn("based+on", body)
        self.assertIn("blockquote", body)             # details are collapsible
        self.assertIn("0.0265", body)                 # price in the details
        self.assertNotIn("not+the+live+chain", body)  # disclaimer dropped

    def test_unjudged_card_is_marked(self):
        payload = dict(ECON_VERDICT_PAYLOAD, range_id=31, significance=None,
                       unjudged=True, what_changed=None, why_it_matters=None,
                       evidence=None)
        add_event(self.fleet_db, "econ-code", "instant", "econ:31", payload,
                  netuid=64)
        _summary, sent = self.scan()
        body = sent[0]
        self.assertIn("unjudged", body)
        self.assertIn("verdict+unavailable", body)

    def test_verdict_text_is_html_escaped(self):
        payload = dict(ECON_VERDICT_PAYLOAD, range_id=32,
                       what_changed="<script>alert(1)</script>")
        add_event(self.fleet_db, "econ-code", "instant", "econ:32", payload,
                  netuid=64)
        _summary, sent = self.scan()
        body = sent[0]
        self.assertNotIn("%3Cscript%3E", body)  # raw tag never emitted
        self.assertIn("%26lt%3B", body)         # escaped &lt;

    def test_layout_has_bold_labels_blank_lines_and_wordsafe_clip(self):
        payload = dict(ECON_VERDICT_PAYLOAD, range_id=41,
                       what_changed="alpha beta gamma " * 40)  # long, spaced
        add_event(self.fleet_db, "econ-code", "instant", "econ:41", payload,
                  netuid=64)
        _summary, sent = self.scan()
        body = sent[0]
        self.assertIn("%3Cb%3Ewhy", body)            # <b>why  (bold label)
        self.assertIn("%3Cb%3Esignificance", body)   # <b>significance
        self.assertIn("%E2%80%A6", body)             # … word-safe clip
        self.assertLess(body.count("gamma"), 40)     # clipped, not the full run
        self.assertIn("%0A%0A", body)                # blank-line separation

    def test_partial_view_flagged(self):
        payload = dict(ECON_VERDICT_PAYLOAD, range_id=33, partial_view=True)
        add_event(self.fleet_db, "econ-code", "instant", "econ:33", payload,
                  netuid=64)
        _summary, sent = self.scan()
        self.assertIn("partial+view", sent[0])

    def test_html_400_falls_back_to_plain(self):
        add_event(self.fleet_db, "econ-code", "instant", "econ:34",
                  dict(ECON_VERDICT_PAYLOAD, range_id=34), netuid=64)
        attempts = []

        def poster(url, data, timeout):
            body = data.decode("utf-8")
            attempts.append(body)
            if "parse_mode=HTML" in body:
                return 400, "Bad Request: can't parse entities"
            return 200, '{"ok":true}'

        summary = tg.notify_scan(self.config, "tok-x", "chat-1", self.store,
                                 poster=poster)
        self.assertEqual(summary["classes"]["fleet-signal"]["delivered"], 1)
        self.assertTrue(any("parse_mode=HTML" not in b for b in attempts))


if __name__ == "__main__":
    unittest.main()
