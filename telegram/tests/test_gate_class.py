"""gate-crossing notifier class (change: gate-crossing-signal): row-id
watermarking, per-netuid cooldown (suppressed recorded, never dropped),
house-style rendering incl. the emission-disabled note, seed-time
behavior (no cooldown recording without a store), and disabled-class /
missing-table inertness."""

import datetime
import os
import sqlite3
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

import atlas_telegram as tg  # noqa: E402
from test_notifier import make_config  # noqa: E402

GATE_SCHEMA = """
CREATE TABLE gate_events (
    id INTEGER PRIMARY KEY,
    observed_at TEXT NOT NULL,
    netuid INTEGER NOT NULL,
    direction TEXT NOT NULL,
    share REAL NOT NULL,
    theta REAL NOT NULL,
    prev_side TEXT NOT NULL,
    emission_enabled INTEGER,
    block_number INTEGER
);
"""


def _iso(hours_ago=0):
    return (datetime.datetime.now(tz=datetime.timezone.utc)
            - datetime.timedelta(hours=hours_ago)).isoformat()


def seed_live(path):
    conn = sqlite3.connect(path)
    conn.executescript(GATE_SCHEMA)
    conn.commit()
    conn.close()


def add_crossing(path, netuid, direction="fell-below", share=0.005,
                 theta=0.010, emission_enabled=1, block=8714000,
                 observed_at=None):
    conn = sqlite3.connect(path)
    cursor = conn.execute(
        "INSERT INTO gate_events (observed_at, netuid, direction, share, "
        "theta, prev_side, emission_enabled, block_number) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (observed_at or _iso(), netuid, direction,
         share, theta, "above" if direction == "fell-below" else "below",
         emission_enabled, block))
    row_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return row_id


class GateAdapterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.live_db = os.path.join(self.tmp.name, "livedata.db")
        seed_live(self.live_db)
        self.config = make_config(self.tmp.name)
        self.spec = {"enabled": True, "source_db": self.live_db,
                     "cooldown_hours": 24}
        self.store = tg.open_store(os.path.join(self.tmp.name,
                                                "telegram.db"))
        self.addCleanup(self.store.close)

    def ctx(self, store="default"):
        return {"config": self.config, "spec": self.spec,
                "connection": self.store if store == "default" else store}

    def test_missing_source_or_table_is_inert(self):
        events, wm = tg.gate_crossing_events(
            os.path.join(self.tmp.name, "absent.db"), "7", self.ctx())
        self.assertEqual((events, wm), ([], "7"))
        bare = os.path.join(self.tmp.name, "bare.db")
        sqlite3.connect(bare).close()
        events, wm = tg.gate_crossing_events(bare, None, self.ctx())
        self.assertEqual((events, wm), ([], None))

    def test_event_rendering_and_watermark(self):
        row_id = add_crossing(self.live_db, 42, "fell-below",
                              share=0.0052, theta=0.0093)
        events, wm = tg.gate_crossing_events(self.live_db, None, self.ctx())
        self.assertEqual(len(events), 1)
        self.assertEqual(wm, str(row_id))
        event = events[0]
        self.assertEqual(event["event_id"],
                         "gate-crossing:42:%d" % row_id)
        self.assertEqual(event["event_class"], "gate-crossing")
        text = event["text"]
        self.assertIn("subnet 42 fell BELOW the bar", text)
        self.assertIn("share 0.520%", text)
        self.assertIn("bar 0.930%", text)
        self.assertIn("shares: TaoSwap panel", text)
        self.assertIn("bar: chain RPC", text)
        self.assertNotIn("—", text)  # em dash
        self.assertNotIn("–", text)  # en dash
        self.assertNotIn("DISABLED", text)  # enabled subnet: no note
        self.assertIn("<b>", event["html"])

    def test_rose_above_and_disabled_note(self):
        add_crossing(self.live_db, 7, "rose-above", share=0.0121,
                     theta=0.0093, emission_enabled=0)
        events, _wm = tg.gate_crossing_events(self.live_db, None,
                                              self.ctx())
        text = events[0]["text"]
        self.assertIn("rose ABOVE the bar", text)
        self.assertIn("amplified emission share", text)
        self.assertIn("emission is DISABLED", text)

    def test_watermark_excludes_seen_rows(self):
        first = add_crossing(self.live_db, 1)
        second = add_crossing(self.live_db, 2)
        events, wm = tg.gate_crossing_events(self.live_db, str(first),
                                             self.ctx())
        self.assertEqual([e["event_id"] for e in events],
                         ["gate-crossing:2:%d" % second])
        self.assertEqual(wm, str(second))

    def test_cooldown_suppresses_and_records_never_drops(self):
        first = add_crossing(self.live_db, 42, "fell-below")
        # A delivered alert for netuid 42 within the window.
        tg.ledger_record(self.store, "gate-crossing:42:%d" % first,
                         "gate-crossing", _iso(1), tg._utc_now(),
                         tg.STATUS_DELIVERED, 1, None)
        second = add_crossing(self.live_db, 42, "rose-above")
        third = add_crossing(self.live_db, 9, "fell-below")
        events, wm = tg.gate_crossing_events(self.live_db, str(first),
                                             self.ctx())
        # netuid 42 suppressed (recorded), netuid 9 pages.
        self.assertEqual([e["event_id"] for e in events],
                         ["gate-crossing:9:%d" % third])
        self.assertEqual(wm, str(third))
        row = self.store.execute(
            "SELECT status FROM events WHERE event_id = ?",
            ("gate-crossing:42:%d" % second,)).fetchone()
        self.assertEqual(row[0], tg.STATUS_SUPPRESSED)

    def test_expired_cooldown_pages_again(self):
        first = add_crossing(self.live_db, 42)
        tg.ledger_record(self.store, "gate-crossing:42:%d" % first,
                         "gate-crossing", _iso(30), _iso(30),
                         tg.STATUS_DELIVERED, 1, None)
        second = add_crossing(self.live_db, 42, "rose-above")
        events, _wm = tg.gate_crossing_events(self.live_db, str(first),
                                              self.ctx())
        self.assertEqual([e["event_id"] for e in events],
                         ["gate-crossing:42:%d" % second])

    def test_seed_context_skips_cooldown_recording(self):
        add_crossing(self.live_db, 42)
        events, wm = tg.gate_crossing_events(self.live_db, None,
                                             self.ctx(store=None))
        self.assertEqual(len(events), 1)   # returned for counting only
        self.assertIsNotNone(wm)
        self.assertEqual(self.store.execute(
            "SELECT COUNT(*) FROM events").fetchone()[0], 0)

    def test_adapter_registered_and_class_config_present(self):
        self.assertIn("gate-crossing", tg._ADAPTERS)
        # The shipped repo config carries the class disabled by default.
        import json
        with open(tg.CONFIG_FILE, "r", encoding="utf-8") as handle:
            shipped = json.load(handle)
        spec = shipped["classes"]["gate-crossing"]
        self.assertFalse(spec["enabled"])
        self.assertEqual(spec["source_db"], "var/livedata/livedata.db")

    def test_disabled_class_is_absent_from_scan(self):
        add_crossing(self.live_db, 42)
        config = make_config(self.tmp.name)
        config["classes"] = {
            "gate-crossing": {"enabled": False,
                              "source_db": self.live_db}}
        sent = []
        summary = tg.notify_scan(
            config, "token", "chat", self.store,
            poster=lambda *a, **k: sent.append(a) or (200, "{\"ok\":true}"))
        self.assertEqual(summary["classes"], {})
        self.assertEqual(sent, [])
        self.assertIsNone(tg.watermark_get(self.store, "gate-crossing"))


if __name__ == "__main__":
    unittest.main()
